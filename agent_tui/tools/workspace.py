"""Workspace inspection tools."""

from __future__ import annotations

import os
import re
from pathlib import Path

from agent_tui.tools.base import JsonObject, Tool, ToolError


def build_workspace_tools(workspace_root: Path) -> dict[str, Tool]:
    def bounded(path_text: str) -> Path:
        return resolve_workspace_path(workspace_root, path_text)

    def list_files(args: JsonObject) -> JsonObject:
        base = bounded(args["path"])
        max_results = args["max_results"]
        include_hidden = args["include_hidden"]
        if not base.exists():
            raise ToolError(f"Path does not exist: {args['path']}")
        if not base.is_dir():
            raise ToolError(f"Path is not a directory: {args['path']}")

        entries: list[JsonObject] = []
        for current, dirnames, filenames in os.walk(base, followlinks=False):
            current_path = Path(current)
            if not include_hidden:
                dirnames[:] = [name for name in dirnames if not is_hidden(name)]
                filenames = [name for name in filenames if not is_hidden(name)]

            for dirname in sorted(dirnames):
                child = (current_path / dirname).resolve()
                if not is_inside(workspace_root, child):
                    continue
                entries.append(format_entry(workspace_root, child))
                if len(entries) >= max_results:
                    return {"path": relpath(workspace_root, base), "entries": entries, "truncated": True}

            for filename in sorted(filenames):
                child = (current_path / filename).resolve()
                if not is_inside(workspace_root, child):
                    continue
                entries.append(format_entry(workspace_root, child))
                if len(entries) >= max_results:
                    return {"path": relpath(workspace_root, base), "entries": entries, "truncated": True}

        return {"path": relpath(workspace_root, base), "entries": entries, "truncated": False}

    def read_text_file(args: JsonObject) -> JsonObject:
        path = bounded(args["path"])
        start_line = args["start_line"]
        max_lines = args["max_lines"]
        if not path.exists():
            raise ToolError(f"File does not exist: {args['path']}")
        if not path.is_file():
            raise ToolError(f"Path is not a file: {args['path']}")
        if path.stat().st_size > 2_000_000:
            raise ToolError("File is larger than 2 MB; narrow the request")

        data = path.read_bytes()
        if b"\x00" in data:
            raise ToolError("File appears to be binary")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        start_index = max(0, start_line - 1)
        selected = lines[start_index : start_index + max_lines]
        numbered = [{"line": start_index + idx + 1, "text": line} for idx, line in enumerate(selected)]
        return {
            "path": relpath(workspace_root, path),
            "line_count": len(lines),
            "start_line": start_line,
            "lines": numbered,
            "truncated": start_index + max_lines < len(lines),
        }

    def search_text(args: JsonObject) -> JsonObject:
        base = bounded(args["path"])
        query = args["query"]
        max_results = args["max_results"]
        regex = args["regex"]
        case_sensitive = args["case_sensitive"]
        if not query:
            raise ToolError("query must not be empty")
        if not base.exists():
            raise ToolError(f"Path does not exist: {args['path']}")

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query if regex else re.escape(query), flags)
        except re.error as exc:
            raise ToolError(f"Invalid regular expression: {exc}") from exc
        files = [base] if base.is_file() else iter_text_files(workspace_root, base)
        matches: list[JsonObject] = []

        for path in files:
            if path.stat().st_size > 1_000_000:
                continue
            data = path.read_bytes()
            if b"\x00" in data:
                continue
            for line_number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
                if pattern.search(line):
                    matches.append({"path": relpath(workspace_root, path), "line": line_number, "text": line[:300]})
                    if len(matches) >= max_results:
                        return {"query": query, "matches": matches, "truncated": True}

        return {"query": query, "matches": matches, "truncated": False}

    return {
        "list_files": Tool(
            name="list_files",
            description="List files and directories under a workspace path. Use this to inspect project structure.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative directory path.", "default": "."},
                    "max_results": {"type": "integer", "description": "Maximum entries to return.", "minimum": 1, "maximum": 200, "default": 80},
                    "include_hidden": {"type": "boolean", "description": "Whether to include hidden files and directories.", "default": False},
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=list_files,
        ),
        "read_text_file": Tool(
            name="read_text_file",
            description="Read a UTF-8 text file from the workspace with line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "start_line": {"type": "integer", "description": "1-based first line to read.", "minimum": 1, "maximum": 100000, "default": 1},
                    "max_lines": {"type": "integer", "description": "Maximum lines to return.", "minimum": 1, "maximum": 300, "default": 120},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=read_text_file,
        ),
        "search_text": Tool(
            name="search_text",
            description="Search text files in the workspace for a literal string or regular expression.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or regex pattern to search for.", "minLength": 1, "maxLength": 200},
                    "path": {"type": "string", "description": "Workspace-relative file or directory path.", "default": "."},
                    "max_results": {"type": "integer", "description": "Maximum matches to return.", "minimum": 1, "maximum": 100, "default": 50},
                    "regex": {"type": "boolean", "description": "Treat query as a Python regular expression.", "default": False},
                    "case_sensitive": {"type": "boolean", "description": "Use case-sensitive matching.", "default": False},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=search_text,
        ),
    }


def resolve_workspace_path(workspace_root: Path, path_text: str) -> Path:
    candidate = (workspace_root / path_text).resolve()
    if not is_inside(workspace_root, candidate):
        raise ToolError(f"Path escapes workspace: {path_text}")
    return candidate


def is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def is_hidden(name: str) -> bool:
    return name.startswith(".")


def iter_text_files(workspace_root: Path, base: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [name for name in dirnames if not is_hidden(name)]
        for filename in sorted(name for name in filenames if not is_hidden(name)):
            path = (Path(current) / filename).resolve()
            if path.is_file() and is_inside(workspace_root, path):
                files.append(path)
    return files


def format_entry(workspace_root: Path, path: Path) -> JsonObject:
    kind = "dir" if path.is_dir() else "file"
    size = path.stat().st_size if path.is_file() else None
    return {"path": relpath(workspace_root, path), "type": kind, "size_bytes": size}


def relpath(workspace_root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(workspace_root)
    return "." if str(relative) == "." else relative.as_posix()

