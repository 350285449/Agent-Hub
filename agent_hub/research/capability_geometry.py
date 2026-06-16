from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .capability_embedding import compute_capability_embedding, export_capability_embedding
from .model_clusters import compute_model_clusters, export_model_clusters
from .model_distance import (
    build_behavior_vectors,
    compute_distance_matrix,
    export_behavior_vectors,
    export_distance_matrix,
    load_model_observations,
    normalize_vectors,
)
from .telemetry import research_dir


def run_capability_geometry_research_program(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    observations = load_model_observations(state_dir)
    behavior_path, behavior = export_behavior_vectors(state_dir)
    distance_json, distance_md, distance = export_distance_matrix(state_dir, behavior)
    embedding_json, embedding_md, embedding = export_capability_embedding(state_dir, behavior)
    clusters_json, clusters_md, clusters = export_model_clusters(state_dir, behavior, distance)

    stability = compute_stability(observations, behavior, distance, clusters, embedding)
    stability_json, stability_md = _export_json_and_md(
        directory,
        "capability_stability",
        stability,
        stability_markdown(stability),
    )
    prediction = compute_prediction(behavior, distance)
    prediction_json, prediction_md = _export_json_and_md(
        directory,
        "capability_prediction",
        prediction,
        prediction_markdown(prediction),
    )
    falsification_md = directory / "capability_falsification.md"
    falsification_md.write_text(falsification_markdown(stability, prediction, clusters, distance), encoding="utf-8")
    evaluation_md = directory / "capability_geometry_evaluation.md"
    evaluation = compute_evaluation(stability, prediction, clusters, distance, state_dir)
    evaluation_md.write_text(evaluation_markdown(evaluation), encoding="utf-8")
    routing_md = directory / "geometric_routing_experiment.md"
    routing = compute_routing_experiment(observations, behavior, distance, clusters)
    routing_md.write_text(routing_markdown(routing), encoding="utf-8")
    summary_md = directory / "capability_geometry_research_summary.md"
    summary_md.write_text(summary_markdown(evaluation, stability, prediction, clusters, routing), encoding="utf-8")

    return {
        "model_behavior_vectors": str(behavior_path),
        "model_distance_matrix": str(distance_json),
        "model_distance_matrix_markdown": str(distance_md),
        "capability_embedding": str(embedding_json),
        "capability_embedding_markdown": str(embedding_md),
        "model_clusters": str(clusters_json),
        "model_clusters_markdown": str(clusters_md),
        "capability_stability": str(stability_json),
        "capability_stability_markdown": str(stability_md),
        "capability_prediction": str(prediction_json),
        "capability_prediction_markdown": str(prediction_md),
        "capability_falsification": str(falsification_md),
        "capability_geometry_evaluation": str(evaluation_md),
        "geometric_routing_experiment": str(routing_md),
        "capability_geometry_research_summary": str(summary_md),
    }


def compute_stability(
    observations: list[dict[str, Any]],
    full_behavior: dict[str, Any],
    full_distance: dict[str, Any],
    full_clusters: dict[str, Any],
    full_embedding: dict[str, Any],
) -> dict[str, Any]:
    splits = _make_splits(observations)
    split_rows = []
    for split_name, rows in splits.items():
        if len({row["model"] for row in rows}) < 2:
            continue
        behavior = build_behavior_vectors(rows)
        distance = compute_distance_matrix(behavior)
        clusters = compute_model_clusters(behavior, distance)
        embedding = compute_capability_embedding(behavior)
        shared_models = sorted(set(full_behavior["models"]) & set(behavior["models"]))
        if len(shared_models) < 3:
            continue
        split_rows.append(
            {
                "split": split_name,
                "rows": len(rows),
                "models": shared_models,
                "distance_correlation": round(_distance_correlation(full_distance, distance, shared_models), 6),
                "cluster_agreement": round(_cluster_agreement(full_clusters, clusters, shared_models), 6),
                "embedding_distance_correlation": round(_embedding_correlation(full_embedding, embedding, shared_models), 6),
            }
        )
    return {
        "object": "agent_hub.research.capability_stability",
        "split_count": len(split_rows),
        "distance_stability": round(_avg(row["distance_correlation"] for row in split_rows), 6),
        "cluster_stability": round(_avg(row["cluster_agreement"] for row in split_rows), 6),
        "embedding_stability": round(_avg(row["embedding_distance_correlation"] for row in split_rows), 6),
        "distance_variance": round(_variance(row["distance_correlation"] for row in split_rows), 8),
        "cluster_variance": round(_variance(row["cluster_agreement"] for row in split_rows), 8),
        "embedding_variance": round(_variance(row["embedding_distance_correlation"] for row in split_rows), 8),
        "splits": split_rows,
        "notes": ["Splits with fewer than three shared models are excluded because pairwise distance correlation is undefined or degenerate."],
        "interpretation": _stability_interpretation(split_rows),
    }


def compute_prediction(behavior_payload: dict[str, Any], distance_payload: dict[str, Any]) -> dict[str, Any]:
    models = sorted(behavior_payload["models"])
    raw = {model: behavior_payload["models"][model]["raw_vector"] for model in models}
    normalized = normalize_vectors(raw)
    features = sorted({feature for vector in normalized.values() for feature in vector})
    rows = []
    all_actual: list[float] = []
    all_predicted: list[float] = []
    for model in models:
        neighbors = [row["model"] for row in distance_payload["nearest_neighbors"].get(model, [])[:2]]
        if not neighbors:
            continue
        actual = [normalized[model].get(feature, 0.0) for feature in features]
        predicted = [_avg(normalized[neighbor].get(feature, 0.0) for neighbor in neighbors) for feature in features]
        all_actual.extend(actual)
        all_predicted.extend(predicted)
        rows.append(
            {
                "model": model,
                "neighbors": neighbors,
                "mae": round(_mae(actual, predicted), 6),
                "correlation": round(_pearson(actual, predicted), 6),
                "variance_explained": round(_r2(actual, predicted), 6),
            }
        )
    return {
        "object": "agent_hub.research.capability_prediction",
        "method": "nearest_neighbor_leave_one_model_behavior_prediction",
        "overall_mae": round(_mae(all_actual, all_predicted), 6),
        "overall_correlation": round(_pearson(all_actual, all_predicted), 6),
        "overall_variance_explained": round(_r2(all_actual, all_predicted), 6),
        "models": rows,
        "interpretation": _prediction_interpretation(_pearson(all_actual, all_predicted), _r2(all_actual, all_predicted)),
    }


def compute_evaluation(
    stability: dict[str, Any],
    prediction: dict[str, Any],
    clusters: dict[str, Any],
    distance: dict[str, Any],
    state_dir: str | Path,
) -> dict[str, Any]:
    distance_score = max(0.0, min(1.0, 1.0 - _avg(row["composite"] for row in distance["pairs"]) / 4.0))
    stability_score = _avg([stability["distance_stability"], stability["cluster_stability"], stability["embedding_stability"]])
    prediction_score = max(0.0, min(1.0, (prediction["overall_correlation"] + max(0.0, prediction["overall_variance_explained"])) / 2.0))
    cluster_score = max(0.0, min(1.0, _avg(row["silhouette"] for row in clusters["candidate_cluster_counts"])))
    score = round(100.0 * (0.30 * stability_score + 0.30 * prediction_score + 0.20 * cluster_score + 0.20 * distance_score), 2)
    ranking = _rank_against_prior_quantities(state_dir, score)
    verdict = "A) Strong evidence for capability geometry." if score >= 70 else "B) Mixed evidence." if score >= 40 else "C) No evidence."
    return {
        "object": "agent_hub.research.capability_geometry_evaluation",
        "score_0_to_100": score,
        "verdict": verdict,
        "criteria": {
            "distance_stability": stability["distance_stability"],
            "cluster_stability": stability["cluster_stability"],
            "embedding_stability": stability["embedding_stability"],
            "prediction_correlation": prediction["overall_correlation"],
            "variance_explained": prediction["overall_variance_explained"],
            "cluster_separation": cluster_score,
            "distance_signal": round(distance_score, 6),
        },
        "ranked_quantities": ranking,
    }


def compute_routing_experiment(
    observations: list[dict[str, Any]],
    behavior: dict[str, Any],
    distance: dict[str, Any],
    clusters: dict[str, Any],
) -> dict[str, Any]:
    task_types = sorted({row["task_type"] for row in observations if row["task_type"]})
    rows = []
    for task_type in task_types:
        task_rows = [row for row in observations if row["task_type"] == task_type]
        if not task_rows:
            continue
        traditional = _best_model(task_rows, behavior["models"].keys())
        best = _best_model(task_rows, behavior["models"].keys(), by_validation=True)
        nearest = _nearest_available(best["model"], task_rows, distance)
        cluster_choice = _cluster_route(task_rows, clusters)
        rows.append(
            {
                "task_type": task_type,
                "traditional": traditional,
                "nearest_capability": nearest,
                "cluster_based": cluster_choice,
            }
        )
    return {
        "object": "agent_hub.research.geometric_routing_experiment",
        "method": "offline_task_type_aggregate_route_simulation",
        "tasks": rows,
        "summary": {
            "traditional": _route_summary(rows, "traditional"),
            "nearest_capability": _route_summary(rows, "nearest_capability"),
            "cluster_based": _route_summary(rows, "cluster_based"),
        },
        "winner": max(("traditional", "nearest_capability", "cluster_based"), key=lambda key: _route_summary(rows, key)["validation_score"]),
        "limitations": [
            "This is an offline aggregate simulation, not an online randomized routing trial.",
            "Nearest-capability routing is constrained by which models have observations for a given task type.",
        ],
    }


def stability_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Capability Stability",
        "",
        f"- Distance stability: {payload['distance_stability']}",
        f"- Cluster stability: {payload['cluster_stability']}",
        f"- Embedding stability: {payload['embedding_stability']}",
        f"- Interpretation: {payload['interpretation']}",
        "",
        "| split | rows | models | distance corr | cluster agreement | embedding corr |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["splits"]:
        lines.append(
            f"| {row['split']} | {row['rows']} | {len(row['models'])} | {row['distance_correlation']} | {row['cluster_agreement']} | {row['embedding_distance_correlation']} |"
        )
    lines.append("")
    return "\n".join(lines)


def prediction_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Capability Prediction",
        "",
        f"- Method: `{payload['method']}`",
        f"- Overall MAE: {payload['overall_mae']}",
        f"- Overall correlation: {payload['overall_correlation']}",
        f"- Overall variance explained: {payload['overall_variance_explained']}",
        f"- Interpretation: {payload['interpretation']}",
        "",
        "| model | neighbors | MAE | correlation | variance explained |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["models"]:
        lines.append(f"| {row['model']} | {', '.join(row['neighbors'])} | {row['mae']} | {row['correlation']} | {row['variance_explained']} |")
    lines.append("")
    return "\n".join(lines)


def falsification_markdown(stability: dict[str, Any], prediction: dict[str, Any], clusters: dict[str, Any], distance: dict[str, Any]) -> str:
    failures = []
    if stability["distance_stability"] < 0.5:
        failures.append("Distance instability: split distance correlations are below 0.5 on average.")
    if stability["cluster_stability"] < 0.5:
        failures.append("Cluster instability: split cluster agreements are below 0.5 on average.")
    if prediction["overall_variance_explained"] <= 0.0:
        failures.append("Predictive failure: nearest neighbors do not explain held-out model behavior variance.")
    if max((row["silhouette"] for row in clusters["candidate_cluster_counts"]), default=0.0) < 0.2:
        failures.append("Cluster collapse: silhouette is weak, so groups may be arbitrary.")
    if _avg(row["jaccard"] for row in distance["pairs"]) > 0.9:
        failures.append("Success-pattern contradiction: Jaccard distances are near maximum because tasks do not align across models.")
    lines = [
        "# Capability Geometry Falsification",
        "",
        "This section tries to destroy the hypothesis that model distance is a useful quantity.",
        "",
        "## Evidence Against",
        *[f"- {item}" for item in failures or ["No hard falsification trigger fired, but evidence remains limited by data coverage."]],
        "",
        "## Evidence That Survived",
        f"- Mean distance stability: {stability['distance_stability']}",
        f"- Mean prediction correlation: {prediction['overall_correlation']}",
        f"- Selected clusters: {clusters['selected_k']}",
        "",
        "## Bottom Line",
        "Capability geometry survives only if the instability and prediction tests are strong enough under future, less duplicated runs.",
        "",
    ]
    return "\n".join(lines)


def evaluation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Capability Geometry Evaluation",
        "",
        f"- Score: {payload['score_0_to_100']}/100",
        f"- Final output: {payload['verdict']}",
        "",
        "## Criteria",
    ]
    for key, value in payload["criteria"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Ranking Against Previously Tested Quantities", "", "| rank | quantity | score | source |", "| --- | --- | --- | --- |"])
    for index, row in enumerate(payload["ranked_quantities"], start=1):
        lines.append(f"| {index} | {row['name']} | {row['score']} | {row['source']} |")
    lines.append("")
    return "\n".join(lines)


def routing_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Geometric Routing Experiment",
        "",
        f"- Method: `{payload['method']}`",
        f"- Winner by validation score: {payload['winner']}",
        "",
        "| strategy | success | validation | latency ms |",
        "| --- | --- | --- | --- |",
    ]
    for key, summary in payload["summary"].items():
        lines.append(f"| {key} | {summary['success_rate']} | {summary['validation_score']} | {summary['latency_ms']} |")
    lines.extend(["", "## Task Routes", "", "| task | traditional | nearest capability | cluster based |", "| --- | --- | --- | --- |"])
    for row in payload["tasks"]:
        lines.append(
            f"| {row['task_type']} | {_route_cell(row['traditional'])} | {_route_cell(row['nearest_capability'])} | {_route_cell(row['cluster_based'])} |"
        )
    lines.extend(["", "## Limitations", *[f"- {item}" for item in payload["limitations"]], ""])
    return "\n".join(lines)


def summary_markdown(
    evaluation: dict[str, Any],
    stability: dict[str, Any],
    prediction: dict[str, Any],
    clusters: dict[str, Any],
    routing: dict[str, Any],
) -> str:
    stronger_than = ", ".join(row["name"] for row in evaluation["ranked_quantities"] if row["name"] == "Capability Geometry") or "none"
    return "\n".join(
        [
            "# Capability Geometry Research Summary",
            "",
            f"Final output: {evaluation['verdict']}",
            "",
            "## Answers",
            f"1. Does model distance appear to exist? {'Yes, as a measurable behavioral construct' if evaluation['score_0_to_100'] >= 40 else 'Not convincingly'}; score {evaluation['score_0_to_100']}/100.",
            f"2. Do models form stable clusters? {'Partly' if stability['cluster_stability'] >= 0.4 else 'No'}; cluster stability is {stability['cluster_stability']} across splits.",
            f"3. Can capability space predict behavior? {'Partly' if prediction['overall_correlation'] > 0.3 else 'Weakly'}; nearest-neighbor correlation is {prediction['overall_correlation']} and variance explained is {prediction['overall_variance_explained']}.",
            "4. Is capability geometry more fundamental than Context Complexity, Information Density, and Agent Difficulty? Not yet; the ranking table places it against prior quantities, and the claim remains mixed unless future stability improves.",
            f"5. Does routing benefit from geometry? Offline, `{routing['winner']}` wins by validation among tested strategies.",
            f"6. Is capability geometry a candidate fundamental quantity? {'Yes, but only as a mixed candidate' if evaluation['score_0_to_100'] >= 40 else 'No, not on this evidence'}.",
            "",
            "## Cluster Result",
            f"- Selected clusters: {clusters['selected_k']}",
            f"- Cluster labels: {', '.join(sorted({row['label'] for row in clusters['clusters'].values()}))}",
            "",
            "## Ranking Note",
            f"- Capability Geometry entry present: {stronger_than}",
            "- Do not overclaim: the strongest falsifier is still data coverage and success-pattern alignment across models.",
            "",
        ]
    )


def _make_splits(observations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    splits: dict[str, list[dict[str, Any]]] = {}
    for key in ("repository", "task_type", "source"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            grouped[str(row.get(key) or "unknown")].append(row)
        for value, rows in grouped.items():
            if len(rows) >= 5:
                splits[f"{key}:{value}"] = rows
    low = [row for row in observations if row["context_percent"] in (0, 25)]
    high = [row for row in observations if row["context_percent"] in (75, 100)]
    if low:
        splits["context:low"] = low
    if high:
        splits["context:high"] = high
    return splits


def _distance_correlation(full: dict[str, Any], split: dict[str, Any], models: list[str]) -> float:
    a, b = [], []
    for index, left in enumerate(models):
        for right in models[index + 1 :]:
            a.append(full["metrics"]["composite"][left][right])
            b.append(split["metrics"]["composite"][left][right])
    return _pearson(a, b)


def _cluster_agreement(full: dict[str, Any], split: dict[str, Any], models: list[str]) -> float:
    if len(models) < 2:
        return 0.0
    full_assign = full["model_assignments"]
    split_assign = split["model_assignments"]
    matches = 0
    total = 0
    for index, left in enumerate(models):
        for right in models[index + 1 :]:
            total += 1
            if (full_assign.get(left) == full_assign.get(right)) == (split_assign.get(left) == split_assign.get(right)):
                matches += 1
    return matches / total if total else 0.0


def _embedding_correlation(full: dict[str, Any], split: dict[str, Any], models: list[str]) -> float:
    return _pearson(_embedded_pair_distances(full, models), _embedded_pair_distances(split, models))


def _embedded_pair_distances(payload: dict[str, Any], models: list[str]) -> list[float]:
    coords = payload["embedding_3d"]
    values = []
    for index, left in enumerate(models):
        for right in models[index + 1 :]:
            if left in coords and right in coords:
                values.append(math.sqrt(sum((coords[left][dim] - coords[right][dim]) ** 2 for dim in range(3))))
    return values


def _best_model(rows: list[dict[str, Any]], model_names: Any, *, by_validation: bool = False) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["model"] in model_names:
            grouped[row["model"]].append(row)
    if not grouped:
        return {"model": "", "success_rate": 0.0, "validation_score": 0.0, "latency_ms": 0.0}
    model = max(grouped, key=lambda item: (_avg(row["validation_score"] for row in grouped[item]) if by_validation else _avg(1.0 if row["success"] else 0.0 for row in grouped[item]), -_avg(row["latency_ms"] for row in grouped[item])))
    return _model_observed_summary(model, grouped[model])


def _nearest_available(model: str, rows: list[dict[str, Any]], distance: dict[str, Any]) -> dict[str, Any]:
    available = {row["model"] for row in rows}
    for neighbor in distance["nearest_neighbors"].get(model, []):
        if neighbor["model"] in available:
            return _model_observed_summary(neighbor["model"], [row for row in rows if row["model"] == neighbor["model"]])
    return _best_model(rows, available, by_validation=True)


def _cluster_route(rows: list[dict[str, Any]], clusters: dict[str, Any]) -> dict[str, Any]:
    assignments = clusters["model_assignments"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[assignments.get(row["model"], "unknown")].append(row)
    best_cluster = max(grouped, key=lambda key: (_avg(row["validation_score"] for row in grouped[key]), -_avg(row["latency_ms"] for row in grouped[key])))
    return _best_model(grouped[best_cluster], {row["model"] for row in grouped[best_cluster]}, by_validation=True)


def _model_observed_summary(model: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": model,
        "success_rate": round(_avg(1.0 if row["success"] else 0.0 for row in rows), 6),
        "validation_score": round(_avg(row["validation_score"] for row in rows), 6),
        "latency_ms": round(_avg(row["latency_ms"] for row in rows), 3),
    }


def _route_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [row[key] for row in rows if row.get(key)]
    return {
        "success_rate": round(_avg(row["success_rate"] for row in values), 6),
        "validation_score": round(_avg(row["validation_score"] for row in values), 6),
        "latency_ms": round(_avg(row["latency_ms"] for row in values), 3),
    }


def _route_cell(row: dict[str, Any]) -> str:
    return f"{row['model']} (s={row['success_rate']}, v={row['validation_score']}, ms={row['latency_ms']})"


def _rank_against_prior_quantities(state_dir: str | Path, capability_score: float) -> list[dict[str, Any]]:
    path = research_dir(state_dir) / "research_portfolio_rankings.json"
    rows = [{"name": "Capability Geometry", "score": round(capability_score / 100.0, 6), "source": "capability_geometry"}]
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload.get("ranked_quantities", []):
                rows.append(
                    {
                        "name": row.get("name", ""),
                        "score": float(row.get("research_potential_score") or row.get("score") or 0.0),
                        "source": "research_portfolio_rankings.json",
                    }
                )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return sorted(rows, key=lambda row: row["score"], reverse=True)


def _export_json_and_md(directory: Path, stem: str, payload: dict[str, Any], markdown: str) -> tuple[Path, Path]:
    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path


def _stability_interpretation(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "not enough split data"
    score = _avg(_avg([row["distance_correlation"], row["cluster_agreement"], row["embedding_distance_correlation"]]) for row in rows)
    if score >= 0.7:
        return "stable under observed splits"
    if score >= 0.4:
        return "partly stable, with important split sensitivity"
    return "unstable; this is evidence against geometry"


def _prediction_interpretation(correlation: float, variance_explained: float) -> str:
    if correlation >= 0.7 and variance_explained > 0.25:
        return "nearby models predict each other usefully"
    if correlation >= 0.3:
        return "nearby models carry partial predictive signal"
    return "weak predictive signal"


def _mae(actual: list[float], predicted: list[float]) -> float:
    return _avg(abs(a - b) for a, b in zip(actual, predicted))


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


def _variance(values: Any) -> float:
    rows = [float(value) for value in values]
    if not rows:
        return 0.0
    mean = sum(rows) / len(rows)
    return sum((value - mean) ** 2 for value in rows) / len(rows)


def _avg(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the capability geometry research program.")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        from ..config import load_config

        state_dir = load_config().state_dir
    result = run_capability_geometry_research_program(state_dir)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "compute_evaluation",
    "compute_prediction",
    "compute_routing_experiment",
    "compute_stability",
    "run_capability_geometry_research_program",
]
