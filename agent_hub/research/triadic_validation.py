from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .telemetry import research_dir


TARGETS = ("success", "validation_score", "failure")
FULL_FEATURES = (
    "model_score",
    "task_score",
    "context_score",
    "model_task",
    "model_context",
    "task_context",
    "error_risk",
    "additive",
    "interaction",
    "radial_gap_extended",
    "bottleneck",
    "reliability_adjusted",
)
ABLATIONS = {
    "full": FULL_FEATURES,
    "remove_model": tuple(feature for feature in FULL_FEATURES if not feature.startswith("model") and feature != "additive"),
    "remove_task": tuple(feature for feature in FULL_FEATURES if not feature.startswith("task") and feature != "additive"),
    "remove_context": tuple(feature for feature in FULL_FEATURES if not feature.startswith("context") and not feature.endswith("context") and feature != "additive"),
    "remove_pairwise_interactions": ("model_score", "task_score", "context_score", "error_risk", "additive", "bottleneck", "reliability_adjusted"),
    "remove_reliability_adjustment": tuple(feature for feature in FULL_FEATURES if feature not in {"error_risk", "reliability_adjusted"}),
}


def compute_triadic_prediction(triadic_payload: dict[str, Any], state_dir: str | Path | None = None) -> dict[str, Any]:
    rows = triadic_payload["rows"]
    results = {
        target: _fit_predict(rows, list(FULL_FEATURES), target)
        for target in TARGETS
    }
    single_metrics = {
        metric: _fit_predict(rows, [metric], "success")
        for metric in ("additive", "interaction", "radial_gap_extended", "bottleneck", "reliability_adjusted")
    }
    best_single = max(single_metrics, key=lambda key: single_metrics[key]["r2"]) if single_metrics else ""
    return {
        "object": "agent_hub.research.triadic_prediction",
        "method": "linear_regression_over_model_task_context_compatibility_terms",
        "features": list(FULL_FEATURES),
        "targets": results,
        "single_metric_success": single_metrics,
        "best_single_metric": best_single,
        "baseline_comparisons": _baseline_comparisons(results, single_metrics, state_dir),
    }


def compute_triadic_ablation(triadic_payload: dict[str, Any]) -> dict[str, Any]:
    rows = triadic_payload["rows"]
    full = _fit_predict(rows, list(ABLATIONS["full"]), "success")
    ablations = {}
    for name, features in ABLATIONS.items():
        result = _fit_predict(rows, list(features), "success")
        result["r2_drop_from_full"] = round(full["r2"] - result["r2"], 6)
        ablations[name] = result
    component_importance = {
        name: row["r2_drop_from_full"]
        for name, row in ablations.items()
        if name != "full"
    }
    return {
        "object": "agent_hub.research.triadic_ablation",
        "full_r2": full["r2"],
        "ablations": ablations,
        "most_important_removed_component": max(component_importance, key=component_importance.get) if component_importance else "",
    }


def compute_triadic_stability(triadic_payload: dict[str, Any]) -> dict[str, Any]:
    rows = triadic_payload["rows"]
    split_rows = []
    for key in ("repository", "model", "task_type", "context_percent"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get(key) or "unknown")].append(row)
        for value, items in grouped.items():
            if len(items) < 20:
                continue
            result = _fit_predict(items, ["reliability_adjusted", "radial_gap_extended", "interaction"], "success")
            split_rows.append({"split": f"{key}:{value}", "rows": len(items), **result})
    return {
        "object": "agent_hub.research.triadic_stability",
        "split_count": len(split_rows),
        "mean_correlation": round(_avg(row["correlation"] for row in split_rows), 6),
        "mean_r2": round(_avg(row["r2"] for row in split_rows), 6),
        "r2_variance": round(_variance(row["r2"] for row in split_rows), 8),
        "splits": split_rows,
    }


def export_triadic_prediction(state_dir: str | Path, triadic_payload: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_triadic_prediction(triadic_payload, state_dir)
    json_path = directory / "triadic_prediction.json"
    md_path = directory / "triadic_prediction.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(prediction_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def export_triadic_ablation(state_dir: str | Path, triadic_payload: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_triadic_ablation(triadic_payload)
    json_path = directory / "triadic_ablation.json"
    md_path = directory / "triadic_ablation.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(ablation_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def export_triadic_stability(state_dir: str | Path, triadic_payload: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_triadic_stability(triadic_payload)
    json_path = directory / "triadic_stability.json"
    md_path = directory / "triadic_stability.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(stability_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def export_triadic_falsification(
    state_dir: str | Path,
    triadic_payload: dict[str, Any],
    prediction: dict[str, Any],
    ablation: dict[str, Any],
) -> Path:
    path = research_dir(state_dir) / "triadic_falsification.md"
    path.write_text(falsification_markdown(triadic_payload, prediction, ablation), encoding="utf-8")
    return path


def export_triadic_summary(
    state_dir: str | Path,
    triadic_payload: dict[str, Any],
    prediction: dict[str, Any],
    ablation: dict[str, Any],
    stability: dict[str, Any],
) -> Path:
    path = research_dir(state_dir) / "model_task_context_research_summary.md"
    evaluation = evaluate(triadic_payload, prediction, ablation, stability)
    path.write_text(summary_markdown(evaluation, triadic_payload, prediction, ablation, stability), encoding="utf-8")
    return path


def evaluate(
    triadic_payload: dict[str, Any],
    prediction: dict[str, Any],
    ablation: dict[str, Any],
    stability: dict[str, Any],
) -> dict[str, Any]:
    success = prediction["targets"]["success"]
    beats_model_task = success["correlation"] > 0.499 and success["r2"] > 0.249
    stability_score = max(0.0, min(1.0, (stability["mean_correlation"] + max(0.0, stability["mean_r2"])) / 2.0))
    predictive = max(0.0, min(1.0, (success["correlation"] + max(0.0, success["r2"])) / 2.0))
    score = round(100.0 * (0.55 * predictive + 0.25 * stability_score + 0.20 * (1.0 if beats_model_task else 0.25)), 2)
    verdict = "A) Strong evidence for Model-Task-Context Compatibility." if score >= 70 else "B) Mixed evidence." if score >= 40 else "C) No evidence."
    return {
        "score": score,
        "verdict": verdict,
        "beats_model_task_geometry": beats_model_task,
        "breakthrough_potential": "high" if score >= 70 else "medium" if score >= 40 else "low",
        "most_important_component": ablation["most_important_removed_component"],
        "best_formula": triadic_payload.get("best_metric"),
    }


def prediction_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Triadic Prediction",
        "",
        f"- Method: `{payload['method']}`",
        f"- Best single success metric: `{payload['best_single_metric']}`",
        "",
        "| target | correlation | R2 | MAE | RMSE | explained variance |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for target, row in payload["targets"].items():
        lines.append(f"| {target} | {row['correlation']} | {row['r2']} | {row['mae']} | {row['rmse']} | {row['explained_variance']} |")
    lines.extend(["", "## Single Metric Success Models", "", "| metric | correlation | R2 | MAE | RMSE |", "| --- | --- | --- | --- | --- |"])
    for metric, row in payload["single_metric_success"].items():
        lines.append(f"| {metric} | {row['correlation']} | {row['r2']} | {row['mae']} | {row['rmse']} |")
    lines.extend(["", "## Baseline Comparisons"])
    for item in payload["baseline_comparisons"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def ablation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Triadic Ablation",
        "",
        f"- Full success R2: {payload['full_r2']}",
        f"- Most important removed component: `{payload['most_important_removed_component']}`",
        "",
        "| ablation | correlation | R2 | R2 drop | MAE | RMSE |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in payload["ablations"].items():
        lines.append(f"| {name} | {row['correlation']} | {row['r2']} | {row['r2_drop_from_full']} | {row['mae']} | {row['rmse']} |")
    lines.append("")
    return "\n".join(lines)


def stability_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Triadic Stability",
        "",
        f"- Mean correlation: {payload['mean_correlation']}",
        f"- Mean R2: {payload['mean_r2']}",
        f"- R2 variance: {payload['r2_variance']}",
        "",
        "| split | rows | correlation | R2 | MAE | RMSE |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["splits"]:
        lines.append(f"| {row['split']} | {row['rows']} | {row['correlation']} | {row['r2']} | {row['mae']} | {row['rmse']} |")
    lines.append("")
    return "\n".join(lines)


def falsification_markdown(triadic_payload: dict[str, Any], prediction: dict[str, Any], ablation: dict[str, Any]) -> str:
    rows = triadic_payload["rows"]
    high_fail = [row for row in rows if row["reliability_adjusted"] >= 0.7 and row["success"] < 0.5]
    context_hurts = _context_hurts(rows)
    failures = []
    if prediction["targets"]["success"]["r2"] <= 0.249:
        failures.append("Triadic compatibility does not beat Model-Task Geometry explained variance.")
    if prediction["targets"]["success"]["correlation"] <= 0.499:
        failures.append("Triadic compatibility does not beat Model-Task Geometry correlation.")
    if high_fail:
        failures.append(f"{len(high_fail)} high-compatibility rows still fail.")
    if context_hurts:
        failures.append(f"{len(context_hurts)} models show lower success at higher context budgets.")
    if ablation["ablations"]["remove_context"]["r2_drop_from_full"] <= 0.01:
        failures.append("Removing context causes little predictive drop.")
    return "\n".join(
        [
            "# Triadic Falsification",
            "",
            "This report tries to falsify Model-Task-Context Compatibility.",
            "",
            "## Evidence Against",
            *[f"- {item}" for item in failures or ["No hard falsification trigger fired."]],
            "",
            "## Stress Cases",
            f"- High compatibility failures: {len(high_fail)}",
            f"- Models where context appears to hurt: {', '.join(context_hurts) if context_hurts else 'none detected'}",
            "",
        ]
    )


def summary_markdown(
    evaluation: dict[str, Any],
    triadic_payload: dict[str, Any],
    prediction: dict[str, Any],
    ablation: dict[str, Any],
    stability: dict[str, Any],
) -> str:
    success = prediction["targets"]["success"]
    context_drop = ablation["ablations"]["remove_context"]["r2_drop_from_full"]
    pair_drop = ablation["ablations"]["remove_pairwise_interactions"]["r2_drop_from_full"]
    return "\n".join(
        [
            "# Model-Task-Context Compatibility Research Summary",
            "",
            f"Final conclusion: {evaluation['verdict']}",
            f"Score: {evaluation['score']}/100",
            "",
            "## Answers",
            f"1. Does context explain the missing variance? {'Partly' if context_drop > 0.01 else 'Weakly'}; removing context changes R2 by {context_drop}.",
            f"2. Does triadic compatibility beat model-task geometry? {evaluation['beats_model_task_geometry']}; success correlation is {success['correlation']} and R2 is {success['r2']}.",
            f"3. Which component matters most? `{evaluation['most_important_component']}` by ablation drop.",
            f"4. Which interaction matters most? Best formula is `{evaluation['best_formula']}`; pairwise interaction removal drops R2 by {pair_drop}.",
            "5. Is this more fundamental than previous theories? Not established unless it beats previous predictive baselines and survives stronger cross-repo tests.",
            "6. Is it useful for routing? Potentially, because the triadic terms are routeable, but offline evidence is not enough for production replacement.",
            f"7. Should this replace Capability Geometry as the main research direction? {evaluation['beats_model_task_geometry'] and evaluation['score'] >= 70}.",
            "",
            "## Required Judgment",
            f"- Breakthrough potential: {evaluation['breakthrough_potential']}.",
            f"- Stability mean correlation: {stability['mean_correlation']}.",
            f"- Strongest contradiction: {'context ablation is weak' if context_drop <= 0.01 else 'high compatibility still fails in some rows'}.",
            "",
        ]
    )


def _fit_predict(rows: list[dict[str, Any]], features: list[str], target: str) -> dict[str, float]:
    if not rows or not features:
        return _stats([], [], [])
    xs = [[1.0] + [float(row.get(feature) or 0.0) for feature in features] for row in rows]
    ys = [float(row.get(target) or 0.0) for row in rows]
    weights = _ridge_weights(xs, ys)
    preds = [max(0.0, min(1.0, sum(w * x for w, x in zip(weights, row)))) for row in xs]
    return _stats(ys, preds)


def _ridge_weights(xs: list[list[float]], ys: list[float], ridge: float = 1e-6) -> list[float]:
    n = len(xs[0])
    xtx = [[sum(row[i] * row[j] for row in xs) + (ridge if i == j else 0.0) for j in range(n)] for i in range(n)]
    xty = [sum(row[i] * y for row, y in zip(xs, ys)) for i in range(n)]
    return _solve(xtx, xty)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [a[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        denom = aug[col][col] or 1e-12
        aug[col] = [value / denom for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [value - factor * aug[col][idx] for idx, value in enumerate(aug[row])]
    return [aug[row][-1] for row in range(n)]


def _stats(actual: list[float], predicted: list[float]) -> dict[str, float]:
    return {
        "correlation": round(_pearson(predicted, actual), 6),
        "r2": round(_r2(actual, predicted), 6),
        "mae": round(_mae(actual, predicted), 6),
        "rmse": round(_rmse(actual, predicted), 6),
        "explained_variance": round(_r2(actual, predicted), 6),
    }


def _baseline_comparisons(results: dict[str, Any], single_metrics: dict[str, Any], state_dir: str | Path | None) -> list[str]:
    success = results["success"]
    best_single = max((row["r2"] for row in single_metrics.values()), default=0.0)
    lines = [
        f"Triadic full success correlation: {success['correlation']}",
        f"Triadic full success R2: {success['r2']}",
        f"Best single triadic formula R2: {best_single}",
        "Reference Model-Task Geometry correlation: 0.499; explained variance: 0.249",
        "Reference Capability Geometry correlation: 0.469",
    ]
    if state_dir is not None:
        path = research_dir(state_dir) / "research_portfolio_rankings.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                names = {
                    "Context Complexity Index",
                    "Information Density Index",
                    "Agent Difficulty Index",
                    "Routing Risk Score",
                    "Expected Utility Score",
                }
                for row in payload.get("ranked_quantities", []):
                    if row.get("name") in names:
                        lines.append(
                            f"Reference {row['name']} predictive power: {round(float(row.get('predictive_power') or 0.0), 6)}"
                        )
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
    return lines


def _context_hurts(rows: list[dict[str, Any]]) -> list[str]:
    hurt = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["model"]].append(row)
    for model, items in grouped.items():
        low = [row for row in items if row["context_percent"] <= 25]
        high = [row for row in items if row["context_percent"] >= 75]
        if low and high and _avg(row["success"] for row in high) + 0.05 < _avg(row["success"] for row in low):
            hurt.append(model)
    return sorted(hurt)


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


def _variance(values: Any) -> float:
    rows = [float(value) for value in values]
    if not rows:
        return 0.0
    mean = sum(rows) / len(rows)
    return sum((value - mean) ** 2 for value in rows) / len(rows)


def _avg(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


__all__ = [
    "compute_triadic_ablation",
    "compute_triadic_prediction",
    "compute_triadic_stability",
    "evaluate",
    "export_triadic_ablation",
    "export_triadic_falsification",
    "export_triadic_prediction",
    "export_triadic_stability",
    "export_triadic_summary",
]
