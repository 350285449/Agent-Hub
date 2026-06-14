from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def reports_dir(config: Any) -> Path:
    return Path(config.state_dir) / "benchmark_reports"


def write_benchmark_report(config: Any, payload: dict[str, Any], *, name: str | None = None) -> Path:
    directory = reports_dir(config)
    directory.mkdir(parents=True, exist_ok=True)
    report_name = name or f"benchmark-{int(time.time())}.json"
    path = directory / report_name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def ledger_savings_summary(summary: dict[str, Any]) -> dict[str, Any]:
    baselines = summary.get("baseline_savings") if isinstance(summary.get("baseline_savings"), list) else []
    positive = [row for row in baselines if isinstance(row, dict) and float(row.get("savings_usd") or 0.0) > 0]
    preferred = _preferred_baseline(positive)
    cost_avoided = float(preferred.get("savings_usd") or 0.0) if preferred else 0.0
    tokens_saved = int(preferred.get("tokens_saved") or 0) if preferred else 0
    recent = summary.get("recent_requests") if isinstance(summary.get("recent_requests"), list) else []
    best = _model_from_recent(recent, success=True)
    worst = _model_from_recent(recent, success=False)
    retries_avoided = sum(max(0, int(row.get("failover_count") or 0)) for row in recent if isinstance(row, dict))
    return {
        "tokens_saved": tokens_saved,
        "cost_avoided_usd": round(cost_avoided, 8),
        "retries_avoided": retries_avoided,
        "best_model_for_repo": best,
        "worst_model_for_repo": worst,
        "baseline_savings": baselines,
    }


def _preferred_baseline(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    for name in ("vs_user_default_model", "vs_static_routing", "vs_claude_sonnet", "vs_gpt_4_1"):
        for row in rows:
            if row.get("baseline_name") == name:
                return row
    return max(rows, key=lambda row: float(row.get("savings_usd") or 0.0))


def _model_from_recent(rows: list[Any], *, success: bool) -> str | None:
    for row in rows:
        if isinstance(row, dict) and bool(row.get("success")) is success:
            return " / ".join(str(row.get(key) or "") for key in ("selected_provider", "selected_model") if row.get(key)) or None
    return None
