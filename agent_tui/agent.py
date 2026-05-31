"""Agent loop: LLM -> tool calls -> observations -> LLM."""

from __future__ import annotations

import time
from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generator, Iterator, Protocol

from agent_tui.llm import LLMError
from agent_tui.tools import ToolRegistry


SYSTEM_PROMPT = """You are MiniHarness, a minimal terminal agent.

You can answer directly, or call tools when you need local workspace facts.
When a user asks about files, code, project structure, or prior tool results,
prefer using tools before making claims. Use tool observations as ground truth.
Keep responses concise, and answer in the user's language unless they ask otherwise.
Do not claim you changed files; your available tools are read/search only.
When you decide to call tools, include a brief visible progress note in content:
one short sentence about what you are checking next and why. Do not reveal hidden
chain-of-thought; provide only a concise decision summary.
"""


class ChatClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        ...


@dataclass
class AgentEvent:
    type: str
    data: dict[str, Any]


class Agent:
    def __init__(
        self,
        client: ChatClient,
        tools: ToolRegistry,
        max_steps: int = 8,
        max_llm_retries: int = 2,
        retry_base_delay: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.tools = tools
        self.max_steps = max_steps
        self.max_llm_retries = max_llm_retries
        self.retry_base_delay = retry_base_delay
        self.sleep = sleep
        self.messages: list[dict[str, Any]] = []
        self.reset()

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def export_messages(self) -> list[dict[str, Any]]:
        return deepcopy(self.messages)

    def load_messages(self, messages: list[dict[str, Any]]) -> None:
        if not messages:
            self.reset()
            return
        if messages[0].get("role") != "system":
            raise ValueError("Session messages must start with a system message")
        self.messages = deepcopy(messages)

    def run_turn(self, user_text: str) -> Iterator[AgentEvent]:
        turn_start_index = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})

        for step in range(1, self.max_steps + 1):
            try:
                assistant_message = yield from self._complete_with_retries(step)
            except LLMError as exc:
                self.rollback_turn(turn_start_index)
                yield AgentEvent(
                    "error",
                    {
                        "message": exc.friendly_message(),
                        "kind": exc.kind,
                        "retryable": exc.retryable,
                        "status_code": exc.status_code,
                    },
                )
                return

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                content = assistant_message.get("content") or ""
                self.messages.append({"role": "assistant", "content": content})
                yield AgentEvent("assistant_final", {"content": content})
                return

            interim_content = assistant_message.get("content") or ""
            yield AgentEvent("step_start", {"step": step, "note": interim_content})

            self.messages.append(
                {
                    "role": "assistant",
                    "content": interim_content or None,
                    "tool_calls": tool_calls,
                }
            )

            for index, tool_call in enumerate(tool_calls, start=1):
                function = tool_call.get("function") or {}
                name = function.get("name", "")
                arguments = function.get("arguments", "{}")
                call_id = tool_call.get("id", f"call_{step}_{index}")

                yield AgentEvent(
                    "tool_call",
                    {
                        "step": step,
                        "id": call_id,
                        "name": name,
                        "arguments": arguments,
                    },
                )
                observation = self.tools.execute(name, arguments)
                self.messages.append({"role": "tool", "tool_call_id": call_id, "content": observation})
                yield AgentEvent(
                    "tool_observation",
                    {
                        "step": step,
                        "id": call_id,
                        "name": name,
                        "observation": observation,
                    },
                )

        content = "Reached the maximum agent loop steps before producing a final answer."
        self.messages.append({"role": "assistant", "content": content})
        yield AgentEvent("assistant_final", {"content": content})

    def _complete_with_retries(self, step: int) -> Generator[AgentEvent, None, dict[str, Any]]:
        max_attempts = self.max_llm_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                return self.client.complete(self.messages, self.tools.schemas)
            except LLMError as exc:
                can_retry = exc.retryable and attempt < max_attempts
                if not can_retry:
                    raise

                delay_seconds = self.retry_base_delay * (2 ** (attempt - 1))
                yield AgentEvent(
                    "retrying",
                    {
                        "step": step,
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "max_attempts": max_attempts,
                        "delay_seconds": delay_seconds,
                        "message": exc.friendly_message(),
                        "kind": exc.kind,
                        "status_code": exc.status_code,
                    },
                )
                if delay_seconds > 0:
                    self.sleep(delay_seconds)

        raise RuntimeError("unreachable retry loop state")

    def rollback_turn(self, turn_start_index: int) -> None:
        del self.messages[turn_start_index:]
