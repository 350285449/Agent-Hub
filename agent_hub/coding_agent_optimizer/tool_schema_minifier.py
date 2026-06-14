from __future__ import annotations

from typing import Any


def minify_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    keep = {key: schema.get(key) for key in ("name", "description", "parameters") if key in schema}
    parameters = keep.get("parameters")
    if isinstance(parameters, dict) and isinstance(parameters.get("properties"), dict):
        keep["parameters"] = {
            "type": parameters.get("type", "object"),
            "properties": {
                key: {"type": value.get("type", "string"), "description": value.get("description", "")}
                for key, value in parameters["properties"].items()
                if isinstance(value, dict)
            },
            "required": list(parameters.get("required") or []),
        }
    return keep


def minify_tool_schemas(schemas: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [minify_tool_schema(schema) for schema in schemas or [] if isinstance(schema, dict)]
