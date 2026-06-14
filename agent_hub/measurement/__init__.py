from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_LEGACY_PATH = Path(__file__).resolve().parent.parent / "measurement.py"
_SPEC = importlib.util.spec_from_file_location("agent_hub._measurement_legacy", _LEGACY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load measurement ledger from {_LEGACY_PATH}")
_legacy = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _legacy
_SPEC.loader.exec_module(_legacy)

for _name in getattr(_legacy, "__all__", []):
    globals()[_name] = getattr(_legacy, _name)


def metrics_summary(config: Any, *, limit: int = 25) -> dict[str, Any]:
    from .benchmark_report import ledger_savings_summary

    summary = usage_ledger_summary(config, limit=limit)
    savings = ledger_savings_summary(summary)
    return {
        "object": "agent_hub.metrics.summary",
        "usage_ledger": summary,
        "savings": savings,
        "request_count": summary.get("request_count", 0),
        "tokens_saved": savings.get("tokens_saved", 0),
        "cost_avoided_usd": savings.get("cost_avoided_usd", 0.0),
        "retries_avoided": savings.get("retries_avoided", 0),
        "best_model_for_repo": savings.get("best_model_for_repo"),
        "worst_model_for_repo": savings.get("worst_model_for_repo"),
    }


def metrics_savings(config: Any) -> dict[str, Any]:
    from .benchmark_report import ledger_savings_summary

    return {
        "object": "agent_hub.metrics.savings",
        **ledger_savings_summary(usage_ledger_summary(config)),
    }


__all__ = [*getattr(_legacy, "__all__", []), "metrics_summary", "metrics_savings"]
