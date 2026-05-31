from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_tui.agent import Agent
from agent_tui.sessions import SessionError, SessionStore
from agent_tui.tools import ToolRegistry


class DummyClient:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return {"role": "assistant", "content": "ok"}


class SessionStoreTest(unittest.TestCase):
    def test_create_save_load_and_list_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            store = SessionStore(Path(temp_dir) / "sessions")
            agent = Agent(DummyClient(), ToolRegistry(workspace))
            agent.messages.append({"role": "user", "content": "hello"})

            session = store.create(agent.export_messages(), model="deepseek-test", workspace=workspace, name="demo")
            session = store.save(session, agent.export_messages())
            loaded = store.load(session.id[:6])

            self.assertEqual(loaded.id, session.id)
            self.assertEqual(loaded.name, "demo")
            self.assertEqual(loaded.messages[-1]["content"], "hello")
            summaries = store.list()
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].id, session.id)

    def test_load_rejects_ambiguous_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(temp_dir)
            first = store.create([{"role": "system", "content": "a"}], model="m", workspace=temp_dir, name="a")
            second = store.create([{"role": "system", "content": "b"}], model="m", workspace=temp_dir, name="b")
            first.id = "abc111"
            second.id = "abc222"
            store.save(first, first.messages)
            store.save(second, second.messages)

            with self.assertRaises(SessionError):
                store.load("abc")

    def test_agent_can_load_saved_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            agent = Agent(DummyClient(), ToolRegistry(workspace))
            messages = [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "resume me"},
            ]

            agent.load_messages(messages)
            self.assertEqual(agent.export_messages(), messages)

    def test_delete_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(temp_dir)
            session = store.create([{"role": "system", "content": "system"}], model="m", workspace=temp_dir)
            session = store.save(session, session.messages)

            deleted_id = store.delete(session.id[:6])

            self.assertEqual(deleted_id, session.id)
            self.assertFalse(store.path_for(session.id).exists())
            with self.assertRaises(SessionError):
                store.load(session.id)


if __name__ == "__main__":
    unittest.main()
