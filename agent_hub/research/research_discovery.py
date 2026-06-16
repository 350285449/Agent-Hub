from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .data_quality_audit import load_audited_rows
from .live_matrix_runner import live_matrix_path
from .telemetry import research_dir


def candidate_discoveries_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "candidate_discoveries.md"


def run_research_discovery(state_dir: str | Path, *, matrix_path: str | Path | None = None) -> dict[str, str]:
    source = Path(matrix_path) if matrix_path else live_matrix_path(state_dir)
    rows, _excluded = load_audited_rows(source)
    payload = discover_candidate_quantities(rows)
    json_path = research_dir(state_dir) / "candidate_discoveries.json"
    md_path = candidate_discoveries_path(state_dir)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"candidate_discoveries_json": str(json_path), "candidate_discoveries": str(md_path)}


def discover_candidate_quantities(rows: list[dict[str, Any]]) -> dict[str, Any]:
    actual = [1.0 if row.get("success") else 0.0 for row in rows]
    numeric = _numeric_features(rows)
    categorical = _categorical_features(rows)
    correlations = _rank(
        [
            {"name": name, "score": abs(_pearson(values, actual)), "detail": f"corr={round(_pearson(values, actual), 6)}"}
            for name, values in numeric.items()
        ]
    )
    categorical_scores = _rank(
        [
            {"name": name, "score": _categorical_lift(values, actual), "detail": "between-group success lift"}
            for name, values in categorical.items()
        ]
    )
    interactions = _rank(_interaction_candidates(rows, actual))
    compatibility = _rank(_compatibility_candidates(rows))
    latent = _rank(_latent_factor_candidates(rows, numeric, categorical_scores))
    predictive = _rank(correlations + categorical_scores + interactions + compatibility + latent)
    return {
        "object": "agent_hub.research.candidate_discoveries",
        "rows": len(rows),
        "correlations": correlations,
        "latent_factors": latent,
        "interactions": interactions,
        "compatibility_measures": compatibility,
        "predictive_variables": predictive,
    }


def _numeric_features(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    fields = ("context_budget", "context_tokens", "validation_score", "latency", "retries")
    return {field: [float(row.get(field, 0.0) or 0.0) for row in rows] for field in fields}


def _categorical_features(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    fields = ("model", "repository", "category")
    return {field: [str(row.get(field) or "") for row in rows] for field in fields}


def _interaction_candidates(rows: list[dict[str, Any]], actual: list[float]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for left, right in (("model", "category"), ("model", "context_budget"), ("repository", "category"), ("category", "context_budget")):
        values = [f"{row.get(left)}|{row.get(right)}" for row in rows]
        candidates.append({"name": f"{left}_x_{right}", "score": _categorical_lift(values, actual), "detail": "interaction lift"})
    return candidates


def _compatibility_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for keys in (("model", "category"), ("model", "repository"), ("model", "category", "context_budget")):
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[tuple(row.get(key) for key in keys)].append(row)
        rates = [_rate(items) for items in grouped.values()]
        spread = max(rates) - min(rates) if rates else 0.0
        candidates.append({"name": "_".join(keys) + "_compatibility", "score": round(spread, 6), "detail": f"{len(grouped)} cells"})
    return candidates


def _latent_factor_candidates(rows: list[dict[str, Any]], numeric: dict[str, list[float]], categorical_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    actual = [1.0 if row.get("success") else 0.0 for row in rows]
    normalized = [_normalize(values) for values in numeric.values()]
    if not normalized:
        return []
    factor = [sum(values[index] for values in normalized) / len(normalized) for index in range(len(rows))]
    categorical_strength = sum(row["score"] for row in categorical_scores[:3]) / max(1, min(3, len(categorical_scores)))
    return [
        {"name": "numeric_operational_factor", "score": abs(round(_pearson(factor, actual), 6)), "detail": "mean normalized numeric features"},
        {"name": "categorical_structure_factor", "score": round(categorical_strength, 6), "detail": "top categorical lift average"},
    ]


def _categorical_lift(values: list[str], actual: list[float]) -> float:
    if not values or len(values) != len(actual):
        return 0.0
    grouped: dict[str, list[float]] = defaultdict(list)
    for value, outcome in zip(values, actual):
        grouped[value].append(outcome)
    if len(grouped) < 2:
        return 0.0
    rates = [sum(items) / len(items) for items in grouped.values() if items]
    return round(max(rates) - min(rates), 6) if rates else 0.0


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high == low:
        return [0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [{**row, "score": round(float(row.get("score", 0.0) or 0.0), 6)} for row in rows]
    return sorted(normalized, key=lambda row: row["score"], reverse=True)


def _rate(rows: list[dict[str, Any]]) -> float:
    return sum(1 for row in rows if row.get("success")) / len(rows) if rows else 0.0


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    ml = sum(left) / len(left)
    mr = sum(right) / len(right)
    dl = math.sqrt(sum((value - ml) ** 2 for value in left))
    dr = math.sqrt(sum((value - mr) ** 2 for value in right))
    if not dl or not dr:
        return 0.0
    return sum((a - ml) * (b - mr) for a, b in zip(left, right)) / (dl * dr)


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Candidate Discoveries",
        "",
        f"- Clean live rows: {payload['rows']}",
        "- Candidate scores are exploratory and must be re-tested by the theory harness before promotion.",
        "",
    ]
    for section in ("correlations", "latent_factors", "interactions", "compatibility_measures", "predictive_variables"):
        lines.extend([f"## {section.replace('_', ' ').title()}", ""])
        rows = payload.get(section, [])
        if not rows:
            lines.append("- No candidates available.")
        for row in rows[:25]:
            lines.append(f"- {row['name']}: score={row['score']} detail={row.get('detail', '')}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover candidate predictive quantities from clean live rows.")
    parser.add_argument("--state-dir", default=".agent-hub/state")
    parser.add_argument("--matrix-path", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run_research_discovery(args.state_dir, matrix_path=args.matrix_path or None)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "candidate_discoveries_path",
    "discover_candidate_quantities",
    "run_research_discovery",
]
