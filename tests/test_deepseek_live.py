from __future__ import annotations

import os
import unittest

from agent_tui.llm import DeepSeekClient


@unittest.skipUnless(os.getenv("RUN_DEEPSEEK_LIVE") == "1" and os.getenv("DEEPSEEK_API_KEY"), "live DeepSeek test disabled")
class DeepSeekLiveTest(unittest.TestCase):
    def test_live_chat_completion(self) -> None:
        client = DeepSeekClient(max_tokens=32)
        message = client.complete(
            messages=[
                {"role": "system", "content": "You are a terse test assistant."},
                {"role": "user", "content": "Reply with exactly: OK"},
            ],
            tools=[],
        )
        self.assertIn("OK", message.get("content") or "")


if __name__ == "__main__":
    unittest.main()

