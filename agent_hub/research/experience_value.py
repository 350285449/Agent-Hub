from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .structure_vs_experience import (
    EXPERIENCE_CAPS,
    build_experience_dataset,
    combine_datasets,
    evaluate_dataset,
)
from .telemetry import research_dir


def compute_experience_gain_curve(rows: list[dict[str, Any]]) -> dict[str, Any]:
    points = []
    for cap in EXPERIENCE_CAPS:
        dataset = build_experience_dataset(rows, cap=cap)
        points.append({"experience_cap": cap, "success": evaluate_dataset(dataset)["targets"]["success"]})
    return {
        "object": "agent_hub.research.experience_gain_curve",
        "points": points,
        "interpretation": _curve_interpretation(points),
    }


def compute_knowledge_value(structure: dict[str, Any], experience: dict[str, Any], combined: dict[str, Any]) -> dict[str, Any]:
    s = evaluate_dataset(structure)["targets"]["success"]
    e = evaluate_dataset(experience)["targets"]["success"]
    c = evaluate_dataset(combined)["targets"]["success"]
    values = _group_knowledge_values(structure, experience, combined)
    return {
        "object": "agent_hub.research.knowledge_value",
        "overall_knowledge_value_r2": round(c["r2"] - s["r2"], 6),
        "experience_only_r2": e["r2"],
        "structure_only_r2": s["r2"],
        "combined_r2": c["r2"],
        "knowledge_value_stability": round(_stability(values), 6),
        "by_repository": values["repository"],
        "by_model": values["model"],
        "by_task": values["task_type"],
        "interpretation": "Knowledge Value is measurable and positive" if c["r2"] > s["r2"] else "Knowledge Value is not positive in this run",
    }


def export_experience_gain_curve(state_dir: str | Path, rows: list[dict[str, Any]]) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_experience_gain_curve(rows)
    json_path = directory / "experience_gain_curve.json"
    md_path = directory / "experience_gain_curve.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(experience_gain_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def export_knowledge_value(
    state_dir: str | Path,
    structure: dict[str, Any],
    experience: dict[str, Any],
    combined: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_knowledge_value(structure, experience, combined)
    json_path = directory / "knowledge_value.json"
    md_path = directory / "knowledge_value.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(knowledge_value_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def experience_gain_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Experience Gain Curve",
        "",
        f"- Interpretation: {payload['interpretation']}",
        "",
        "| experience cap | correlation | R2 | MAE | RMSE |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["points"]:
        success = row["success"]
        lines.append(f"| {row['experience_cap']} | {success['correlation']} | {success['r2']} | {success['mae']} | {success['rmse']} |")
    lines.append("")
    return "\n".join(lines)


def knowledge_value_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Knowledge Value",
        "",
        f"- Overall K by R2 gain over structure: {payload['overall_knowledge_value_r2']}",
        f"- Knowledge Value stability: {payload['knowledge_value_stability']}",
        f"- Interpretation: {payload['interpretation']}",
        "",
        "## By Repository",
        *[f"- {key}: {value}" for key, value in payload["by_repository"].items()],
        "",
        "## By Model",
        *[f"- {key}: {value}" for key, value in payload["by_model"].items()],
        "",
        "## By Task",
        *[f"- {key}: {value}" for key, value in payload["by_task"].items()],
        "",
    ]
    return "\n".join(lines)


def _group_knowledge_values(structure: dict[str, Any], experience: dict[str, Any], combined: dict[str, Any]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {"repository": {}, "model": {}, "task_type": {}}
    for key in result:
        grouped: dict[str, list[int]] = defaultdict(list)
        for index, record in enumerate(structure["records"]):
            grouped[str(record[key])].append(index)
        for value, indexes in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[:5]:
            if len(indexes) < 20:
                continue
            s = _subset(structure, indexes)
            c = _subset(combined, indexes)
            result[key][value] = round(evaluate_dataset(c)["targets"]["success"]["r2"] - evaluate_dataset(s)["targets"]["success"]["r2"], 6)
    return result


def _subset(dataset: dict[str, Any], indexes: list[int]) -> dict[str, Any]:
    records = [dataset["records"][index] for index in indexes]
    return {"name": dataset["name"], "records": records, "feature_names": dataset["feature_names"]}


def _stability(values: dict[str, dict[str, float]]) -> float:
    rows = [value for group in values.values() for value in group.values()]
    if not rows:
        return 0.0
    mean = sum(rows) / len(rows)
    variance = sum((value - mean) ** 2 for value in rows) / len(rows)
    return 1.0 / (1.0 + variance)


def _curve_interpretation(points: list[dict[str, Any]]) -> str:
    if not points:
        return "no points"
    if points[-1]["success"]["r2"] > points[0]["success"]["r2"] + 0.05:
        return "experience accumulates measurable predictive value"
    return "experience gain is flat or weak"


__all__ = [
    "compute_experience_gain_curve",
    "compute_knowledge_value",
    "export_experience_gain_curve",
    "export_knowledge_value",
]
