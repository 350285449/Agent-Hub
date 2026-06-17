from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .live_matrix_runner import live_matrix_path
from .prospective_evaluator import prospective_predictions_path
from .telemetry import research_dir


FORBIDDEN_PROVIDER_TYPES = {"local", "local-research", "echo", "ollama", "self-hosted", "on-device"}
BOOTSTRAP_SAMPLES = 400
SMOOTHING_ALPHA = 1.0
SMOOTHING_BETA = 1.0


@dataclass(frozen=True, slots=True)
class CompatibilityV2Row:
    row_id: str
    dataset: str
    model: str
    provider: str
    provider_type: str
    route: str
    repository: str
    category: str
    context_budget: int
    compatibility_v1_score: float
    success: float
    timestamp: datetime | None

    def key(self) -> tuple[str, str, str, int]:
        return (self.model, self.repository, self.category, self.context_budget)


def compatibility_v2_results_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "compatibility_v2_results.json"


def compatibility_v2_report_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "compatibility_v2_report.md"


def compatibility_v2_calibration_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "compatibility_v2_calibration.md"


def compatibility_v1_vs_v2_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "compatibility_v1_vs_v2.md"


def run_compatibility_v2_evaluation(state_dir: str | Path = ".agent-hub") -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = evaluate_compatibility_v2(state_dir)
    paths = {
        "results_json": compatibility_v2_results_path(state_dir),
        "report": compatibility_v2_report_path(state_dir),
        "calibration": compatibility_v2_calibration_path(state_dir),
        "v1_vs_v2": compatibility_v1_vs_v2_path(state_dir),
    }
    paths["results_json"].write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    paths["report"].write_text(_report_markdown(payload), encoding="utf-8")
    paths["calibration"].write_text(_calibration_markdown(payload), encoding="utf-8")
    paths["v1_vs_v2"].write_text(_v1_vs_v2_markdown(payload), encoding="utf-8")
    return paths


def evaluate_compatibility_v2(state_dir: str | Path = ".agent-hub") -> dict[str, Any]:
    frozen = load_frozen_v1_predictions(prospective_predictions_path(state_dir))
    live_rows = load_cloud_live_rows(live_matrix_path(state_dir), frozen)
    freeze_time = _prospective_freeze_time(state_dir)
    datasets = build_evaluation_datasets(state_dir, live_rows, frozen, freeze_time)

    evaluated: dict[str, Any] = {}
    for name, spec in datasets.items():
        rows = spec["rows"]
        history = spec.get("history", [])
        features = compute_non_leaky_features(rows, history=history, mode=spec["mode"])
        comparisons = evaluate_feature_sets(features)
        evaluated[name] = {
            "rows": len(rows),
            "successes": int(sum(row.success for row in rows)),
            "failures": int(len(rows) - sum(row.success for row in rows)),
            "prior_mode": spec["mode"],
            "comparisons": comparisons,
            "ablation": ablation_summary(comparisons),
            "calibration": calibration_comparison(features),
            "leakage_checks": leakage_checks(features, mode=spec["mode"]),
        }

    verdict = scientific_verdict(evaluated)
    return {
        "object": "agent_hub.research.compatibility_v2_results",
        "theory": "Compatibility v2 = Model-Task-Context Compatibility + Model/Route Reliability",
        "scope": "cloud_models_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "leakage_rule": "Reliability priors use only rows before the evaluated row when timestamps are available; otherwise leave-one-out excludes the current row.",
        "fixed_v2_formula": fixed_v2_formula(),
        "datasets": evaluated,
        "scientific_verdict": verdict,
        "v1_artifacts_preserved": _v1_artifacts_preserved(state_dir),
    }


def load_frozen_v1_predictions(path: str | Path) -> dict[tuple[str, str, str, int], float]:
    frozen: dict[tuple[str, str, str, int], float] = {}
    file = Path(path)
    if not file.exists():
        return frozen
    for row in _load_jsonl(file):
        key = (
            str(row.get("model") or ""),
            str(row.get("repository") or ""),
            str(row.get("category") or ""),
            int(row.get("context_budget", 0) or 0),
        )
        frozen[key] = _clip(row.get("compatibility_score", row.get("predicted_success_probability", 0.5)))
    return frozen


def load_cloud_live_rows(path: str | Path, frozen: dict[tuple[str, str, str, int], float]) -> list[CompatibilityV2Row]:
    rows = []
    for index, row in enumerate(_load_jsonl(Path(path))):
        normalized = _row_from_payload(row, f"live-{index}", "historical_pooled", frozen)
        if normalized is not None:
            rows.append(normalized)
    return rows


def build_evaluation_datasets(
    state_dir: str | Path,
    live_rows: list[CompatibilityV2Row],
    frozen: dict[tuple[str, str, str, int], float],
    freeze_time: datetime | None,
) -> dict[str, dict[str, Any]]:
    phase1 = load_phase_rows(research_dir(state_dir) / "deconfounded_collection_results.json", "deconfounded_phase1", frozen)
    phase2 = load_phase_rows(research_dir(state_dir) / "deconfounded_phase2_collection_results.json", "deconfounded_phase2", frozen)
    phase_start = min((row.timestamp for row in phase1 + phase2 if row.timestamp), default=None)
    pre_freeze = [row for row in live_rows if freeze_time and row.timestamp and row.timestamp <= freeze_time]
    if not freeze_time:
        pre_freeze = live_rows
    prospective_match_times = _prospective_match_timestamps(state_dir)
    if prospective_match_times:
        prospective = [row for row in live_rows if row.timestamp and row.timestamp.isoformat() in prospective_match_times]
    else:
        prospective = [
            row
            for row in live_rows
            if freeze_time
            and row.timestamp
            and row.timestamp > freeze_time
            and (phase_start is None or row.timestamp < phase_start)
            and row.key() in frozen
        ]
    prospective_and_deconfounded = sorted(prospective + phase1 + phase2, key=_sort_key)
    return {
        "historical_pooled": {"rows": pre_freeze, "history": [], "mode": "leave_one_out"},
        "original_prospective_frozen": {"rows": prospective, "history": pre_freeze, "mode": "time_aware"},
        "deconfounded_phase1": {"rows": phase1, "history": pre_freeze, "mode": "time_aware"},
        "deconfounded_phase2": {"rows": phase2, "history": pre_freeze + phase1, "mode": "time_aware"},
        "combined_prospective_deconfounded": {
            "rows": prospective_and_deconfounded,
            "history": pre_freeze,
            "mode": "time_aware",
        },
    }


def load_phase_rows(path: str | Path, dataset: str, frozen: dict[tuple[str, str, str, int], float]) -> list[CompatibilityV2Row]:
    file = Path(path)
    if not file.exists():
        return []
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    raw_rows = payload.get("rows", [])
    rows = []
    if isinstance(raw_rows, list):
        for index, row in enumerate(raw_rows):
            if isinstance(row, dict):
                normalized = _row_from_payload(row, f"{dataset}-{index}", dataset, frozen)
                if normalized is not None:
                    rows.append(normalized)
    return rows


def compute_non_leaky_features(
    rows: list[CompatibilityV2Row],
    *,
    history: list[CompatibilityV2Row] | None = None,
    mode: str = "time_aware",
) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=_sort_key)
    base_history = sorted(history or [], key=_sort_key)
    features = []
    if mode == "leave_one_out":
        all_rows = base_history + ordered
        for row in ordered:
            prior_rows = [item for item in all_rows if item.row_id != row.row_id]
            features.append(_feature_row(row, prior_rows, mode))
        return features

    prior_rows = list(base_history)
    for row in ordered:
        features.append(_feature_row(row, prior_rows, mode))
        prior_rows.append(row)
    return features


def evaluate_feature_sets(feature_rows: list[dict[str, Any]]) -> dict[str, Any]:
    variants = {
        "Compatibility v1": "compatibility_v1_score",
        "model only": "model_reliability_prior",
        "provider only": "provider_reliability_prior",
        "route only": "route_reliability_prior",
        "model-route only": "model_route_reliability_prior",
        "v1 + model reliability": "v1_model_reliability",
        "v1 + route reliability": "v1_route_reliability",
        "v1 + model-route reliability": "v1_model_route_reliability",
        "full Compatibility v2": "compatibility_v2_probability",
    }
    actual = [row["success"] for row in feature_rows]
    result = {}
    for name, field in variants.items():
        predicted = [row[field] for row in feature_rows]
        metrics = metrics_payload(actual, predicted)
        result[name] = {
            **metrics,
            "confidence_intervals": bootstrap_confidence_intervals(actual, predicted),
        }
    result["delta_full_v2_vs_v1"] = bootstrap_delta_intervals(
        actual,
        [row["compatibility_v1_score"] for row in feature_rows],
        [row["compatibility_v2_probability"] for row in feature_rows],
    )
    return result


def ablation_summary(comparisons: dict[str, Any]) -> dict[str, Any]:
    v1 = comparisons.get("Compatibility v1", {})
    full = comparisons.get("full Compatibility v2", {})
    gains = {}
    for name in (
        "model only",
        "provider only",
        "route only",
        "model-route only",
        "v1 + model reliability",
        "v1 + route reliability",
        "v1 + model-route reliability",
        "full Compatibility v2",
    ):
        row = comparisons.get(name, {})
        gains[name] = {
            "r2_gain_over_v1": round(float(row.get("r2", 0.0)) - float(v1.get("r2", 0.0)), 6),
            "auc_gain_over_v1": round(float(row.get("auc", 0.0)) - float(v1.get("auc", 0.0)), 6),
            "brier_improvement_over_v1": round(float(v1.get("brier_score", 0.0)) - float(row.get("brier_score", 0.0)), 6),
        }
    strongest = max(gains, key=lambda key: (gains[key]["r2_gain_over_v1"], gains[key]["brier_improvement_over_v1"])) if gains else ""
    return {
        "strongest_improvement_source": strongest,
        "gains": gains,
        "true_interaction_with_compatibility": {
            "full_minus_v1_model_route_r2": round(float(full.get("r2", 0.0)) - float(comparisons.get("v1 + model-route reliability", {}).get("r2", 0.0)), 6),
            "interpretation": "positive only if task/context conditions add beyond v1 plus model-route reliability",
        },
    }


def calibration_comparison(feature_rows: list[dict[str, Any]]) -> dict[str, Any]:
    actual = [row["success"] for row in feature_rows]
    v1 = [row["compatibility_v1_score"] for row in feature_rows]
    v2 = [row["compatibility_v2_probability"] for row in feature_rows]
    return {
        "v1": calibration_payload(actual, v1),
        "v2": calibration_payload(actual, v2),
        "regions": {
            "p=0.4-0.6": _region_summary(actual, v1, v2, 0.4, 0.6),
            "p>0.8": _region_summary(actual, v1, v2, 0.8, 1.0, include_lower=False),
        },
        "overconfidence_delta_v2_minus_v1": round(_overconfidence(actual, v2) - _overconfidence(actual, v1), 6),
        "mid_probability_failure_delta_v2_minus_v1": round(
            _failure_rate(actual, v2, 0.4, 0.6) - _failure_rate(actual, v1, 0.4, 0.6),
            6,
        ),
    }


def leakage_checks(feature_rows: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "rows_checked": len(feature_rows),
        "current_row_excluded_from_prior": all(row["prior_excludes_current_row"] for row in feature_rows),
        "future_rows_excluded_from_prior_when_time_aware": all(row["future_rows_excluded"] for row in feature_rows),
        "minimum_prior_count": min((row["model_route_reliability_prior_count"] for row in feature_rows), default=0),
        "uses_success_outcome_fields_as_features": False,
    }


def scientific_verdict(datasets: dict[str, Any]) -> dict[str, Any]:
    prospective = datasets.get("original_prospective_frozen", {})
    combined = datasets.get("combined_prospective_deconfounded", {})
    phase2 = datasets.get("deconfounded_phase2", {})

    def gain(payload: dict[str, Any], metric: str) -> float:
        comparisons = payload.get("comparisons", {})
        return float(comparisons.get("full Compatibility v2", {}).get(metric, 0.0)) - float(comparisons.get("Compatibility v1", {}).get(metric, 0.0))

    prospective_r2_gain = gain(prospective, "r2")
    prospective_auc_gain = gain(prospective, "auc")
    combined_r2_gain = gain(combined, "r2")
    combined_auc_gain = gain(combined, "auc")
    phase2_r2_gain = gain(phase2, "r2")
    combined_brier_gain = -gain(combined, "brier_score")
    leakage_ok = all(
        payload.get("leakage_checks", {}).get("current_row_excluded_from_prior")
        and payload.get("leakage_checks", {}).get("future_rows_excluded_from_prior_when_time_aware")
        for payload in datasets.values()
    )
    combined_delta = combined.get("comparisons", {}).get("delta_full_v2_vs_v1", {})
    ci_supports_r2 = combined_delta.get("r2", {}).get("low", -1.0) > 0
    ci_supports_brier = combined_delta.get("brier_improvement", {}).get("low", -1.0) > 0

    if not leakage_ok or prospective_r2_gain < -0.02 or combined_r2_gain < -0.02:
        verdict = "v2 rejected"
    elif (
        prospective_r2_gain > 0
        and combined_r2_gain > 0
        and phase2_r2_gain >= 0
        and prospective_auc_gain >= 0
        and combined_auc_gain >= 0
        and ci_supports_r2
        and ci_supports_brier
    ):
        verdict = "v2 Tier A candidate"
    elif prospective_r2_gain > 0 and combined_r2_gain > 0:
        verdict = "v2 Tier B"
    else:
        verdict = "v2 engineering heuristic"
    return {
        "verdict": verdict,
        "prospective_r2_gain": round(prospective_r2_gain, 6),
        "prospective_auc_gain": round(prospective_auc_gain, 6),
        "combined_r2_gain": round(combined_r2_gain, 6),
        "combined_auc_gain": round(combined_auc_gain, 6),
        "phase2_r2_gain": round(phase2_r2_gain, 6),
        "combined_brier_improvement": round(combined_brier_gain, 6),
        "leakage_ok": leakage_ok,
        "confidence_intervals_support_improvement": bool(ci_supports_r2 and ci_supports_brier),
        "breakthrough_claim": False,
    }


def fixed_v2_formula() -> dict[str, float]:
    return {
        "compatibility_v1_score": 0.45,
        "model_route_reliability_prior": 0.25,
        "model_reliability_prior": 0.10,
        "route_reliability_prior": 0.07,
        "provider_reliability_prior": 0.05,
        "task_category_condition": 0.05,
        "context_budget_condition": 0.03,
    }


def metrics_payload(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual:
        return {
            "correlation": 0.0,
            "r2": 0.0,
            "pseudo_r2": 0.0,
            "auc": 0.0,
            "calibration_error": 0.0,
            "brier_score": 0.0,
            "accuracy": 0.0,
            "log_loss": 0.0,
        }
    return {
        "correlation": round(max(0.0, _pearson(actual, predicted)), 6),
        "r2": round(max(0.0, _r2(actual, predicted)), 6),
        "pseudo_r2": round(max(0.0, _pseudo_r2(actual, predicted)), 6),
        "auc": _auc(actual, predicted),
        "calibration_error": _calibration_error(actual, predicted),
        "brier_score": _brier_score(actual, predicted),
        "accuracy": round(sum(1 for a, p in zip(actual, predicted) if a == (1.0 if p >= 0.5 else 0.0)) / len(actual), 6),
        "log_loss": _log_loss(actual, predicted),
    }


def bootstrap_confidence_intervals(actual: list[float], predicted: list[float], *, samples: int = BOOTSTRAP_SAMPLES) -> dict[str, dict[str, float]]:
    if len(actual) < 2:
        return {name: {"low": 0.0, "high": 0.0} for name in ("correlation", "r2", "pseudo_r2", "auc", "calibration_error", "brier_score")}
    rng = random.Random(47)
    values: dict[str, list[float]] = defaultdict(list)
    for _ in range(samples):
        indices = [rng.randrange(len(actual)) for _item in actual]
        sample_actual = [actual[index] for index in indices]
        sample_predicted = [predicted[index] for index in indices]
        metrics = metrics_payload(sample_actual, sample_predicted)
        for name in ("correlation", "r2", "pseudo_r2", "auc", "calibration_error", "brier_score"):
            values[name].append(metrics[name])
    return {name: _percentile_interval(series) for name, series in values.items()}


def bootstrap_delta_intervals(
    actual: list[float],
    v1: list[float],
    v2: list[float],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
) -> dict[str, dict[str, float]]:
    if len(actual) < 2:
        return {name: {"low": 0.0, "high": 0.0} for name in ("r2", "pseudo_r2", "auc", "brier_improvement", "calibration_improvement")}
    rng = random.Random(48)
    values: dict[str, list[float]] = defaultdict(list)
    for _ in range(samples):
        indices = [rng.randrange(len(actual)) for _item in actual]
        a = [actual[index] for index in indices]
        p1 = [v1[index] for index in indices]
        p2 = [v2[index] for index in indices]
        m1 = metrics_payload(a, p1)
        m2 = metrics_payload(a, p2)
        values["r2"].append(m2["r2"] - m1["r2"])
        values["pseudo_r2"].append(m2["pseudo_r2"] - m1["pseudo_r2"])
        values["auc"].append(m2["auc"] - m1["auc"])
        values["brier_improvement"].append(m1["brier_score"] - m2["brier_score"])
        values["calibration_improvement"].append(m1["calibration_error"] - m2["calibration_error"])
    return {name: _percentile_interval(series) for name, series in values.items()}


def calibration_payload(actual: list[float], predicted: list[float]) -> dict[str, Any]:
    bins = []
    for index in range(10):
        lower = index / 10.0
        upper = (index + 1) / 10.0
        bucket = [(a, p) for a, p in zip(actual, predicted) if (lower <= p <= upper if index == 9 else lower <= p < upper)]
        predicted_rate = sum(p for _a, p in bucket) / len(bucket) if bucket else 0.0
        actual_rate = sum(a for a, _p in bucket) / len(bucket) if bucket else 0.0
        bins.append(
            {
                "bin": f"{index * 10}-{(index + 1) * 10}%",
                "rows": len(bucket),
                "predicted_success": round(predicted_rate, 6),
                "actual_success": round(actual_rate, 6),
                "overconfidence": round(max(0.0, predicted_rate - actual_rate), 6),
            }
        )
    return {"calibration_error": _calibration_error(actual, predicted), "brier_score": _brier_score(actual, predicted), "bins": bins}


def _feature_row(row: CompatibilityV2Row, prior_rows: list[CompatibilityV2Row], mode: str) -> dict[str, Any]:
    model = _beta_prior(prior_rows, lambda item: item.model == row.model)
    provider = _beta_prior(prior_rows, lambda item: _provider_key(item) == _provider_key(row))
    route = _beta_prior(prior_rows, lambda item: _route_key(item) == _route_key(row))
    model_route = _beta_prior(prior_rows, lambda item: _model_route_key(item) == _model_route_key(row))
    task_condition = _beta_prior(prior_rows, lambda item: item.model == row.model and item.category == row.category)
    context_condition = _beta_prior(prior_rows, lambda item: item.model == row.model and item.context_budget == row.context_budget)
    formula = fixed_v2_formula()
    v2 = (
        formula["compatibility_v1_score"] * row.compatibility_v1_score
        + formula["model_route_reliability_prior"] * model_route["rate"]
        + formula["model_reliability_prior"] * model["rate"]
        + formula["route_reliability_prior"] * route["rate"]
        + formula["provider_reliability_prior"] * provider["rate"]
        + formula["task_category_condition"] * task_condition["rate"]
        + formula["context_budget_condition"] * context_condition["rate"]
    )
    prior_timestamps = [item.timestamp for item in prior_rows if item.timestamp and row.timestamp]
    return {
        "row_id": row.row_id,
        "dataset": row.dataset,
        "model": row.model,
        "provider": row.provider,
        "route": row.route,
        "category": row.category,
        "context_budget": row.context_budget,
        "success": row.success,
        "compatibility_v1_score": row.compatibility_v1_score,
        "model_reliability_prior": model["rate"],
        "provider_reliability_prior": provider["rate"],
        "route_reliability_prior": route["rate"],
        "model_route_reliability_prior": model_route["rate"],
        "task_category_condition": task_condition["rate"],
        "context_budget_condition": context_condition["rate"],
        "v1_model_reliability": _avg(row.compatibility_v1_score, model["rate"]),
        "v1_route_reliability": _avg(row.compatibility_v1_score, route["rate"]),
        "v1_model_route_reliability": _avg(row.compatibility_v1_score, model_route["rate"]),
        "compatibility_v2_probability": round(_clip(v2), 6),
        "model_route_reliability_prior_count": model_route["count"],
        "prior_excludes_current_row": all(item.row_id != row.row_id for item in prior_rows),
        "future_rows_excluded": mode != "time_aware" or not row.timestamp or all(ts <= row.timestamp for ts in prior_timestamps),
    }


def _beta_prior(rows: Iterable[CompatibilityV2Row], predicate: Any) -> dict[str, float | int]:
    selected = [row for row in rows if predicate(row)]
    successes = sum(row.success for row in selected)
    count = len(selected)
    return {"rate": round((successes + SMOOTHING_ALPHA) / (count + SMOOTHING_ALPHA + SMOOTHING_BETA), 6), "count": count}


def _provider_key(row: CompatibilityV2Row) -> str:
    return row.provider_type or row.provider


def _route_key(row: CompatibilityV2Row) -> str:
    return row.route or _provider_key(row)


def _model_route_key(row: CompatibilityV2Row) -> tuple[str, str]:
    return (row.model, _route_key(row))


def _row_from_payload(
    row: dict[str, Any],
    fallback_id: str,
    dataset: str,
    frozen: dict[tuple[str, str, str, int], float],
) -> CompatibilityV2Row | None:
    if not _is_cloud_row(row):
        return None
    model = str(row.get("model") or "")
    provider = str(row.get("provider") or row.get("agent") or row.get("provider_type") or "")
    provider_type = str(row.get("provider_type") or provider)
    route = str(row.get("route") or row.get("agent") or provider or provider_type)
    repository = str(row.get("repository") or "")
    category = str(row.get("category") or row.get("task_type") or "")
    context_budget = int(row.get("context_budget", row.get("context budget", 0)) or 0)
    key = (model, repository, category, context_budget)
    compatibility = _clip(row.get("compatibility_score", row.get("predicted_probability", frozen.get(key, 0.5))))
    if "success" in row:
        success = 1.0 if row.get("success") else 0.0
    elif row.get("actual_outcome") == "success":
        success = 1.0
    else:
        success = 0.0
    return CompatibilityV2Row(
        row_id=str(row.get("row_id") or row.get("dedupe_key") or fallback_id),
        dataset=dataset,
        model=model,
        provider=provider,
        provider_type=provider_type,
        route=route,
        repository=repository,
        category=category,
        context_budget=context_budget,
        compatibility_v1_score=compatibility,
        success=success,
        timestamp=_row_time(row),
    )


def _is_cloud_row(row: dict[str, Any]) -> bool:
    provider_type = str(row.get("provider_type") or row.get("provider") or "").lower()
    provider = str(row.get("provider") or "").lower()
    route = str(row.get("route") or "").lower()
    if any(value in FORBIDDEN_PROVIDER_TYPES for value in (provider_type, provider, route)):
        return False
    if provider_type in {"configuration", ""} and row.get("live") is not True:
        return False
    if row.get("live") is False and provider_type not in {"ollama-cloud", "codex-cli", "openai-compatible"}:
        return False
    return bool(str(row.get("model") or ""))


def _prospective_freeze_time(state_dir: str | Path) -> datetime | None:
    path = research_dir(state_dir) / "prospective_results.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            parsed = _parse_time(payload.get("freeze_time_utc"))
            if parsed:
                return parsed
        except json.JSONDecodeError:
            pass
    predictions = prospective_predictions_path(state_dir)
    if predictions.exists():
        return datetime.fromtimestamp(predictions.stat().st_mtime, tz=timezone.utc)
    return None


def _prospective_match_timestamps(state_dir: str | Path) -> set[str]:
    path = research_dir(state_dir) / "prospective_results.json"
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    matches = payload.get("matches", [])
    timestamps = set()
    if isinstance(matches, list):
        for row in matches:
            if isinstance(row, dict):
                parsed = _parse_time(row.get("timestamp"))
                if parsed:
                    timestamps.add(parsed.isoformat())
    return timestamps


def _v1_artifacts_preserved(state_dir: str | Path) -> dict[str, bool]:
    directory = research_dir(state_dir)
    names = (
        "compatibility_metrics.json",
        "compatibility_prediction.json",
        "compatibility_v1_postmortem.md",
        "prospective_results.json",
    )
    return {name: (directory / name).exists() for name in names}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _row_time(row: dict[str, Any]) -> datetime | None:
    return _parse_time(row.get("timestamp"))


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sort_key(row: CompatibilityV2Row) -> tuple[str, str]:
    return ((row.timestamp or datetime.min.replace(tzinfo=timezone.utc)).isoformat(), row.row_id)


def _clip(value: Any) -> float:
    try:
        return max(0.001, min(0.999, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _avg(*values: float) -> float:
    return round(sum(values) / len(values), 6) if values else 0.5


def _pearson(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(set(a)) < 2 or len(set(b)) < 2:
        return 0.0
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    den_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    den_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
    return numerator / (den_a * den_b) if den_a and den_b else 0.0


def _r2(actual: list[float], predicted: list[float]) -> float:
    mean = sum(actual) / len(actual) if actual else 0.0
    total = sum((value - mean) ** 2 for value in actual)
    if total == 0:
        return 0.0
    residual = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    return 1.0 - residual / total


def _pseudo_r2(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    base = sum(actual) / len(actual)
    null = _log_loss(actual, [base for _item in actual], rounded=False)
    model = _log_loss(actual, predicted, rounded=False)
    if null <= 0:
        return 0.0
    return 1.0 - model / null


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


def _calibration_error(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    total = 0.0
    for index in range(10):
        lower = index / 10.0
        upper = (index + 1) / 10.0
        bucket = [(a, p) for a, p in zip(actual, predicted) if (lower <= p <= upper if index == 9 else lower <= p < upper)]
        if bucket:
            actual_rate = sum(a for a, _p in bucket) / len(bucket)
            predicted_rate = sum(p for _a, p in bucket) / len(bucket)
            total += (len(bucket) / len(actual)) * abs(actual_rate - predicted_rate)
    return round(total, 6)


def _brier_score(actual: list[float], predicted: list[float]) -> float:
    return round(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual), 6) if actual else 0.0


def _log_loss(actual: list[float], predicted: list[float], *, rounded: bool = True) -> float:
    if not actual:
        return 0.0
    value = -sum(a * math.log(_clip(p)) + (1.0 - a) * math.log(1.0 - _clip(p)) for a, p in zip(actual, predicted)) / len(actual)
    return round(value, 6) if rounded else value


def _percentile_interval(values: list[float]) -> dict[str, float]:
    if not values:
        return {"low": 0.0, "high": 0.0}
    ordered = sorted(values)
    low_index = max(0, int(0.025 * (len(ordered) - 1)))
    high_index = min(len(ordered) - 1, int(0.975 * (len(ordered) - 1)))
    return {"low": round(ordered[low_index], 6), "high": round(ordered[high_index], 6)}


def _region_summary(actual: list[float], v1: list[float], v2: list[float], lower: float, upper: float, *, include_lower: bool = True) -> dict[str, Any]:
    def rows(predicted: list[float]) -> list[tuple[float, float]]:
        return [
            (a, p)
            for a, p in zip(actual, predicted)
            if ((lower <= p <= upper) if include_lower else (lower < p <= upper))
        ]

    def summary(bucket: list[tuple[float, float]]) -> dict[str, float | int]:
        return {
            "rows": len(bucket),
            "failure_rate": round(1.0 - (sum(a for a, _p in bucket) / len(bucket)), 6) if bucket else 0.0,
            "mean_prediction": round(sum(p for _a, p in bucket) / len(bucket), 6) if bucket else 0.0,
        }

    return {"v1": summary(rows(v1)), "v2": summary(rows(v2))}


def _overconfidence(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    return sum(max(0.0, p - a) for a, p in zip(actual, predicted)) / len(actual)


def _failure_rate(actual: list[float], predicted: list[float], lower: float, upper: float) -> float:
    bucket = [a for a, p in zip(actual, predicted) if lower <= p <= upper]
    return 1.0 - (sum(bucket) / len(bucket)) if bucket else 0.0


def _report_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Compatibility v2 Report",
        "",
        f"- Scope: {payload['scope']}",
        f"- Verdict: `{payload['scientific_verdict']['verdict']}`",
        f"- Breakthrough claim: {payload['scientific_verdict']['breakthrough_claim']}",
        f"- Leakage rule: {payload['leakage_rule']}",
        "",
        "## Dataset Metrics",
        "",
        "| dataset | rows | v1 R2 | v2 R2 | delta R2 | v1 AUC | v2 AUC | v1 Brier | v2 Brier | strongest source |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, data in payload["datasets"].items():
        comparisons = data["comparisons"]
        v1 = comparisons["Compatibility v1"]
        v2 = comparisons["full Compatibility v2"]
        lines.append(
            f"| {name} | {data['rows']} | {v1['r2']:.6f} | {v2['r2']:.6f} | {v2['r2'] - v1['r2']:.6f} | "
            f"{v1['auc']:.6f} | {v2['auc']:.6f} | {v1['brier_score']:.6f} | {v2['brier_score']:.6f} | "
            f"{data['ablation']['strongest_improvement_source']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Compatibility v2 is evaluated as a separate candidate theory. Compatibility v1 artifacts are not overwritten and remain the baseline.",
            "Reliability features are Beta-smoothed priors over prior cloud rows, not post-hoc labels from the evaluated row.",
        ]
    )
    return "\n".join(lines) + "\n"


def _calibration_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Compatibility v2 Calibration", ""]
    for name, data in payload["datasets"].items():
        calibration = data["calibration"]
        lines.extend(
            [
                f"## {name}",
                "",
                f"- v1 calibration error: {calibration['v1']['calibration_error']}",
                f"- v2 calibration error: {calibration['v2']['calibration_error']}",
                f"- overconfidence delta v2-v1: {calibration['overconfidence_delta_v2_minus_v1']}",
                f"- mid-probability failure delta v2-v1: {calibration['mid_probability_failure_delta_v2_minus_v1']}",
                "",
                "| bin | v1 rows | v1 predicted | v1 actual | v2 rows | v2 predicted | v2 actual |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for v1_bin, v2_bin in zip(calibration["v1"]["bins"], calibration["v2"]["bins"]):
            lines.append(
                f"| {v1_bin['bin']} | {v1_bin['rows']} | {v1_bin['predicted_success']:.6f} | {v1_bin['actual_success']:.6f} | "
                f"{v2_bin['rows']} | {v2_bin['predicted_success']:.6f} | {v2_bin['actual_success']:.6f} |"
            )
        lines.append("")
    return "\n".join(lines)


def _v1_vs_v2_markdown(payload: dict[str, Any]) -> str:
    verdict = payload["scientific_verdict"]
    lines = [
        "# Compatibility v1 vs v2",
        "",
        f"- Final verdict: `{verdict['verdict']}`",
        f"- Prospective R2 gain: {verdict['prospective_r2_gain']}",
        f"- Combined prospective/deconfounded R2 gain: {verdict['combined_r2_gain']}",
        f"- Combined Brier improvement: {verdict['combined_brier_improvement']}",
        f"- Confidence intervals support improvement: {verdict['confidence_intervals_support_improvement']}",
        f"- Leakage checks passed: {verdict['leakage_ok']}",
        "",
        "## Baselines",
        "",
    ]
    for name, data in payload["datasets"].items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| model | corr | R2 | pseudo-R2 | AUC | calibration error | Brier |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for model_name, metrics in data["comparisons"].items():
            if model_name == "delta_full_v2_vs_v1":
                continue
            lines.append(
                f"| {model_name} | {metrics['correlation']:.6f} | {metrics['r2']:.6f} | {metrics['pseudo_r2']:.6f} | "
                f"{metrics['auc']:.6f} | {metrics['calibration_error']:.6f} | {metrics['brier_score']:.6f} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Compatibility v2 as a new candidate theory.")
    parser.add_argument("--state-dir", default=".agent-hub", help="Agent-Hub state directory.")
    parser.add_argument("--json", action="store_true", help="Print output paths as JSON.")
    args = parser.parse_args(argv)
    paths = run_compatibility_v2_evaluation(args.state_dir)
    output = {key: str(value) for key, value in paths.items()}
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        for key, value in output.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CompatibilityV2Row",
    "build_evaluation_datasets",
    "calibration_payload",
    "compute_non_leaky_features",
    "compatibility_v1_vs_v2_path",
    "compatibility_v2_calibration_path",
    "compatibility_v2_report_path",
    "compatibility_v2_results_path",
    "evaluate_compatibility_v2",
    "load_cloud_live_rows",
    "load_frozen_v1_predictions",
    "load_phase_rows",
    "run_compatibility_v2_evaluation",
]
