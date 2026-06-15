from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .ablation import context_ablation_path
from .telemetry import research_dir


def compute_context_strategy_comparison(state_dir: str | Path) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(state_dir):
        grouped[str(row.get("context_strategy") or "default_context")].append(row)
    strategies = {name: _summary(rows) for name, rows in sorted(grouped.items())}
    return {
        "object": "agent_hub.research.context_strategy_comparison",
        "strategies": strategies,
        "winner_by_success_per_1k_tokens": _winner(strategies, "success_per_1k_tokens"),
        "winner_by_validation_score": _winner(strategies, "average_validation_score"),
    }


def export_context_strategy_comparison(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = compute_context_strategy_comparison(state_dir)
    json_path = directory / "context_strategy_comparison.json"
    md_path = directory / "context_strategy_comparison.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _rows(state_dir: str | Path) -> list[dict[str, Any]]:
    path = context_ablation_path(state_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(raw)
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successes = sum(1 for row in rows if row.get("success") is True)
    tokens = sum(_float(row.get("context_token_count")) for row in rows)
    validation = [_float(row.get("validation_score")) for row in rows]
    return {
        "runs": len(rows),
        "success_rate": round(successes / len(rows), 6) if rows else 0.0,
        "average_validation_score": round(sum(validation) / len(validation), 6) if validation else 0.0,
        "average_context_tokens": round(tokens / len(rows), 6) if rows else 0.0,
        "total_context_tokens": int(tokens),
        "success_per_1k_tokens": round(successes / max(1.0, tokens / 1000.0), 6),
    }


def _winner(strategies: dict[str, dict[str, Any]], metric: str) -> str:
    if not strategies:
        return "not_enough_data"
    return max(strategies.items(), key=lambda item: float(item[1].get(metric) or 0.0))[0]


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Context Strategy Comparison",
        "",
        f"Winner by success per 1k tokens: `{payload.get('winner_by_success_per_1k_tokens')}`",
        f"Winner by validation score: `{payload.get('winner_by_validation_score')}`",
        "",
        "| strategy | runs | success_rate | average_validation_score | average_context_tokens | success_per_1k_tokens |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    strategies = payload.get("strategies") if isinstance(payload.get("strategies"), dict) else {}
    for name, row in strategies.items():
        lines.append(
            f"| {name} | {row.get('runs')} | {row.get('success_rate')} | {row.get('average_validation_score')} | {row.get('average_context_tokens')} | {row.get('success_per_1k_tokens')} |"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = ["compute_context_strategy_comparison", "export_context_strategy_comparison"]
