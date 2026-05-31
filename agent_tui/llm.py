"""DeepSeek chat-completions client.

The client intentionally sticks to the OpenAI-compatible HTTP shape instead of
depending on the OpenAI SDK. That keeps this prototype install-free.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    """Raised when the LLM request cannot be completed."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "unknown",
        retryable: bool = False,
        status_code: int | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code
        self.suggestion = suggestion

    def friendly_message(self) -> str:
        if self.suggestion:
            return f"{self.message}\nSuggestion: {self.suggestion}"
        return self.message


@dataclass
class DeepSeekClient:
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    timeout: float = 60.0
    temperature: float = 0.2
    max_tokens: int = 2048
    thinking: str | None = None

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = self.model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.base_url = (self.base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.thinking = self.thinking if self.thinking is not None else os.getenv("DEEPSEEK_THINKING", "disabled")

        timeout_env = os.getenv("DEEPSEEK_TIMEOUT")
        if timeout_env:
            try:
                self.timeout = float(timeout_env)
            except ValueError as exc:
                raise LLMError(
                    "DEEPSEEK_TIMEOUT must be a number.",
                    kind="configuration",
                    suggestion="Set DEEPSEEK_TIMEOUT to a numeric value, for example 60.",
                ) from exc

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.api_key:
            raise LLMError(
                "Missing DEEPSEEK_API_KEY.",
                kind="authentication",
                suggestion="Set DEEPSEEK_API_KEY before starting the TUI.",
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if self._should_send_thinking():
            payload["thinking"] = {"type": self.thinking}

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise http_error(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise LLMError(
                f"Could not reach DeepSeek API: {exc.reason}",
                kind="network",
                retryable=True,
                suggestion="Check your network connection or retry shortly.",
            ) from exc
        except json.JSONDecodeError as exc:
            raise LLMError(
                "DeepSeek API returned invalid JSON.",
                kind="invalid_response",
                retryable=True,
                suggestion="This can be transient; retrying may help.",
            ) from exc

        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                f"Unexpected DeepSeek response shape: {data}",
                kind="invalid_response",
                suggestion="Check whether the configured model and endpoint are compatible.",
            ) from exc

        finish_reason = choice.get("finish_reason")
        if finish_reason == "content_filter":
            raise LLMError(
                "DeepSeek blocked the response with finish_reason=content_filter.",
                kind="content_filter",
                suggestion="Try rephrasing the request or reducing sensitive content.",
            )
        if finish_reason == "insufficient_system_resource":
            raise LLMError(
                "DeepSeek stopped with finish_reason=insufficient_system_resource.",
                kind="server_overloaded",
                retryable=True,
                suggestion="Retry shortly; the provider reported temporary resource pressure.",
            )

        return self._normalize_message(message)

    def _should_send_thinking(self) -> bool:
        if self.thinking not in {"enabled", "disabled"}:
            return False
        # Legacy compatibility aliases may reject the newer thinking switch.
        return bool(self.model and self.model.startswith("deepseek-v4-"))

    @staticmethod
    def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content"),
        }
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            normalized["tool_calls"] = tool_calls
        return normalized


def http_error(status_code: int, detail: str) -> LLMError:
    detail_text = extract_error_detail(detail)
    retryable = status_code in {408, 409, 429, 500, 502, 503, 504}
    kind = "http_error"
    suggestion = "Retry shortly or reduce request rate." if retryable else None

    if status_code in {401, 403}:
        kind = "authentication"
        suggestion = "Check DEEPSEEK_API_KEY and account permissions."
    elif status_code == 400:
        kind = "bad_request"
        suggestion = "Check model name, message format, and tool schema compatibility."
    elif status_code == 429:
        kind = "rate_limit"
        suggestion = "You are being rate limited. Wait a moment or lower request frequency."
    elif 500 <= status_code <= 599:
        kind = "server_error"
        suggestion = "DeepSeek returned a temporary server error. Retrying may help."

    return LLMError(
        f"DeepSeek API HTTP {status_code}: {detail_text}",
        kind=kind,
        retryable=retryable,
        status_code=status_code,
        suggestion=suggestion,
    )


def extract_error_detail(detail: str) -> str:
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        return detail[:500] if detail else "No response body."

    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("type") or error
        return str(message)[:500]
    return json.dumps(parsed, ensure_ascii=False)[:500]
