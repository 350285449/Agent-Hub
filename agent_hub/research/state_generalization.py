from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent_state_vector import AgentStateVector, feature_names, records_from_vectors
from .state_space_theory import evaluate_records, train_and_predict
from .telemetry import research_dir


def compute_state_generalization(vectors: list[AgentStateVector]) -> dict[str, Any]:
    records = records_from_vectors(vectors)
    return {
        "object": "agent_hub.research.state_generalization",
        "row_count": len(records),
        "unseen_repository": _leave_one_group(records, "repository"),
        "unseen_task_type": _leave_one_group(records, "task_type"),
        "unseen_model": _leave_one_group(records, "model"),
        "cold_start": _cold_start(records),
        "warm_start": _warm_start(records),
        "interpretation": "Leave-one-group-out tests train on all other groups and score the held-out group. Cold start zeroes history features.",
    }


def export_state_generalization(state_dir: str | Path, vectors: list[AgentStateVector]) -> tuple[Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_state_generalization(vectors)
    path = directory / "state_generalization.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path, payload


def _leave_one_group(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        groups.setdefault(str(record.get(key) or "unknown"), []).append(index)
    selected = [(name, indexes) for name, indexes in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True) if len(indexes) >= 5][:8]
    families = {
        "structure_only": "structure_only",
        "history_only": "history_only",
        "structure_history": "structure_history",
        "model_task_context_compatibility": "compatibility",
        "state_space_model": "state_space",
    }
    results: dict[str, Any] = {family: [] for family in families}
    for name, indexes in selected:
        test_ids = set(indexes)
        train = [record for index, record in enumerate(records) if index not in test_ids]
        test = [record for index, record in enumerate(records) if index in test_ids]
        for family, feature_family in families.items():
            names = _family_feature_names(records, feature_family)
            stats = train_and_predict(train, test, names, "success")
            stats["group"] = name
            stats["rows"] = len(test)
            results[family].append(stats)
    return {family: _weighted_average(rows) for family, rows in results.items()} | {"folds": {family: rows for family, rows in results.items()}}


def _cold_start(records: list[dict[str, Any]]) -> dict[str, Any]:
    cold = [_zero_history(record) for record in records]
    return {
        "structure_only": evaluate_records(cold, _family_feature_names(cold, "structure_only")),
        "state_space_zero_history": evaluate_records(cold, _family_feature_names(cold, "state_space")),
    }


def _warm_start(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "history_only": evaluate_records(records, _family_feature_names(records, "history_only")),
        "state_space": evaluate_records(records, _family_feature_names(records, "state_space")),
    }


def _zero_history(record: dict[str, Any]) -> dict[str, Any]:
    copy = {**record, "features": dict(record["features"])}
    for key in list(copy["features"]):
        if key.startswith("history."):
            copy["features"][key] = 0.0
    return copy


def _family_feature_names(records: list[dict[str, Any]], family: str) -> list[str]:
    if not records:
        return []
    names = sorted(records[0]["features"])
    if family == "structure_only":
        return [name for name in names if name.startswith("structure.")]
    if family == "history_only":
        return [name for name in names if name.startswith("history.")]
    if family == "structure_history":
        return [name for name in names if name.startswith(("structure.", "history."))]
    if family == "compatibility":
        return [name for name in names if name.startswith("compatibility.")]
    return names


def _weighted_average(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"correlation": 0.0, "r2": 0.0, "mae": 0.0, "rmse": 0.0, "calibration_error": 0.0, "rows": 0}
    total = sum(int(row.get("rows", 0)) for row in rows) or len(rows)
    return {
        metric: round(sum(float(row.get(metric, 0.0)) * int(row.get("rows", 1)) for row in rows) / total, 6)
        for metric in ("correlation", "r2", "mae", "rmse", "calibration_error")
    } | {"rows": total}


__all__ = ["compute_state_generalization", "export_state_generalization"]
