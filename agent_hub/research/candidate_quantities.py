from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from .quantity_tests import (
    absolute_correlation_score,
    clamp01,
    entropy_binary,
    falsification_notes,
    falsification_resistance,
    grouped_stability,
    mean,
    pearson,
    predictive_power,
    routing_usefulness,
)


@dataclass(frozen=True, slots=True)
class CandidateQuantity:
    key: str
    name: str
    measures: str
    why_it_matters: str
    calculation: str
    novelty_proxy: float
    value_fn: Callable[[list[dict[str, Any]]], tuple[float, list[float], dict[str, Any]]]
    stability_keys: tuple[str, ...] = ("task_type", "model")


def candidate_quantities() -> list[CandidateQuantity]:
    return [
        CandidateQuantity(
            "context_complexity_index",
            "Context Complexity Index",
            "How much context a task/repo/model appears to need.",
            "If stable, it gives routers an early estimate of context budget and retrieval effort.",
            "Log context tokens, context file count, input tokens, and observed context percent are normalized per run.",
            0.72,
            _context_complexity,
        ),
        CandidateQuantity(
            "failure_entropy",
            "Failure Entropy",
            "Whether failures are random-looking or concentrated in predictable buckets.",
            "Predictable failures are easier to route around, reproduce, and falsify.",
            "Binary failure entropy is computed within task/model/route buckets and inverted per observation.",
            0.76,
            _failure_entropy,
            ("task_type", "model", "route"),
        ),
        CandidateQuantity(
            "agent_difficulty_index",
            "Agent Difficulty Index",
            "Task difficulty after averaging over observed models.",
            "A model-independent difficulty signal can separate hard tasks from weak model choices.",
            "Failure rate and validation deficit are averaged by task or task type, then assigned back to runs.",
            0.82,
            _agent_difficulty,
            ("task_type", "task_id"),
        ),
        CandidateQuantity(
            "model_context_tolerance",
            "Model Context Tolerance",
            "How much context a model can use before validation or reliability degrades.",
            "Routers need to know which models benefit from larger context and which get slower or worse.",
            "High-context effective score is compared with low-context effective score for each model.",
            0.78,
            _model_context_tolerance,
            ("model",),
        ),
        CandidateQuantity(
            "model_specialization_index",
            "Model Specialization Index",
            "Whether models naturally specialize by task type.",
            "Specialization would justify routing by task family instead of one global model ranking.",
            "For each model, task-type performance spread is measured against its overall average.",
            0.74,
            _model_specialization,
            ("model", "task_type"),
        ),
        CandidateQuantity(
            "repository_intelligence_index",
            "Repository Intelligence Index",
            "How AI-friendly a repository appears under the observed tasks.",
            "Repository structure and testability may be a first-class factor in agent success.",
            "Repo-level success, validation, context efficiency, and low-error rate are combined.",
            0.80,
            _repository_intelligence,
            ("repo",),
        ),
        CandidateQuantity(
            "routing_risk_score",
            "Routing Risk Score",
            "Pre-execution risk that a selected route/model/task combination will fail.",
            "This is directly actionable for routers, fallbacks, and confidence gates.",
            "Historical failure and validation deficit are averaged by route, model, task type, and context bucket.",
            0.70,
            _routing_risk,
            ("route", "model", "task_type"),
        ),
        CandidateQuantity(
            "model_distance_metric",
            "Model Distance Metric",
            "Behavioral distance between models from success and validation vectors.",
            "Distance can expose redundancy, ensemble value, and routing diversity.",
            "Per-model vectors over task/context buckets are compared with Euclidean distance.",
            0.86,
            _model_distance,
            ("model",),
        ),
        CandidateQuantity(
            "information_density_index",
            "Information Density Index",
            "Useful success contribution per context token.",
            "It rewards context that improves outcomes without bloating prompts.",
            "Effective validation success is divided by log-scaled context tokens.",
            0.77,
            _information_density,
        ),
        CandidateQuantity(
            "expected_utility_score",
            "Expected Utility Score",
            "Net utility after validation, success, cost, latency, retries, and error risk.",
            "A practical objective can rank routes when correctness is not the only constraint.",
            "Validation and success are penalized by normalized latency, cost, retries, and errors.",
            0.68,
            _expected_utility,
            ("model", "route", "task_type"),
        ),
    ]


def evaluate_candidate(quantity: CandidateQuantity, rows: list[dict[str, Any]]) -> dict[str, Any]:
    value, vector, details = quantity.value_fn(rows)
    outcomes = [row for row in rows if row.get("success") is not None]
    vector = vector[: len(outcomes)]
    success = [bool(row.get("success")) for row in outcomes]
    validation = [float(row.get("validation_score") or 0.0) for row in outcomes]
    stability = grouped_stability(outcomes, vector, quantity.stability_keys)
    predictive = predictive_power(vector, success, validation)
    success_corr = pearson(vector, [1.0 if item else 0.0 for item in success])
    validation_corr = pearson(vector, validation)
    usefulness = routing_usefulness(outcomes, vector)
    resistance = falsification_resistance(stability, predictive, usefulness, len(outcomes))
    evidence, limitations = falsification_notes(
        sample_size=len(outcomes),
        stability=stability,
        predictive=predictive,
        success_correlation=success_corr,
        validation_correlation=validation_corr,
        usefulness=usefulness,
    )
    potential = (
        0.25 * stability
        + 0.25 * predictive
        + 0.20 * usefulness
        + 0.15 * quantity.novelty_proxy
        + 0.15 * resistance
    )
    survives = resistance >= 0.2 and (predictive >= 0.15 or usefulness >= 0.15)
    return {
        "key": quantity.key,
        "name": quantity.name,
        "value": round(value, 6),
        "stability": round(stability, 6),
        "predictive_power": round(predictive, 6),
        "correlation_with_success": round(success_corr, 6),
        "correlation_with_validation_score": round(validation_corr, 6),
        "usefulness_for_routing": round(usefulness, 6),
        "novelty_proxy": round(quantity.novelty_proxy, 6),
        "falsification_resistance": round(resistance, 6),
        "research_potential_score": round(clamp01(potential), 6),
        "falsification_evidence": evidence,
        "limitations": limitations,
        "survives_falsification": survives,
        "recommendation": "continue" if survives else "kill or redesign",
        "what_it_measures": quantity.measures,
        "why_it_could_matter": quantity.why_it_matters,
        "how_it_is_calculated": quantity.calculation,
        "details": details,
    }


def evaluate_all_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [evaluate_candidate(quantity, rows) for quantity in candidate_quantities()]


def _context_complexity(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    values = []
    max_context = max([float(row.get("context_tokens") or 0.0) for row in rows] + [1.0])
    max_input = max([float(row.get("input_tokens") or 0.0) for row in rows] + [1.0])
    max_files = max([float(row.get("file_count") or 0.0) for row in rows] + [1.0])
    for row in rows:
        value = (
            0.45 * _log_norm(float(row.get("context_tokens") or 0.0), max_context)
            + 0.20 * _log_norm(float(row.get("input_tokens") or 0.0), max_input)
            + 0.20 * _log_norm(float(row.get("file_count") or 0.0), max_files)
            + 0.15 * clamp01(float(row.get("context_percent") or 0.0) / 100.0)
        )
        values.append(value)
    return mean(values), values, {"higher_means": "more observed context demand"}


def _failure_entropy(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[bool]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("task_type") or ""), str(row.get("model") or ""), str(row.get("route") or ""))].append(not bool(row.get("success")))
    entropy_by_key = {key: entropy_binary(values) for key, values in groups.items()}
    values = [1.0 - entropy_by_key[(str(row.get("task_type") or ""), str(row.get("model") or ""), str(row.get("route") or ""))] for row in rows]
    return mean(entropy_by_key.values()), values, {"group_count": len(groups), "per_run_value": "predictability = 1 - entropy"}


def _agent_difficulty(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get("task_id") or row.get("task_type") or "unknown").rsplit("-", 1)[0]
        groups[key].append(row)
    difficulty = {
        key: 0.6 * mean(1.0 if not bool(item.get("success")) else 0.0 for item in items)
        + 0.4 * mean(1.0 - float(item.get("validation_score") or 0.0) for item in items)
        for key, items in groups.items()
    }
    values = [difficulty[str(row.get("task_id") or row.get("task_type") or "unknown").rsplit("-", 1)[0]] for row in rows]
    return mean(values), values, {"task_groups": len(groups)}


def _model_context_tolerance(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_model[str(row.get("model") or "unknown")].append(row)
    scores: dict[str, float] = {}
    for model, items in by_model.items():
        low = [item for item in items if float(item.get("context_percent") or 0.0) <= 25 or float(item.get("context_tokens") or 0.0) <= 1000]
        high = [item for item in items if float(item.get("context_percent") or 0.0) >= 75 or float(item.get("context_tokens") or 0.0) > 1000]
        low_score = _effective_score(low)
        high_score = _effective_score(high)
        scores[model] = clamp01(0.5 + (high_score - low_score) / 2.0)
    values = [scores[str(row.get("model") or "unknown")] for row in rows]
    return mean(scores.values()), values, {"models": scores}


def _model_specialization(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    model_task: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        model_task[str(row.get("model") or "unknown")][str(row.get("task_type") or "unknown")].append(row)
    scores: dict[str, float] = {}
    for model, task_rows in model_task.items():
        task_scores = [_effective_score(items) for items in task_rows.values()]
        avg = mean(task_scores)
        scores[model] = clamp01(mean(abs(score - avg) for score in task_scores) * 2.0)
    values = [scores[str(row.get("model") or "unknown")] for row in rows]
    return mean(scores.values()), values, {"models": scores}


def _repository_intelligence(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_repo[str(row.get("repo") or "unknown")].append(row)
    scores = {}
    for repo, items in by_repo.items():
        context_penalty = mean(_log_norm(float(item.get("context_tokens") or 0.0), 100_000.0) for item in items)
        error_penalty = mean(float(item.get("error_count") or 0.0) > 0.0 for item in items)
        scores[repo] = clamp01(0.45 * _success_rate(items) + 0.40 * mean(float(item.get("validation_score") or 0.0) for item in items) + 0.15 * (1.0 - max(context_penalty, error_penalty)))
    values = [scores[str(row.get("repo") or "unknown")] for row in rows]
    return mean(scores.values()), values, {"repositories": scores}


def _routing_risk(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    groups: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("route") or ""),
            str(row.get("model") or ""),
            str(row.get("task_type") or ""),
            int(float(row.get("context_percent") or 0.0) // 25),
        )
        groups[key].append(row)
    risk = {
        key: clamp01(0.65 * (1.0 - _success_rate(items)) + 0.35 * mean(1.0 - float(item.get("validation_score") or 0.0) for item in items))
        for key, items in groups.items()
    }
    values = [
        risk[(str(row.get("route") or ""), str(row.get("model") or ""), str(row.get("task_type") or ""), int(float(row.get("context_percent") or 0.0) // 25))]
        for row in rows
    ]
    return mean(values), values, {"risk_buckets": len(groups)}


def _model_distance(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    model_vectors: dict[str, dict[tuple[str, int], float]] = defaultdict(dict)
    buckets = sorted({(str(row.get("task_type") or "unknown"), int(float(row.get("context_percent") or 0.0) // 25)) for row in rows})
    by_model_bucket: dict[tuple[str, tuple[str, int]], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        model = str(row.get("model") or "unknown")
        bucket = (str(row.get("task_type") or "unknown"), int(float(row.get("context_percent") or 0.0) // 25))
        by_model_bucket[(model, bucket)].append(row)
    models = sorted({str(row.get("model") or "unknown") for row in rows})
    for model in models:
        for bucket in buckets:
            model_vectors[model][bucket] = _effective_score(by_model_bucket.get((model, bucket), []))
    distances: dict[str, float] = {}
    for model in models:
        others = [other for other in models if other != model]
        if not others:
            distances[model] = 0.0
            continue
        distances[model] = mean(_euclidean([model_vectors[model][bucket] for bucket in buckets], [model_vectors[other][bucket] for bucket in buckets]) for other in others)
    max_distance = max(distances.values()) if distances else 1.0
    normalized = {model: (value / max_distance if max_distance else 0.0) for model, value in distances.items()}
    values = [normalized[str(row.get("model") or "unknown")] for row in rows]
    return mean(values), values, {"models": normalized, "bucket_count": len(buckets)}


def _information_density(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    values = []
    for row in rows:
        effective = (1.0 if bool(row.get("success")) else 0.0) * float(row.get("validation_score") or 0.0)
        values.append(effective / math.log1p(max(1.0, float(row.get("context_tokens") or row.get("input_tokens") or 1.0))))
    max_value = max(values) if values else 1.0
    normalized = [value / max_value if max_value else 0.0 for value in values]
    return mean(normalized), normalized, {"higher_means": "more validation success per token"}


def _expected_utility(rows: list[dict[str, Any]]) -> tuple[float, list[float], dict[str, Any]]:
    max_latency = max([float(row.get("latency_ms") or 0.0) for row in rows] + [1.0])
    max_cost = max([float(row.get("cost_estimate") or 0.0) for row in rows] + [1.0])
    max_retry = max([float(row.get("retry_count") or 0.0) for row in rows] + [1.0])
    values = []
    for row in rows:
        positive = 0.65 * float(row.get("validation_score") or 0.0) + 0.35 * (1.0 if bool(row.get("success")) else 0.0)
        penalty = (
            0.35 * _log_norm(float(row.get("latency_ms") or 0.0), max_latency)
            + 0.25 * _log_norm(float(row.get("cost_estimate") or 0.0), max_cost)
            + 0.25 * _log_norm(float(row.get("retry_count") or 0.0), max_retry)
            + 0.15 * clamp01(float(row.get("error_count") or 0.0))
        )
        values.append(clamp01(positive * (1.0 - 0.6 * penalty)))
    return mean(values), values, {"higher_means": "more net observed value"}


def _effective_score(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return clamp01(0.5 * _success_rate(rows) + 0.5 * mean(float(row.get("validation_score") or 0.0) for row in rows))


def _success_rate(rows: list[dict[str, Any]]) -> float:
    return mean(1.0 if bool(row.get("success")) else 0.0 for row in rows)


def _log_norm(value: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return clamp01(math.log1p(max(0.0, value)) / math.log1p(max(1.0, maximum)))


def _euclidean(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)) / len(left))


__all__ = [
    "CandidateQuantity",
    "candidate_quantities",
    "evaluate_all_candidates",
    "evaluate_candidate",
]
