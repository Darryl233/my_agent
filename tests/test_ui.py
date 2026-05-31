from __future__ import annotations

import json
import unittest

from agent_tui.ui import Renderer, display_width


class RendererTest(unittest.TestCase):
    def test_read_text_file_observation_hides_file_content(self) -> None:
        renderer = Renderer(use_color=False)
        observation = json.dumps(
            {
                "ok": True,
                "tool": "read_text_file",
                "result": {
                    "path": "agent_tui/llm.py",
                    "line_count": 2,
                    "start_line": 1,
                    "lines": [
                        {"line": 1, "text": "secret line"},
                        {"line": 2, "text": "another line"},
                    ],
                    "truncated": False,
                },
            }
        )

        rendered = renderer.format_observation(observation, max_chars=2000)
        self.assertIn("read_text_file ok", rendered)
        self.assertIn("2 lines sent to model", rendered)
        self.assertIn("2 total lines", rendered)
        self.assertNotIn("secret line", rendered)
        self.assertNotIn("another line", rendered)

    def test_input_prompt_is_plain_for_fallback_input(self) -> None:
        renderer = Renderer(use_color=True)
        self.assertEqual(renderer.prompt(), "> ")

    def test_list_files_observation_hides_entries(self) -> None:
        renderer = Renderer(use_color=False)
        observation = json.dumps(
            {
                "ok": True,
                "tool": "list_files",
                "result": {
                    "path": ".",
                    "entries": [
                        {"path": "agent_tui", "type": "dir", "size_bytes": None},
                        {"path": "README.md", "type": "file", "size_bytes": 123},
                    ],
                    "truncated": False,
                },
            }
        )

        rendered = renderer.format_observation(observation, max_chars=2000)
        self.assertIn("list_files ok", rendered)
        self.assertIn("2 entries", rendered)
        self.assertIn("dir=1", rendered)
        self.assertIn("file=1", rendered)
        self.assertNotIn("README.md", rendered)
        self.assertNotIn("agent_tui", rendered)

    def test_tool_decision_summarizes_arguments(self) -> None:
        renderer = Renderer(use_color=False)
        decision = renderer.describe_tool_decision(
            "read_text_file",
            json.dumps({"path": "agent_tui/agent.py", "start_line": 10, "max_lines": 40}),
        )

        self.assertIn("agent_tui/agent.py", decision)
        self.assertIn("line 10", decision)
        self.assertIn("40 lines", decision)

    def test_display_width_handles_ansi_and_cjk(self) -> None:
        self.assertEqual(display_width("\033[31m你好\033[0m"), 4)
        self.assertEqual(display_width("abc"), 3)

    def test_search_text_observation_is_summarized(self) -> None:
        renderer = Renderer(use_color=False)
        observation = json.dumps(
            {
                "ok": True,
                "tool": "search_text",
                "result": {
                    "query": "Agent",
                    "matches": [
                        {"path": "agent_tui/agent.py", "line": 1, "text": "Agent"},
                        {"path": "README.md", "line": 2, "text": "Agent"},
                    ],
                    "truncated": False,
                },
            }
        )

        rendered = renderer.format_observation(observation, max_chars=2000)
        self.assertIn("search_text ok", rendered)
        self.assertIn("2 matches in 2 files", rendered)
        self.assertNotIn("agent_tui/agent.py", rendered)
        self.assertNotIn("README.md", rendered)


if __name__ == "__main__":
    unittest.main()
