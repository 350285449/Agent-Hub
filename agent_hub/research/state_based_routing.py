from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent_state_vector import AgentStateVector, records_from_vectors
from .telemetry import research_dir


def evaluate_state_based_routing(vectors: list[AgentStateVector]) -> dict[str, Any]:
    from .state_space_theory import fit_model, predict_with_model

    records = records_from_vectors(vectors)
    features = sorted(records[0]["features"]) if records else []
    model = fit_model(records, features, "success")
    for record in records:
        record["predicted_success"] = predict_with_model(model, record)
    groups = _decision_groups(records)
    strategies = {
        "state_based": lambda rows: max(rows, key=lambda row: (row["predicted_success"], -float(row.get("estimated_cost", 0.0)))),
        "default_routing": lambda rows: rows[0],
        "cheapest_routing": lambda rows: min(rows, key=lambda row: float(row.get("estimated_cost", 0.0))),
        "fastest_routing": lambda rows: min(rows, key=lambda row: float(row.get("latency_ms", 0.0))),
        "historical_best_routing": _historical_best,
    }
    return {
        "object": "agent_hub.research.state_based_routing",
        "decision_groups": len(groups),
        "candidate_rows": sum(len(rows) for rows in groups),
        "strategies": {name: _score([chooser(rows) for rows in groups]) for name, chooser in strategies.items()},
        "notes": [
            "Routing is an offline counterfactual over observed alternatives sharing repository, task type, task key, and similar context plan.",
            "Estimated cost uses local provider/model heuristics when explicit cost telemetry is absent.",
        ],
    }


def export_state_based_routing(state_dir: str | Path, vectors: list[AgentStateVector]) -> tuple[Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = evaluate_state_based_routing(vectors)
    path = directory / "state_based_routing.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path, payload


def _decision_groups(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (str(record.get("repository")), str(record.get("task_type")), str(record.get("task_key")))
        groups.setdefault(key, []).append(record)
    return [rows for rows in groups.values() if len({row["model"] for row in rows}) > 1 or len({row["route"] for row in rows}) > 1]


def _historical_best(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def score(row: dict[str, Any]) -> tuple[float, float]:
        features = row.get("features", {})
        return (
            float(features.get("history.model_task.success_rate", features.get("history.model.success_rate", 0.5))),
            -float(row.get("estimated_cost", 0.0)),
        )

    return max(rows, key=score)


def _score(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"success_rate": 0.0, "validation_score": 0.0, "latency_ms": 0.0, "error_rate": 0.0, "estimated_cost": 0.0}
    n = len(rows)
    return {
        "success_rate": round(sum(float(row.get("success", 0.0)) for row in rows) / n, 6),
        "validation_score": round(sum(float(row.get("validation_score", 0.0)) for row in rows) / n, 6),
        "latency_ms": round(sum(float(row.get("latency_ms", 0.0)) for row in rows) / n, 3),
        "error_rate": round(sum(float(row.get("error", row.get("failure", 0.0))) for row in rows) / n, 6),
        "estimated_cost": round(sum(float(row.get("estimated_cost", 0.0)) for row in rows) / n, 8),
    }


__all__ = ["evaluate_state_based_routing", "export_state_based_routing"]
