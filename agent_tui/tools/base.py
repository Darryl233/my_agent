"""Common tool types, validation, and observation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


class ToolError(ValueError):
    """Raised when a tool cannot validate or execute a request."""


JsonObject = dict[str, Any]
ToolFunc = Callable[[JsonObject], JsonObject]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: JsonObject
    handler: ToolFunc

    def schema(self) -> JsonObject:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, raw_arguments: str | JsonObject | None) -> JsonObject:
        arguments = parse_arguments(raw_arguments)
        validated = validate_arguments(self.parameters, arguments)
        return self.handler(validated)


def parse_arguments(raw_arguments: str | JsonObject | None) -> JsonObject:
    if raw_arguments in (None, ""):
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str):
        raise ToolError("Tool arguments must be a JSON object or a JSON string")
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ToolError(f"Tool arguments are not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ToolError("Tool arguments must decode to a JSON object")
    return parsed


def validate_arguments(schema: JsonObject, arguments: JsonObject) -> JsonObject:
    if schema.get("type") != "object":
        raise ToolError("Tool schema must be an object")

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    additional = schema.get("additionalProperties", True)
    validated: JsonObject = {}

    for key in required:
        if key not in arguments:
            raise ToolError(f"Missing required argument: {key}")

    for key, value in arguments.items():
        if key not in properties:
            if additional:
                validated[key] = value
                continue
            raise ToolError(f"Unexpected argument: {key}")
        validated[key] = validate_value(key, value, properties[key])

    for key, prop_schema in properties.items():
        if key not in validated and "default" in prop_schema:
            validated[key] = prop_schema["default"]

    return validated


def validate_value(name: str, value: Any, schema: JsonObject) -> Any:
    expected = schema.get("type")
    if expected == "string":
        if not isinstance(value, str):
            raise ToolError(f"{name} must be a string")
        if "enum" in schema and value not in schema["enum"]:
            raise ToolError(f"{name} must be one of {schema['enum']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ToolError(f"{name} is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ToolError(f"{name} is too long")
        return value
    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolError(f"{name} must be an integer")
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolError(f"{name} must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolError(f"{name} must be <= {schema['maximum']}")
        return value
    if expected == "boolean":
        if not isinstance(value, bool):
            raise ToolError(f"{name} must be a boolean")
        return value
    if expected == "array":
        if not isinstance(value, list):
            raise ToolError(f"{name} must be an array")
        return value
    if expected == "object":
        if not isinstance(value, dict):
            raise ToolError(f"{name} must be an object")
        return value
    return value


def observation(ok: bool, tool: str, result: JsonObject | None = None, error_type: str | None = None, message: str | None = None) -> str:
    payload: JsonObject = {"ok": ok, "tool": tool}
    if ok:
        payload["result"] = result or {}
    else:
        payload["error"] = {"type": error_type or "tool_error", "message": message or "Tool failed"}
    return json.dumps(payload, ensure_ascii=False, indent=2)

