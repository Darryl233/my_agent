from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent_tui.agent import Agent
from agent_tui.llm import LLMError
from agent_tui.tools import ToolRegistry


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "I will inspect the project structure first.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "list_files", "arguments": json.dumps({"path": ".", "max_results": 5})},
                    }
                ],
            }
        tool_messages = [message for message in messages if message["role"] == "tool"]
        assert tool_messages
        return {"role": "assistant", "content": "I inspected the workspace."}


class FlakyClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise LLMError("Temporary server error.", kind="server_error", retryable=True)
        return {"role": "assistant", "content": "Recovered."}


class FailingClient:
    def __init__(self, error: LLMError) -> None:
        self.error = error
        self.calls = 0

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        raise self.error


class FailsAfterToolClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "I will inspect files.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "list_files", "arguments": json.dumps({"path": "."})},
                    }
                ],
            }
        raise LLMError("Bad request.", kind="bad_request", retryable=False, suggestion="Check the request payload.")


class AgentLoopTest(unittest.TestCase):
    def test_tool_observation_is_fed_back_before_final_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
            agent = Agent(FakeClient(), ToolRegistry(root))

            events = list(agent.run_turn("inspect"))
            event_types = [event.type for event in events]
            self.assertEqual(
                event_types,
                ["step_start", "tool_call", "tool_observation", "assistant_final"],
            )
            self.assertEqual(events[0].data["note"], "I will inspect the project structure first.")
            self.assertEqual(agent.messages[-1]["content"], "I inspected the workspace.")

    def test_retryable_llm_error_retries_and_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = FlakyClient()
            agent = Agent(client, ToolRegistry(temp_dir), retry_base_delay=0, sleep=lambda _: None)

            events = list(agent.run_turn("hello"))
            event_types = [event.type for event in events]
            self.assertEqual(event_types, ["retrying", "assistant_final"])
            self.assertEqual(events[0].data["next_attempt"], 2)
            self.assertEqual(client.calls, 2)
            self.assertEqual(agent.messages[-1]["content"], "Recovered.")

    def test_non_retryable_llm_error_rolls_back_user_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            error = LLMError(
                "Missing DEEPSEEK_API_KEY.",
                kind="authentication",
                suggestion="Set DEEPSEEK_API_KEY.",
            )
            agent = Agent(FailingClient(error), ToolRegistry(temp_dir), retry_base_delay=0, sleep=lambda _: None)

            events = list(agent.run_turn("hello"))
            self.assertEqual([event.type for event in events], ["error"])
            self.assertIn("Suggestion: Set DEEPSEEK_API_KEY.", events[0].data["message"])
            self.assertEqual(len(agent.messages), 1)
            self.assertEqual(agent.messages[0]["role"], "system")

    def test_llm_error_after_tool_rolls_back_entire_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
            agent = Agent(FailsAfterToolClient(), ToolRegistry(root), retry_base_delay=0, sleep=lambda _: None)

            events = list(agent.run_turn("inspect"))
            self.assertEqual([event.type for event in events], ["step_start", "tool_call", "tool_observation", "error"])
            self.assertEqual(len(agent.messages), 1)
            self.assertEqual(agent.messages[0]["role"], "system")


if __name__ == "__main__":
    unittest.main()
