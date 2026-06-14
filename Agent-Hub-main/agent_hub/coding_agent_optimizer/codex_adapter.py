from __future__ import annotations

from .prompt_compactor import compact_prompt
from .tool_schema_minifier import minify_tool_schemas


def prepare_codex_prompt(prompt: str, *, mode: str = "save_codex_tokens", tools: list[dict] | None = None) -> dict[str, object]:
    result = {"adapter": "codex", **compact_prompt(prompt, mode=mode)}
    if tools is not None:
        result["tools"] = minify_tool_schemas(tools)
    return result
