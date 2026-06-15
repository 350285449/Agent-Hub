from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .ablation import context_ablation_path
from .analysis import CONTEXT_BUCKETS, context_bucket
from .dataset import dataset_path
from .telemetry import research_dir


def compute_context_efficiency_curve(state_dir: str | Path) -> list[dict[str, Any]]:
    rows = [*_dataset_rows(state_dir), *_ablation_rows(state_dir)]
    grouped = {label: [] for label, _lower, _upper in CONTEXT_BUCKETS}
    for row in rows:
        grouped[context_bucket(row["tokens"])].append(row)
    curve: list[dict[str, Any]] = []
    previous_success = 0.0
    previous_validation = 0.0
    for label, _lower, _upper in CONTEXT_BUCKETS:
        items = grouped[label]
        success_rate = _rate(sum(1 for item in items if item["success"]), len(items))
        validation = _average(item["validation_score"] for item in items)
        curve.append(
            {
                "context_bucket": label,
                "average_tokens": _average(item["tokens"] for item in items),
                "success_rate": success_rate,
                "average_validation_score": validation,
                "marginal_success_gain": round(success_rate - previous_success, 6) if curve else 0.0,
                "marginal_validation_gain": round(validation - previous_validation, 6) if curve else 0.0,
                "runs": len(items),
            }
        )
        previous_success = success_rate
        previous_validation = validation
    return curve


def export_context_efficiency_curve(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    curve = compute_context_efficiency_curve(state_dir)
    json_path = directory / "context_efficiency_curve.json"
    md_path = directory / "context_efficiency_curve.md"
    json_path.write_text(
        json.dumps({"object": "agent_hub.research.context_efficiency_curve", "curve": curve}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    md_path.write_text(_markdown(curve), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _dataset_rows(state_dir: str | Path) -> list[dict[str, Any]]:
    path = dataset_path(state_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "tokens": _int(row.get("context_tokens")),
                    "success": str(row.get("success")).lower() in {"true", "1", "yes"},
                    "validation_score": _float(row.get("validation_score")),
                }
            )
    return rows


def _ablation_rows(state_dir: str | Path) -> list[dict[str, Any]]:
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
        rows.append(
            {
                "tokens": _int(raw.get("tokens_used")),
                "success": bool(raw.get("success")),
                "validation_score": _float(raw.get("validation_score")),
            }
        )
    return rows


def _markdown(curve: list[dict[str, Any]]) -> str:
    lines = [
        "# Context Efficiency Curve",
        "",
        "| context_bucket | average_tokens | success_rate | average_validation_score | marginal_success_gain | marginal_validation_gain |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in curve:
        lines.append(
            "| {context_bucket} | {average_tokens} | {success_rate} | {average_validation_score} | {marginal_success_gain} | {marginal_validation_gain} |".format(
                **row
            )
        )
    lines.append("")
    return "\n".join(lines)


def _average(values: Any) -> float:
    rows = [float(value) for value in values]
    return round(sum(rows) / len(rows), 6) if rows else 0.0


def _rate(count: int, total: int) -> float:
    return round(count / total, 6) if total else 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["compute_context_efficiency_curve", "export_context_efficiency_curve"]
