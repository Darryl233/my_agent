"""Small ANSI terminal renderer for the prototype TUI."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import textwrap
import unicodedata
from typing import Any

try:
    from prompt_toolkit import prompt as toolkit_prompt
    from prompt_toolkit.styles import Style
except ImportError:  # prompt_toolkit is optional; plain input remains supported.
    toolkit_prompt = None
    Style = None


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
TITLE = "\033[38;5;111m"
META = "\033[38;5;245m"
USER = "\033[38;5;81m"
ASSISTANT = "\033[38;5;114m"
AGENT = "\033[38;5;221m"
TOOL = "\033[38;5;176m"
OBSERVATION = "\033[38;5;181m"
JSON_TEXT = "\033[38;5;250m"
ERROR = "\033[38;5;203m"
NOTICE = "\033[38;5;215m"

SECTION_STYLES = {
    "User": USER,
    "Assistant": ASSISTANT,
    "Help": TITLE,
    "Tools": TOOL,
}

PROMPT_TOOLKIT_STYLE = Style.from_dict({"user-prompt": "bold ansicyan"}) if Style else None
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class Renderer:
    def __init__(self, use_color: bool | None = None) -> None:
        self.use_color = os.getenv("NO_COLOR") is None if use_color is None else use_color

    def banner(self, model: str, tools: list[str]) -> None:
        title = "Mini Agent TUI"
        print("\n" + self.styled(title, BOLD, TITLE))
        print(self.muted("Commands: /help, /tools, /reset, /exit"))
        print(self.muted(f"Model: {model} | Tools: {', '.join(tools)}\n"))

    def help(self) -> None:
        print(self.section("Help"))
        print(self.styled("  /help        show commands", META))
        print(self.styled("  /tools       list available tools", META))
        print(self.styled("  /session     show current session", META))
        print(self.styled("  /sessions    list saved sessions", META))
        print(self.styled("  /resume ID   resume a saved session by id or unique prefix", META))
        print(self.styled("  /new [name]  start a new saved session", META))
        print(self.styled("  /save        save current session", META))
        print(self.styled("  /delete ID   delete a saved session by id or unique prefix", META))
        print(self.styled("  /reset       clear current session context", META))
        print(self.styled("  /exit        quit", META))
        print(self.styled("  Any other input is sent to the agent.\n", META))

    def user(self, text: str) -> None:
        print(self.section("User"))
        print(self.styled_block(self.wrap(text), USER))

    def step_start(self, step: int, note: str) -> None:
        summary = note.strip() or "Planning next action."
        block = self.styled_block(self.wrap(f"[step {step}] {summary}"), DIM, AGENT)
        self.emit_trace("\n" + block)

    def retrying(self, step: int, attempt: int, max_attempts: int, delay_seconds: float, message: str) -> None:
        text = (
            f"[retry] step {step}: LLM call failed on attempt {attempt}/{max_attempts}; "
            f"retrying in {delay_seconds:.1f}s. {first_line(message)}"
        )
        self.emit_trace("\n" + self.styled_block(self.wrap(text), DIM, NOTICE))

    def tool_call(self, name: str, arguments: str, call_id: str) -> None:
        header = f"{self.styled('[tool call]', BOLD, TOOL)} {self.styled(name, TOOL)}  {self.muted(call_id)}"
        block = "\n".join(
            [
                "\n" + header,
                self.styled("[decision] " + self.describe_tool_decision(name, arguments), DIM, AGENT),
                self.format_json_or_text(arguments, max_chars=1200, style=JSON_TEXT),
            ]
        )
        self.emit_trace(block)

    def observation(self, observation: str) -> None:
        block = f"{self.styled('[observation]', BOLD, OBSERVATION)} {self.format_observation(observation, max_chars=900)}"
        self.emit_trace(block)

    def assistant(self, text: str) -> None:
        print(self.section("Assistant"))
        print(self.styled_block(self.wrap(text or "(empty response)"), ASSISTANT))
        print()

    def error(self, message: str) -> None:
        print("\n" + self.styled(f"[error] {message}\n", BOLD, ERROR))

    def tools(self, tool_names: list[str]) -> None:
        print(self.section("Tools"))
        for name in tool_names:
            print(self.styled(f"  - {name}", TOOL))
        print()

    def session_notice(self, message: str) -> None:
        print(self.styled(message + "\n", NOTICE))

    def session_status(self, session_id: str, name: str, updated_at: str, message_count: int, path: str) -> None:
        print(self.section("Session"))
        print(self.styled(f"  id: {session_id}", META))
        print(self.styled(f"  name: {name}", META))
        print(self.styled(f"  updated: {updated_at}", META))
        print(self.styled(f"  messages: {message_count}", META))
        print(self.styled(f"  file: {path}\n", META))

    def sessions(self, summaries: list[Any]) -> None:
        print(self.section("Sessions"))
        if not summaries:
            print(self.muted("  No saved sessions.\n"))
            return
        for summary in summaries:
            print(
                self.styled(
                    f"  {summary.id}  {summary.updated_at}  messages={summary.message_count}  {summary.name}",
                    META,
                )
            )
        print()

    def reset_notice(self) -> None:
        print(self.styled("Session context reset.\n", NOTICE))

    def prompt(self) -> str:
        # Keep fallback input prompts free of ANSI escapes. Basic terminal line
        # editing often miscalculates cursor movement with ANSI + CJK text.
        return "> "

    def emit_trace(self, text: str) -> None:
        print(text)

    def section(self, name: str) -> str:
        style = SECTION_STYLES.get(name, TITLE)
        return "\n" + self.styled(f"{name}:", BOLD, style)

    def muted(self, text: str) -> str:
        return self.styled(text, DIM, META)

    def styled(self, text: str, *styles: str) -> str:
        if not self.use_color:
            return text
        return "".join(styles) + text + RESET

    def styled_block(self, text: str, *styles: str) -> str:
        if not self.use_color:
            return text
        return "\n".join(self.styled(line, *styles) if line else "" for line in text.splitlines())

    def wrap(self, text: str) -> str:
        width = max(40, shutil.get_terminal_size((100, 24)).columns)
        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            if not paragraph:
                lines.append("")
                continue
            lines.extend(textwrap.wrap(paragraph, width=width, replace_whitespace=False) or [""])
        return "\n".join(lines)

    def format_json_or_text(self, value: str, max_chars: int, style: str = JSON_TEXT) -> str:
        try:
            parsed: Any = json.loads(value)
            text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            text = value
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... <truncated in TUI>"
        return self.styled_block(text, DIM, style)

    def format_observation(self, value: str, max_chars: int, style: str = JSON_TEXT) -> str:
        try:
            parsed: Any = json.loads(value)
        except json.JSONDecodeError:
            return self.format_json_or_text(value, max_chars=max_chars, style=style)

        summary = self.summarize_observation_for_tui(parsed)
        text = summary if summary is not None else json.dumps(parsed, ensure_ascii=False, indent=2)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... <truncated in TUI>"
        return self.styled_block(text, DIM, style)

    def summarize_observation_for_tui(self, parsed: Any) -> str | None:
        if not isinstance(parsed, dict):
            return None
        tool = str(parsed.get("tool", "tool"))
        if not parsed.get("ok"):
            error = parsed.get("error")
            if isinstance(error, dict):
                message = error.get("message", "failed")
                error_type = error.get("type")
                suffix = f" ({error_type})" if error_type else ""
                return f"{tool} failed: {message}{suffix}."
            return f"{tool} failed."

        result = parsed.get("result")
        if not isinstance(result, dict):
            return f"{tool} ok."
        if tool == "list_files":
            return self.summarize_list_files(result)
        if tool == "read_text_file":
            return self.summarize_read_text_file(result)
        if tool == "search_text":
            return self.summarize_search_text(result)
        return f"{tool} ok."

    def summarize_list_files(self, result: dict[str, Any]) -> str:
        entries = result.get("entries", [])
        entry_count = len(entries) if isinstance(entries, list) else 0
        type_counts: dict[str, int] = {}
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    entry_type = str(entry.get("type", "unknown"))
                    type_counts[entry_type] = type_counts.get(entry_type, 0) + 1
        counts = format_counts(type_counts)
        suffix = ", truncated" if result.get("truncated") else ""
        return f"list_files ok: {entry_count} entries under {result.get('path', '.')!r}{counts}{suffix}."

    def summarize_read_text_file(self, result: dict[str, Any]) -> str:
        lines = result.get("lines", [])
        line_count = len(lines) if isinstance(lines, list) else 0
        suffix = ", truncated" if result.get("truncated") else ""
        return (
            f"read_text_file ok: {result.get('path', '<unknown>')!r}, "
            f"{line_count} lines sent to model from line {result.get('start_line', 1)}, "
            f"{result.get('line_count', '?')} total lines{suffix}."
        )

    def summarize_search_text(self, result: dict[str, Any]) -> str:
        matches = result.get("matches", [])
        match_count = len(matches) if isinstance(matches, list) else 0
        paths = {
            str(match.get("path"))
            for match in matches
            if isinstance(match, dict) and match.get("path")
        } if isinstance(matches, list) else set()
        file_part = f" in {len(paths)} files" if paths else ""
        suffix = ", truncated" if result.get("truncated") else ""
        return f"search_text ok: {match_count} matches{file_part} for {result.get('query', '<query>')!r}{suffix}."

    def describe_tool_decision(self, name: str, arguments: str) -> str:
        try:
            args: Any = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}

        if name == "list_files":
            path = args.get("path", ".")
            hidden = " including hidden entries" if args.get("include_hidden") else ""
            return f"Inspect directory {path!r}{hidden} to understand the workspace structure."
        if name == "read_text_file":
            path = args.get("path", "<missing path>")
            start = args.get("start_line", 1)
            max_lines = args.get("max_lines")
            span = f" from line {start}" if not max_lines else f" from line {start}, up to {max_lines} lines"
            return f"Read {path!r}{span} to ground the next answer in file contents."
        if name == "search_text":
            query = args.get("query", "<missing query>")
            path = args.get("path", ".")
            mode = "regex" if args.get("regex") else "literal text"
            return f"Search {path!r} for {mode} {query!r} to find relevant references."
        return "Run a local tool because the model needs workspace facts before answering."


def display_width(text: str) -> int:
    width = 0
    for char in ANSI_RE.sub("", text):
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def format_counts(type_counts: dict[str, int]) -> str:
    if not type_counts:
        return ""
    parts = [f"{key}={type_counts[key]}" for key in sorted(type_counts)]
    return " (" + ", ".join(parts) + ")"


def read_user_input(prompt: str = "> ", use_color: bool = True) -> str:
    if toolkit_prompt and sys.stdin.isatty() and sys.stdout.isatty():
        if use_color and PROMPT_TOOLKIT_STYLE:
            return toolkit_prompt([("class:user-prompt", prompt)], style=PROMPT_TOOLKIT_STYLE).strip()
        return toolkit_prompt(prompt).strip()
    return input(prompt).strip()
