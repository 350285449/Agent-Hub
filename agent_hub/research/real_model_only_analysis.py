from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .telemetry import research_dir


BUCKETS = (
    ("0", 0, 0),
    ("1-2k", 1, 2_000),
    ("2k-5k", 2_000, 5_000),
    ("5k-10k", 5_000, 10_000),
    ("10k+", 10_000, None),
)

DETERMINISTIC_REFERENCE = {
    "source": "previously reported deterministic/local study summary; deterministic files were not read by this analyzer",
    "success_rate": 0.7962745098039216,
    "tau": None,
    "best_efficiency_bucket": "1-2k",
    "diminishing_return_threshold": "2k-5k",
}


def run_real_model_only_analysis(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows = load_real_model_rows(state_dir)
    dataset_path = export_real_model_only_dataset(directory, rows)
    context_payload = compute_context_analysis(rows)
    context_json, context_md = export_context_analysis(directory, context_payload)
    curve_payload = compute_curve_fit(context_payload["buckets"])
    curve_json, curve_md = export_curve_fit(directory, curve_payload)
    tau_payload = compute_tau_report(curve_payload)
    tau_json, tau_md = export_tau_report(directory, tau_payload)
    diminishing_md = export_diminishing_returns(directory, context_payload)
    comparison_md = export_deterministic_comparison(directory, context_payload, tau_payload)
    falsification_md = export_falsification_report(directory, rows, context_payload, curve_payload)
    summary_md = export_real_model_only_summary(directory, rows, context_payload, curve_payload, tau_payload)
    return {
        "real_model_only_dataset": str(dataset_path),
        "real_model_context_analysis": str(context_json),
        "real_model_context_analysis_markdown": str(context_md),
        "real_model_curve_fit": str(curve_json),
        "real_model_curve_fit_markdown": str(curve_md),
        "real_model_tau": str(tau_json),
        "real_model_tau_markdown": str(tau_md),
        "real_model_diminishing_returns": str(diminishing_md),
        "deterministic_vs_real_model": str(comparison_md),
        "tau_falsification_report": str(falsification_md),
        "real_model_only_summary": str(summary_md),
    }


def load_real_model_rows(state_dir: str | Path) -> list[dict[str, Any]]:
    path = research_dir(state_dir) / "real_model_validation_results.jsonl"
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(_normalize(raw))
    return rows


def export_real_model_only_dataset(directory: Path, rows: list[dict[str, Any]]) -> Path:
    path = directory / "real_model_only_dataset.csv"
    fields = [
        "model",
        "repository",
        "context_percent",
        "context_tokens",
        "validation_score",
        "success",
        "latency_ms",
        "error",
        "timestamp",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    return path


def compute_context_analysis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = {label: [] for label, _lower, _upper in BUCKETS}
    for row in rows:
        grouped[bucket_for(row["context_tokens"])].append(row)
    bucket_rows = []
    previous_success = 0.0
    previous_validation = 0.0
    for label, _lower, _upper in BUCKETS:
        items = grouped[label]
        successes = sum(1 for item in items if item["success"])
        errors = sum(1 for item in items if item["error"])
        tokens = _average(item["context_tokens"] for item in items)
        success_rate = successes / len(items) if items else 0.0
        validation = _average(item["validation_score"] for item in items)
        bucket_rows.append(
            {
                "bucket": label,
                "runs": len(items),
                "average_context_tokens": round(tokens, 6),
                "success_rate": round(success_rate, 6),
                "average_validation_score": round(validation, 6),
                "average_latency_ms": round(_average(item["latency_ms"] for item in items), 6),
                "error_rate": round(errors / len(items), 6) if items else 0.0,
                "success_per_1k_tokens": round(successes / max(1.0, sum(item["context_tokens"] for item in items) / 1000.0), 6),
                "marginal_success_gain": round(success_rate - previous_success, 6),
                "marginal_validation_gain": round(validation - previous_validation, 6),
            }
        )
        previous_success = success_rate
        previous_validation = validation
    return {
        "object": "agent_hub.research.real_model_context_analysis",
        "source_file": ".agent-hub/research/real_model_validation_results.jsonl",
        "total_rows": len(rows),
        "models": sorted({row["model"] for row in rows if row["model"]}),
        "repositories": sorted({row["repository"] for row in rows if row["repository"]}),
        "overall_success_rate": round(sum(1 for row in rows if row["success"]) / len(rows), 6) if rows else 0.0,
        "overall_validation_score": round(_average(row["validation_score"] for row in rows), 6),
        "overall_error_rate": round(sum(1 for row in rows if row["error"]) / len(rows), 6) if rows else 0.0,
        "buckets": bucket_rows,
    }


def export_context_analysis(directory: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    json_path = directory / "real_model_context_analysis.json"
    md_path = directory / "real_model_context_analysis.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_context_markdown(payload), encoding="utf-8")
    return json_path, md_path


def compute_curve_fit(buckets: list[dict[str, Any]]) -> dict[str, Any]:
    points = [
        (float(row["average_context_tokens"]), float(row["success_rate"]))
        for row in buckets
        if int(row.get("runs") or 0) > 0
    ]
    fits = {
        "linear": _fit_linear(points, lambda x: x),
        "logarithmic": _fit_linear(points, lambda x: math.log1p(x)),
        "saturating_exponential": _fit_saturating_exponential(points),
        "michaelis_menten": _fit_michaelis(points),
    }
    winner, winning_fit = min(fits.items(), key=lambda item: (item[1]["mse"], -item[1]["r2"], item[0]))
    return {
        "object": "agent_hub.research.real_model_curve_fit",
        "points": [{"context_tokens": x, "success_rate": y} for x, y in points],
        "fits": fits,
        "winning_model": winner,
        "winning_fit": winning_fit,
    }


def export_curve_fit(directory: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    json_path = directory / "real_model_curve_fit.json"
    md_path = directory / "real_model_curve_fit.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_curve_markdown(payload), encoding="utf-8")
    return json_path, md_path


def compute_tau_report(curve_payload: dict[str, Any]) -> dict[str, Any]:
    sat = curve_payload["fits"]["saturating_exponential"]
    points = [(float(row["context_tokens"]), float(row["success_rate"])) for row in curve_payload["points"]]
    tau = float(sat["parameters"].get("tau") or 0.0)
    ci = _tau_confidence_interval(points, sat["mse"])
    return {
        "object": "agent_hub.research.real_model_tau",
        "tau_estimate": tau if curve_payload["winning_model"] == "saturating_exponential" else None,
        "saturating_tau_estimate": tau,
        "confidence_interval": ci,
        "fit_quality": {"r2": sat["r2"], "mse": sat["mse"]},
        "prediction_error": sat["mse"],
        "saturating_exponential_wins": curve_payload["winning_model"] == "saturating_exponential",
        "winning_model": curve_payload["winning_model"],
    }


def export_tau_report(directory: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    json_path = directory / "real_model_tau.json"
    md_path = directory / "real_model_tau.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_tau_markdown(payload), encoding="utf-8")
    return json_path, md_path


def export_diminishing_returns(directory: Path, context_payload: dict[str, Any]) -> Path:
    path = directory / "real_model_diminishing_returns.md"
    buckets = context_payload["buckets"]
    more_context = _more_context_helps(buckets)
    flatten = _flatten_bucket(buckets)
    best = _best_efficiency_bucket(buckets)
    decrease = _large_context_decrease(buckets)
    path.write_text(
        "\n".join(
            [
                "# Real Model Diminishing Returns",
                "",
                f"- Does more context help? {more_context}",
                f"- Where do gains flatten? {flatten}",
                f"- Best success-per-token bucket: {best}",
                f"- Does performance decrease at large contexts? {decrease}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def export_deterministic_comparison(directory: Path, context_payload: dict[str, Any], tau_payload: dict[str, Any]) -> Path:
    path = directory / "deterministic_vs_real_model.md"
    real_best = _best_efficiency_bucket(context_payload["buckets"])
    real_flatten = _flatten_bucket(context_payload["buckets"])
    agreements = []
    contradictions = []
    if real_best == DETERMINISTIC_REFERENCE["best_efficiency_bucket"]:
        agreements.append("Best efficiency bucket matches the deterministic result.")
    else:
        contradictions.append("Best efficiency bucket differs from deterministic result.")
    if real_flatten == DETERMINISTIC_REFERENCE["diminishing_return_threshold"]:
        agreements.append("Diminishing-return threshold matches the deterministic result.")
    else:
        contradictions.append("Diminishing-return threshold differs or is not detectable.")
    if tau_payload["tau_estimate"] is None:
        contradictions.append("Saturating exponential did not win, so real tau is not the primary fit.")
    path.write_text(
        "\n".join(
            [
                "# Deterministic vs Real Model",
                "",
                "## Deterministic Reference",
                f"- Success rate: {DETERMINISTIC_REFERENCE['success_rate']}",
                f"- Tau: {DETERMINISTIC_REFERENCE['tau'] if DETERMINISTIC_REFERENCE['tau'] is not None else 'not read due to real-only constraint'}",
                f"- Best efficiency bucket: {DETERMINISTIC_REFERENCE['best_efficiency_bucket']}",
                f"- Diminishing-return threshold: {DETERMINISTIC_REFERENCE['diminishing_return_threshold']}",
                f"- Source: {DETERMINISTIC_REFERENCE['source']}",
                "",
                "## Real Model",
                f"- Success rate: {context_payload['overall_success_rate']}",
                f"- Tau: {tau_payload['tau_estimate'] if tau_payload['tau_estimate'] is not None else 'not primary fit'}",
                f"- Saturating tau estimate: {tau_payload['saturating_tau_estimate']}",
                f"- Best efficiency bucket: {real_best}",
                f"- Diminishing-return threshold: {real_flatten}",
                "",
                "## Agreements",
                *[f"- {item}" for item in agreements or ["None."]],
                "",
                "## Contradictions",
                *[f"- {item}" for item in contradictions or ["None."]],
                "",
                "## Potential Causes",
                "- The real-model dataset is timeout-heavy and incomplete across repositories.",
                "- Local inference latency increases sharply with larger context.",
                "- Validation uses keyword scoring over short generated answers.",
                "- Deterministic tau was not recomputed here because this analysis intentionally reads only the real-model JSONL.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def export_falsification_report(
    directory: Path,
    rows: list[dict[str, Any]],
    context_payload: dict[str, Any],
    curve_payload: dict[str, Any],
) -> Path:
    path = directory / "tau_falsification_report.md"
    buckets = context_payload["buckets"]
    failures = []
    if curve_payload["winning_model"] != "saturating_exponential":
        failures.append(f"Saturating exponential did not win; `{curve_payload['winning_model']}` fit best.")
    for row in buckets:
        if row["runs"] and row["error_rate"] >= 0.5:
            failures.append(f"Bucket {row['bucket']} has high error rate {row['error_rate']}.")
    repos = _repo_summaries(rows)
    for repo, summary in repos.items():
        if summary["rows"] < 20:
            failures.append(f"Repository {repo} has too few rows for stable tau analysis.")
        if summary["error_rate"] >= 0.5:
            failures.append(f"Repository {repo} has high timeout/error rate {summary['error_rate']}.")
    if _large_context_decrease(buckets).startswith("yes"):
        failures.append("Observed success decreases at a larger context bucket.")
    path.write_text(
        "\n".join(
            [
                "# Tau Falsification Report",
                "",
                "This report searches for evidence against tau using only real-model rows.",
                "",
                "## Evidence Against Tau",
                *[f"- {item}" for item in failures or ["No hard falsification condition triggered, but evidence remains weak."]],
                "",
                "## Repository Stability",
                *[
                    f"- {repo}: rows={summary['rows']} success={summary['success_rate']} error={summary['error_rate']}"
                    for repo, summary in sorted(repos.items())
                ],
                "",
                "## Latency Effects",
                f"- Overall average latency: {round(_average(row['latency_ms'] for row in rows), 3)} ms",
                f"- Error rows: {sum(1 for row in rows if row['error'])}/{len(rows)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def export_real_model_only_summary(
    directory: Path,
    rows: list[dict[str, Any]],
    context_payload: dict[str, Any],
    curve_payload: dict[str, Any],
    tau_payload: dict[str, Any],
) -> Path:
    path = directory / "real_model_only_summary.md"
    conclusion = _final_conclusion(context_payload, curve_payload, tau_payload)
    path.write_text(
        "\n".join(
            [
                "# Real Model Only Summary",
                "",
                f"- Rows analyzed: {len(rows)}",
                f"- Model(s): {', '.join(context_payload['models'])}",
                f"- Repositories: {', '.join(context_payload['repositories'])}",
                f"- Overall success rate: {context_payload['overall_success_rate']}",
                f"- Overall validation score: {context_payload['overall_validation_score']}",
                f"- Overall error rate: {context_payload['overall_error_rate']}",
                f"- Winning curve: {curve_payload['winning_model']}",
                f"- Saturating tau estimate: {tau_payload['saturating_tau_estimate']}",
                f"- Primary tau estimate: {tau_payload['tau_estimate'] if tau_payload['tau_estimate'] is not None else 'not available because saturating exponential did not win'}",
                "",
                "## Answers",
                f"- Did tau survive real model execution? {_tau_survival_answer(curve_payload, tau_payload)}",
                f"- Is the context law still visible? {_more_context_helps(context_payload['buckets'])}",
                "- Is the evidence stronger or weaker than deterministic mode? Weaker; real rows are incomplete and timeout-heavy.",
                "- What claims are supported? Real qwen2.5-coder rows can be analyzed offline; context has measurable effects; timeout/error rate is a major factor.",
                "- What claims are not supported? A stable universal tau, cross-model stability, and deterministic-to-real generalization are not supported yet.",
                f"- Is tau currently useful? {'Only as a diagnostic/falsification metric, not as a validated routing law.'}",
                "- What experiment should be run next? A smaller controlled real run: coding-only, one repo first, 0/1k/2k/5k fixed token budgets, 5 repetitions, strict latency caps.",
                "",
                f"Final conclusion: {conclusion}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def bucket_for(tokens: int | float) -> str:
    value = max(0, int(tokens or 0))
    if value == 0:
        return "0"
    for label, lower, upper in BUCKETS:
        if upper is None and value >= lower:
            return label
        if upper is not None and lower <= value < upper:
            return label
    return "10k+"


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": str(raw.get("model") or raw.get("selected_model") or ""),
        "repository": str(raw.get("repo_id") or raw.get("repository") or ""),
        "context_percent": _int(raw.get("context_percent")),
        "context_tokens": _int(raw.get("context_token_count") or raw.get("context_tokens")),
        "validation_score": _float(raw.get("validation_score")),
        "success": bool(raw.get("success")),
        "latency_ms": _float(raw.get("latency_ms")),
        "error": str(raw.get("error") or ""),
        "timestamp": raw.get("timestamp", ""),
    }


def _fit_linear(points: list[tuple[float, float]], transform: Callable[[float], float]) -> dict[str, Any]:
    xs = [transform(x) for x, _y in points]
    ys = [y for _x, y in points]
    if not points:
        return _fit_result({}, ys, [])
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0.0
    intercept = my - slope * mx
    return _fit_result({"intercept": intercept, "slope": slope}, ys, [intercept + slope * transform(x) for x, _y in points])


def _fit_saturating_exponential(points: list[tuple[float, float]]) -> dict[str, Any]:
    ys = [y for _x, y in points]
    best_tau = 0.0
    best_predictions: list[float] = []
    best_mse = float("inf")
    for tau in _grid(50.0, 50_000.0, 500):
        predictions = [1.0 - math.exp(-x / tau) for x, _y in points]
        mse = _mse(ys, predictions)
        if mse < best_mse:
            best_tau = tau
            best_predictions = predictions
            best_mse = mse
    return _fit_result({"tau": best_tau}, ys, best_predictions)


def _fit_michaelis(points: list[tuple[float, float]]) -> dict[str, Any]:
    ys = [y for _x, y in points]
    best_km = 0.0
    best_vmax = 0.0
    best_predictions: list[float] = []
    best_mse = float("inf")
    for km in _grid(50.0, 50_000.0, 500):
        features = [x / (km + x) if x else 0.0 for x, _y in points]
        vmax = _scale(features, ys)
        predictions = [vmax * feature for feature in features]
        mse = _mse(ys, predictions)
        if mse < best_mse:
            best_km = km
            best_vmax = vmax
            best_predictions = predictions
            best_mse = mse
    return _fit_result({"km": best_km, "vmax": best_vmax}, ys, best_predictions)


def _fit_result(parameters: dict[str, float], ys: list[float], predictions: list[float]) -> dict[str, Any]:
    return {
        "parameters": {key: round(value, 6) for key, value in parameters.items()},
        "r2": round(_r2(ys, predictions), 6),
        "mse": round(_mse(ys, predictions), 10),
        "predictions": [round(value, 6) for value in predictions],
    }


def _tau_confidence_interval(points: list[tuple[float, float]], best_mse: float) -> dict[str, Any]:
    ys = [y for _x, y in points]
    accepted = []
    threshold = best_mse * 1.25 + 0.0025
    for tau in _grid(50.0, 50_000.0, 500):
        predictions = [1.0 - math.exp(-x / tau) for x, _y in points]
        if _mse(ys, predictions) <= threshold:
            accepted.append(tau)
    if not accepted:
        return {"low": None, "high": None, "method": "mse_threshold", "note": "no accepted tau range"}
    return {"low": round(min(accepted), 6), "high": round(max(accepted), 6), "method": "mse_threshold"}


def _context_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Real Model Context Analysis",
        "",
        f"- Total rows: {payload['total_rows']}",
        f"- Models: {', '.join(payload['models'])}",
        f"- Repositories: {', '.join(payload['repositories'])}",
        f"- Overall success rate: {payload['overall_success_rate']}",
        f"- Overall error rate: {payload['overall_error_rate']}",
        "",
        "| bucket | runs | avg tokens | success | validation | latency ms | error rate | success / 1k tokens |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["buckets"]:
        lines.append(
            f"| {row['bucket']} | {row['runs']} | {row['average_context_tokens']} | {row['success_rate']} | {row['average_validation_score']} | {row['average_latency_ms']} | {row['error_rate']} | {row['success_per_1k_tokens']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _curve_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Real Model Curve Fit", "", f"Winning model: `{payload['winning_model']}`", "", "| model | R2 | MSE | parameters |", "| --- | --- | --- | --- |"]
    for name, fit in payload["fits"].items():
        lines.append(f"| {name} | {fit['r2']} | {fit['mse']} | `{json.dumps(fit['parameters'], sort_keys=True)}` |")
    lines.append("")
    return "\n".join(lines)


def _tau_markdown(payload: dict[str, Any]) -> str:
    ci = payload["confidence_interval"]
    return "\n".join(
        [
            "# Real Model Tau",
            "",
            f"- Winning model: {payload['winning_model']}",
            f"- Saturating exponential wins: {payload['saturating_exponential_wins']}",
            f"- Tau estimate: {payload['tau_estimate'] if payload['tau_estimate'] is not None else 'not primary fit'}",
            f"- Saturating tau estimate: {payload['saturating_tau_estimate']}",
            f"- Confidence interval: {ci.get('low')} to {ci.get('high')} ({ci.get('method')})",
            f"- Fit quality: R2={payload['fit_quality']['r2']} MSE={payload['fit_quality']['mse']}",
            f"- Prediction error: {payload['prediction_error']}",
            "",
        ]
    )


def _repo_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["repository"]].append(row)
    return {
        repo: {
            "rows": len(items),
            "success_rate": round(sum(1 for item in items if item["success"]) / len(items), 6),
            "error_rate": round(sum(1 for item in items if item["error"]) / len(items), 6),
        }
        for repo, items in grouped.items()
        if items
    }


def _more_context_helps(buckets: list[dict[str, Any]]) -> str:
    measured = [row for row in buckets if row["runs"] > 0]
    if len(measured) < 2:
        return "not enough data"
    first = measured[0]["success_rate"]
    best_later = max(row["success_rate"] for row in measured[1:])
    return f"yes; success improves from {first} to {best_later}" if best_later > first else "no; later buckets do not exceed the lowest-context bucket"


def _flatten_bucket(buckets: list[dict[str, Any]]) -> str:
    measured = [row for row in buckets if row["runs"] > 0]
    previous = None
    for row in measured:
        gain = row["marginal_success_gain"]
        if previous is not None and gain <= previous:
            return row["bucket"]
        previous = gain
    return "not_detected"


def _best_efficiency_bucket(buckets: list[dict[str, Any]]) -> str:
    measured = [row for row in buckets if row["runs"] > 0 and row["average_context_tokens"] > 0]
    if not measured:
        return "not_enough_data"
    return max(measured, key=lambda row: row["success_per_1k_tokens"])["bucket"]


def _large_context_decrease(buckets: list[dict[str, Any]]) -> str:
    measured = [row for row in buckets if row["runs"] > 0]
    for previous, current in zip(measured, measured[1:]):
        if current["success_rate"] < previous["success_rate"]:
            return f"yes; {current['bucket']} success {current['success_rate']} is below {previous['bucket']} success {previous['success_rate']}"
    return "not detected"


def _tau_survival_answer(curve_payload: dict[str, Any], tau_payload: dict[str, Any]) -> str:
    if curve_payload["winning_model"] != "saturating_exponential":
        return f"not cleanly; {curve_payload['winning_model']} fit better than saturating exponential"
    if tau_payload["fit_quality"]["r2"] < 0.5:
        return "weakly; saturating exponential won but fit quality is low"
    return "yes, with caveats"


def _final_conclusion(context_payload: dict[str, Any], curve_payload: dict[str, Any], tau_payload: dict[str, Any]) -> str:
    if curve_payload["winning_model"] == "saturating_exponential" and tau_payload["fit_quality"]["r2"] >= 0.5 and context_payload["overall_error_rate"] < 0.5:
        return "A) Evidence supports tau under real-model execution."
    if curve_payload["winning_model"] == "linear" and not _more_context_helps(context_payload["buckets"]).startswith("yes"):
        return "C) Evidence contradicts tau."
    return "B) Evidence is mixed."


def _average(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


def _mse(ys: list[float], predictions: list[float]) -> float:
    return sum((y - predicted) ** 2 for y, predicted in zip(ys, predictions)) / len(ys) if ys else 0.0


def _r2(ys: list[float], predictions: list[float]) -> float:
    if not ys:
        return 0.0
    mean = sum(ys) / len(ys)
    total = sum((y - mean) ** 2 for y in ys)
    residual = sum((y - predicted) ** 2 for y, predicted in zip(ys, predictions))
    return 1.0 - residual / total if total else 1.0


def _scale(features: list[float], targets: list[float]) -> float:
    denom = sum(feature * feature for feature in features)
    return sum(feature * target for feature, target in zip(features, targets)) / denom if denom else 0.0


def _grid(start: float, stop: float, count: int) -> list[float]:
    step = (stop - start) / max(1, count - 1)
    return [start + index * step for index in range(count)]


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate real-model-only tau analysis.")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        from ..config import load_config

        state_dir = load_config().state_dir
    result = run_real_model_only_analysis(state_dir)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "compute_context_analysis",
    "compute_curve_fit",
    "compute_tau_report",
    "load_real_model_rows",
    "run_real_model_only_analysis",
]
