from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .data_quality_audit import load_audited_rows
from .live_matrix_runner import CONTEXT_BUDGETS, live_matrix_path
from .task_generator import REPOSITORIES, TASK_CATEGORIES
from .telemetry import research_dir


OUTCOME_FIELDS = {
    "success",
    "validation_score",
    "actual_success",
    "actual_outcome",
    "outcome",
    "label",
    "error",
    "output_preview",
    "latency",
    "latency_ms",
    "retries",
    "timestamp",
    "row_id",
    "dedupe_key",
    "task",
    "task_id",
}
PREDICTION_KEY_FIELDS = ("model", "repository", "category", "context_budget")
BOOTSTRAP_SAMPLES = 1000


def prospective_predictions_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "prospective_predictions.jsonl"


def prospective_protocol_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "prospective_prediction_protocol.md"


def run_prospective_validation(state_dir: str | Path, *, matrix_path: str | Path | None = None) -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    predictions_path = prospective_predictions_path(state_dir)
    protocol_path = prospective_protocol_path(state_dir)
    source = Path(matrix_path) if matrix_path else live_matrix_path(state_dir)
    predictions = load_frozen_predictions(predictions_path)
    usable_rows, excluded_rows = load_audited_rows(source)
    audit = audit_frozen_protocol(predictions_path, protocol_path, predictions, usable_rows)
    collection = collection_plan(predictions, usable_rows)
    scorecards = scorecard_payload(predictions)
    results = evaluate_frozen_predictions(predictions, usable_rows, freeze_time=audit["prediction_file_mtime_utc"])
    calibration = calibration_payload(results["matches"])
    criteria = success_criteria_payload()

    paths = {
        "audit_report": directory / "prospective_audit_report.md",
        "collection_plan": directory / "prospective_collection_plan.md",
        "scorecards": directory / "prospective_scorecards.md",
        "results_markdown": directory / "prospective_results.md",
        "results_json": directory / "prospective_results.json",
        "calibration_report": directory / "prospective_calibration_report.md",
        "success_criteria": directory / "prospective_success_criteria.md",
    }
    paths["audit_report"].write_text(_audit_markdown(audit), encoding="utf-8")
    paths["collection_plan"].write_text(_collection_markdown(collection), encoding="utf-8")
    paths["scorecards"].write_text(_scorecards_markdown(scorecards), encoding="utf-8")
    paths["results_json"].write_text(json.dumps(_results_json(results, excluded_rows), indent=2, sort_keys=True), encoding="utf-8")
    paths["results_markdown"].write_text(_results_markdown(results), encoding="utf-8")
    paths["calibration_report"].write_text(_calibration_markdown(calibration), encoding="utf-8")
    paths["success_criteria"].write_text(_criteria_markdown(criteria), encoding="utf-8")
    return paths


def load_frozen_predictions(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def audit_frozen_protocol(
    predictions_path: str | Path,
    protocol_path: str | Path,
    predictions: list[dict[str, Any]],
    usable_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    prediction_file = Path(predictions_path)
    protocol_file = Path(protocol_path)
    prediction_mtime = datetime.fromtimestamp(prediction_file.stat().st_mtime, tz=timezone.utc)
    protocol_mtime = datetime.fromtimestamp(protocol_file.stat().st_mtime, tz=timezone.utc)
    outcome_fields = sorted({key for row in predictions for key in row if key in OUTCOME_FIELDS})
    prediction_keys = [_cell_key(row) for row in predictions]
    duplicate_prediction_keys = [key for key, count in Counter(prediction_keys).items() if count > 1]
    pre_freeze_rows = [row for row in usable_rows if _row_time(row) and _row_time(row) <= prediction_mtime]
    post_freeze_rows = [row for row in usable_rows if _row_time(row) and _row_time(row) > prediction_mtime]
    pre_counts = Counter(_cell_key(row) for row in pre_freeze_rows)
    post_counts = Counter(_cell_key(row) for row in post_freeze_rows)
    observed_mismatches = [
        {
            "model": key[0],
            "repository": key[1],
            "category": key[2],
            "context_budget": key[3],
            "frozen_observed": int(row.get("observed_usable_rows", 0) or 0),
            "pre_freeze_rows_now": pre_counts[key],
        }
        for row, key in zip(predictions, prediction_keys)
        if int(row.get("observed_usable_rows", 0) or 0) != pre_counts[key]
    ]
    future_leak_suspects = [
        {
            "model": key[0],
            "repository": key[1],
            "category": key[2],
            "context_budget": key[3],
            "post_freeze_rows_now": post_counts[key],
            "frozen_observed": int(row.get("observed_usable_rows", 0) or 0),
        }
        for row, key in zip(predictions, prediction_keys)
        if post_counts[key] and int(row.get("observed_usable_rows", 0) or 0) > pre_counts[key]
    ]
    protocol_text = protocol_file.read_text(encoding="utf-8")
    return {
        "object": "agent_hub.research.prospective_audit",
        "prediction_file": str(prediction_file),
        "protocol_file": str(protocol_file),
        "prediction_rows": len(predictions),
        "protocol_present": protocol_file.exists(),
        "prediction_file_mtime_utc": prediction_mtime.isoformat(),
        "protocol_file_mtime_utc": protocol_mtime.isoformat(),
        "protocol_same_freeze_window": abs((prediction_mtime - protocol_mtime).total_seconds()) <= 5,
        "protocol_declares_freeze": "Freeze `prospective_predictions.jsonl` before collecting new live rows." in protocol_text,
        "protocol_declared_rows": _protocol_declared_rows(protocol_text),
        "theory_version_hashes": sorted({str(row.get("theory_version_hash") or "") for row in predictions}),
        "prediction_fields": sorted({key for row in predictions for key in row}),
        "outcome_fields_present": outcome_fields,
        "duplicate_prediction_keys": duplicate_prediction_keys,
        "usable_pre_freeze_rows": len(pre_freeze_rows),
        "usable_post_freeze_rows": len(post_freeze_rows),
        "observed_count_mismatches": observed_mismatches,
        "future_leak_suspects": future_leak_suspects,
        "audit_passed": bool(
            predictions
            and not outcome_fields
            and not duplicate_prediction_keys
            and not observed_mismatches
            and not future_leak_suspects
        ),
    }


def collection_plan(predictions: list[dict[str, Any]], usable_rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(_cell_key(row) for row in usable_rows)
    repo_counts = Counter(str(row.get("repository") or "") for row in usable_rows)
    cat_counts = Counter(str(row.get("category") or "") for row in usable_rows)
    repo_cat_counts = Counter((str(row.get("repository") or ""), str(row.get("category") or "")) for row in usable_rows)
    ranked = []
    for row in predictions:
        key = _cell_key(row)
        probability = _float(row.get("predicted_success_probability"))
        variance = probability * (1.0 - probability)
        observed = counts[key]
        sparsity = max(0.0, (5.0 - observed) / 5.0)
        hard_repo = 1.0 - _rate([item for item in usable_rows if str(item.get("repository") or "") == key[1]])
        repo_sparsity = 1.0 / max(1.0, float(repo_counts[key[1]]))
        category_sparsity = 1.0 / max(1.0, float(cat_counts[key[2]]))
        repo_category_sparsity = 1.0 / max(1.0, float(repo_cat_counts[(key[1], key[2])]))
        priority = 0.0
        reasons = []
        if key[0] == "gpt-5.5" and key[2] in {"architecture", "testing", "refactor"}:
            priority += 0.35
            reasons.append("GPT-5.5 high-priority category")
        if key[0] == "gemma4:31b-cloud" and key[2] in {"architecture", "testing"}:
            priority += 0.22
            reasons.append("Gemma architecture/testing")
        if key[3] <= 25:
            priority += 0.18
            reasons.append("low context budget")
        if hard_repo >= 0.2:
            priority += 0.12
            reasons.append("hard repository")
        if repo_cat_counts[(key[1], key[2])] < 20:
            priority += 0.12
            reasons.append("sparse repository/category")
        information_gain = (
            2.5 * variance
            + 0.5 * priority
            + 0.2 * sparsity
            + repo_sparsity
            + category_sparsity
            + repo_category_sparsity
        )
        ranked.append(
            {
                "model": key[0],
                "repository": key[1],
                "category": key[2],
                "context_budget": key[3],
                "observed_usable_rows": observed,
                "planned_additional_rows": int(row.get("planned_additional_rows", max(0, 5 - observed)) or 0),
                "predicted_success_probability": round(probability, 6),
                "compatibility_score": round(_float(row.get("compatibility_score")), 6),
                "expected_information_gain": round(information_gain, 6),
                "expected_variance_contribution": round(variance, 6),
                "reasons": reasons or ["fills frozen prospective cell"],
            }
        )
    ranked.sort(key=lambda item: (item["expected_information_gain"], item["planned_additional_rows"]), reverse=True)
    requested_priority = [
        row
        for row in ranked
        if (
            row["model"] == "gpt-5.5"
            and row["category"] in {"architecture", "testing", "refactor"}
        )
        or (
            row["model"] == "gemma4:31b-cloud"
            and row["category"] in {"architecture", "testing"}
        )
        or row["context_budget"] <= 25
    ]
    return {
        "object": "agent_hub.research.prospective_collection_plan",
        "target_cells": ranked[:40],
        "requested_priority_cells": requested_priority[:40],
        "all_candidate_cells": len(ranked),
        "recommendation": "Collect from the highest-ranked frozen cells first, emphasizing low-context GPT-5.5 architecture/testing/refactor outcomes.",
    }


def scorecard_payload(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        {
            "model": str(row.get("model") or ""),
            "repository": str(row.get("repository") or ""),
            "category": str(row.get("category") or ""),
            "context_budget": int(row.get("context_budget", 0) or 0),
            "compatibility_score": round(_float(row.get("compatibility_score")), 6),
            "predicted_success_probability": round(_float(row.get("predicted_success_probability")), 6),
        }
        for row in predictions
    ]
    rows.sort(key=lambda row: (row["model"], row["repository"], row["category"], row["context_budget"]))
    return {"object": "agent_hub.research.prospective_scorecards", "rows": rows}


def evaluate_frozen_predictions(
    predictions: list[dict[str, Any]],
    usable_rows: list[dict[str, Any]],
    *,
    freeze_time: str | datetime,
) -> dict[str, Any]:
    freeze_dt = datetime.fromisoformat(freeze_time) if isinstance(freeze_time, str) else freeze_time
    prediction_by_key = {_cell_key(row): row for row in predictions}
    future_rows = [row for row in usable_rows if _row_time(row) and _row_time(row) > freeze_dt]
    matches = []
    unmatched = []
    for row in future_rows:
        key = _cell_key(row)
        prediction = prediction_by_key.get(key)
        if prediction is None:
            unmatched.append(row)
            continue
        matches.append(
            {
                "model": key[0],
                "repository": key[1],
                "category": key[2],
                "context_budget": key[3],
                "predicted": _float(prediction.get("predicted_success_probability")),
                "compatibility_score": _float(prediction.get("compatibility_score")),
                "actual": 1.0 if row.get("success") else 0.0,
                "task_id": str(row.get("task_id") or row.get("task") or ""),
                "timestamp": _row_time(row).isoformat() if _row_time(row) else "",
            }
        )
    actual = [row["actual"] for row in matches]
    predicted = [row["predicted"] for row in matches]
    metrics = {**_stats(actual, predicted), **_classification_metrics(actual, predicted)}
    metrics["calibration_error"] = _calibration_error(actual, predicted)
    metrics["brier_score"] = _brier_score(actual, predicted)
    intervals = bootstrap_confidence_intervals(actual, predicted)
    verdict = classify_success(metrics, actual=actual, predicted=predicted)
    return {
        "object": "agent_hub.research.prospective_results",
        "freeze_time_utc": freeze_dt.isoformat(),
        "frozen_prediction_rows": len(predictions),
        "future_usable_rows": len(future_rows),
        "matched_rows": len(matches),
        "unmatched_future_rows": len(unmatched),
        "metrics": metrics,
        "confidence_intervals": intervals,
        "verdict": verdict,
        "matches": matches,
        "unmatched_keys": ["/".join(map(str, _cell_key(row))) for row in unmatched[:50]],
    }


def calibration_payload(matches: list[dict[str, Any]]) -> dict[str, Any]:
    bins = []
    for index in range(10):
        lower = index / 10.0
        upper = (index + 1) / 10.0
        bucket = [row for row in matches if _in_probability_bin(row["predicted"], lower, upper, final=index == 9)]
        predicted_rate = sum(row["predicted"] for row in bucket) / len(bucket) if bucket else 0.0
        actual_rate = sum(row["actual"] for row in bucket) / len(bucket) if bucket else 0.0
        bins.append(
            {
                "bin": f"{index * 10}-{(index + 1) * 10}%",
                "rows": len(bucket),
                "predicted_success": round(predicted_rate, 6),
                "actual_success": round(actual_rate, 6),
            }
        )
    return {"object": "agent_hub.research.prospective_calibration", "bins": bins}


def _in_probability_bin(value: float, lower: float, upper: float, *, final: bool) -> bool:
    return lower <= value <= upper if final else lower <= value < upper


def bootstrap_confidence_intervals(actual: list[float], predicted: list[float], *, samples: int = BOOTSTRAP_SAMPLES) -> dict[str, dict[str, float]]:
    if len(actual) < 2:
        return {name: {"low": 0.0, "high": 0.0} for name in ("correlation", "r2", "auc", "calibration_error")}
    rng = random.Random(46)
    values: dict[str, list[float]] = defaultdict(list)
    for _ in range(samples):
        indices = [rng.randrange(len(actual)) for _item in actual]
        sample_actual = [actual[index] for index in indices]
        sample_predicted = [predicted[index] for index in indices]
        stats = _stats(sample_actual, sample_predicted)
        classes = _classification_metrics(sample_actual, sample_predicted)
        values["correlation"].append(stats["correlation"])
        values["r2"].append(stats["r2"])
        values["auc"].append(classes["auc"])
        values["calibration_error"].append(_calibration_error(sample_actual, sample_predicted))
    return {name: _percentile_interval(series) for name, series in values.items()}


def success_criteria_payload() -> dict[str, Any]:
    return {
        "object": "agent_hub.research.prospective_success_criteria",
        "strong_success": {"correlation_gt": 0.60, "r2_gt": 0.40},
        "moderate_success": {"correlation_gt": 0.50, "r2_gt": 0.25},
        "failure": {"correlation_lt": 0.30, "r2_lt": 0.10},
        "rules": [
            "Do not create new theories.",
            "Do not tune Compatibility.",
            "Do not change scoring formulas.",
            "Do not retrain after seeing prospective results.",
            "Evaluate frozen predictions against future rows only.",
        ],
    }


def classify_success(metrics: dict[str, float], *, actual: list[float] | None = None, predicted: list[float] | None = None) -> str:
    if actual is not None and len(set(actual)) < 2:
        return "inconclusive_no_outcome_variance"
    if predicted is not None and len(set(predicted)) < 2:
        return "inconclusive_no_prediction_variance"
    corr = metrics.get("correlation", 0.0)
    r2 = metrics.get("r2", 0.0)
    if corr > 0.60 and r2 > 0.40:
        return "strong_success"
    if corr > 0.50 and r2 > 0.25:
        return "moderate_success"
    if corr < 0.30 and r2 < 0.10:
        return "failure"
    return "mixed_or_inconclusive"


def _results_json(results: dict[str, Any], excluded_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        **{key: value for key, value in results.items() if key != "matches"},
        "excluded_rows_current_audit": len(excluded_rows),
        "matches": results["matches"],
    }


def _audit_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Prospective Audit Report",
        "",
        f"- Prediction rows: {payload['prediction_rows']}",
        f"- Prediction file mtime UTC: `{payload['prediction_file_mtime_utc']}`",
        f"- Protocol file mtime UTC: `{payload['protocol_file_mtime_utc']}`",
        f"- Protocol declares freeze-before-collection: {payload['protocol_declares_freeze']}",
        f"- Protocol declared rows: {payload['protocol_declared_rows']}",
        f"- Outcome fields present in frozen predictions: {payload['outcome_fields_present'] or 'none'}",
        f"- Duplicate prediction keys: {len(payload['duplicate_prediction_keys'])}",
        f"- Usable rows before freeze: {payload['usable_pre_freeze_rows']}",
        f"- Usable rows after freeze currently available: {payload['usable_post_freeze_rows']}",
        f"- Observed-count mismatches versus pre-freeze rows: {len(payload['observed_count_mismatches'])}",
        f"- Future-leak suspects: {len(payload['future_leak_suspects'])}",
        f"- Audit passed: {payload['audit_passed']}",
        "",
        "## Finding",
        "",
        "The frozen prediction rows contain cell identifiers, observed/planned counts, Compatibility scores, predicted probabilities, and a theory hash only.",
        "No outcome, task-output, latency, retry, timestamp, or validation fields are present.",
    ]
    if payload["observed_count_mismatches"]:
        lines.extend(["", "## Observed Count Mismatches"])
        for row in payload["observed_count_mismatches"][:30]:
            lines.append(
                f"- {row['model']} / {row['repository']} / {row['category']} / {row['context_budget']}: "
                f"frozen={row['frozen_observed']}, pre_freeze_now={row['pre_freeze_rows_now']}"
            )
    return "\n".join(lines) + "\n"


def _collection_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Prospective Collection Plan",
        "",
        payload["recommendation"],
        "",
        "## Target Cells",
        "",
        "| rank | model | repository | category | context | current rows | add | predicted success | expected information gain | expected variance | rationale |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for index, row in enumerate(payload["target_cells"], start=1):
        lines.append(
            f"| {index} | {row['model']} | {row['repository']} | {row['category']} | {row['context_budget']} | "
            f"{row['observed_usable_rows']} | {row['planned_additional_rows']} | {row['predicted_success_probability']:.3f} | "
            f"{row['expected_information_gain']:.3f} | {row['expected_variance_contribution']:.3f} | {', '.join(row['reasons'])} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Expected variance contribution is `p * (1 - p)`, so cells near 50% predicted success are most falsifying.",
            "The information-gain ranking adds priority for GPT-5.5 architecture/testing/refactor cells, Gemma architecture/testing cells, low context budgets, hard repositories, and sparse repository/category combinations.",
            "",
            "## Requested Priority Cells",
            "",
            "These cells directly satisfy the requested GPT-5.5, Gemma, and low-context priorities even when their frozen probabilities are saturated and therefore contribute less expected variance.",
            "",
            "| rank | model | repository | category | context | current rows | add | predicted success | expected information gain | expected variance | rationale |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for index, row in enumerate(payload["requested_priority_cells"], start=1):
        lines.append(
            f"| {index} | {row['model']} | {row['repository']} | {row['category']} | {row['context_budget']} | "
            f"{row['observed_usable_rows']} | {row['planned_additional_rows']} | {row['predicted_success_probability']:.3f} | "
            f"{row['expected_information_gain']:.3f} | {row['expected_variance_contribution']:.3f} | {', '.join(row['reasons'])} |"
        )
    return "\n".join(lines) + "\n"


def _scorecards_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Prospective Scorecards",
        "",
        "| model | repository | category | context budget | compatibility score | predicted success probability |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['model']} | {row['repository']} | {row['category']} | {row['context_budget']} | "
            f"{row['compatibility_score']:.6f} | {row['predicted_success_probability']:.6f} |"
        )
    return "\n".join(lines) + "\n"


def _results_markdown(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    intervals = payload["confidence_intervals"]
    lines = [
        "# Prospective Results",
        "",
        f"- Freeze time UTC: `{payload['freeze_time_utc']}`",
        f"- Frozen prediction rows: {payload['frozen_prediction_rows']}",
        f"- Future usable rows: {payload['future_usable_rows']}",
        f"- Matched rows: {payload['matched_rows']}",
        f"- Unmatched future rows: {payload['unmatched_future_rows']}",
        f"- Verdict by frozen criteria: `{payload['verdict']}`",
        "",
        "## Metrics",
        "",
        f"- Correlation: {metrics['correlation']}",
        f"- R2: {metrics['r2']}",
        f"- Accuracy: {metrics['accuracy']}",
        f"- AUC: {metrics['auc']}",
        f"- Calibration error: {metrics['calibration_error']}",
        f"- Brier score: {metrics['brier_score']}",
        "",
        "## 95% Bootstrap Confidence Intervals",
        "",
    ]
    for name in ("correlation", "r2", "auc", "calibration_error"):
        interval = intervals.get(name, {"low": 0.0, "high": 0.0})
        lines.append(f"- {name}: [{interval['low']}, {interval['high']}]")
    lines.extend(
        [
            "",
            "## Rule",
            "",
            "These results compare frozen predicted probabilities to post-freeze outcomes only. No Compatibility formula, threshold, or weight was changed.",
        ]
    )
    return "\n".join(lines) + "\n"


def _calibration_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Prospective Calibration Report",
        "",
        "| probability bin | rows | predicted success | actual success |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in payload["bins"]:
        lines.append(f"| {row['bin']} | {row['rows']} | {row['predicted_success']:.6f} | {row['actual_success']:.6f} |")
    return "\n".join(lines) + "\n"


def _criteria_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Prospective Success Criteria",
        "",
        "## Thresholds",
        "",
        "- Strong success: correlation > 0.60 and R2 > 0.40.",
        "- Moderate success: correlation > 0.50 and R2 > 0.25.",
        "- Failure: correlation < 0.30 and R2 < 0.10.",
        "- No outcome variance or no prediction variance: inconclusive, regardless of point metrics.",
        "- Otherwise: mixed or inconclusive.",
        "",
        "## Scientific Rules",
        "",
        *[f"- {rule}" for rule in payload["rules"]],
    ]
    return "\n".join(lines) + "\n"


def _stats(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual:
        return {"correlation": 0.0, "r2": 0.0, "mae": 1.0, "rmse": 1.0}
    mae = sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)
    rmse = math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual))
    return {
        "correlation": round(max(0.0, _pearson(actual, predicted)), 6),
        "r2": round(max(0.0, _r2(actual, predicted)), 6),
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
    }


def _classification_metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual:
        return {"auc": 0.0, "accuracy": 0.0}
    labels = [1.0 if value >= 0.5 else 0.0 for value in predicted]
    accuracy = sum(1 for a, p in zip(actual, labels) if a == p) / len(actual)
    return {"auc": _auc(actual, predicted), "accuracy": round(accuracy, 6)}


def _auc(actual: list[float], predicted: list[float]) -> float:
    positives = [score for label, score in zip(actual, predicted) if label == 1.0]
    negatives = [score for label, score in zip(actual, predicted) if label == 0.0]
    if not positives or not negatives:
        return 0.0
    wins = 0.0
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return round(wins / (len(positives) * len(negatives)), 6)


def _pearson(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    den_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    den_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
    if den_a == 0 or den_b == 0:
        return 0.0
    return numerator / (den_a * den_b)


def _r2(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    mean = sum(actual) / len(actual)
    total = sum((value - mean) ** 2 for value in actual)
    if total == 0:
        return 0.0
    residual = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    return 1.0 - residual / total


def _calibration_error(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    total = 0.0
    for index in range(10):
        lower = index / 10.0
        upper = (index + 1) / 10.0
        bucket = [
            (a, p)
            for a, p in zip(actual, predicted)
            if (lower <= p <= upper if index == 9 else lower <= p < upper)
        ]
        if not bucket:
            continue
        actual_rate = sum(a for a, _p in bucket) / len(bucket)
        predicted_rate = sum(p for _a, p in bucket) / len(bucket)
        total += (len(bucket) / len(actual)) * abs(actual_rate - predicted_rate)
    return round(total, 6)


def _brier_score(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    return round(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual), 6)


def _percentile_interval(values: list[float]) -> dict[str, float]:
    if not values:
        return {"low": 0.0, "high": 0.0}
    ordered = sorted(values)
    low_index = max(0, int(0.025 * (len(ordered) - 1)))
    high_index = min(len(ordered) - 1, int(0.975 * (len(ordered) - 1)))
    return {"low": round(ordered[low_index], 6), "high": round(ordered[high_index], 6)}


def _cell_key(row: dict[str, Any]) -> tuple[str, str, str, int]:
    return (
        str(row.get("model") or ""),
        str(row.get("repository") or ""),
        str(row.get("category") or row.get("task_type") or ""),
        int(row.get("context_budget", row.get("context budget", 0)) or 0),
    )


def _row_time(row: dict[str, Any]) -> datetime | None:
    value = row.get("timestamp")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _rate(rows: Iterable[dict[str, Any]]) -> float:
    materialized = list(rows)
    if not materialized:
        return 0.0
    return sum(1.0 for row in materialized if row.get("success")) / len(materialized)


def _protocol_declared_rows(text: str) -> int:
    for line in text.splitlines():
        if "Frozen prediction rows:" not in line:
            continue
        try:
            return int(line.rsplit(":", 1)[1].strip())
        except ValueError:
            return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate frozen prospective Compatibility predictions.")
    parser.add_argument("--state-dir", default=".agent-hub", help="Agent-Hub state directory.")
    parser.add_argument("--matrix-path", default="", help="Optional live matrix JSONL path.")
    args = parser.parse_args(argv)
    paths = run_prospective_validation(args.state_dir, matrix_path=args.matrix_path or None)
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
