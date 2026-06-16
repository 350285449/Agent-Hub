from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .compatibility_space import build_shared_geometry, compute_compatibility_metrics
from .model_distance import load_model_observations
from .task_embedding import build_task_embeddings
from .telemetry import research_dir


def predict_compatibility(compatibility_payload: dict[str, Any]) -> dict[str, Any]:
    rows = compatibility_payload["interactions"]
    results = {}
    for metric in ("inverse_distance", "cosine_similarity", "projection", "radial_gap", "combined_compatibility"):
        xs = [float(row[metric]) for row in rows]
        ys = [float(row["success"]) for row in rows]
        invert = metric == "radial_gap"
        predictions = _linear_predictions(xs, ys, invert=invert)
        results[metric] = _prediction_stats(ys, predictions, xs)
    best = max(results, key=lambda key: results[key]["explained_variance"]) if results else ""
    return {
        "object": "agent_hub.research.compatibility_prediction",
        "method": "single_metric_linear_prediction_from_model_and_task_positions_only",
        "best_metric": best,
        "metrics": results,
        "interaction_count": len(rows),
        "notes": [
            "Predictors are scalar compatibility values computed from model and task coordinates only.",
            "The target is observed success rate; context size, routing decisions, and raw validation predictors are excluded.",
        ],
    }


def compute_geometry_stability(state_dir: str | Path, observations: list[dict[str, Any]], full_shared: dict[str, Any]) -> dict[str, Any]:
    full_compat = compute_compatibility_metrics(full_shared)
    splits = _splits(observations)
    rows = []
    for name, split_rows in splits.items():
        if len({row["model"] for row in split_rows}) < 2:
            continue
        task_payload = build_task_embeddings(state_dir, split_rows)
        shared = build_shared_geometry(state_dir, task_payload)
        compat = compute_compatibility_metrics(shared)
        rows.append(
            {
                "split": name,
                "rows": len(split_rows),
                "embedding_stability": round(_shared_distance_correlation(full_shared, shared), 6),
                "cluster_stability": round(_cluster_agreement(full_shared, shared), 6),
                "compatibility_stability": round(_compatibility_correlation(full_compat, compat), 6),
            }
        )
    return {
        "object": "agent_hub.research.geometry_stability",
        "split_count": len(rows),
        "embedding_stability": round(_avg(row["embedding_stability"] for row in rows), 6),
        "cluster_stability": round(_avg(row["cluster_stability"] for row in rows), 6),
        "compatibility_stability": round(_avg(row["compatibility_stability"] for row in rows), 6),
        "splits": rows,
        "notes": [
            "High stability is encouraging but partly structural: all splits reuse the same difficulty task matrix for model-task interactions.",
            "A stronger future test should rebuild the interaction matrix independently per repository and task subset.",
        ],
    }


def compare_against_theories(state_dir: str | Path, prediction: dict[str, Any]) -> dict[str, Any]:
    directory = research_dir(state_dir)
    theories = []
    portfolio = _load_json(directory / "research_portfolio_rankings.json")
    for row in portfolio.get("ranked_quantities", []):
        theories.append(
            {
                "name": row.get("name", ""),
                "predictive_power": float(row.get("predictive_power") or 0.0),
                "routing_usefulness": float(row.get("usefulness_for_routing") or 0.0),
                "score": float(row.get("research_potential_score") or 0.0),
                "source": "research_portfolio_rankings.json",
            }
        )
    cap_eval = _read_capability_score(directory / "capability_geometry_evaluation.md")
    if cap_eval is not None:
        theories.append({"name": "Capability Geometry", "predictive_power": cap_eval, "routing_usefulness": cap_eval, "score": cap_eval, "source": "capability_geometry_evaluation.md"})
    best_metric = prediction.get("best_metric", "")
    compatibility_power = max(0.0, prediction["metrics"].get(best_metric, {}).get("explained_variance", 0.0))
    theories.append(
        {
            "name": "Model-Task Compatibility",
            "predictive_power": compatibility_power,
            "routing_usefulness": compatibility_power,
            "score": compatibility_power,
            "source": "compatibility_prediction.json",
        }
    )
    ranked = sorted(theories, key=lambda row: row["predictive_power"], reverse=True)
    return {
        "object": "agent_hub.research.geometry_vs_all_theories",
        "compatibility_outperforms_all": ranked and ranked[0]["name"] == "Model-Task Compatibility",
        "ranked": ranked,
        "best_metric": best_metric,
    }


def evaluate_compatibility(
    prediction: dict[str, Any],
    stability: dict[str, Any],
    comparison: dict[str, Any],
    compatibility: dict[str, Any],
) -> dict[str, Any]:
    best = prediction["metrics"].get(prediction.get("best_metric", ""), {})
    predictive = max(0.0, min(1.0, (max(0.0, best.get("correlation", 0.0)) + max(0.0, best.get("explained_variance", 0.0))) / 2.0))
    stable = max(0.0, min(1.0, _avg([stability["embedding_stability"], stability["cluster_stability"], stability["compatibility_stability"]])))
    interpretable = 0.65 if compatibility.get("best_metric") in {"inverse_distance", "combined_compatibility", "cosine_similarity"} else 0.45
    comparative = 1.0 if comparison["compatibility_outperforms_all"] else 0.35
    score = round(100.0 * (0.35 * predictive + 0.30 * stable + 0.15 * interpretable + 0.20 * comparative), 2)
    verdict = "A) Strong evidence for Model-Task Geometry." if score >= 70 else "B) Mixed evidence." if score >= 40 else "C) No evidence."
    return {
        "object": "agent_hub.research.compatibility_evaluation",
        "score_0_to_100": score,
        "verdict": verdict,
        "criteria": {
            "predictive": round(predictive, 6),
            "stability": round(stable, 6),
            "interpretable": round(interpretable, 6),
            "beats_previous_theories": comparison["compatibility_outperforms_all"],
        },
        "breakthrough_potential": "medium" if 40 <= score < 70 else "high" if score >= 70 else "low",
        "replace_previous_research": bool(score >= 80 and comparison["compatibility_outperforms_all"]),
    }


def export_prediction(state_dir: str | Path, compatibility_payload: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = predict_compatibility(compatibility_payload)
    json_path = directory / "compatibility_prediction.json"
    md_path = directory / "compatibility_prediction.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(prediction_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def export_stability(state_dir: str | Path, observations: list[dict[str, Any]], shared_payload: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_geometry_stability(state_dir, observations, shared_payload)
    json_path = directory / "geometry_stability.json"
    md_path = directory / "geometry_stability.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(stability_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def export_comparison(state_dir: str | Path, prediction: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compare_against_theories(state_dir, prediction)
    path = directory / "geometry_vs_all_theories.md"
    path.write_text(comparison_markdown(payload), encoding="utf-8")
    return path, payload


def export_falsification(state_dir: str | Path, prediction: dict[str, Any], stability: dict[str, Any], compatibility: dict[str, Any]) -> Path:
    path = research_dir(state_dir) / "geometry_falsification.md"
    path.write_text(falsification_markdown(prediction, stability, compatibility), encoding="utf-8")
    return path


def export_evaluation(state_dir: str | Path, evaluation: dict[str, Any]) -> Path:
    path = research_dir(state_dir) / "compatibility_evaluation.md"
    path.write_text(evaluation_markdown(evaluation), encoding="utf-8")
    return path


def export_summary(
    state_dir: str | Path,
    evaluation: dict[str, Any],
    prediction: dict[str, Any],
    stability: dict[str, Any],
    comparison: dict[str, Any],
    compatibility: dict[str, Any],
) -> Path:
    path = research_dir(state_dir) / "model_task_geometry_research_summary.md"
    path.write_text(summary_markdown(evaluation, prediction, stability, comparison, compatibility), encoding="utf-8")
    return path


def prediction_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Compatibility Prediction",
        "",
        f"- Method: `{payload['method']}`",
        f"- Best metric: `{payload['best_metric']}`",
        f"- Interactions: {payload['interaction_count']}",
        "",
        "| metric | correlation | MAE | RMSE | explained variance |",
        "| --- | --- | --- | --- | --- |",
    ]
    for metric, row in payload["metrics"].items():
        lines.append(f"| {metric} | {row['correlation']} | {row['mae']} | {row['rmse']} | {row['explained_variance']} |")
    lines.append("")
    return "\n".join(lines)


def stability_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Geometry Stability",
        "",
        f"- Embedding stability: {payload['embedding_stability']}",
        f"- Cluster stability: {payload['cluster_stability']}",
        f"- Compatibility stability: {payload['compatibility_stability']}",
        "- Note: high values are partly structural because the same interaction matrix anchors each split.",
        "",
        "| split | rows | embedding | clusters | compatibility |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["splits"]:
        lines.append(f"| {row['split']} | {row['rows']} | {row['embedding_stability']} | {row['cluster_stability']} | {row['compatibility_stability']} |")
    lines.append("")
    return "\n".join(lines)


def comparison_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Geometry vs All Theories",
        "",
        f"- Does compatibility outperform all previous quantities? {payload['compatibility_outperforms_all']}",
        f"- Best compatibility metric: `{payload['best_metric']}`",
        "",
        "| rank | theory | predictive power | score | source |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(payload["ranked"], start=1):
        lines.append(f"| {index} | {row['name']} | {round(row['predictive_power'], 6)} | {round(row['score'], 6)} | {row['source']} |")
    lines.append("")
    return "\n".join(lines)


def falsification_markdown(prediction: dict[str, Any], stability: dict[str, Any], compatibility: dict[str, Any]) -> str:
    failures = []
    best = prediction["metrics"].get(prediction.get("best_metric", ""), {})
    if best.get("explained_variance", 0.0) <= 0.05:
        failures.append("Predictive weakness: best compatibility metric explains little success variance.")
    if stability["compatibility_stability"] < 0.5:
        failures.append("Compatibility instability across repository/task/model splits.")
    if compatibility["metrics"].get("inverse_distance", {}).get("success_correlation", 0.0) <= 0.0:
        failures.append("Distance contradiction: closer model-task pairs are not more successful under inverse distance.")
    if compatibility.get("best_metric") not in {"inverse_distance", "combined_compatibility"}:
        failures.append("Metric fragility: the best metric is not the most direct distance formulation.")
    return "\n".join(
        [
            "# Model-Task Geometry Falsification",
            "",
            "This report searches for evidence against shared geometry.",
            "",
            "## Evidence Against",
            *[f"- {item}" for item in failures or ["No hard falsifier fired, but this remains an offline correlation study."]],
            "",
            "## Strongest Surviving Signal",
            f"- Best metric: {prediction.get('best_metric')} with correlation {best.get('correlation')} and explained variance {best.get('explained_variance')}.",
            "",
        ]
    )


def evaluation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Compatibility Evaluation",
        "",
        f"- Score: {payload['score_0_to_100']}/100",
        f"- Final conclusion: {payload['verdict']}",
        f"- Breakthrough potential: {payload['breakthrough_potential']}",
        f"- Replace previous research directions: {payload['replace_previous_research']}",
        "",
        "## Criteria",
    ]
    for key, value in payload["criteria"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def summary_markdown(
    evaluation: dict[str, Any],
    prediction: dict[str, Any],
    stability: dict[str, Any],
    comparison: dict[str, Any],
    compatibility: dict[str, Any],
) -> str:
    best = prediction["metrics"].get(prediction.get("best_metric", ""), {})
    contradiction = "compatibility does not outperform all previous theories" if not comparison["compatibility_outperforms_all"] else "prediction is still offline and may not generalize"
    return "\n".join(
        [
            "# Model-Task Geometry Research Summary",
            "",
            f"Final conclusion: {evaluation['verdict']}",
            "",
            "## Answers",
            "1. Do models and tasks occupy a shared space? Partly; the program can construct a shared interaction space, but this is empirical rather than proven.",
            f"2. Does compatibility predict success? Partly; best metric `{prediction.get('best_metric')}` has correlation {best.get('correlation')} and explained variance {best.get('explained_variance')}.",
            "3. Is compatibility more predictive than model quality alone? Not established here; the comparison table keeps it below the strongest prior quantities if its predictive power is lower.",
            "4. Is compatibility more predictive than task difficulty alone? Mixed; it captures pair structure, but Agent Difficulty remains competitive in the prior ranking.",
            "5. Does this explain why previous theories partially succeeded? Yes, plausibly: context, difficulty, routing risk, and model geometry can be projections of interaction compatibility.",
            "6. Is geometry only part of the story? Yes; context and validation effects still matter.",
            f"7. Is compatibility a candidate fundamental quantity? {'Yes, as a mixed candidate' if evaluation['score_0_to_100'] >= 40 else 'No, not on this evidence'}.",
            "",
            "## Required Judgments",
            f"- Strongest supporting result: best compatibility metric correlation {best.get('correlation')}.",
            f"- Strongest contradiction: {contradiction}.",
            f"- Estimated breakthrough potential: {evaluation['breakthrough_potential']}.",
            f"- Should this replace all previous research directions? {evaluation['replace_previous_research']}.",
            f"- Stability: embedding={stability['embedding_stability']}, cluster={stability['cluster_stability']}, compatibility={stability['compatibility_stability']}.",
            f"- Best raw compatibility metric by success correlation: {compatibility.get('best_metric')}.",
            "",
        ]
    )


def _linear_predictions(xs: list[float], ys: list[float], *, invert: bool = False) -> list[float]:
    if invert:
        xs = [-x for x in xs]
    if not xs:
        return []
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0.0
    intercept = my - slope * mx
    return [max(0.0, min(1.0, intercept + slope * x)) for x in xs]


def _prediction_stats(actual: list[float], predicted: list[float], raw_metric: list[float]) -> dict[str, float]:
    return {
        "correlation": round(_pearson(raw_metric, actual), 6),
        "mae": round(_mae(actual, predicted), 6),
        "rmse": round(_rmse(actual, predicted), 6),
        "explained_variance": round(_r2(actual, predicted), 6),
    }


def _splits(observations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for key in ("repository", "task_type", "model"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            grouped[str(row.get(key) or "unknown")].append(row)
        for value, rows in grouped.items():
            if len(rows) >= 10:
                result[f"{key}:{value}"] = rows
    return result


def _shared_distance_correlation(full: dict[str, Any], split: dict[str, Any]) -> float:
    common = sorted(set(full["tasks"]) & set(split["tasks"]))
    if len(common) < 3:
        return 0.0
    return _pair_distance_correlation(full["tasks"], split["tasks"], common)


def _cluster_agreement(full: dict[str, Any], split: dict[str, Any]) -> float:
    # Shared geometry itself does not cluster; this checks whether task coordinate neighborhoods are stable.
    return max(0.0, _shared_distance_correlation(full, split))


def _compatibility_correlation(full: dict[str, Any], split: dict[str, Any]) -> float:
    by_key = {(row["model"], row["task"]): row["combined_compatibility"] for row in split["interactions"]}
    a, b = [], []
    for row in full["interactions"]:
        key = (row["model"], row["task"])
        if key in by_key:
            a.append(row["combined_compatibility"])
            b.append(by_key[key])
    return _pearson(a, b)


def _pair_distance_correlation(left: dict[str, list[float]], right: dict[str, list[float]], keys: list[str]) -> float:
    a, b = [], []
    for index, first in enumerate(keys):
        for second in keys[index + 1 :]:
            a.append(_euclidean(left[first], left[second]))
            b.append(_euclidean(right[first], right[second]))
    return _pearson(a, b)


def _read_capability_score(path: Path) -> float | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- Score:"):
            try:
                return float(line.split(":", 1)[1].split("/", 1)[0].strip()) / 100.0
            except ValueError:
                return None
    return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _euclidean(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _mae(actual: list[float], predicted: list[float]) -> float:
    return _avg(abs(a - b) for a, b in zip(actual, predicted))


def _rmse(actual: list[float], predicted: list[float]) -> float:
    return math.sqrt(_avg((a - b) ** 2 for a, b in zip(actual, predicted)))


def _r2(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    mean = sum(actual) / len(actual)
    total = sum((value - mean) ** 2 for value in actual)
    residual = sum((a - b) ** 2 for a, b in zip(actual, predicted))
    return 1.0 - residual / total if total else 0.0


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    ml = sum(left) / len(left)
    mr = sum(right) / len(right)
    numerator = sum((a - ml) * (b - mr) for a, b in zip(left, right))
    denom_l = math.sqrt(sum((a - ml) ** 2 for a in left))
    denom_r = math.sqrt(sum((b - mr) ** 2 for b in right))
    return numerator / (denom_l * denom_r) if denom_l and denom_r else 0.0


def _avg(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


__all__ = [
    "compare_against_theories",
    "compute_geometry_stability",
    "evaluate_compatibility",
    "predict_compatibility",
]
