from __future__ import annotations

import unittest

from agent_tui.llm import http_error


class LLMErrorClassificationTest(unittest.TestCase):
    def test_rate_limit_is_retryable(self) -> None:
        error = http_error(429, '{"error":{"message":"rate limit"}}')
        self.assertTrue(error.retryable)
        self.assertEqual(error.kind, "rate_limit")
        self.assertEqual(error.status_code, 429)
        self.assertIn("rate limited", error.friendly_message())

    def test_authentication_error_is_not_retryable(self) -> None:
        error = http_error(401, '{"error":{"message":"bad key"}}')
        self.assertFalse(error.retryable)
        self.assertEqual(error.kind, "authentication")
        self.assertIn("DEEPSEEK_API_KEY", error.friendly_message())


if __name__ == "__main__":
    unittest.main()

