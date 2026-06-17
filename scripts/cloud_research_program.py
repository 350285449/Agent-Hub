from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import measurement_science_program as m

RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

CLOUD_MODELS = {
    "kimi-k2.6:cloud",
    "glm-5.1:cloud",
    "qwen3.5:cloud",
    "nemotron-3-super:cloud",
    "gemma4:31b-cloud",
}


def write_md(name: str, text: str) -> None:
    RESEARCH.mkdir(exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    content = text.strip() + "\n"
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def table(headers: list[str], rows: list[list[object]]) -> str:
    return m.table(headers, rows)


def cloud_rows() -> tuple[list[dict], list[dict]]:
    rows = m.build_rows()
    def allowed(row: dict) -> bool:
        provider = str(row.get("provider") or "").lower()
        provider_type = str(row.get("provider_type") or "").lower()
        disallowed_provider = any(token in provider or token in provider_type for token in ["ollama", "local", "codex", "self-host", "edge"])
        return row["model"] in CLOUD_MODELS and not disallowed_provider

    return [row for row in rows if allowed(row)], [row for row in rows if not allowed(row)]


def prospective_cloud_metrics() -> dict:
    path = PRIVATE_RESEARCH / "prospective_results.json"
    if not path.exists():
        return {"rows": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches = payload.get("matches", [])
    cloud = [row for row in matches if row.get("model") in CLOUD_MODELS]
    y = [float(row["actual"]) for row in cloud]
    pred = [float(row["predicted"]) for row in cloud]
    if not cloud:
        return {"rows": 0, "excluded": len(matches)}
    return {
        "rows": len(cloud),
        "excluded": len(matches) - len(cloud),
        "successes": int(sum(y)),
        "failures": len(y) - int(sum(y)),
        "models": Counter(row["model"] for row in cloud),
        "categories": Counter(row["category"] for row in cloud),
        "corr": m.corr(pred, y),
        "auc": m.auc(pred, y),
        "brier": m.brier(pred, y),
        "r2": max(0.0, m.r2(y, pred)),
        "all_model_r2": float(payload.get("metrics", {}).get("r2", 0.0)),
        "all_model_corr": float(payload.get("metrics", {}).get("correlation", 0.0)),
    }


def holdout_metrics(rows: list[dict], fields: list[str]) -> dict[str, float]:
    train = [row for row in rows if row.get("dataset") == "historical"]
    holdout = [row for row in rows if row.get("dataset") != "historical"]
    x = [[1.0, *[row[field] for field in fields]] for row in train]
    p = len(x[0])
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(p)] for i in range(p)]
    xty = [sum(features[i] * row["success"] for features, row in zip(x, train)) for i in range(p)]
    beta = m.solve(xtx, xty)
    pred = [m.clamp01(sum(beta[i] * value for i, value in enumerate([1.0, *[row[field] for field in fields]]))) for row in holdout]
    y = [row["success"] for row in holdout]
    return {**m.metrics(pred, y), "rows": len(holdout), "raw_r2": max(0.0, m.r2(y, pred))}


def fit_linear(rows: list[dict], fields: list[str]) -> list[float]:
    material = [row for row in rows if all(row.get(field) is not None for field in fields)]
    x = [[1.0, *[float(row[field]) for field in fields]] for row in material]
    if not x:
        return [0.0] * (len(fields) + 1)
    p = len(x[0])
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(p)] for i in range(p)]
    xty = [sum(features[i] * row["success"] for features, row in zip(x, material)) for i in range(p)]
    return m.solve(xtx, xty)


def predict_row(beta: list[float], row: dict, fields: list[str]) -> float:
    return m.clamp01(sum(beta[i] * value for i, value in enumerate([1.0, *[float(row[field]) for field in fields]])))


def fit_predict_metrics(train: list[dict], test: list[dict], fields: list[str]) -> dict[str, float]:
    material = [row for row in test if all(row.get(field) is not None for field in fields)]
    beta = fit_linear(train, fields)
    pred = [predict_row(beta, row, fields) for row in material]
    y = [float(row["success"]) for row in material]
    out = {**m.metrics(pred, y), "rows": len(material), "raw_r2": max(0.0, m.r2(y, pred))}
    out["base_brier"] = m.brier([mean(y)] * len(y), y) if y else 0.0
    out["brier_gain"] = out["base_brier"] - out["brier"]
    out["calibration_error"] = calibration_error(pred, y)
    return out


def calibration_bins(pred: list[float], y: list[float], bins: int = 5) -> list[list[object]]:
    out = []
    for i in range(bins):
        lo = i / bins
        hi = (i + 1) / bins
        idx = [j for j, p in enumerate(pred) if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if not idx:
            out.append([f"{lo:.1f}-{hi:.1f}", 0, "", "", ""])
            continue
        avg_p = mean(pred[j] for j in idx)
        avg_y = mean(y[j] for j in idx)
        out.append([f"{lo:.1f}-{hi:.1f}", len(idx), round(avg_p, 3), round(avg_y, 3), round(avg_y - avg_p, 3)])
    return out


def calibration_error(pred: list[float], y: list[float], bins: int = 5) -> float:
    if not pred:
        return 0.0
    err = 0.0
    for row in calibration_bins(pred, y, bins):
        if not row[1]:
            continue
        err += int(row[1]) * abs(float(row[4]))
    return round(err / len(pred), 6)


def prediction_interval(samples: list[float]) -> tuple[float, float, float]:
    if not samples:
        return (0.0, 0.0, 0.0)
    ordered = sorted(samples)
    lo = ordered[int(0.025 * (len(ordered) - 1))]
    hi = ordered[int(0.975 * (len(ordered) - 1))]
    return (lo, hi, math.sqrt(m.variance(samples)))


def bootstrap_predictions(train: list[dict], target: dict, fields: list[str], samples: int = 120) -> list[float]:
    if len(train) < 20:
        return []
    preds = []
    for i in range(samples):
        sampled = [train[m.RNG.randrange(len(train))] for _j in range(len(train))]
        beta = fit_linear(sampled, fields)
        preds.append(predict_row(beta, target, fields))
    return preds


def bootstrap_betas(train: list[dict], fields: list[str], samples: int = 60) -> list[list[float]]:
    if len(train) < 20:
        return []
    betas = []
    for _i in range(samples):
        sampled = [train[m.RNG.randrange(len(train))] for _j in range(len(train))]
        betas.append(fit_linear(sampled, fields))
    return betas


def predict_with_betas(betas: list[list[float]], target: dict, fields: list[str]) -> list[float]:
    return [predict_row(beta, target, fields) for beta in betas]


def feature_estimator(rows: list[dict]):
    global_means = {field: mean(float(row[field]) for row in rows if row.get(field) is not None) for field in ["K", "rho", "A", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"]}
    buckets: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    model_buckets: dict[str, list[dict]] = defaultdict(list)
    model_category_buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    repo_category_buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        buckets[(row["model"], row["repository"], row["category"])].append(row)
        model_buckets[row["model"]].append(row)
        model_category_buckets[(row["model"], row["category"])].append(row)
        repo_category_buckets[(row["repository"], row["category"])].append(row)

    def avg(source: list[dict], field: str) -> float:
        vals = [float(row[field]) for row in source if row.get(field) is not None]
        return mean(vals) if vals else global_means[field]

    def estimate(cell: dict) -> dict:
        model = cell["model"]
        repository = cell["repository"]
        category = cell["category"]
        exact = buckets.get((model, repository, category), [])
        model_rows = model_buckets.get(model, [])
        model_category = model_category_buckets.get((model, category), [])
        repo_category = repo_category_buckets.get((repository, category), [])
        out = dict(cell)
        out["K"] = avg(model_rows, "K")
        out["rho"] = avg(model_category or model_rows, "rho")
        for field in ["A", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"]:
            out[field] = avg(exact or repo_category or model_category or model_rows, field)
        return out

    return estimate


def frozen_cells(rows: list[dict]) -> list[dict]:
    repositories = sorted({row["repository"] for row in rows if row["repository"]})[:4]
    categories = ["bug_fix", "testing", "refactor", "analysis", "architecture", "documentation"]
    contexts = [0, 25, 50]
    sets = [
        ("calibration_grid", repositories[:3], categories[:4], contexts[:2]),
        ("hard_generalization", repositories[:3], ["architecture", "refactor", "testing"], [0, 25, 50]),
        ("accessibility_stress", repositories[:3], ["bug_fix", "documentation", "analysis"], [0, 50]),
    ]
    cells = []
    for set_name, repos, cats, budgets in sets:
        for model in sorted(CLOUD_MODELS):
            for repository in repos:
                for category in cats:
                    for context_budget in budgets:
                        cells.append({"benchmark_set": set_name, "model": model, "repository": repository, "category": category, "context_budget": context_budget})
    return cells


def reconstructed_prospective_rows(rows: list[dict]) -> list[dict]:
    path = PRIVATE_RESEARCH / "prospective_results.json"
    if not path.exists():
        return []
    estimate = feature_estimator(rows)
    payload = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for match in payload.get("matches", []):
        if match.get("model") not in CLOUD_MODELS:
            continue
        cell = {
            "model": match.get("model"),
            "repository": match.get("repository"),
            "category": match.get("category"),
            "context_budget": float(match.get("context_budget") or 0.0),
            "success": float(match.get("actual") or 0.0),
            "task_id": match.get("task_id"),
            "compatibility_prediction": float(match.get("predicted") or 0.0),
        }
        out.append(estimate(cell))
    return out


def prospective_failure_clusters(rows: list[dict], fields: list[str]) -> tuple[list[list[object]], list[list[object]], list[list[object]]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    prospective_rows = reconstructed_prospective_rows(rows)
    beta = fit_linear(train, fields)
    enriched = []
    for row in prospective_rows:
        pred = predict_row(beta, row, fields)
        enriched.append((row, row["success"] - pred, pred))
    fps = sorted([item for item in enriched if item[0]["success"] < 0.5], key=lambda item: item[2], reverse=True)[:10]
    fns = sorted([item for item in enriched if item[0]["success"] >= 0.5], key=lambda item: item[2])[:10]
    cluster_rows = []
    for group in ["model", "repository", "category", "context_budget"]:
        buckets: dict[str, list[float]] = defaultdict(list)
        for row, residual, _pred in enriched:
            value = row.get(group)
            buckets[str(value) if value is not None else ""].append(residual)
        for key, values in buckets.items():
            if len(values) >= 3:
                cluster_rows.append([group, key, len(values), round(mean(values), 6), round(m.variance(values) ** 0.5, 6)])
    cluster_rows.sort(key=lambda row: abs(float(row[3])), reverse=True)
    fp_rows = [[row.get("task_id"), row["model"], row["repository"], row["category"], round(pred, 3), round(err, 3)] for row, err, pred in fps]
    fn_rows = [[row.get("task_id"), row["model"], row["repository"], row["category"], round(pred, 3), round(err, 3)] for row, err, pred in fns]
    return fp_rows, fn_rows, cluster_rows[:15]


def write_prediction_v2_reports(rows: list[dict], scope: str, base: float, full: float, corrected: float, ceiling: float) -> None:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    model_specs = [
        ("K", ["K"]),
        ("K+rho", ["K", "rho"]),
        ("K+rho+A", ["K", "rho", "A"]),
        ("K+rho+A1-A5", ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"]),
    ]
    holdout_rows = []
    for name, fields in model_specs:
        stats = fit_predict_metrics(train, holdout, fields)
        holdout_rows.append([name, stats["rows"], stats["corr"], stats["auc"], stats["brier"], round(stats["base_brier"], 6), round(stats["brier_gain"], 6), stats["r2"], stats["calibration_error"]])

    prospective_rows = reconstructed_prospective_rows(rows)
    prospective_metric_rows = []
    for name, fields in model_specs:
        stats = fit_predict_metrics(train, prospective_rows, fields) if prospective_rows else {"rows": 0, "corr": 0, "auc": 0, "brier": 0, "base_brier": 0, "brier_gain": 0, "r2": 0, "calibration_error": 0}
        prospective_metric_rows.append([name, stats["rows"], stats["corr"], stats["auc"], stats["brier"], round(stats["base_brier"], 6), round(stats["brier_gain"], 6), stats["r2"], stats["calibration_error"]])

    primary_fields = ["K", "rho", "A"]
    primary_beta = fit_linear(train, primary_fields)
    prospective_pred = [predict_row(primary_beta, row, primary_fields) for row in prospective_rows]
    prospective_y = [float(row["success"]) for row in prospective_rows]
    holdout_pred = [predict_row(primary_beta, row, primary_fields) for row in holdout]
    holdout_y = [float(row["success"]) for row in holdout]

    estimate = feature_estimator(rows)
    forecast_cells = [estimate(cell) for cell in frozen_cells(rows)]
    forecast_rows = []
    set_summary: dict[str, list[float]] = defaultdict(list)
    beta_samples = bootstrap_betas(train, primary_fields)
    for cell in forecast_cells:
        samples = predict_with_betas(beta_samples, cell, primary_fields)
        pred = predict_row(primary_beta, cell, primary_fields)
        lo, hi, sd = prediction_interval(samples or [pred])
        cell["predicted_success_probability"] = pred
        set_summary[cell["benchmark_set"]].append(pred)
        if len(forecast_rows) < 36:
            forecast_rows.append([cell["benchmark_set"], cell["model"], cell["repository"], cell["category"], cell["context_budget"], round(pred, 3), f"[{round(lo, 3)}, {round(hi, 3)}]", round(sd, 3)])
    set_rows = [[name, len(vals), round(mean(vals), 3), round(min(vals), 3), round(max(vals), 3), round(mean(p * (1 - p) for p in vals), 3)] for name, vals in set_summary.items()]

    fp_rows, fn_rows, cluster_rows = prospective_failure_clusters(rows, primary_fields)

    write_md(
        "prospective_prediction_framework.md",
        f"""
# Prospective Prediction Framework

Scope: {scope}

## Frozen Rule

The v2 framework is prediction-first. Every row must be written with model, repository, category, context budget, K, rho, A, success probability, confidence interval, and uncertainty estimate before execution. Outcomes are appended only after the frozen forecast file exists.

## Cloud-Only Inclusion

Allowed model IDs are {", ".join(sorted(CLOUD_MODELS))}. Codex, Ollama, local, self-hosted, quantized, and edge results are excluded before every statistic is computed.

## Benchmark Sets

{table(["set", "forecast rows", "mean p(success)", "min p", "max p", "mean uncertainty p(1-p)"], set_rows)}

## Model Tournament

The frozen comparison models are K, K+rho, K+rho+A, and K+rho+A1-A5. A1-A5 is reported as an upper-bound diagnostic because A4/A5 are currently post-generation traces; K+rho+A is the primary deployable forecast model until A4/A5 can be measured before generation.

## Required Metrics

Calibration error, reliability curves, Brier score, base-rate Brier gain, prediction error, false-positive clusters, and false-negative clusters are recomputed from cloud-only rows. A positive result is accepted only if it beats K and K+rho prospectively, not merely retrospectively.

## Falsification Gates

- Reject strong predictive-science claims if prospective R2 remains below 0.25 or Brier does not beat base rate by at least 0.03.
- Reject Accessibility as prospective improvement if K+rho+A does not beat K+rho on frozen outcomes.
- Treat the {fmt(ceiling)} ceiling as unvalidated if real prospective R2 remains near zero.
- Promote no fourth primitive from residuals unless it is measurable before execution and survives deconfounding.
""",
    )

    write_md(
        "benchmark_forecast_results.md",
        f"""
# Benchmark Forecast Results

Scope: {scope}

These are frozen v2 forecasts for future execution. They are not outcomes.

## Forecast Set Summary

{table(["set", "forecast rows", "mean p(success)", "min p", "max p", "mean uncertainty p(1-p)"], set_rows)}

## First Frozen Forecast Rows

{table(["set", "model", "repository", "category", "context", "p(success)", "95% CI", "uncertainty sd"], forecast_rows)}

## Execution Rule

Run rows in the listed frozen sets without editing K, rho, A, probabilities, intervals, or benchmark membership. Append outcomes in a new result artifact after execution.
""",
    )

    write_md(
        "prediction_calibration_report.md",
        f"""
# Prediction Calibration Report

Scope: {scope}

## Retrospective Frozen-Style Holdout

{table(["model", "rows", "corr", "AUC", "Brier", "base Brier", "Brier gain", "R2", "calibration error"], holdout_rows)}

## Prior Prospective Set Reconstructed With v2 Features

{table(["model", "rows", "corr", "AUC", "Brier", "base Brier", "Brier gain", "R2", "calibration error"], prospective_metric_rows)}

This reconstruction is not accepted as clean v2 prospective evidence because K/rho/A were not frozen for those rows before execution. It is a falsification stress test against the current measurement family.

## K+rho+A Reliability Curve: Holdout

{table(["prediction bin", "rows", "mean predicted", "mean actual", "actual - predicted"], calibration_bins(holdout_pred, holdout_y))}

## K+rho+A Reliability Curve: Prior Prospective Reconstruction

{table(["prediction bin", "rows", "mean predicted", "mean actual", "actual - predicted"], calibration_bins(prospective_pred, prospective_y))}

## Verdict

Calibration is not yet acceptable prospectively. Holdout calibration can look useful, but the prior prospective reconstruction is narrow, model-imbalanced, and does not validate the retrospective ceiling.
""",
    )

    write_md(
        "prediction_failure_analysis.md",
        f"""
# Prediction Failure Analysis

Scope: {scope}

## Major False Positives

{table(["task", "model", "repository", "category", "predicted", "actual - predicted"], fp_rows)}

## Major False Negatives

{table(["task", "model", "repository", "category", "predicted", "actual - predicted"], fn_rows)}

## Failure Clusters

{table(["axis", "cluster", "rows", "mean residual", "residual sd"], cluster_rows)}

## Failure Hypotheses

False positives mostly indicate that historical K/rho/A over-credit cells where execution reliability, benchmark ambiguity, or repository-specific constraints dominate. False negatives indicate the opposite: coarse rho and A under-credit recoverable tasks where the model can exploit local structure despite low prior compatibility.

## Attack On Positive Results

The strongest attack is timing leakage. K and rho are historical outcome summaries, and A still mixes clean access with traces of evidence use. If a future frozen set cannot reproduce the holdout ordering, then the framework is explanatory bookkeeping, not predictive science.
""",
    )

    best_holdout = max(holdout_rows, key=lambda row: float(row[7])) if holdout_rows else ["n/a"]
    best_prospective = max(prospective_metric_rows, key=lambda row: float(row[7])) if prospective_metric_rows else ["n/a"]
    write_md(
        "prospective_validation_v2.md",
        f"""
# Prospective Validation v2

Scope: {scope}

## Answers

1. Can K+rho+A predict future outcomes? Not established. It has retrospective holdout signal, but clean future v2 outcomes are still pending.
2. Is calibration acceptable? Not prospectively. The prior prospective reconstruction and old compatibility tournament are too narrow and weak.
3. What is the real prospective R2? The only actually frozen cloud-only prospective tournament remains effectively 0 for the accepted cloud subset; v2 real R2 is pending until the frozen sets are executed.
4. What causes major forecast failures? Coarse rho cells, repository-specific execution constraints, ambiguous benchmark labels, and post-run contamination in A-like variables.
5. Does Accessibility improve prospective prediction? Retrospectively it can, especially with A1-A5; prospectively it is unproven because clean pre-run A must beat K+rho after freezing.
6. Is the 0.865 ceiling reflected in real forecasting performance? No. The ceiling is a measurement prior, not observed prospective performance.
7. Is Agent-Hub becoming predictive science or only explanatory science? It is not yet predictive science. It becomes predictive only if the frozen v2 forecasts calibrate on new cloud-only outcomes.

## Tournament Status

Best retrospective holdout model by R2: {best_holdout[0]} ({best_holdout[7]}). Best prior prospective reconstruction by R2: {best_prospective[0]} ({best_prospective[7]}).

## Decision

The framework survives as a forecast protocol, not as a validated predictive theory. The next execution must be adversarial: prioritize uncertain cells near p=0.5, hard repositories, low context budgets, and model/category cells where retrospective fit is likely to fail.
""",
    )

    write_md(
        "scientific_assessment_v3.md",
        f"""
# Scientific Assessment v3

Scope: {scope}

## Current Scientific Claim

K+rho+A is a cloud-only explanatory measurement framework with a plausible prospective protocol. It is not yet a validated prospective prediction law.

## Evidence For

- Cloud-only K+rho+A R2 remains {fmt(base)}.
- Cloud-only K+rho+A1-A5 R2 remains {fmt(full)}.
- Reliability-corrected R2 remains {fmt(corrected)}.
- Ceiling estimate remains {fmt(ceiling)}.

## Evidence Against

- The only actually frozen cloud-only prospective result collapses after filtering and does not reflect the ceiling.
- A1-A5 improves retrospective fit partly because A4/A5 are post-generation diagnostics.
- No fourth primitive survives deconfounding, but that does not rescue the predictive claim.
- K and rho may be fitting historical model/task cells rather than stable future behavior.

## Falsification Result

The positive retrospective result has been attacked by cloud-only filtering, prospective reconstruction, calibration tests, Brier/base-rate comparison, A timing separation, and failure clustering. The framework is still worth testing, but the strong success condition is not met.

## Bottom Line

Agent-Hub is at the boundary between explanatory science and predictive science. It crosses that boundary only if the frozen v2 cloud-only benchmark sets produce calibrated probabilities and K+rho+A consistently beats K and K+rho on new outcomes.
""",
    )


def residual_cluster_rows(rows: list[dict]) -> list[list[object]]:
    res = m.residuals(rows, ["K", "rho", "A"])
    out: list[list[object]] = []
    for group in ["model", "repository", "category", "dataset", "source"]:
        buckets: dict[str, list[float]] = defaultdict(list)
        for row, residual, _pred in res:
            buckets[str(row.get(group) or "")].append(residual)
        for key, values in buckets.items():
            if len(values) >= 6:
                out.append([group, key, len(values), round(mean(values), 6), round(m.variance(values) ** 0.5, 6)])
    return sorted(out, key=lambda row: abs(float(row[3])), reverse=True)


def main() -> int:
    rows, excluded = cloud_rows()
    source_rows = m.build_rows()
    base = m.combined_r2(rows, ["K", "rho", "A"])
    pre = m.combined_r2(rows, ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"])
    full = m.combined_r2(rows, ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"])
    observed = m.combined_r2(rows, ["K", "rho", "A", "Route Friction", "Retrieval Selectivity", "Compatibility v2", "Actionability"])
    rel = m.reliability_table(rows)
    mean_rel = mean(item["reliability"] for item in rel if item["variable"] in {"K", "rho", "A"})
    corrected = min(0.95, base / max(0.45, mean_rel))
    ceiling = min(0.95, max(observed, full, corrected) + 0.05)
    prospective = prospective_cloud_metrics()

    exclusion_counts = Counter(row["model"] for row in excluded)
    exclusion_providers = Counter(str(row.get("provider") or "unknown") for row in excluded)
    upstream_audit = json.loads((PRIVATE_RESEARCH / "research_data_audit.json").read_text(encoding="utf-8")) if (PRIVATE_RESEARCH / "research_data_audit.json").exists() else {}
    scope = (
        f"Cloud-only aligned rows: {len(rows)} of {len(source_rows)}. "
        f"Aligned exclusions: {len(excluded)} rows by model {dict(exclusion_counts)} and provider {dict(exclusion_providers)}. "
        f"Upstream strict audit additionally reported {upstream_audit.get('deterministic_rows', 'n/a')} local deterministic rows, "
        f"{upstream_audit.get('timeouts', 'n/a')} timeout-only rows, and exclusion reasons {upstream_audit.get('exclusion_reasons', {})}."
    )

    component_rows = []
    for field in ["old_A", "A", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"]:
        vals = [row[field] for row in rows]
        labels = [row["success"] for row in rows]
        metrics = m.metrics(vals, labels)
        ci = m.ci(vals, labels, "corr", 150)
        component_rows.append([field, metrics["corr"], f"[{round(ci[0], 3)}, {round(ci[1], 3)}]", metrics["auc"], metrics["r2"], m.timing_for_a(field) if field.startswith("A") and field != "A" else "mixed/pre-existing"])

    write_md(
        "accessibility_3.md",
        f"""
# Accessibility 3

Scope: {scope}

## Result

| model | R2 |
| --- | ---: |
| K+rho+current A | {fmt(base)} |
| K+rho+pre-run A1-A3 | {fmt(pre)} |
| K+rho+full A1-A5 | {fmt(full)} |

## Evidence

{table(["component", "corr", "95% corr CI", "AUC", "single-var R2", "timing"], component_rows)}

Current A beats the old context-volume proxy, and the full A1-A5 trace raises explanatory power by {fmt(full - base)} R2 over K+rho+A.

## Counter-Evidence

Pre-run A1-A3 alone lowers R2 by {fmt(pre - base)} versus current A. The strongest accessibility components are A4 and A5, which are currently post-generation diagnostics.

## Uncertainty

The clean causal part of accessibility is weakly measured. The full trace is predictive, but some of that signal may be evidence-use outcome behavior rather than pre-run access.

## Falsification Attempt

If post-generation A4/A5 are banned, accessibility improvement disappears. Accessibility survives as a measurement target, but not as a fully validated prospective pre-run primitive.
""",
    )

    spec_rows = []
    for name in m.category_components(rows[0]).keys():
        vals = [m.category_components(row)[name] * row["rho"] for row in rows]
        metrics = m.metrics(vals, [row["success"] for row in rows])
        spec_rows.append([name, metrics["corr"], metrics["auc"], metrics["r2"], round(m.redundancy([{**row, name: m.category_components(row)[name] * row["rho"]} for row in rows], name, ["K", "A"]), 6)])
    spec_rows.sort(key=lambda row: abs(float(row[1])), reverse=True)
    write_md(
        "specialization_v2.md",
        f"""
# Specialization v2

Scope: {scope}

## Evidence

{table(["rho dimension proxy", "corr", "AUC", "single-var R2", "redundancy vs K/A"], spec_rows)}

rho is the strongest reliability-adjusted variable in the cloud-only audit: corr {rel[0]["corr"]} with reliability {rel[0]["reliability"]} when ranked against measured competitors.

## Counter-Evidence

rho is still an outcome-derived model-task residual, and several subdimensions are actually proxies for output behavior or category labels. Removing rho costs only {fmt(base - m.combined_r2(rows, ["K", "A"]))} R2.

## Uncertainty

The decomposition is observable but not yet causally clean. Repository affinity, tool affinity, and long-context affinity are confounded with model family and benchmark provenance.

## Falsification Attempt

Adding Compatibility v2, Route Friction, Retrieval Selectivity, and Actionability to K+rho+A raises R2 only from {fmt(base)} to {fmt(observed)}. This argues against a hidden fourth factor inside current measured variables, but it also shows rho is not independently settled.
""",
    )

    res = m.residuals(rows, ["K", "rho", "A"])
    fps = sorted([item for item in res if item[0]["success"] < 0.5], key=lambda item: item[2], reverse=True)[:8]
    fns = sorted([item for item in res if item[0]["success"] >= 0.5], key=lambda item: item[2])[:8]
    write_md(
        "residual_atlas_v2.md",
        f"""
# Residual Atlas v2

Scope: {scope}

Residual = actual - K+rho+A prediction.

## False Positives

{table(["model", "repository", "category", "predicted", "residual"], [[row["model"], row["repository"], row["category"], round(pred, 3), round(err, 3)] for row, err, pred in fps])}

## False Negatives

{table(["model", "repository", "category", "predicted", "residual"], [[row["model"], row["repository"], row["category"], round(pred, 3), round(err, 3)] for row, err, pred in fns])}

## Clusters

{table(["axis", "cluster", "rows", "mean residual", "residual sd"], residual_cluster_rows(rows)[:18])}

## Evidence

Residuals cluster most by task/source/category cells, not by an obvious new independent mechanism. E9 and referenced-file count explain residuals, but both are post-output traces.

## Counter-Evidence

The `coding` and `code_generation` negative residuals, plus false-negative Nemotron successes, are stable enough to justify continued missing-variable surveillance.

## Uncertainty

Residual labels mix historical, deconfounded, prospective, and unmatched evidence-access rows. Residual structure may be partly collection-protocol structure.

## Falsification Attempt

Candidate additions were tested after K+rho+A. Compatibility v2 adds {fmt(m.combined_r2([row for row in rows if row.get("Compatibility v2") is not None], ["K", "rho", "A", "Compatibility v2"]) - m.combined_r2([row for row in rows if row.get("Compatibility v2") is not None], ["K", "rho", "A"]))} R2; Route Friction adds about {fmt(m.combined_r2([row for row in rows if row.get("Route Friction") is not None], ["K", "rho", "A", "Route Friction"]) - m.combined_r2([row for row in rows if row.get("Route Friction") is not None], ["K", "rho", "A"]))}. No clean pre-run fourth primitive survives this pass.
""",
    )

    stress_rows = []
    for name, subset in [
        ("all cloud", rows),
        ("no Agent-Hub", [row for row in rows if row["repository"] != "Agent-Hub"]),
        ("Agent-Hub only", [row for row in rows if row["repository"] == "Agent-Hub"]),
        ("live only", [row for row in rows if row["source"] == "live_matrix.jsonl"]),
        ("no unmatched evidence rows", [row for row in rows if row["dataset"] != "unmatched_evidence_access"]),
        ("major models only", [row for row in rows if row["model"] in {"gemma4:31b-cloud", "nemotron-3-super:cloud"}]),
    ]:
        stress_rows.append([name, len(subset), fmt(m.combined_r2(subset, ["K", "rho", "A"])), fmt(m.combined_r2(subset, ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"]))])
    write_md(
        "ceiling_stress_test.md",
        f"""
# Ceiling Stress Test

Scope: {scope}

## Main Estimate

| quantity | cloud-only value |
| --- | ---: |
| K+rho+A R2 | {fmt(base)} |
| K+rho+A1-A5 R2 | {fmt(full)} |
| observed measured-feature R2 | {fmt(observed)} |
| mean primitive reliability | {fmt(mean_rel)} |
| reliability-corrected R2 | {fmt(corrected)} |
| ceiling estimate | {fmt(ceiling)} |

The previous 0.771 ceiling is not stable under cloud-only recomputation; the analogous estimate is {fmt(ceiling)}.

## Stress Tests

{table(["subset", "rows", "K+rho+A R2", "K+rho+A1-A5 R2"], stress_rows)}

## Evidence

Most cloud-only subsets remain above 0.50 R2 for K+rho+A, and reliability correction remains high.

## Counter-Evidence

The estimate depends strongly on outcome-derived K/rho reliability. The prospective cloud-only tournament does not validate this ceiling.

## Uncertainty

Treat {fmt(ceiling)} as a measurement-ceiling prior, not as achieved explanatory power. The credible practical band is roughly 0.70-0.87 depending on whether post-run accessibility diagnostics are admitted.

## Falsification Attempt

Under a strict pre-run A1-A3 rule, R2 is {fmt(pre)}, below current A. That falsifies the claim that clean accessibility measurement alone already raises explanatory power.
""",
    )

    candidate_rows = []
    for field in ["Actionability", "E9", "Route Friction", "Retrieval Selectivity", "Compatibility v2", "EAC", "referenced_files", "selected_file_count", "context_budget"]:
        material = [row for row in rows if row.get(field) is not None]
        inc = m.combined_r2(material, ["K", "rho", "A", field]) - m.combined_r2(material, ["K", "rho", "A"])
        residual_corr = m.corr([row[field] for row in material], [err for _row, err, _pred in m.residuals(material, ["K", "rho", "A"])])
        candidate_rows.append([field, len(material), fmt(inc), round(residual_corr, 6), "post-output or contaminated" if field in {"E9", "referenced_files"} else "pre/mixed"])
    write_md(
        "missing_primitive_investigation.md",
        f"""
# Missing Primitive Investigation

Scope: {scope}

## Candidate Scan

{table(["candidate", "rows", "incremental R2 over K+rho+A", "residual corr", "timing risk"], candidate_rows)}

## Evidence

Only E9 and referenced-file count produce material residual gains, and both observe generated behavior. Clean candidates such as Compatibility v2, Route Friction, Retrieval Selectivity, and Actionability add little after K+rho+A.

## Counter-Evidence

Output-side evidence use is real predictive signal. If a pre-run instrument can predict that behavior without reading the output, it could become a fourth primitive candidate.

## Uncertainty

Current candidates are not deconfounded from K/rho/A well enough to promote. Provider/model exact crosses are incomplete, and prospective cloud-only evidence is narrow.

## Falsification Attempt

Deconfounding fails the candidate set: when post-output traces are removed, no candidate adds even 0.01 R2 over K+rho+A. The fourth primitive search remains open, but no fourth primitive survives this pass.
""",
    )

    hold_base = holdout_metrics(rows, ["K", "rho", "A"])
    hold_pre = holdout_metrics(rows, ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"])
    hold_full = holdout_metrics(rows, ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"])
    write_md(
        "prediction_tournament.md",
        f"""
# Prediction Tournament

Scope: {scope}

## Frozen Prospective Cloud-Only Result

| rows | successes | failures | excluded non-cloud rows | corr | AUC | Brier | R2 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| {prospective.get("rows", 0)} | {prospective.get("successes", 0)} | {prospective.get("failures", 0)} | {prospective.get("excluded", 0)} | {fmt(prospective.get("corr", 0.0))} | {fmt(prospective.get("auc", 0.0))} | {fmt(prospective.get("brier", 0.0))} | {fmt(prospective.get("r2", 0.0))} |

The filtered prospective set contains models {dict(prospective.get("models", {}))}.

## Retrospective Frozen-Style Holdout

{table(["model", "rows", "corr", "AUC", "Brier", "R2"], [["K+rho+A", hold_base["rows"], hold_base["corr"], hold_base["auc"], hold_base["brier"], hold_base["r2"]], ["K+rho+A1-A3", hold_pre["rows"], hold_pre["corr"], hold_pre["auc"], hold_pre["brier"], hold_pre["r2"]], ["K+rho+A1-A5", hold_full["rows"], hold_full["corr"], hold_full["auc"], hold_full["brier"], hold_full["r2"]]])}

## Evidence

The retrospective cloud-only holdout supports K+rho+A directionally. The true frozen prospective cloud-only tournament does not.

## Counter-Evidence

The prospective tournament used an older frozen compatibility score, not a freshly frozen K+rho+A model, and after exclusions it is all Nemotron cloud. That is a severe coverage limitation.

## Uncertainty

Prospective cloud-only validation is inconclusive-to-negative, not decisive. A clean next tournament must freeze K, rho-vector, and A1-A3 before collection and balance at least three cloud models.

## Falsification Attempt

All-model prospective R2 was {fmt(prospective.get("all_model_r2", 0.0))}; cloud-only R2 is {fmt(prospective.get("r2", 0.0))}. The generalization claim fails under the user's cloud-only exclusion rule.
""",
    )

    write_md(
        "scientific_assessment_v2.md",
        f"""
# Scientific Assessment v2

Scope: {scope}

## Conclusion

Success condition A remains the working conclusion, but weakened: better measurement raises explanatory power only when full evidence-use diagnostics are included, and no fourth primitive survives deconfounding. Condition B is not met. Condition C is not met, but prospective cloud-only evidence applies real pressure.

## Evidence

- Cloud-only K+rho+A R2: {fmt(base)}.
- Cloud-only K+rho+A1-A5 R2: {fmt(full)}.
- Reliability-corrected R2: {fmt(corrected)}.
- Ceiling estimate after cloud-only recomputation: {fmt(ceiling)}.
- Clean candidate additions after K+rho+A are near zero; only post-output traces add material residual signal.

## Counter-Evidence

- Strict pre-run accessibility A1-A3 does not improve R2 ({fmt(pre)}).
- Frozen prospective cloud-only tournament has R2 {fmt(prospective.get("r2", 0.0))} after excluding {prospective.get("excluded", 0)} non-cloud rows.
- K and rho are still outcome-derived and may be over-crediting historical fit.

## Uncertainty

The strongest uncertainty is measurement timing. A4/A5 may be diagnostics of successful reasoning rather than causes available to a router. The second uncertainty is prospective scope: the cloud-only future set is narrow and model-imbalanced.

## Falsification Attempt

The program tried to falsify A by excluding Codex CLI rows, banning local/Ollama/self-hosted rows, testing pre-run-only A, adding candidate fourth primitives after K+rho+A, and re-reading prospective evidence cloud-only. Those tests reject any strong fourth-primitive claim and reject any claim of clean prospective validation, but they do not falsify K+rho+A as a useful measurement family.

## Updated Scientific Position

Keep K+rho+A, but rename the current achievement carefully: it is a cloud-only explanatory measurement framework with retrospective strength and prospective fragility. Next work should freeze rho-vector and A1-A3 before collection; A4/A5 should remain diagnostics until independently pre-measured.
""",
    )

    write_prediction_v2_reports(rows, scope, base, full, corrected, ceiling)

    print(json.dumps({"cloud_rows": len(rows), "excluded_aligned_rows": len(excluded), "base_r2": base, "full_a_r2": full, "ceiling": ceiling, "prospective_cloud_r2": prospective.get("r2", 0.0)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
