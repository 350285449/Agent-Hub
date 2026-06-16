from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable


def clamp01(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, value))


def mean(values: Iterable[float]) -> float:
    rows = [float(value) for value in values if value is not None]
    return sum(rows) / len(rows) if rows else 0.0


def stdev(values: Iterable[float]) -> float:
    rows = [float(value) for value in values if value is not None]
    if len(rows) < 2:
        return 0.0
    avg = mean(rows)
    return math.sqrt(sum((value - avg) ** 2 for value in rows) / (len(rows) - 1))


def pearson(xs: Iterable[float], ys: Iterable[float]) -> float:
    left = [float(value) for value in xs]
    right = [float(value) for value in ys]
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    mx = mean(left)
    my = mean(right)
    sx = math.sqrt(sum((value - mx) ** 2 for value in left))
    sy = math.sqrt(sum((value - my) ** 2 for value in right))
    if sx == 0.0 or sy == 0.0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(left, right)) / (sx * sy)


def absolute_correlation_score(xs: Iterable[float], ys: Iterable[float]) -> float:
    return round(clamp01(abs(pearson(xs, ys))), 6)


def entropy_binary(values: Iterable[bool]) -> float:
    rows = [bool(value) for value in values]
    if not rows:
        return 0.0
    p = sum(1 for value in rows if value) / len(rows)
    if p in {0.0, 1.0}:
        return 0.0
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


def normalized_inverse_variation(values: Iterable[float]) -> float:
    rows = [float(value) for value in values]
    if len(rows) < 2:
        return 0.0
    avg_abs = mean(abs(value) for value in rows)
    return round(clamp01(1.0 - stdev(rows) / (avg_abs + 1e-9)), 6)


def median(values: Iterable[float]) -> float:
    rows = sorted(float(value) for value in values)
    if not rows:
        return 0.0
    middle = len(rows) // 2
    if len(rows) % 2:
        return rows[middle]
    return (rows[middle - 1] + rows[middle]) / 2.0


def auc_score(scores: Iterable[float], labels: Iterable[bool]) -> float:
    pairs = [(float(score), bool(label)) for score, label in zip(scores, labels)]
    positive_count = sum(1 for _, label in pairs if label)
    negative_count = len(pairs) - positive_count
    if not positive_count or not negative_count:
        return 0.5
    sorted_pairs = sorted(pairs, key=lambda item: item[0])
    rank_sum = 0.0
    rank = 1
    index = 0
    while index < len(sorted_pairs):
        end = index + 1
        while end < len(sorted_pairs) and sorted_pairs[end][0] == sorted_pairs[index][0]:
            end += 1
        average_rank = (rank + rank + (end - index) - 1) / 2.0
        rank_sum += average_rank * sum(1 for _, label in sorted_pairs[index:end] if label)
        rank += end - index
        index = end
    return (rank_sum - positive_count * (positive_count + 1) / 2.0) / (positive_count * negative_count)


def predictive_power(values: Iterable[float], success: Iterable[bool], validation: Iterable[float]) -> float:
    rows = [float(value) for value in values]
    labels = [bool(value) for value in success]
    scores = [float(value) for value in validation]
    if len(rows) < 3:
        return 0.0
    success_auc = abs(auc_score(rows, labels) - 0.5) * 2.0
    validation_corr = abs(pearson(rows, scores))
    return round(clamp01(0.55 * success_auc + 0.45 * validation_corr), 6)


def grouped_stability(rows: list[dict[str, Any]], values: list[float], keys: tuple[str, ...]) -> float:
    if len(rows) != len(values) or len(rows) < 4:
        return normalized_inverse_variation(values)
    even: dict[tuple[str, ...], list[float]] = defaultdict(list)
    odd: dict[tuple[str, ...], list[float]] = defaultdict(list)
    for index, (row, value) in enumerate(zip(rows, values)):
        key = tuple(str(row.get(item) or "") for item in keys)
        (even if index % 2 == 0 else odd)[key].append(float(value))
    shared = sorted(set(even) & set(odd))
    if len(shared) >= 2:
        corr = pearson([mean(even[key]) for key in shared], [mean(odd[key]) for key in shared])
        return round(clamp01((corr + 1.0) / 2.0), 6)
    return normalized_inverse_variation([mean(bucket) for bucket in list(even.values()) + list(odd.values())])


def routing_usefulness(rows: list[dict[str, Any]], values: list[float]) -> float:
    if len(rows) != len(values) or len(rows) < 3:
        return 0.0
    labels = [not bool(row.get("success")) for row in rows]
    validation_penalty = [1.0 - float(row.get("validation_score") or 0.0) for row in rows]
    return round(clamp01(0.7 * abs(auc_score(values, labels) - 0.5) * 2.0 + 0.3 * abs(pearson(values, validation_penalty))), 6)


def falsification_resistance(stability: float, predictive: float, usefulness: float, sample_size: int) -> float:
    evidence = min(1.0, sample_size / 40.0)
    weak_signal_penalty = 1.0 if max(predictive, usefulness) >= 0.15 else 0.55
    return round(clamp01((0.35 * stability + 0.35 * predictive + 0.30 * usefulness) * evidence * weak_signal_penalty), 6)


def falsification_notes(
    *,
    sample_size: int,
    stability: float,
    predictive: float,
    success_correlation: float,
    validation_correlation: float,
    usefulness: float,
) -> tuple[list[str], list[str]]:
    evidence: list[str] = []
    limitations: list[str] = []
    if sample_size < 20:
        evidence.append("Small sample size; apparent structure may be noise.")
    if stability < 0.35:
        evidence.append("Low split-run stability.")
    if predictive < 0.15:
        evidence.append("Weak predictive signal in current observations.")
    if abs(success_correlation) < 0.1 and abs(validation_correlation) < 0.1:
        evidence.append("Near-zero direct correlation with success and validation.")
    if usefulness < 0.15:
        evidence.append("Limited routing usefulness under a simple pre-execution test.")
    if not evidence:
        evidence.append("No simple falsification test rejected it, but this is not proof.")
    limitations.append("Observational telemetry cannot establish causality.")
    limitations.append("Rows may mix deterministic proofs and real-model runs unless filtered upstream.")
    return evidence, limitations


__all__ = [
    "absolute_correlation_score",
    "auc_score",
    "clamp01",
    "entropy_binary",
    "falsification_notes",
    "falsification_resistance",
    "grouped_stability",
    "mean",
    "median",
    "normalized_inverse_variation",
    "pearson",
    "predictive_power",
    "routing_usefulness",
    "stdev",
]
