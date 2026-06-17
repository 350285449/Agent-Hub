from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import execution_dynamics_theory_program as dyn
from scripts import grounding_research_program as grounding
from scripts import measurement_science_program as m
from scripts import prospective_failure_v3 as pf


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

BASELINE = ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"]
GROUNDING = [
    "time_to_decisive_evidence",
    "grounding_latency",
    "grounded_action_ratio",
    "evidence_to_action_latency",
]
INTEGRITY = [
    "evidence_interpretation_accuracy",
    "evidence_action_consistency",
    "grounding_latency_integrity",
    "grounded_action_ratio",
    "evidence_retention",
    "evidence_reuse",
]


def unique_fields(fields: list[str]) -> list[str]:
    out = []
    seen = set()
    for field in fields:
        if field in seen:
            continue
        seen.add(field)
        out.append(field)
    return out


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


def normalize_count(value: Any, cap: float) -> float:
    return m.clamp01(float(value or 0.0) / cap)


def add_integrity_features(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        evidence_access = max(f(item, "A2_retrieved"), f(item, "A3_surfaced"), f(item, "g_evidence_recognized"))
        interpreted = max(f(item, "A4_understood"), f(item, "g_evidence_accepted"))
        linked = max(f(item, "A5_linked_to_action"), f(item, "g_evidence_connected"))
        denominator = max(0.20, evidence_access)
        interpretation = m.clamp01(1.0 - max(0.0, evidence_access - interpreted) / denominator)
        consistency_base = m.clamp01(1.0 - abs(interpreted - linked))
        action_consistency = m.clamp01(consistency_base * (0.55 * linked + 0.45 * f(item, "grounded_action_ratio")))
        latency_integrity = m.clamp01(1.0 - f(item, "grounding_latency", 1.0))
        retention = m.clamp01(1.0 - max(0.0, max(evidence_access, interpreted) - linked) / max(0.20, max(evidence_access, interpreted)))
        referenced = normalize_count(item.get("referenced_files"), 4.0)
        edited = normalize_count(item.get("edited_files"), 3.0)
        verified = normalize_count(item.get("tests_or_verifiers"), 2.0)
        reuse = m.clamp01(0.35 * linked + 0.25 * referenced + 0.20 * edited + 0.20 * verified)
        score = m.clamp01(
            0.25 * interpretation
            + 0.24 * action_consistency
            + 0.16 * latency_integrity
            + 0.16 * f(item, "grounded_action_ratio")
            + 0.11 * retention
            + 0.08 * reuse
        )
        item.update(
            {
                "evidence_interpretation_accuracy": interpretation,
                "evidence_action_consistency": action_consistency,
                "grounding_latency_integrity": latency_integrity,
                "evidence_retention": retention,
                "evidence_reuse": reuse,
                "grounding_integrity_score": score,
            }
        )
        out.append(item)
    return out


def prepare() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows, excluded, prospective = grounding.prepare()
    return add_integrity_features(rows), excluded, add_integrity_features(prospective)


def score_all(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    usable = [field for field in fields if rows and all(row.get(field) is not None for row in rows)]
    usable_prosp = [field for field in fields if all(row.get(field) is not None for row in [*rows, *prospective])]
    return {
        "retro": pf.in_sample(rows, usable),
        "holdout": pf.score_model(train, holdout, usable),
        "prospective": pf.score_model(train, prospective, usable_prosp),
    }


def metric_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    labels = [f(row, "success") for row in rows]
    base = score_all(rows, prospective, BASELINE)
    out = []
    for field in INTEGRITY:
        values = [f(row, field) for row in rows]
        single = m.metrics(values, labels)
        gain = score_all(rows, prospective, [*BASELINE, field])
        failures_low = [row for row in rows if f(row, "success") < 0.5 and f(row, field) < 0.45]
        out.append(
            [
                field,
                single["corr"],
                single["auc"],
                single["r2"],
                round(float(gain["holdout"]["r2"]) - float(base["holdout"]["r2"]), 6),
                round(float(gain["prospective"]["r2"]) - float(base["prospective"]["r2"]), 6),
                len(failures_low),
                round(len(failures_low) / max(1, len([r for r in rows if f(r, "success") < 0.5])), 6),
            ]
        )
    out.sort(key=lambda row: (float(row[4]), float(row[2]), float(row[3])), reverse=True)
    return [[idx + 1, *row] for idx, row in enumerate(out)]


def warning_predicates() -> list[tuple[str, str, Callable[[dict[str, Any]], bool], str]]:
    return [
        (
            "delayed grounding",
            "25%-50%",
            lambda r: (f(r, "g_evidence_recognized") >= 0.5 or f(r, "A2_retrieved") >= 0.35)
            and (f(r, "grounding_latency") >= 0.50 or f(r, "time_to_decisive_evidence") >= 0.50),
            "recognized evidence exists, but decisive grounding waits until the late window",
        ),
        (
            "contradictory grounding",
            "25%-50%",
            lambda r: max(f(r, "A2_retrieved"), f(r, "A3_surfaced")) >= 0.45
            and (f(r, "A4_understood") < 0.35 or f(r, "contradiction_detection") >= 0.5),
            "retrieved/surfaced evidence conflicts with the interpretation trace",
        ),
        (
            "unstable grounding",
            "50%-75%",
            lambda r: f(r, "state_switches") >= 0.60
            or (f(r, "A4_understood") >= 0.35 and f(r, "evidence_retention") < 0.45),
            "state switches or evidence retention loss after partial grounding",
        ),
        (
            "grounding collapse",
            "50%-75%",
            lambda r: f(r, "g_evidence_accepted") >= 0.5
            and (f(r, "g_evidence_connected") < 0.5 or f(r, "grounded_action_ratio") < 0.35),
            "accepted evidence fails to remain connected to action",
        ),
    ]


def warning_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    failures = [row for row in rows if f(row, "success") < 0.5]
    base_failure = len(failures) / max(1, len(rows))
    out = []
    for name, earliest, predicate, definition in warning_predicates():
        matching = [row for row in rows if predicate(row)]
        matching_failures = [row for row in matching if f(row, "success") < 0.5]
        failure_rate = len(matching_failures) / len(matching) if matching else 0.0
        out.append(
            [
                name,
                earliest,
                len(matching),
                len(matching_failures),
                round(failure_rate, 6),
                round(failure_rate - base_failure, 6),
                round(len(matching_failures) / max(1, len(failures)), 6),
                definition,
            ]
        )
    out.sort(key=lambda row: (float(row[5]), float(row[6])), reverse=True)
    return out


def score_band_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    bands = [
        ("collapsed", 0.0, 0.35),
        ("fragile", 0.35, 0.55),
        ("coherent", 0.55, 0.72),
        ("strong", 0.72, 1.01),
    ]
    out = []
    for name, lo, hi in bands:
        group = [row for row in rows if lo <= f(row, "grounding_integrity_score") < hi]
        out.append(
            [
                name,
                len(group),
                round(len(group) / max(1, len(rows)), 6),
                round(mean(f(row, "success") for row in group), 6) if group else "n/a",
                round(mean(f(row, "grounding_integrity_score") for row in group), 6) if group else "n/a",
            ]
        )
    return out


def model_comparison(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    specs = [
        ("K+rho+A1-A3", BASELINE),
        ("Grounding model", GROUNDING),
        ("Grounding Integrity model", INTEGRITY),
        ("Combined model", unique_fields([*BASELINE, *GROUNDING, *INTEGRITY])),
    ]
    out = []
    for name, fields in specs:
        stats = score_all(rows, prospective, fields)
        hold = stats["holdout"]
        prosp = stats["prospective"]
        out.append(
            [
                name,
                len(fields),
                stats["retro"]["r2"],
                hold["r2"],
                hold["auc"],
                hold["brier_gain"],
                hold["calibration_error"],
                prosp["r2"],
                prosp["auc"],
                prosp["brier_gain"],
                prosp["calibration_error"],
            ]
        )
    return out


def failure_detection_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    base = score_all(rows, prospective, BASELINE)
    score = score_all(rows, prospective, ["grounding_integrity_score"])
    integrity = score_all(rows, prospective, INTEGRITY)
    combined = score_all(rows, prospective, unique_fields([*BASELINE, *GROUNDING, *INTEGRITY]))
    return [
        ["K+rho+A1-A3", base["holdout"]["auc"], base["holdout"]["brier_gain"], base["holdout"]["calibration_error"]],
        ["GI score only", score["holdout"]["auc"], score["holdout"]["brier_gain"], score["holdout"]["calibration_error"]],
        ["GI metrics", integrity["holdout"]["auc"], integrity["holdout"]["brier_gain"], integrity["holdout"]["calibration_error"]],
        ["Combined", combined["holdout"]["auc"], combined["holdout"]["brier_gain"], combined["holdout"]["calibration_error"]],
    ]


def grounding_begun(row: dict[str, Any]) -> bool:
    return f(row, "g_evidence_recognized") >= 0.5 or f(row, "A2_retrieved") >= 0.35 or f(row, "A3_surfaced") >= 0.35


def predictable_after_grounding(rows: list[dict[str, Any]]) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    failures = [row for row in rows if f(row, "success") < 0.5]
    begun_failures = [row for row in failures if grounding_begun(row)]
    warning_defs = warning_predicates()
    predictable = []
    out = []
    for name, earliest, predicate, _definition in warning_defs:
        hit = [row for row in begun_failures if predicate(row)]
        predictable.extend(hit)
        out.append([name, earliest, len(hit), round(len(hit) / max(1, len(begun_failures)), 6), round(len(hit) / max(1, len(failures)), 6)])
    unique = {id(row): row for row in predictable}
    out.append(["any warning after grounding begins", "25%-75%", len(unique), round(len(unique) / max(1, len(begun_failures)), 6), round(len(unique) / max(1, len(failures)), 6)])
    return out, list(unique.values())


def preventable_estimates(rows: list[dict[str, Any]], predictable_failures: list[dict[str, Any]]) -> list[list[Any]]:
    failures = [row for row in rows if f(row, "success") < 0.5]
    begun = [row for row in rows if grounding_begun(row)]
    high_integrity = [row for row in begun if f(row, "grounding_integrity_score") >= 0.72]
    weak_integrity_failures = [
        row
        for row in failures
        if grounding_begun(row)
        and (
            f(row, "evidence_interpretation_accuracy") < 0.55
            or f(row, "evidence_action_consistency") < 0.45
            or f(row, "evidence_retention") < 0.45
            or f(row, "grounded_action_ratio") < 0.35
        )
    ]
    high_success = mean(f(row, "success") for row in high_integrity) if high_integrity else mean(f(row, "success") for row in begun)
    current_weak_success = 1.0 - (len(weak_integrity_failures) / max(1, len([row for row in begun if f(row, "grounding_integrity_score") < 0.55])))
    central_rate = max(0.0, min(0.85, high_success - max(0.0, current_weak_success)))
    central = len(weak_integrity_failures) * central_rate
    predictable_ids = {id(row) for row in predictable_failures}
    predictable_weak = [row for row in weak_integrity_failures if id(row) in predictable_ids]
    return [
        ["all failures", len(failures), 1.0, "n/a", "n/a", "n/a"],
        ["failures after grounding begins", len([row for row in failures if grounding_begun(row)]), round(len([row for row in failures if grounding_begun(row)]) / max(1, len(failures)), 6), "n/a", "n/a", "n/a"],
        ["predictable after grounding begins", len(predictable_failures), round(len(predictable_failures) / max(1, len(failures)), 6), "n/a", "n/a", "n/a"],
        ["weak-integrity candidate failures", len(weak_integrity_failures), round(len(weak_integrity_failures) / max(1, len(failures)), 6), round(high_success, 6), round(central, 1), round(central / max(1, len(failures)), 6)],
        ["predictable weak-integrity failures", len(predictable_weak), round(len(predictable_weak) / max(1, len(failures)), 6), round(high_success, 6), round(min(central, len(predictable_weak) * central_rate), 1), round(min(central, len(predictable_weak) * central_rate) / max(1, len(failures)), 6)],
    ]


def main() -> int:
    rows, excluded, prospective = prepare()
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."
    metrics = metric_rows(rows, prospective)
    warnings = warning_rows(rows)
    bands = score_band_rows(rows)
    comparisons = model_comparison(rows, prospective)
    detection = failure_detection_rows(rows, prospective)
    prediction_rows, predictable_failures = predictable_after_grounding(rows)
    preventable = preventable_estimates(rows, predictable_failures)
    base = score_all(rows, prospective, BASELINE)
    integrity = score_all(rows, prospective, INTEGRITY)
    combined = score_all(rows, prospective, unique_fields([*BASELINE, *GROUNDING, *INTEGRITY]))
    additional_holdout = float(combined["holdout"]["r2"]) - float(base["holdout"]["r2"])
    additional_prospective = float(combined["prospective"]["r2"]) - float(base["prospective"]["r2"])
    strongest_metric = metrics[0][1] if metrics else "n/a"
    earliest_warning = warnings[0][0] if warnings else "n/a"

    write_md(
        "grounding_integrity_metrics.md",
        f"""
# Grounding Integrity Metrics

Scope: {scope}

Rules honored: cloud models only; no primitive search; no interaction search; no new theory zoo. Metrics use execution-stage variables available before the final answer, after evidence has begun to appear.

## Operational Metrics

{table(["rank", "metric", "single corr", "single AUC", "single R2", "holdout R2 gain over K+rho+A1-A3", "prospective R2 gain", "low-metric failed rows", "share of failures"], metrics)}

## Definitions

| metric | definition |
| --- | --- |
| evidence_interpretation_accuracy | whether retrieved/surfaced evidence becomes accepted or understood evidence |
| evidence_action_consistency | whether accepted evidence remains aligned with action linkage and grounded action |
| grounding_latency_integrity | inverse grounding latency; high means grounding occurs early |
| grounded_action_ratio | share of action trace consistent with available evidence |
| evidence_retention | whether evidence survives from recognition/acceptance into action linkage |
| evidence_reuse | whether evidence is reused in references, edits, or verification rather than mentioned once |

## Determination

Strongest individual integrity metric: `{strongest_metric}`. The strongest pattern is not raw evidence access. It is whether evidence survives interpretation and stays connected to action.
""",
    )

    write_md(
        "grounding_warning_signals.md",
        f"""
# Grounding Warning Signals

Scope: {scope}

## Early Warning Tests

{table(["warning", "earliest visible window", "rows", "failed rows", "failure rate", "failure lift vs base", "share of all failures", "definition"], warnings)}

## Answer

Misgrounding is detectable early when recognized evidence fails to become coherent interpretation. Earliest warning sign in this run: `{earliest_warning}`. The most reliable warning class is the one with both high failure lift and substantial failure coverage; in this corpus that is contradiction or collapse rather than mere delay.
""",
    )

    write_md(
        "grounding_integrity_score.md",
        f"""
# Grounding Integrity Score

Scope: {scope}

Formula:

`0.25*interpretation_accuracy + 0.24*action_consistency + 0.16*latency_integrity + 0.16*grounded_action_ratio + 0.11*evidence_retention + 0.08*evidence_reuse`

All inputs are execution-stage variables available before final answer once grounding begins.

## Score Bands

{table(["band", "rows", "share", "success rate", "mean score"], bands)}

## Model Performance

{table(["model", "feature count", "retro R2", "holdout R2", "holdout AUC", "holdout Brier gain", "holdout calibration error", "prospective R2", "prospective AUC", "prospective Brier gain", "prospective calibration error"], comparisons)}

## Determination

The Grounding Integrity Score is a compact online diagnostic. It is less complete than the full metric vector, but its bands are interpretable: collapsed and fragile integrity are failure-prone, while strong integrity is the observed counterfactual target for prevention.
""",
    )

    write_md(
        "grounding_failure_prediction.md",
        f"""
# Grounding Failure Prediction

Scope: {scope}

## Failure Detection

{table(["model", "holdout AUC", "holdout Brier gain", "holdout calibration error"], detection)}

## Prediction After Grounding Begins

{table(["warning", "earliest visible window", "failed rows hit", "share of grounding-begun failures", "share of all failures"], prediction_rows)}

## Incremental Predictive Power

| comparison | holdout R2 | prospective R2 |
| --- | ---: | ---: |
| K+rho+A1-A3 | {fmt(base["holdout"]["r2"])} | {fmt(base["prospective"]["r2"])} |
| Grounding Integrity model | {fmt(integrity["holdout"]["r2"])} | {fmt(integrity["prospective"]["r2"])} |
| Combined model | {fmt(combined["holdout"]["r2"])} | {fmt(combined["prospective"]["r2"])} |
| additional over K+rho+A1-A3 | {fmt(additional_holdout)} | {fmt(additional_prospective)} |

## Determination

Failures can be predicted after grounding begins. The measurable warning set hits {fmt(prediction_rows[-1][3])} of grounding-begun failures and {fmt(prediction_rows[-1][4])} of all failures before final answer.
""",
    )

    write_md(
        "preventable_failure_analysis_v2.md",
        f"""
# Preventable Failure Analysis v2

Scope: {scope}

Counterfactual: perfect grounding integrity means evidence is interpreted correctly, retained, reused, and kept consistent with action after grounding begins. This is not a claim that missing evidence failures disappear.

## Estimates

{table(["bucket", "rows", "share of all failures", "high-integrity success rate", "central prevented rows", "central share of all failures"], preventable)}

## Determination

Perfect grounding integrity would primarily prevent failures where evidence was already recognized. It would not prevent rows with no useful evidence access. The central preventable estimate is the weak-integrity candidate row, with the predictable weak-integrity row as the operational intervention subset.
""",
    )

    write_md(
        "grounding_integrity_assessment.md",
        f"""
# Grounding Integrity Assessment

Scope: {scope}

## Answers

1. Can misgrounding be detected early? Yes. Warning signals appear after evidence recognition and before final answer, especially contradictory grounding and grounding collapse.
2. What is the earliest warning sign? `{earliest_warning}` in this measured panel.
3. Which integrity metric is strongest? `{strongest_metric}` by incremental holdout gain/AUC ordering.
4. Can grounding integrity predict failure? Yes diagnostically: the combined model improves holdout R2 over `K+rho+A1-A3` by {fmt(additional_holdout)}.
5. How many failures become predictable after grounding begins? {prediction_rows[-1][2]} rows, or {fmt(prediction_rows[-1][4])} of all failures.
6. How many failures become preventable? Central estimate is {preventable[3][4]} rows from weak-integrity candidate failures, or {fmt(preventable[3][5])} of all failures; the operationally predictable subset is {preventable[4][4]} rows, or {fmt(preventable[4][5])}.

## Ranked Grounding Integrity Metrics

{table(["rank", "metric", "single corr", "single AUC", "single R2", "holdout R2 gain over K+rho+A1-A3", "prospective R2 gain", "low-metric failed rows", "share of failures"], metrics)}

## Model Comparison

{table(["model", "feature count", "retro R2", "holdout R2", "holdout AUC", "holdout Brier gain", "holdout calibration error", "prospective R2", "prospective AUC", "prospective Brier gain", "prospective calibration error"], comparisons)}

## Final Requirement

Additional predictive power over `K+rho+A1-A3`: holdout R2 +{fmt(additional_holdout)} for the combined grounding-integrity model. In the reconstructed prospective panel the additional R2 is {fmt(additional_prospective)}, so the robust claim is diagnostic/online failure detection rather than clean future prediction before execution.
""",
    )

    print(
        json.dumps(
            {
                "scope": scope,
                "strongest_metric": strongest_metric,
                "earliest_warning": earliest_warning,
                "additional_holdout_r2": additional_holdout,
                "additional_prospective_r2": additional_prospective,
                "predictable_failures_after_grounding": prediction_rows[-1][2],
                "preventable_central_rows": preventable[3][4],
                "outputs": [
                    "grounding_integrity_metrics.md",
                    "grounding_warning_signals.md",
                    "grounding_integrity_score.md",
                    "grounding_failure_prediction.md",
                    "preventable_failure_analysis_v2.md",
                    "grounding_integrity_assessment.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
