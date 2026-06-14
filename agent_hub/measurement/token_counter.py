from __future__ import annotations

from typing import Any


def estimate_text_tokens(text: str) -> int:
    return max(0, (len(text or "") + 3) // 4)


def estimate_messages_tokens(messages: list[dict[str, Any]] | None) -> int:
    total = 0
    for message in messages or []:
        content = message.get("content") if isinstance(message, dict) else ""
        if isinstance(content, list):
            total += sum(estimate_text_tokens(str(part)) for part in content)
        else:
            total += estimate_text_tokens(str(content or ""))
    return total


def normalize_usage(usage: dict[str, Any] | None, *, fallback_input: int = 0, fallback_output: int = 0) -> dict[str, int]:
    usage = usage or {}
    input_tokens = _int(usage.get("prompt_tokens"), usage.get("input_tokens"), fallback_input)
    output_tokens = _int(usage.get("completion_tokens"), usage.get("output_tokens"), fallback_output)
    total = _int(usage.get("total_tokens"), input_tokens + output_tokens)
    if total and not output_tokens and input_tokens:
        output_tokens = max(0, total - input_tokens)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}


def _int(*values: Any) -> int:
    for value in values:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0
