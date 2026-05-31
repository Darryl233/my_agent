"""Tool registry used by the agent loop."""

from __future__ import annotations

from pathlib import Path

from agent_tui.tools.base import JsonObject, Tool, ToolError, observation
from agent_tui.tools.workspace import build_workspace_tools


class ToolRegistry:
    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self._tools = build_tools(self.workspace_root)

    @property
    def schemas(self) -> list[JsonObject]:
        return [tool.schema() for tool in self._tools.values()]

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def execute(self, name: str, raw_arguments: str | JsonObject | None) -> str:
        tool = self._tools.get(name)
        if not tool:
            return observation(False, name, error_type="unknown_tool", message=f"No tool named {name!r}")

        try:
            result = tool.run(raw_arguments)
            return observation(True, name, result=result)
        except ToolError as exc:
            return observation(False, name, error_type="validation_or_execution_error", message=str(exc))
        except Exception as exc:  # Defensive: never let a local tool crash the loop.
            return observation(False, name, error_type=exc.__class__.__name__, message=str(exc))


def build_tools(workspace_root: Path) -> dict[str, Tool]:
    tools: dict[str, Tool] = {}
    tools.update(build_workspace_tools(workspace_root))
    return tools

