from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .context_embedding import load_context_observations
from .telemetry import research_dir


FEATURES = (
    "model_prior_success",
    "model_prior_error",
    "model_prior_latency",
    "task_type_prior_success",
    "model_task_prior_success",
    "repo_complexity",
    "repo_file_count",
    "context_token_score",
    "context_budget_score",
    "file_count_score",
    "redundancy",
    "python_file_fraction",
    "test_file_fraction",
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


def run_leakage_audit(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    observations = load_context_observations(state_dir)
    rows = build_pre_execution_rows(observations)
    payload = evaluate_pre_execution(rows)
    json_path = directory / "leakage_audit.json"
    md_path = directory / "leakage_audit.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(leakage_audit_markdown(payload), encoding="utf-8")
    return {"leakage_audit": str(json_path), "leakage_audit_markdown": str(md_path)}


def build_pre_execution_rows(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [row for row in observations if row.get("model")]
    fingerprints = [_fingerprint(row) for row in rows]
    global_stats = _aggregate(rows, fingerprints, lambda _row: "global")
    by_model = _aggregate(rows, fingerprints, lambda row: row["model"])
    by_task = _aggregate(rows, fingerprints, lambda row: row["task_type"])
    by_model_task = _aggregate(rows, fingerprints, lambda row: (row["model"], row["task_type"]))
    audited = []
    for row, fp in zip(rows, fingerprints):
        model = _prior(by_model, row["model"], fp, global_stats)
        task = _prior(by_task, row["task_type"], fp, global_stats)
        model_task = _prior(by_model_task, (row["model"], row["task_type"]), fp, global_stats)
        context = _context_features(row)
        error_risk = _clamp(0.55 * model["error_rate"] + 0.25 * context["overload"] + 0.20 * context["redundancy"])
        additive = (model["success_rate"] + task["success_rate"] + context["context_score"]) / 3.0
        model_context = model["success_rate"] * (1.0 - context["overload"])
        task_context = task["success_rate"] * context["context_score"]
        interaction = (model_task["success_rate"] + model_context + task_context) / 3.0
        radial_gap_extended = 1.0 / (
            1.0
            + abs(model["success_rate"] - task["success_rate"])
            + abs(context["context_score"] - ((model["success_rate"] + task["success_rate"]) / 2.0))
        )
        bottleneck = min(model["success_rate"], task["success_rate"], context["context_score"])
        reliability_adjusted = interaction * (1.0 - error_risk)
        audited.append(
            {
                "model": row["model"],
                "task_type": row["task_type"],
                "repository": row["repository"],
                "context_percent": row["context_percent"],
                "success": 1.0 if row["success"] else 0.0,
                "validation_score": row["validation_score"],
                "failure": 1.0 if (not row["success"] or row["error"]) else 0.0,
                "model_prior_success": model["success_rate"],
                "model_prior_error": model["error_rate"],
                "model_prior_latency": _scale_log(model["latency_ms"], 120000.0),
                "task_type_prior_success": task["success_rate"],
                "model_task_prior_success": model_task["success_rate"],
                "repo_complexity": _scale_log(row["repo_complexity"], 1000.0),
                "repo_file_count": _scale_log(row["repo_file_count"], 1000.0),
                "context_token_score": context["context_token_score"],
                "context_budget_score": context["context_budget_score"],
                "file_count_score": context["file_count_score"],
                "redundancy": context["redundancy"],
                "python_file_fraction": context["python_file_fraction"],
                "test_file_fraction": context["test_file_fraction"],
                "context_score": context["context_score"],
                "model_task": model_task["success_rate"],
                "model_context": model_context,
                "task_context": task_context,
                "error_risk": error_risk,
                "additive": additive,
                "interaction": interaction,
                "radial_gap_extended": radial_gap_extended,
                "bottleneck": bottleneck,
                "reliability_adjusted": reliability_adjusted,
            }
        )
    return audited


def evaluate_pre_execution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    targets = {
        "success": _fit_predict(rows, list(FEATURES), "success"),
        "validation_score": _fit_predict(rows, list(FEATURES), "validation_score"),
        "failure": _fit_predict(rows, list(FEATURES), "failure"),
    }
    single = {
        metric: _fit_predict(rows, [metric], "success")
        for metric in ("additive", "interaction", "radial_gap_extended", "bottleneck", "reliability_adjusted")
    }
    ablations = {
        "full": _fit_predict(rows, list(FEATURES), "success"),
        "remove_model": _fit_predict(rows, [feature for feature in FEATURES if not feature.startswith("model")], "success"),
        "remove_task": _fit_predict(rows, [feature for feature in FEATURES if not feature.startswith("task")], "success"),
        "remove_context": _fit_predict(
            rows,
            [
                feature
                for feature in FEATURES
                if "context" not in feature and feature not in {"file_count_score", "redundancy", "python_file_fraction", "test_file_fraction"}
            ],
            "success",
        ),
        "remove_pairwise_interactions": _fit_predict(
            rows,
            [
                "model_prior_success",
                "model_prior_error",
                "model_prior_latency",
                "task_type_prior_success",
                "repo_complexity",
                "repo_file_count",
                "context_token_score",
                "context_budget_score",
                "file_count_score",
                "redundancy",
                "python_file_fraction",
                "test_file_fraction",
                "context_score",
                "error_risk",
                "additive",
                "bottleneck",
                "reliability_adjusted",
            ],
            "success",
        ),
        "remove_reliability_adjustment": _fit_predict(
            rows,
            [feature for feature in FEATURES if feature not in {"error_risk", "reliability_adjusted"}],
            "success",
        ),
        "remove_historical_outcome_priors": _fit_predict(
            rows,
            [
                "repo_complexity",
                "repo_file_count",
                "context_token_score",
                "context_budget_score",
                "file_count_score",
                "redundancy",
                "python_file_fraction",
                "test_file_fraction",
                "context_score",
            ],
            "success",
        ),
    }
    full_r2 = ablations["full"]["r2"]
    for value in ablations.values():
        value["r2_drop_from_full"] = round(full_r2 - value["r2"], 6)
    result = {
        "object": "agent_hub.research.leakage_audit",
        "row_count": len(rows),
        "feature_policy": {
            "allowed_pre_execution": [
                "model name",
                "task type",
                "repo metrics",
                "planned context tokens",
                "selected files",
                "historical model stats excluding same pre-execution fingerprint",
                "historical error rates excluding same pre-execution fingerprint",
                "historical latency excluding same pre-execution fingerprint",
            ],
            "banned_post_execution": [
                "same-run validation score as predictor",
                "same-run success as predictor",
                "same-run error as predictor",
                "same-run latency as predictor",
                "same-run retry count as predictor",
            ],
        },
        "excluded_features": [
            "actual validation score predictors",
            "actual success predictors",
            "actual error predictors",
            "actual latency for the same run",
            "actual retry count for the same run",
            "context observed success/error aggregates",
            "task embeddings derived from same-run validation/success",
        ],
        "features_used": list(FEATURES),
        "targets": targets,
        "single_metric_success": single,
        "best_single_metric": max(single, key=lambda key: single[key]["r2"]) if single else "",
        "ablations": ablations,
        "verdict": _verdict(targets["success"]),
        "baseline_reference": {
            "capability_geometry_correlation": 0.469,
            "model_task_geometry_correlation": 0.499,
            "model_task_geometry_explained_variance": 0.249,
            "leaky_triadic_correlation": 0.907564,
            "leaky_triadic_r2": 0.819303,
        },
        "audit_caveats": [
            "Historical priors are allowed by the audit policy, but the dataset contains many repeated deterministic/local rows.",
            "The remove_historical_outcome_priors ablation is a cold structural stress test, not the primary allowed-feature result.",
        ],
    }
    return result


def leakage_audit_markdown(payload: dict[str, Any]) -> str:
    success = payload["targets"]["success"]
    lines = [
        "# Leakage Audit",
        "",
        f"- Rows audited: {payload['row_count']}",
        f"- Verdict: {payload['verdict']}",
        f"- Pre-execution success correlation: {success['correlation']}",
        f"- Pre-execution success R2: {success['r2']}",
        f"- Pre-execution success MAE: {success['mae']}",
        f"- Pre-execution success RMSE: {success['rmse']}",
        "",
        "## Feature Separation",
        "",
        "Allowed pre-execution features:",
        *[f"- {item}" for item in payload["feature_policy"]["allowed_pre_execution"]],
        "",
        "Banned post-execution features removed:",
        *[f"- {item}" for item in payload["feature_policy"]["banned_post_execution"]],
        "",
        "Additional leakage-prone features excluded:",
        *[f"- {item}" for item in payload["excluded_features"]],
        "",
        "## Recomputed Prediction",
        "",
        "| target | correlation | R2 | MAE | RMSE |",
        "| --- | --- | --- | --- | --- |",
    ]
    for target, row in payload["targets"].items():
        lines.append(f"| {target} | {row['correlation']} | {row['r2']} | {row['mae']} | {row['rmse']} |")
    lines.extend(["", "## Single Formula Success", "", "| formula | correlation | R2 | MAE | RMSE |", "| --- | --- | --- | --- | --- |"])
    for metric, row in payload["single_metric_success"].items():
        lines.append(f"| {metric} | {row['correlation']} | {row['r2']} | {row['mae']} | {row['rmse']} |")
    lines.extend(["", "## Ablation", "", "| ablation | correlation | R2 | R2 drop |", "| --- | --- | --- | --- |"])
    for name, row in payload["ablations"].items():
        lines.append(f"| {name} | {row['correlation']} | {row['r2']} | {row['r2_drop_from_full']} |")
    ref = payload["baseline_reference"]
    lines.extend(
        [
            "",
            "## Baseline Check",
            f"- Capability Geometry correlation: {ref['capability_geometry_correlation']}",
            f"- Model-Task Geometry correlation: {ref['model_task_geometry_correlation']}",
            f"- Model-Task Geometry explained variance: {ref['model_task_geometry_explained_variance']}",
            f"- Previous triadic report before strict audit: correlation {ref['leaky_triadic_correlation']}, R2 {ref['leaky_triadic_r2']}",
            "",
            "## Caveats",
            *[f"- {item}" for item in payload["audit_caveats"]],
            "",
            "## Conclusion",
            _conclusion(payload),
            "",
        ]
    )
    return "\n".join(lines)


def _aggregate(rows: list[dict[str, Any]], fingerprints: list[str], key_fn: Any) -> dict[str, Any]:
    totals: dict[Any, dict[str, float]] = defaultdict(lambda: {"n": 0.0, "success": 0.0, "error": 0.0, "latency": 0.0})
    by_fp: dict[tuple[Any, str], dict[str, float]] = defaultdict(lambda: {"n": 0.0, "success": 0.0, "error": 0.0, "latency": 0.0})
    for row, fp in zip(rows, fingerprints):
        key = key_fn(row)
        target = totals[key]
        fp_target = by_fp[(key, fp)]
        for bucket in (target, fp_target):
            bucket["n"] += 1.0
            bucket["success"] += 1.0 if row["success"] else 0.0
            bucket["error"] += 1.0 if row["error"] else 0.0
            bucket["latency"] += float(row["latency_ms"] or 0.0)
    return {"totals": totals, "by_fp": by_fp}


def _prior(aggregate: dict[str, Any], key: Any, fingerprint: str, fallback_aggregate: dict[str, Any]) -> dict[str, float]:
    total = dict(aggregate["totals"].get(key, {}))
    remove = aggregate["by_fp"].get((key, fingerprint), {})
    values = {
        name: float(total.get(name, 0.0)) - float(remove.get(name, 0.0))
        for name in ("n", "success", "error", "latency")
    }
    if values["n"] <= 0:
        total = dict(fallback_aggregate["totals"].get("global", {}))
        remove = fallback_aggregate["by_fp"].get(("global", fingerprint), {})
        values = {
            name: float(total.get(name, 0.0)) - float(remove.get(name, 0.0))
            for name in ("n", "success", "error", "latency")
        }
    n = max(1.0, values["n"])
    return {
        "success_rate": values["success"] / n,
        "error_rate": values["error"] / n,
        "latency_ms": values["latency"] / n,
    }


def _context_features(row: dict[str, Any]) -> dict[str, float]:
    files = row.get("selected_files") or []
    file_count = max(0.0, float(row.get("file_count") or len(files)))
    context_tokens = max(0.0, float(row.get("context_tokens") or 0.0))
    context_percent = max(0.0, float(row.get("context_percent") or 0.0))
    redundancy = _redundancy(files)
    python_fraction = _fraction(files, ".py")
    test_fraction = sum(1 for item in files if "test" in item.lower()) / len(files) if files else 0.0
    token_score = 1.0 / (1.0 + abs(context_tokens - 4000.0) / 4000.0)
    budget_score = 1.0 / (1.0 + abs(context_percent - 50.0) / 50.0) if context_percent else 0.35
    file_score = 1.0 / (1.0 + abs(file_count - 8.0) / 8.0) if file_count else 0.35
    overload = _clamp((context_tokens - 8000.0) / 8000.0 + redundancy * 0.5)
    context_score = _clamp(0.35 * token_score + 0.25 * budget_score + 0.20 * file_score + 0.10 * python_fraction + 0.10 * test_fraction - 0.20 * redundancy)
    return {
        "context_token_score": token_score,
        "context_budget_score": budget_score,
        "file_count_score": file_score,
        "redundancy": redundancy,
        "python_file_fraction": python_fraction,
        "test_file_fraction": test_fraction,
        "overload": overload,
        "context_score": context_score,
    }


def _fit_predict(rows: list[dict[str, Any]], features: list[str], target: str) -> dict[str, float]:
    if not rows or not features:
        return _stats([], [])
    xs = [[1.0] + [float(row.get(feature) or 0.0) for feature in features] for row in rows]
    ys = [float(row.get(target) or 0.0) for row in rows]
    weights = _ridge_weights(xs, ys)
    predictions = [_clamp(sum(weight * value for weight, value in zip(weights, row))) for row in xs]
    return _stats(ys, predictions)


def _ridge_weights(xs: list[list[float]], ys: list[float], ridge: float = 1e-5) -> list[float]:
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
    }


def _fingerprint(row: dict[str, Any]) -> str:
    payload = {
        "model": row.get("model"),
        "task_type": row.get("task_type"),
        "repository": row.get("repository"),
        "context_tokens": int(float(row.get("context_tokens") or 0.0) // 250) * 250,
        "context_percent": int(float(row.get("context_percent") or 0.0)),
        "file_count": int(float(row.get("file_count") or 0.0)),
        "files": row.get("selected_files", [])[:80],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def _fraction(files: list[str], suffix: str) -> float:
    return sum(1 for item in files if item.endswith(suffix)) / len(files) if files else 0.0


def _redundancy(files: list[str]) -> float:
    if not files:
        return 0.0
    roots = [item.split("/", 1)[0] for item in files]
    return 1.0 - len(set(roots)) / len(roots)


def _scale_log(value: float, maximum: float) -> float:
    return math.log1p(max(0.0, value)) / math.log1p(maximum)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


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


def _verdict(success: dict[str, float]) -> str:
    if success["correlation"] >= 0.7 and success["r2"] >= 0.5:
        return "strong after leakage audit"
    if success["correlation"] >= 0.4 or success["r2"] >= 0.25:
        return "mixed after leakage audit"
    return "weak after leakage audit"


def _conclusion(payload: dict[str, Any]) -> str:
    success = payload["targets"]["success"]
    if success["correlation"] >= 0.7 and success["r2"] >= 0.5:
        return "The pre-execution-only recomputation remains strong."
    if success["correlation"] >= 0.4 or success["r2"] >= 0.25:
        return "The pre-execution-only recomputation remains useful but no longer strongly supports the earlier claim."
    return "The strong triadic result does not survive the strict leakage audit."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a leakage audit for triadic compatibility.")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        from ..config import load_config

        state_dir = load_config().state_dir
    result = run_leakage_audit(state_dir)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_pre_execution_rows", "evaluate_pre_execution", "run_leakage_audit"]
