from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_tui.tools import ToolRegistry


class ToolRegistryTest(unittest.TestCase):
    def test_read_file_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Demo\nhello agent\n", encoding="utf-8")
            tools = ToolRegistry(root)

            read_obs = json.loads(tools.execute("read_text_file", {"path": "README.md"}))
            self.assertTrue(read_obs["ok"])
            self.assertEqual(read_obs["result"]["lines"][0]["text"], "# Demo")

            search_obs = json.loads(tools.execute("search_text", {"query": "agent"}))
            self.assertTrue(search_obs["ok"])
            self.assertEqual(search_obs["result"]["matches"][0]["path"], "README.md")

    def test_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tools = ToolRegistry(temp_dir)
            obs = json.loads(tools.execute("read_text_file", {"path": "../secret.txt"}))
            self.assertFalse(obs["ok"])
            self.assertIn("escapes workspace", obs["error"]["message"])


if __name__ == "__main__":
    unittest.main()

