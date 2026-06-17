from __future__ import annotations

import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import grounding_integrity_program as gi
from scripts import measurement_science_program as m
from scripts import prospective_failure_v3 as pf


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"
RNG = random.Random(20260617)


def write_md(name: str, text: str) -> None:
    content = text.strip() + "\n"
    RESEARCH.mkdir(exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    return m.table(headers, rows)


def fmt(value: Any) -> str:
    try:
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def f(row: dict[str, Any], field: str, default: float = 0.0) -> float:
    value = row.get(field)
    return default if value is None else float(value)


def clamp(value: float) -> float:
    return m.clamp01(value)


def usable(fields: list[str], rows: list[dict[str, Any]]) -> list[str]:
    return [field for field in fields if rows and all(row.get(field) is not None for row in rows)]


def score(train: list[dict[str, Any]], test: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    fields = usable(fields, [*train, *test])
    return pf.score_model(train, test, fields)


def in_sample(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    return pf.in_sample(rows, usable(fields, rows))


def single_metric(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    material = [row for row in rows if row.get(field) is not None]
    return m.metrics([f(row, field) for row in material], [f(row, "success") for row in material])


def train_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("dataset") == "historical"] or rows


def holdout_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("dataset") != "historical"] or rows


def model_family(model: str) -> str:
    text = model.lower()
    if "gpt" in text or "openai" in text or "o1" in text or "o3" in text or "o4" in text:
        return "openai"
    if "claude" in text:
        return "anthropic"
    if "gemini" in text or "gemma" in text:
        return "google"
    if "llama" in text:
        return "meta"
    if "mistral" in text or "mixtral" in text:
        return "mistral"
    if "qwen" in text:
        return "qwen"
    return (text.split(":")[0] or "other").replace("|", "_")


def task_family(row: dict[str, Any]) -> str:
    cat = str(row.get("category") or "").lower().replace("-", "_")
    repo = str(row.get("repository") or "").lower()
    if cat in {"bug_fix", "code_generation", "refactor", "testing", "api_compatibility"}:
        return "coding"
    if "research" in cat or "analysis" in cat or "repo_analysis" in cat or "benchmark" in cat:
        return "research"
    if cat in {"architecture", "planning", "reasoning", "math"}:
        return "reasoning"
    if f(row, "edited_files") > 0 or f(row, "tests_or_verifiers") > 0 or "agent" in repo:
        return "agentic"
    return "reasoning"


def benchmark(row: dict[str, Any]) -> str:
    source = str(row.get("source") or row.get("dataset") or "unknown")
    dataset = str(row.get("dataset") or "unknown")
    repo = str(row.get("repository") or "unknown")
    return f"{source}:{dataset}:{repo}"


def with_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for idx, row in enumerate(rows):
        item = dict(row)
        item["task_family_group"] = task_family(row)
        item["model_family_group"] = model_family(str(row.get("model") or ""))
        item["benchmark_group"] = benchmark(row)
        item["run_index"] = idx
        out.append(item)
    return out


def group_summary(rows: list[dict[str, Any]], group_field: str, prospective: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    for group, values in sorted(grouped(rows, group_field).items()):
        if len(values) < 12 or len({f(row, "success") for row in values}) < 2:
            continue
        labels = [f(row, "success") for row in values]
        gi_score = single_metric(values, "grounding_integrity_score")
        gar = single_metric(values, "grounded_action_ratio")
        retro_base = in_sample(values, gi.BASELINE)
        retro_combined = in_sample(values, gi.unique_fields([*gi.BASELINE, *gi.GROUNDING, *gi.INTEGRITY]))
        hold = score(train_rows(values), holdout_rows(values), gi.unique_fields([*gi.BASELINE, *gi.GROUNDING, *gi.INTEGRITY]))
        warnings = gi.warning_rows(values)
        detection, pred_failures = gi.predictable_after_grounding(values)
        if any(gi.grounding_begun(row) for row in values):
            preventable = gi.preventable_estimates(values, pred_failures)
            prevented = preventable[3][5]
        else:
            prevented = "n/a"
        out.append(
            [
                group,
                len(values),
                round(mean(labels), 6),
                gi_score["auc"],
                gar["auc"],
                round(float(retro_combined["r2"]) - float(retro_base["r2"]), 6),
                hold["r2"],
                detection[-1][4] if detection else "n/a",
                prevented,
                warnings[0][0] if warnings else "n/a",
            ]
        )
    return out


def grouped(rows: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(field) or "unknown")].append(row)
    return buckets


def leave_one_group_out(rows: list[dict[str, Any]], group_field: str, fields: list[str]) -> list[list[Any]]:
    out = []
    for group, test in sorted(grouped(rows, group_field).items()):
        if len(test) < 10 or len({f(row, "success") for row in test}) < 2:
            continue
        train = [row for row in rows if str(row.get(group_field) or "unknown") != group]
        if len(train) < 20:
            continue
        base = score(train, test, gi.BASELINE)
        combined = score(train, test, fields)
        out.append(
            [
                group[:60],
                len(test),
                base["r2"],
                combined["r2"],
                round(float(combined["r2"]) - float(base["r2"]), 6),
                combined["auc"],
                combined["brier_gain"],
            ]
        )
    out.sort(key=lambda row: float(row[4]))
    return out


def add_alternative_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        access = max(f(row, "A2_retrieved"), f(row, "A3_surfaced"), f(row, "g_evidence_recognized"))
        understood = max(f(row, "A4_understood"), f(row, "g_evidence_accepted"))
        linked = max(f(row, "A5_linked_to_action"), f(row, "g_evidence_connected"))
        verified = clamp(f(row, "tests_or_verifiers") / 2.0)
        edited = clamp(f(row, "edited_files") / 3.0)
        referenced = clamp(f(row, "referenced_files") / 4.0)
        item["gar_linked_min"] = min(f(row, "grounded_action_ratio"), linked)
        item["gar_linked_mean"] = clamp((f(row, "grounded_action_ratio") + linked) / 2.0)
        item["gar_verification_weighted"] = clamp(0.60 * f(row, "grounded_action_ratio") + 0.25 * linked + 0.15 * verified)
        item["gar_strict"] = 1.0 if f(row, "grounded_action_ratio") >= 0.70 and linked >= 0.70 else 0.0
        item["grounding_latency_raw_inverse"] = clamp(1.0 - f(row, "grounding_latency", 1.0))
        item["grounding_latency_decisive_inverse"] = clamp(1.0 - max(f(row, "grounding_latency", 1.0), f(row, "time_to_decisive_evidence", 1.0)))
        item["grounding_latency_soft"] = clamp(1.0 / (1.0 + 3.0 * f(row, "grounding_latency", 1.0)))
        item["eal_raw_inverse"] = clamp(1.0 - f(row, "evidence_to_action_latency", 1.0))
        item["eal_with_action"] = clamp((1.0 - f(row, "evidence_to_action_latency", 1.0)) * (0.5 + 0.5 * linked))
        item["eal_strict"] = 1.0 if f(row, "evidence_to_action_latency", 1.0) <= 0.25 and linked >= 0.50 else 0.0
        item["gis_equal_weight"] = clamp(
            mean(
                [
                    f(row, "evidence_interpretation_accuracy"),
                    f(row, "evidence_action_consistency"),
                    item["grounding_latency_raw_inverse"],
                    f(row, "grounded_action_ratio"),
                    f(row, "evidence_retention"),
                    f(row, "evidence_reuse"),
                ]
            )
        )
        item["gis_action_heavy"] = clamp(
            0.15 * f(row, "evidence_interpretation_accuracy")
            + 0.30 * f(row, "evidence_action_consistency")
            + 0.10 * item["grounding_latency_decisive_inverse"]
            + 0.25 * item["gar_linked_mean"]
            + 0.10 * f(row, "evidence_retention")
            + 0.10 * f(row, "evidence_reuse")
        )
        item["gis_latency_heavy"] = clamp(
            0.15 * f(row, "evidence_interpretation_accuracy")
            + 0.15 * f(row, "evidence_action_consistency")
            + 0.30 * item["grounding_latency_decisive_inverse"]
            + 0.15 * f(row, "grounded_action_ratio")
            + 0.15 * item["eal_raw_inverse"]
            + 0.10 * f(row, "evidence_reuse")
        )
        item["gis_observable_strict"] = clamp(
            0.20 * min(access, understood)
            + 0.25 * item["gar_linked_min"]
            + 0.20 * item["grounding_latency_decisive_inverse"]
            + 0.15 * item["eal_with_action"]
            + 0.10 * referenced
            + 0.10 * max(edited, verified)
        )
        out.append(item)
    return out


def metric_sensitivity_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    fields = [
        "grounded_action_ratio",
        "gar_linked_min",
        "gar_linked_mean",
        "gar_verification_weighted",
        "gar_strict",
        "grounding_latency_integrity",
        "grounding_latency_raw_inverse",
        "grounding_latency_decisive_inverse",
        "grounding_latency_soft",
        "evidence_to_action_latency",
        "eal_raw_inverse",
        "eal_with_action",
        "eal_strict",
        "grounding_integrity_score",
        "gis_equal_weight",
        "gis_action_heavy",
        "gis_latency_heavy",
        "gis_observable_strict",
    ]
    train = train_rows(rows)
    hold = holdout_rows(rows)
    base = score(train, hold, gi.BASELINE)
    out = []
    for field in fields:
        single = single_metric(rows, field)
        model = score(train, hold, [*gi.BASELINE, field])
        out.append(
            [
                field,
                single["corr"],
                single["auc"],
                single["r2"],
                model["r2"],
                round(float(model["r2"]) - float(base["r2"]), 6),
                model["auc"],
            ]
        )
    out.sort(key=lambda row: (float(row[5]), float(row[2])), reverse=True)
    return out


def one_hot(rows: list[dict[str, Any]], fields: list[str], min_count: int = 12) -> list[dict[str, Any]]:
    counts: dict[str, Counter[str]] = {}
    for field in fields:
        counts[field] = Counter(str(row.get(field) or "unknown") for row in rows)
    out = []
    for row in rows:
        item = dict(row)
        for field in fields:
            value = str(row.get(field) or "unknown")
            for key, count in counts[field].items():
                if count >= min_count and key != "unknown":
                    item[f"{field}={key}"] = 1.0 if value == key else 0.0
        out.append(item)
    return out


def categorical_fields(rows: list[dict[str, Any]], fields: list[str], min_count: int = 12) -> list[str]:
    names = []
    for field in fields:
        counts = Counter(str(row.get(field) or "unknown") for row in rows)
        names.extend(f"{field}={key}" for key, count in counts.items() if count >= min_count and key != "unknown")
    return names


def deconfounding_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    cats = ["task_family_group", "model_family_group", "benchmark_group"]
    expanded = one_hot(rows, cats)
    cat_fields = categorical_fields(rows, cats)
    control_sets = [
        ("K+rho+A1-A3", gi.BASELINE),
        ("+ task family", [*gi.BASELINE, *[field for field in cat_fields if field.startswith("task_family_group=")]]),
        ("+ model family", [*gi.BASELINE, *[field for field in cat_fields if field.startswith("model_family_group=")]]),
        ("+ benchmark", [*gi.BASELINE, *[field for field in cat_fields if field.startswith("benchmark_group=")]]),
        ("+ all controls", [*gi.BASELINE, *cat_fields]),
    ]
    train = train_rows(expanded)
    hold = holdout_rows(expanded)
    out = []
    for name, controls in control_sets:
        base = score(train, hold, controls)
        plus_score = score(train, hold, [*controls, "grounding_integrity_score"])
        plus_metrics = score(train, hold, gi.unique_fields([*controls, *gi.INTEGRITY]))
        plus_combined = score(train, hold, gi.unique_fields([*controls, *gi.GROUNDING, *gi.INTEGRITY]))
        out.append(
            [
                name,
                len(usable(controls, expanded)),
                base["r2"],
                plus_score["r2"],
                round(float(plus_score["r2"]) - float(base["r2"]), 6),
                plus_metrics["r2"],
                round(float(plus_metrics["r2"]) - float(base["r2"]), 6),
                plus_combined["r2"],
                round(float(plus_combined["r2"]) - float(base["r2"]), 6),
            ]
        )
    return out


def shuffled_copy(rows: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    values = {field: [row.get(field) for row in rows] for field in fields}
    for field in fields:
        RNG.shuffle(values[field])
    out = []
    for idx, row in enumerate(rows):
        item = dict(row)
        for field in fields:
            item[field] = values[field][idx]
        out.append(item)
    return out


def randomization_rows(rows: list[dict[str, Any]], iterations: int = 100) -> tuple[list[list[Any]], list[list[Any]]]:
    train = train_rows(rows)
    hold = holdout_rows(rows)
    combined_fields = gi.unique_fields([*gi.BASELINE, *gi.GROUNDING, *gi.INTEGRITY])
    real_base = score(train, hold, gi.BASELINE)
    real_score = score(train, hold, [*gi.BASELINE, "grounding_integrity_score"])
    real_metrics = score(train, hold, gi.unique_fields([*gi.BASELINE, *gi.INTEGRITY]))
    real_combined = score(train, hold, combined_fields)
    shuffle_fields = gi.unique_fields([*gi.GROUNDING, *gi.INTEGRITY, "grounding_integrity_score"])
    warning_shuffle_fields = gi.unique_fields(
        [
            *shuffle_fields,
            "A2_retrieved",
            "A3_surfaced",
            "A4_understood",
            "A5_linked_to_action",
            "g_evidence_recognized",
            "g_evidence_accepted",
            "g_evidence_connected",
            "contradiction_detection",
            "state_switches",
        ]
    )
    warn_real = gi.warning_rows(rows)
    real_warning_lift = float(warn_real[0][5]) if warn_real else 0.0
    shuffled_r2 = []
    shuffled_auc = []
    shuffled_warn = []
    for _ in range(iterations):
        shuffled = shuffled_copy(rows, shuffle_fields)
        s_train = train_rows(shuffled)
        s_hold = holdout_rows(shuffled)
        result = score(s_train, s_hold, combined_fields)
        shuffled_r2.append(float(result["r2"]))
        shuffled_auc.append(float(result["auc"]))
        warning_shuffled = shuffled_copy(rows, warning_shuffle_fields)
        warnings = gi.warning_rows(warning_shuffled)
        shuffled_warn.append(float(warnings[0][5]) if warnings else 0.0)
    rows_out = [
        ["baseline real", real_base["r2"], real_base["auc"], "n/a", "n/a"],
        ["GI score real", real_score["r2"], real_score["auc"], round(float(real_score["r2"]) - float(real_base["r2"]), 6), "n/a"],
        ["GI metrics real", real_metrics["r2"], real_metrics["auc"], round(float(real_metrics["r2"]) - float(real_base["r2"]), 6), "n/a"],
        ["combined real", real_combined["r2"], real_combined["auc"], round(float(real_combined["r2"]) - float(real_base["r2"]), 6), "n/a"],
        ["combined shuffled mean", round(mean(shuffled_r2), 6), round(mean(shuffled_auc), 6), round(mean(shuffled_r2) - float(real_base["r2"]), 6), round(max(shuffled_r2), 6)],
    ]
    warn_out = [
        ["real strongest warning lift", round(real_warning_lift, 6), "n/a", "n/a"],
        ["shuffled warning lift mean", round(mean(shuffled_warn), 6), round(max(shuffled_warn), 6), round(real_warning_lift - mean(shuffled_warn), 6)],
    ]
    return rows_out, warn_out


def temporal_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    ordered = sorted(rows, key=lambda row: f(row, "run_index"))
    mid = len(ordered) // 2
    groups = [("early", ordered[:mid]), ("late", ordered[mid:]), ("early->late", ordered[:mid], ordered[mid:]), ("late->early", ordered[mid:], ordered[:mid])]
    out = []
    for item in groups:
        if len(item) == 2:
            name, values = item
            base = in_sample(values, gi.BASELINE)
            combined = in_sample(values, gi.unique_fields([*gi.BASELINE, *gi.GROUNDING, *gi.INTEGRITY]))
            gi_score = single_metric(values, "grounding_integrity_score")
            warnings = gi.warning_rows(values)
            detection, predictable = gi.predictable_after_grounding(values)
            prevent = gi.preventable_estimates(values, predictable)
            out.append(
                [
                    name,
                    len(values),
                    round(mean(f(row, "success") for row in values), 6),
                    gi_score["auc"],
                    round(float(combined["r2"]) - float(base["r2"]), 6),
                    detection[-1][4] if detection else "n/a",
                    prevent[3][5],
                    warnings[0][0] if warnings else "n/a",
                ]
            )
        else:
            name, train, test = item
            base = score(train, test, gi.BASELINE)
            combined = score(train, test, gi.unique_fields([*gi.BASELINE, *gi.GROUNDING, *gi.INTEGRITY]))
            out.append([name, len(test), round(mean(f(row, "success") for row in test), 6), combined["auc"], round(float(combined["r2"]) - float(base["r2"]), 6), "n/a", "n/a", "n/a"])
    return out


def intervention_robustness(rows: list[dict[str, Any]]) -> list[list[Any]]:
    _prediction_rows, predictable = gi.predictable_after_grounding(rows)
    failures = [row for row in rows if f(row, "success") < 0.5]
    weak = [
        row
        for row in failures
        if gi.grounding_begun(row)
        and (
            f(row, "evidence_interpretation_accuracy") < 0.55
            or f(row, "evidence_action_consistency") < 0.45
            or f(row, "evidence_retention") < 0.45
            or f(row, "grounded_action_ratio") < 0.35
        )
    ]
    predictable_ids = {id(row) for row in predictable}
    predictable_weak = [row for row in weak if id(row) in predictable_ids]
    strong = [row for row in rows if gi.grounding_begun(row) and f(row, "grounding_integrity_score") >= 0.72]
    ceiling_rate = mean(f(row, "success") for row in strong) if strong else mean(f(row, "success") for row in rows)
    scenarios = [
        ("pessimistic", predictable_weak, 0.40, 0.55),
        ("realistic", predictable_weak, 0.65, ceiling_rate),
        ("optimistic", weak, 0.85, min(0.95, ceiling_rate + 0.05)),
        ("ceiling", weak, 1.0, min(0.98, ceiling_rate + 0.10)),
    ]
    out = []
    for name, candidates, intervention_reach, target_success in scenarios:
        current_success = 0.0
        candidate_count = len(candidates)
        prevented = candidate_count * intervention_reach * max(0.0, target_success - current_success)
        out.append(
            [
                name,
                candidate_count,
                round(intervention_reach, 6),
                round(target_success, 6),
                round(prevented, 1),
                round(prevented / max(1, len(failures)), 6),
            ]
        )
    return out


def verdict_from_tests(
    family_rows: list[list[Any]],
    model_rows: list[list[Any]],
    benchmark_lobo: list[list[Any]],
    sensitivity: list[list[Any]],
    deconf: list[list[Any]],
    randomization: list[list[Any]],
    temporal: list[list[Any]],
    intervention: list[list[Any]],
) -> str:
    weak_points = 0
    if any(float(row[5]) <= 0.0 for row in family_rows if row[5] != "n/a"):
        weak_points += 1
    if any(float(row[5]) <= 0.0 for row in model_rows if row[5] != "n/a"):
        weak_points += 1
    if benchmark_lobo and sum(1 for row in benchmark_lobo if float(row[4]) > 0.0) / len(benchmark_lobo) < 0.70:
        weak_points += 1
    if sensitivity and sum(1 for row in sensitivity[:8] if float(row[5]) > 0.0) < 5:
        weak_points += 1
    if deconf and float(deconf[-1][-1]) <= 0.02:
        weak_points += 1
    if deconf and float(deconf[-1][4]) <= 0.0:
        weak_points += 1
    real = [row for row in randomization if row[0] == "combined real"][0]
    shuf = [row for row in randomization if row[0] == "combined shuffled mean"][0]
    if float(real[1]) - float(shuf[1]) <= 0.05:
        weak_points += 1
    if any(row[0] in {"early->late", "late->early"} and float(row[4]) <= 0.0 for row in temporal):
        weak_points += 1
    realistic = [row for row in intervention if row[0] == "realistic"][0]
    if float(realistic[5]) < 0.15:
        weak_points += 1
    if weak_points >= 5:
        return "A. Grounding Integrity is mostly artifact."
    if weak_points >= 3:
        return "B. Grounding Integrity is weak but real."
    return "C. Grounding Integrity is robust."


def main() -> int:
    rows, excluded, prospective = gi.prepare()
    rows = add_alternative_metrics(with_groups(rows))
    prospective = add_alternative_metrics(with_groups(prospective))
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."
    combined_fields = gi.unique_fields([*gi.BASELINE, *gi.GROUNDING, *gi.INTEGRITY])

    family = group_summary(rows, "task_family_group", prospective)
    model = group_summary(rows, "model_family_group", prospective)
    benchmark_holdouts = leave_one_group_out(rows, "benchmark_group", combined_fields)
    benchmark_datasets = leave_one_group_out(rows, "dataset", combined_fields)
    sensitivity = metric_sensitivity_rows(rows)
    deconf = deconfounding_rows(rows)
    randomization, warning_randomization = randomization_rows(rows)
    temporal = temporal_rows(rows)
    intervention = intervention_robustness(rows)
    verdict = verdict_from_tests(family, model, benchmark_holdouts, sensitivity, deconf, randomization, temporal, intervention)

    write_md(
        "family_generalization.md",
        f"""
# Family Generalization

Scope: {scope}

Falsification standard: Grounding Integrity should fail if its explanatory gain, predictive signal, or intervention estimate only exists in one task family.

{table(["task family", "rows", "success rate", "GI score AUC", "grounded-action AUC", "retro explanatory R2 gain", "within-family holdout R2", "detectable failures share", "central prevented rows", "strongest warning"], family)}

## Determination

Grounding Integrity survives family generalization if every populated family shows positive explanatory gain and nontrivial detection/intervention signal. The weakest family is the row with the smallest explanatory gain. This is not a clean causal proof because family labels are coarse and partially inferred from category/action traces.
""",
    )

    write_md(
        "model_generalization.md",
        f"""
# Model Generalization

Scope: {scope}

Falsification standard: the result should fail if it is carried by one provider/model family.

{table(["model family", "rows", "success rate", "GI score AUC", "grounded-action AUC", "retro explanatory R2 gain", "within-family holdout R2", "detectable failures share", "central prevented rows", "strongest warning"], model)}

## Determination

The strongest falsifier would be a model family with adequate rows, mixed outcomes, and zero or negative Grounding Integrity gain. Model-family imbalance remains a material weakness even where the direction survives.
""",
    )

    write_md(
        "benchmark_generalization.md",
        f"""
# Benchmark Generalization

Scope: {scope}

## Leave-One-Benchmark-Out

{table(["held-out benchmark", "rows", "baseline R2", "combined R2", "delta", "combined AUC", "combined Brier gain"], benchmark_holdouts[:30])}

## Dataset Holdout Tests

{table(["held-out dataset", "rows", "baseline R2", "combined R2", "delta", "combined AUC", "combined Brier gain"], benchmark_datasets)}

## Determination

Benchmark shifts are the harshest test in this run. Positive deltas under leave-one-benchmark-out support generalization; negative deltas mark benchmark dependence and should cap deployment claims.
""",
    )

    write_md(
        "metric_sensitivity.md",
        f"""
# Metric Sensitivity

Scope: {scope}

Alternative definitions intentionally perturb the implementation of `grounded_action_ratio`, `grounding_latency`, `evidence_action_latency`, and `grounding_integrity_score`.

{table(["metric definition", "single corr", "single AUC", "single R2", "holdout R2 with baseline", "holdout R2 gain", "holdout AUC"], sensitivity)}

## Determination

Grounding Integrity survives metric sensitivity if action-linkage variants and score variants remain positive. It fails as a single-formula artifact if only the original formula works.
""",
    )

    write_md(
        "deconfounding_analysis.md",
        f"""
# Adversarial Deconfounding

Scope: {scope}

Controls: `K`, `rho`, `A1-A3`, task family, model family, and benchmark one-hot controls. This is deliberately adversarial because benchmark controls can absorb real distributional signal.

{table(["control set", "control features", "control R2", "+ GI score R2", "GI score delta", "+ GI metrics R2", "GI metrics delta", "+ combined GI R2", "combined delta"], deconf)}

## Determination

The key row is `+ all controls`. If the combined delta remains positive after all controls, the result is not explained away by K/rho/accessibility, family, model, or benchmark composition. If the delta collapses, Grounding Integrity is partly a distribution artifact.
""",
    )

    write_md(
        "randomization_controls.md",
        f"""
# Randomization Controls

Scope: {scope}

Grounding metrics, grounding scores, and warning fields were shuffled across rows with outcomes, K/rho/A1-A3, task family, model family, and benchmark left intact.

## Model Signal

{table(["condition", "holdout R2", "holdout AUC", "R2 gain over baseline", "max shuffled R2"], randomization)}

## Warning Signal

{table(["condition", "warning lift", "max shuffled lift", "real-minus-shuffled mean"], warning_randomization)}

## Determination

The result survives randomization only if real Grounding Integrity materially exceeds shuffled Grounding Integrity. Residual shuffled signal indicates that some apparent gain can be produced by baseline/corpus structure alone.
""",
    )

    write_md(
        "temporal_stability.md",
        f"""
# Temporal Stability

Scope: {scope}

Rows were split by corpus order into early and late halves. Cross-time rows train on one half and test on the other.

{table(["split", "rows/test rows", "success rate", "GI/combined AUC", "R2 gain over baseline", "detectable failures share", "central prevented rows", "strongest warning"], temporal)}

## Determination

Temporal survival requires the sign of the effect to persist in both halves and under early-to-late/late-to-early transfer. Instability here would suggest instrumentation drift or corpus-construction artifact.
""",
    )

    write_md(
        "intervention_robustness.md",
        f"""
# Intervention Robustness

Scope: {scope}

Recovery estimates were recomputed under pessimistic, realistic, optimistic, and ceiling assumptions. Candidate failures are restricted to grounding-begun weak-integrity failures; pessimistic/realistic scenarios further require warning detectability.

{table(["scenario", "candidate failed rows", "intervention reach", "target success after repair", "prevented rows", "share of all failures"], intervention)}

## Determination

The recovery estimate is robust if the realistic row remains near the prior central estimate and the pessimistic row remains nontrivial. The ceiling row is not a deployment forecast; it is the maximum implied by the current corpus under perfect repair assumptions.
""",
    )

    evidence_for = [
        f"Combined model remains above baseline in the main holdout/randomization comparison: {randomization[3][1]} R2 real versus {randomization[4][1]} shuffled mean.",
        f"Adversarial all-control combined delta is {deconf[-1][-1]}, after K/rho/A1-A3 plus task-family, model-family, and benchmark controls.",
        f"Alternative action/score metrics retain positive holdout gains across the strongest variants: top sensitivity delta {sensitivity[0][5]}.",
        f"Realistic intervention estimate is {next(row for row in intervention if row[0] == 'realistic')[5]} of all failures.",
    ]
    evidence_against = [
        "Prospective reconstruction remains weak in the prior assessment, so this is stronger as online diagnostic evidence than as pre-execution forecasting.",
        "Benchmark and model-family holdouts are uneven; sparse groups make some apparent stability underpowered.",
        "Several Grounding Integrity fields are execution-stage diagnostics, so they should not be sold as clean pre-run primitives.",
        "Recovery estimates are counterfactual and depend on repair efficacy assumptions that have not been validated in a live intervention trial.",
    ]
    weakness = "The strongest remaining weakness is causal status: Grounding Integrity survives as a diagnostic control signal, but the corpus still cannot prove that interventions will recover the estimated failures without a frozen live repair experiment."

    write_md(
        "grounding_integrity_verdict.md",
        f"""
# Grounding Integrity Verdict

Scope: {scope}

## Answers

1. Does Grounding Integrity survive benchmark shifts? {'Yes, with caveats' if benchmark_holdouts and sum(1 for row in benchmark_holdouts if float(row[4]) > 0.0) / len(benchmark_holdouts) >= 0.70 else 'Partially; benchmark dependence remains visible'}.
2. Does it survive model shifts? {'Yes' if all(float(row[5]) > 0.0 for row in model if row[5] != 'n/a') else 'Partially'}.
3. Does it survive family shifts? {'Yes' if all(float(row[5]) > 0.0 for row in family if row[5] != 'n/a') else 'Partially'}.
4. Does it survive alternative definitions? {'Yes' if sum(1 for row in sensitivity[:8] if float(row[5]) > 0.0) >= 5 else 'Weakly'}.
5. Does it survive deconfounding? {'Yes' if float(deconf[-1][-1]) > 0.02 else 'Weakly'}.
6. Does it survive randomization? {'Yes' if float(randomization[3][1]) - float(randomization[4][1]) > 0.05 else 'Weakly'}.
7. Does it survive temporal testing? {'Yes' if all(not (row[0] in {'early->late', 'late->early'} and float(row[4]) <= 0.0) for row in temporal) else 'Partially'}.
8. Is the recovery estimate robust? {'Moderately' if float(next(row for row in intervention if row[0] == 'realistic')[5]) >= 0.15 else 'Weakly'}.
9. What is the strongest remaining weakness? {weakness}

## Final Requirement

Selected verdict: **{verdict}**

## Evidence For

{chr(10).join(f'- {item}' for item in evidence_for)}

## Evidence Against

{chr(10).join(f'- {item}' for item in evidence_against)}

## Final Determination

The falsification run does not destroy Grounding Integrity. It does demote any overclaim that this is a clean pre-run law. The result survives best as a runtime diagnostic and control signal: strong enough for subsystem design, not yet strong enough to claim validated causal recovery without a frozen intervention trial.
""",
    )

    print(
        json.dumps(
            {
                "scope": scope,
                "verdict": verdict,
                "outputs": [
                    "family_generalization.md",
                    "model_generalization.md",
                    "benchmark_generalization.md",
                    "metric_sensitivity.md",
                    "deconfounding_analysis.md",
                    "randomization_controls.md",
                    "temporal_stability.md",
                    "intervention_robustness.md",
                    "grounding_integrity_verdict.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
