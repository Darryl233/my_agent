#!/usr/bin/env python3
"""Entry point for the minimal agent TUI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent_tui.agent import Agent
from agent_tui.llm import DeepSeekClient, LLMError
from agent_tui.sessions import SessionError, SessionRecord, SessionStore
from agent_tui.tools import ToolRegistry
from agent_tui.ui import Renderer, read_user_input


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal DeepSeek agent TUI")
    parser.add_argument("--resume", help="Resume a saved session by id or unique prefix")
    parser.add_argument("--session-dir", help="Directory for session JSON files")
    parser.add_argument("--name", help="Name for a newly created session")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path.cwd()
    renderer = Renderer()

    try:
        client = DeepSeekClient()
    except LLMError as exc:
        renderer.error(str(exc))
        return 2

    tools = ToolRegistry(workspace)
    agent = Agent(client=client, tools=tools)
    session_dir = Path(args.session_dir or os.getenv("MINI_AGENT_SESSION_DIR") or workspace / ".mini_agent_sessions")

    try:
        store = SessionStore(session_dir)
        current_session = load_or_create_session(store, agent, client.model or "unknown", workspace, args.resume, args.name)
    except (SessionError, ValueError) as exc:
        renderer.error(str(exc))
        return 2

    renderer.banner(model=client.model or "unknown", tools=tools.names)
    renderer.session_notice(f"Session: {current_session.id} ({current_session.name})")

    if not os.getenv("DEEPSEEK_API_KEY"):
        renderer.error("DEEPSEEK_API_KEY is not set. The TUI will start, but agent calls will fail until it is set.")

    while True:
        try:
            user_text = read_user_input(renderer.prompt(), use_color=renderer.use_color)
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not user_text:
            continue
        command = user_text.split(maxsplit=1)[0]
        if user_text in {"/exit", "/quit", ":q"}:
            return 0
        if user_text == "/help":
            renderer.help()
            continue
        if user_text == "/tools":
            renderer.tools(tools.names)
            continue
        if user_text == "/session":
            renderer.session_status(
                current_session.id,
                current_session.name,
                current_session.updated_at,
                len(agent.messages),
                str(store.path_for(current_session.id)),
            )
            continue
        if user_text == "/sessions":
            renderer.sessions(store.list())
            continue
        if command == "/resume":
            session_id = command_arg(user_text)
            if not session_id:
                renderer.error("Usage: /resume SESSION_ID")
                continue
            try:
                current_session = store.save(current_session, agent.export_messages())
                current_session = store.load(session_id)
                agent.load_messages(current_session.messages)
            except (SessionError, ValueError) as exc:
                renderer.error(str(exc))
                continue
            renderer.session_notice(f"Resumed session {current_session.id} ({current_session.name})")
            continue
        if command == "/new":
            name = command_arg(user_text) or None
            try:
                current_session = store.save(current_session, agent.export_messages())
                agent.reset()
                current_session = store.create(agent.export_messages(), model=client.model or "unknown", workspace=workspace, name=name)
                current_session = store.save(current_session, agent.export_messages())
            except SessionError as exc:
                renderer.error(str(exc))
                continue
            renderer.session_notice(f"Started session {current_session.id} ({current_session.name})")
            continue
        if user_text == "/save":
            try:
                current_session = store.save(current_session, agent.export_messages())
            except SessionError as exc:
                renderer.error(str(exc))
                continue
            renderer.session_notice(f"Saved session {current_session.id}")
            continue
        if command == "/delete":
            session_id = command_arg(user_text)
            if not session_id:
                renderer.error("Usage: /delete SESSION_ID")
                continue
            try:
                resolved_id = store.resolve_id(session_id)
                deleting_current = resolved_id == current_session.id
                deleted_id = store.delete(resolved_id)
                if deleting_current:
                    agent.reset()
                    current_session = store.create(
                        agent.export_messages(),
                        model=client.model or "unknown",
                        workspace=workspace,
                        name=None,
                    )
                    current_session = store.save(current_session, agent.export_messages())
                    renderer.session_notice(
                        f"Deleted current session {deleted_id}. Started session {current_session.id} ({current_session.name})"
                    )
                else:
                    renderer.session_notice(f"Deleted session {deleted_id}")
            except SessionError as exc:
                renderer.error(str(exc))
            continue
        if user_text == "/reset":
            agent.reset()
            try:
                current_session = store.save(current_session, agent.export_messages())
            except SessionError as exc:
                renderer.error(str(exc))
                continue
            renderer.reset_notice()
            continue

        renderer.user(user_text)
        turn_completed = False
        for event in agent.run_turn(user_text):
            if event.type == "step_start":
                renderer.step_start(event.data["step"], event.data["note"])
            elif event.type == "retrying":
                renderer.retrying(
                    event.data["step"],
                    event.data["attempt"],
                    event.data["max_attempts"],
                    event.data["delay_seconds"],
                    event.data["message"],
                )
            elif event.type == "tool_call":
                renderer.tool_call(event.data["name"], event.data["arguments"], event.data["id"])
            elif event.type == "tool_observation":
                renderer.observation(event.data["observation"])
            elif event.type == "assistant_final":
                renderer.assistant(event.data["content"])
                turn_completed = True
            elif event.type == "error":
                renderer.error(event.data["message"])
        if turn_completed:
            try:
                current_session = store.save(current_session, agent.export_messages())
            except SessionError as exc:
                renderer.error(str(exc))


def load_or_create_session(
    store: SessionStore,
    agent: Agent,
    model: str,
    workspace: Path,
    resume_id: str | None,
    name: str | None,
) -> SessionRecord:
    if resume_id:
        session = store.load(resume_id)
        agent.load_messages(session.messages)
        return session
    session = store.create(agent.export_messages(), model=model, workspace=workspace, name=name)
    return store.save(session, agent.export_messages())


def command_arg(text: str) -> str:
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


if __name__ == "__main__":
    sys.exit(main())
