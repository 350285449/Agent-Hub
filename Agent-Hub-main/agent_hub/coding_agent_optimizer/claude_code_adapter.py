from __future__ import annotations

from .prompt_compactor import compact_prompt
from .tool_schema_minifier import minify_tool_schemas


def prepare_claude_code_prompt(prompt: str, *, mode: str = "quality_first", tools: list[dict] | None = None) -> dict[str, object]:
    result = {"adapter": "claude_code", **compact_prompt(prompt, mode=mode)}
    if tools is not None:
        result["tools"] = minify_tool_schemas(tools)
    return result
