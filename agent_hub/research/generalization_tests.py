from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .structure_vs_experience import train_predict
from .telemetry import research_dir


def compute_generalization_results(structure: dict[str, Any], experience: dict[str, Any], combined: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "agent_hub.research.generalization_results",
        "unseen_repositories": _split_eval(structure, experience, combined, "repository"),
        "unseen_tasks": _split_eval(structure, experience, combined, "task_type"),
        "interpretation": "generalization tested by leave-one-group-out splits",
    }


def export_generalization_results(
    state_dir: str | Path,
    structure: dict[str, Any],
    experience: dict[str, Any],
    combined: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_generalization_results(structure, experience, combined)
    json_path = directory / "generalization_results.json"
    md_path = directory / "generalization_results.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(generalization_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def generalization_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Generalization Results", "", f"- Interpretation: {payload['interpretation']}", ""]
    for section in ("unseen_repositories", "unseen_tasks"):
        lines.extend([f"## {section.replace('_', ' ').title()}", "", "| predictor | correlation | R2 | MAE | RMSE |", "| --- | --- | --- | --- | --- |"])
        for predictor in ("structure", "experience", "combined"):
            row = payload[section][predictor]
            lines.append(f"| {predictor} | {row['correlation']} | {row['r2']} | {row['mae']} | {row['rmse']} |")
        lines.append("")
    return "\n".join(lines)


def _split_eval(structure: dict[str, Any], experience: dict[str, Any], combined: dict[str, Any], key: str) -> dict[str, Any]:
    grouped = {}
    for index, record in enumerate(structure["records"]):
        grouped.setdefault(str(record[key]), []).append(index)
    test_keys = [
        name
        for name, _indexes in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[:4]
        if len(grouped[name]) >= 20
    ]
    return {
        "structure": _leave_one_group(structure, grouped, test_keys),
        "experience": _leave_one_group(experience, grouped, test_keys),
        "combined": _leave_one_group(combined, grouped, test_keys),
    }


def _leave_one_group(dataset: dict[str, Any], grouped: dict[str, list[int]], test_keys: list[str]) -> dict[str, float]:
    actual = []
    predicted_stats = []
    # Aggregate fold-level predictions by pooling pseudo-record stats weighted approximately by row count.
    # The final metric is the mean of fold metrics to avoid huge prediction payloads.
    for key in test_keys:
        test_idx = set(grouped[key])
        train = [record for index, record in enumerate(dataset["records"]) if index not in test_idx]
        test = [record for index, record in enumerate(dataset["records"]) if index in test_idx]
        if train and test:
            stat = train_predict(train, test, dataset["feature_names"], "success")
            stat["rows"] = len(test)
            predicted_stats.append(stat)
    if not predicted_stats:
        return {"correlation": 0.0, "r2": 0.0, "mae": 0.0, "rmse": 0.0, "explained_variance": 0.0}
    total = sum(row["rows"] for row in predicted_stats)
    return {
        metric: round(sum(row[metric] * row["rows"] for row in predicted_stats) / total, 6)
        for metric in ("correlation", "r2", "mae", "rmse", "explained_variance")
    }


__all__ = ["compute_generalization_results", "export_generalization_results"]
