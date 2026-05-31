"""JSON-backed session persistence for the terminal agent."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class SessionError(RuntimeError):
    """Raised when a session cannot be loaded or saved."""


@dataclass
class SessionRecord:
    id: str
    name: str
    created_at: str
    updated_at: str
    model: str
    workspace: str
    messages: list[dict[str, Any]]

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
            "workspace": self.workspace,
            "messages": self.messages,
        }


@dataclass
class SessionSummary:
    id: str
    name: str
    updated_at: str
    model: str
    message_count: int


class SessionStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SessionError(f"Could not create session directory {self.root}: {exc}") from exc

    def create(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        workspace: str | Path,
        name: str | None = None,
    ) -> SessionRecord:
        now = timestamp()
        session_id = self.new_session_id()
        return SessionRecord(
            id=session_id,
            name=name or f"session-{session_id}",
            created_at=now,
            updated_at=now,
            model=model,
            workspace=str(Path(workspace).resolve()),
            messages=clone_messages(messages),
        )

    def save(self, record: SessionRecord, messages: list[dict[str, Any]]) -> SessionRecord:
        updated = SessionRecord(
            id=record.id,
            name=record.name,
            created_at=record.created_at,
            updated_at=timestamp(),
            model=record.model,
            workspace=record.workspace,
            messages=clone_messages(messages),
        )
        path = self.path_for(updated.id)
        temp_path = path.with_suffix(".json.tmp")
        try:
            temp_path.write_text(json.dumps(updated.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp_path.replace(path)
        except OSError as exc:
            raise SessionError(f"Could not save session {updated.id}: {exc}") from exc
        return updated

    def load(self, session_id_or_prefix: str) -> SessionRecord:
        session_id = self.resolve_id(session_id_or_prefix)
        path = self.path_for(session_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SessionError(f"No session found for {session_id_or_prefix!r}") from exc
        except json.JSONDecodeError as exc:
            raise SessionError(f"Session file is not valid JSON: {path}") from exc
        return record_from_json(data, path)

    def delete(self, session_id_or_prefix: str) -> str:
        session_id = self.resolve_id(session_id_or_prefix)
        path = self.path_for(session_id)
        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise SessionError(f"No session found for {session_id_or_prefix!r}") from exc
        except OSError as exc:
            raise SessionError(f"Could not delete session {session_id}: {exc}") from exc
        return session_id

    def list(self) -> list[SessionSummary]:
        summaries: list[SessionSummary] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                record = record_from_json(json.loads(path.read_text(encoding="utf-8")), path)
            except (OSError, json.JSONDecodeError, SessionError):
                continue
            summaries.append(
                SessionSummary(
                    id=record.id,
                    name=record.name,
                    updated_at=record.updated_at,
                    model=record.model,
                    message_count=record.message_count,
                )
            )
        return sorted(summaries, key=lambda summary: summary.updated_at, reverse=True)

    def path_for(self, session_id: str) -> Path:
        if not is_safe_session_id(session_id):
            raise SessionError(f"Invalid session id: {session_id!r}")
        return self.root / f"{session_id}.json"

    def resolve_id(self, session_id_or_prefix: str) -> str:
        key = session_id_or_prefix.strip()
        if not key:
            raise SessionError("Session id is required")
        if not is_safe_session_id(key):
            raise SessionError("Session id must contain only letters, numbers, '_' or '-'")
        exact = self.path_for(key)
        if exact.exists():
            return key

        matches = [path.stem for path in self.root.glob(f"{key}*.json") if is_safe_session_id(path.stem)]
        if not matches:
            raise SessionError(f"No session found for prefix {key!r}")
        if len(matches) > 1:
            preview = ", ".join(sorted(matches)[:5])
            raise SessionError(f"Session prefix {key!r} is ambiguous: {preview}")
        return matches[0]

    def new_session_id(self) -> str:
        for _ in range(20):
            session_id = uuid.uuid4().hex[:12]
            if not self.path_for(session_id).exists():
                return session_id
        raise SessionError("Could not allocate a unique session id")


def record_from_json(data: dict[str, Any], path: Path) -> SessionRecord:
    if not isinstance(data, dict):
        raise SessionError(f"Session file must contain a JSON object: {path}")
    if data.get("version") != 1:
        raise SessionError(f"Unsupported session version in {path}")

    messages = data.get("messages")
    if not isinstance(messages, list) or not all(isinstance(message, dict) for message in messages):
        raise SessionError(f"Session messages are invalid in {path}")
    if messages and messages[0].get("role") != "system":
        raise SessionError(f"Session messages must start with a system message: {path}")

    session_id = require_string(data, "id", path)
    if not is_safe_session_id(session_id):
        raise SessionError(f"Invalid session id in {path}")

    return SessionRecord(
        id=session_id,
        name=require_string(data, "name", path),
        created_at=require_string(data, "created_at", path),
        updated_at=require_string(data, "updated_at", path),
        model=require_string(data, "model", path),
        workspace=require_string(data, "workspace", path),
        messages=clone_messages(messages),
    )


def require_string(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise SessionError(f"Session field {key!r} must be a string in {path}")
    return value


def clone_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(messages, ensure_ascii=False))


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def is_safe_session_id(session_id: str) -> bool:
    return bool(session_id) and all(char.isalnum() or char in {"_", "-"} for char in session_id)
