from __future__ import annotations

from .context_digest import digest_context
from .savings_estimator import estimate_savings


MODES = ("save_codex_calls", "save_codex_tokens", "maximum_savings", "quality_first")


def compact_prompt(prompt: str, *, mode: str = "save_codex_tokens") -> dict[str, object]:
    limits = {
        "save_codex_calls": 6000,
        "save_codex_tokens": 4000,
        "maximum_savings": 2200,
        "quality_first": 9000,
    }
    selected_mode = mode if mode in MODES else "save_codex_tokens"
    max_chars = limits.get(selected_mode, limits["save_codex_tokens"])
    compacted = digest_context(prompt, max_chars=max_chars)
    original_tokens = _tokens(prompt)
    optimized_tokens = _tokens(compacted)
    return {
        "mode": selected_mode,
        "prompt": compacted,
        "original_chars": len(prompt or ""),
        "compacted_chars": len(compacted),
        "chars_saved": max(0, len(prompt or "") - len(compacted)),
        "original_tokens_estimated": original_tokens,
        "optimized_tokens_estimated": optimized_tokens,
        "savings": estimate_savings(original_tokens=original_tokens, optimized_tokens=optimized_tokens),
        "strategy": _strategy(selected_mode),
    }


def _tokens(text: str) -> int:
    return max(0, (len(text or "") + 3) // 4)


def _strategy(mode: str) -> dict[str, object]:
    strategies = {
        "save_codex_calls": {
            "goal": "Avoid repeat calls by keeping enough task context for a complete attempt.",
            "tool_schema": "minified",
            "context": "balanced digest",
        },
        "save_codex_tokens": {
            "goal": "Minimize prompt tokens while preserving task and error lines.",
            "tool_schema": "minified",
            "context": "compact digest",
        },
        "maximum_savings": {
            "goal": "Use the smallest viable prompt for low-risk edits.",
            "tool_schema": "aggressively minified",
            "context": "head/tail plus important lines",
        },
        "quality_first": {
            "goal": "Preserve more repository context for hard tasks.",
            "tool_schema": "standard",
            "context": "wide digest",
        },
    }
    return dict(strategies.get(mode, strategies["save_codex_tokens"]))
