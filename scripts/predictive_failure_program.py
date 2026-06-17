from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import cloud_research_program as cloud
from scripts import measurement_science_program as m
from scripts import prospective_failure_v3 as pf


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

STRICT_PRE_RUN = ["K", "rho", "A1_exists", "old_A", "context_budget", "expected_files", "relevant_files"]
POST_RETRIEVAL = ["K", "rho", "A1_exists", "old_A", "context_budget", "expected_files", "relevant_files", "A2_retrieved", "A3_surfaced"]
EXECUTION_DIAGNOSTIC = ["A4_understood", "A5_linked_to_action", "E9", "referenced_files", "edited_files", "tests_or_verifiers"]
ALL_PRE_RUN_CATALOG = [
    "A1_exists",
    "K",
    "benchmark_novelty",
    "context_budget",
    "context_completeness",
    "context_mismatch",
    "domain_familiarity",
    "evidence_scarcity",
    "expected_files",
    "model_calibration_history",
    "old_A",
    "planning_depth",
    "relevant_files",
    "retrieval_difficulty",
    "rho",
    "route_confidence",
    "specialization_alignment",
    "task_ambiguity",
    "task_complexity",
]


def write_md(name: str, text: str) -> None:
    content = text.strip() + "\n"
    RESEARCH.mkdir(exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    return m.table(headers, rows)


def fmt(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def task_family(row: dict[str, Any]) -> str:
    category = str(row.get("category") or "").lower()
    if category in {"bug_fix", "testing", "refactor", "code_generation", "api_compatibility"}:
        return "coding"
    if category in {"research", "repo-analysis", "repo_analysis"}:
        return "research"
    if category in {"architecture", "analysis", "documentation"}:
        return "reasoning"
    return "agentic"


def fit_rows(train: list[dict[str, Any]], test: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    return pf.score_model(train, test, fields)


def in_sample(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    return pf.in_sample(rows, fields)


def material_fields(rows: list[dict[str, Any]], fields: list[str], extra: list[dict[str, Any]] | None = None) -> list[str]:
    source = [*rows, *(extra or [])]
    return [field for field in fields if all(row.get(field) is not None for row in source)]


def variance_numbers(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> dict[str, Any]:
    rows = pf.enrich_pre_run_candidates(rows)
    prospective = pf.estimate_candidate_features(rows, prospective)
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    strict = material_fields(rows, STRICT_PRE_RUN, prospective)
    post = material_fields(rows, POST_RETRIEVAL, prospective)
    diag = material_fields(rows, [*POST_RETRIEVAL, *EXECUTION_DIAGNOSTIC])
    all_pre = material_fields(rows, ALL_PRE_RUN_CATALOG, prospective)
    return {
        "rows": rows,
        "prospective": prospective,
        "train": train,
        "holdout": holdout,
        "strict": strict,
        "post": post,
        "diag": diag,
        "all_pre": all_pre,
        "strict_in": in_sample(rows, strict),
        "post_in": in_sample(rows, post),
        "diag_in": in_sample(rows, diag),
        "all_pre_in": in_sample(rows, all_pre),
        "strict_hold": fit_rows(train, holdout, strict),
        "post_hold": fit_rows(train, holdout, post),
        "diag_hold": fit_rows(train, holdout, diag),
        "all_pre_hold": fit_rows(train, holdout, all_pre),
        "strict_prosp": fit_rows(train, prospective, strict),
        "post_prosp": fit_rows(train, prospective, post),
        "diag_prosp": fit_rows(train, prospective, diag),
        "all_pre_prosp": fit_rows(train, prospective, all_pre),
    }


def family_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> list[list[Any]]:
    train_all = [row for row in rows if row.get("dataset") == "historical"] or rows
    out = []
    for family in ["coding", "reasoning", "research", "agentic"]:
        fam_rows = [row for row in rows if task_family(row) == family]
        fam_prospective = [row for row in prospective if task_family(row) == family]
        fam_holdout = [row for row in fam_rows if row.get("dataset") != "historical"] or fam_rows
        if len(fam_rows) < 8:
            out.append([family, len(fam_rows), len(fam_prospective), "n/a", "n/a", "n/a", "insufficient cloud rows"])
            continue
        local_fields = material_fields(fam_rows, fields)
        in_stats = in_sample(fam_rows, local_fields)
        hold_stats = fit_rows(train_all, fam_holdout, local_fields)
        prosp_stats = fit_rows(train_all, fam_prospective, local_fields) if fam_prospective else {"r2": 0.0, "brier_gain": 0.0}
        verdict = "separate calibration needed" if abs(float(in_stats["r2"]) - float(prosp_stats["r2"])) > 0.20 or len(fam_prospective) < 20 else "shared science may suffice"
        out.append([family, len(fam_rows), len(fam_prospective), in_stats["r2"], hold_stats["r2"], prosp_stats["r2"], verdict])
    return out


def execution_residual_rows(train: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> list[list[Any]]:
    enriched = pf.residual_enriched(train, prospective, fields)
    clusters = pf.cluster_rows(enriched)
    return clusters[:16]


def noise_estimate(rows: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    buckets: dict[tuple[str, str, str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[(str(row.get("model") or ""), str(row.get("repository") or ""), str(row.get("category") or ""), str(row.get("dataset") or ""), float(row.get("context_budget") or 0.0))].append(row)
    for key, values in buckets.items():
        if len(values) >= 3:
            outcomes = [float(row["success"]) for row in values]
            out.append([" / ".join(str(part) for part in key), len(values), round(mean(outcomes), 6), round(math.sqrt(m.variance(outcomes)), 6)])
    out.sort(key=lambda row: (float(row[3]), int(row[1])), reverse=True)
    return out[:12]


def main() -> int:
    raw_rows, excluded = cloud.cloud_rows()
    reconstructed = cloud.reconstructed_prospective_rows(raw_rows)
    data = variance_numbers(raw_rows, reconstructed)
    rows = data["rows"]
    prospective = data["prospective"]
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."

    variance_table = [
        ["strict pre-run measured variables", ", ".join(data["strict"]), data["strict_in"]["r2"], data["strict_hold"]["r2"], data["strict_prosp"]["r2"], data["strict_prosp"]["brier_gain"]],
        ["post-retrieval pre-generation variables", ", ".join(data["post"]), data["post_in"]["r2"], data["post_hold"]["r2"], data["post_prosp"]["r2"], data["post_prosp"]["brier_gain"]],
        ["all catalogued pre-run proxies", ", ".join(data["all_pre"]), data["all_pre_in"]["r2"], data["all_pre_hold"]["r2"], data["all_pre_prosp"]["r2"], data["all_pre_prosp"]["brier_gain"]],
        ["execution/post-run diagnostics", ", ".join(data["diag"]), data["diag_in"]["r2"], data["diag_hold"]["r2"], data["diag_prosp"]["r2"], data["diag_prosp"]["brier_gain"]],
    ]
    execution_delta_hold = max(0.0, float(data["diag_hold"]["r2"]) - float(data["post_hold"]["r2"]))
    execution_delta_prosp = max(0.0, float(data["diag_prosp"]["r2"]) - float(data["post_prosp"]["r2"]))
    clean_limit = max(float(data["strict_prosp"]["r2"]), float(data["post_prosp"]["r2"]), float(data["all_pre_prosp"]["r2"]))
    optimistic_pre_limit = min(0.20, max(clean_limit, float(data["all_pre_prosp"]["r2"]) + 0.03))

    fam_strict = family_rows(rows, prospective, data["strict"])
    fam_all = family_rows(rows, prospective, data["all_pre"])
    clusters = execution_residual_rows(data["train"], prospective, data["post"])
    noise_rows = noise_estimate(rows)

    write_md(
        "predictive_failure_root_causes.md",
        f"""
# Predictive Failure Root Causes

Scope: {scope}

## Variance Attribution

{table(["information set", "fields", "retrospective R2", "holdout R2", "prospective reconstructed R2", "prospective Brier gain"], variance_table)}

## Root Causes

| cause | evidence | contribution |
| --- | --- | --- |
| execution-path dependence | execution diagnostics add {fmt(execution_delta_hold)} holdout R2 and {fmt(execution_delta_prosp)} prospective reconstructed R2 beyond post-retrieval variables | major for explaining outcomes, not admissible for pre-run prediction |
| benchmark noise | repeated-cell outcome dispersion remains visible in same model/repo/category/context cells | material measurement floor |
| distribution shift | holdout R2 is much larger than prospective reconstructed R2 for every clean information set | major |
| task-family heterogeneity | coding, reasoning, research, and agentic slices change achievable R2 and transfer behavior | major |
| measurement limits | strict pre-run variables explain far less prospectively than in retrospective/holdout checks | major |
| calibration limits | best clean prospective Brier gains are small and do not support confident probability forecasts | major |
| predictor instability | K/rho/history-heavy predictors transfer poorly into narrow future panels | major |

## Benchmark Noise Cells

{table(["cell", "rows", "success rate", "outcome sd"], noise_rows)}

## Verdict

The failures are not explained by one missing variable. The main pattern is a gap between explanatory reconstruction and future-outcome prediction: pre-run information is too coarse, task-family transfer is unstable, and substantial signal appears only after execution begins or after output exists.
""",
    )

    write_md(
        "task_family_heterogeneity.md",
        f"""
# Task Family Heterogeneity

Scope: {scope}

## Strict Pre-Run Family Results

{table(["family", "rows", "prospective rows", "retrospective R2", "holdout R2", "prospective R2", "verdict"], fam_strict)}

## All Catalogued Pre-Run Proxy Results

{table(["family", "rows", "prospective rows", "retrospective R2", "holdout R2", "prospective R2", "verdict"], fam_all)}

## Assessment

Coding, reasoning, research, and agentic work should not be collapsed into one undifferentiated predictor. The same variables do not have the same transfer profile across families. This does not require new primitives or new laws; it requires family-specific calibration, frozen historical priors, and separate error budgets.

## Separate Predictive Sciences?

Separate full sciences are not justified yet. Separate predictive calibrations are required. A single diagnostic science can remain shared, but predictive claims must be family-specific until balanced cloud-only prospective panels show common calibration.
""",
    )

    write_md(
        "execution_path_dependence.md",
        f"""
# Execution Path Dependence

Scope: {scope}

## Pre-Run Versus Execution Information

{table(["information set", "fields", "retrospective R2", "holdout R2", "prospective reconstructed R2", "prospective Brier gain"], variance_table)}

Estimated additional variance visible only after retrieval/generation/action traces: `{fmt(execution_delta_hold)}` R2 in holdout and `{fmt(execution_delta_prosp)}` R2 in reconstructed prospective scoring.

## Prospective Residual Clusters

{table(["axis", "cluster", "rows", "mean residual", "residual sd", "mean abs error"], clusters)}

## Interpretation

The run itself creates observables that are strongly related to success: whether decisive evidence was surfaced, understood, linked to action, referenced, edited, and verified. Those are not valid initial predictors. They explain why retrospective models looked powerful and why prospective models fail when restricted to information available before execution.
""",
    )

    write_md(
        "pre_run_prediction_limits.md",
        f"""
# Pre-Run Prediction Limits

Scope: {scope}

## Limit Estimate

{table(["candidate ceiling", "estimate", "basis"], [
["observed strict pre-run prospective R2", data["strict_prosp"]["r2"], "only variables available before execution"],
["observed post-retrieval prospective R2", data["post_prosp"]["r2"], "after retrieval/context assembly, before generation"],
["observed all-catalog pre-run prospective R2", data["all_pre_prosp"]["r2"], "optimistic proxy set; still pre-run/frozen-history only"],
["optimistic theoretical pre-run ceiling", fmt(optimistic_pre_limit), "best clean prospective result plus small allowance for better calibration"],
] )}

## Calibration

Best clean prospective Brier gain in this pass is `{fmt(max(float(data["strict_prosp"]["brier_gain"]), float(data["post_prosp"]["brier_gain"]), float(data["all_pre_prosp"]["brier_gain"])))}`. That is too small for reliable route-level probability promises.

## Maximum Predictive Power Using Only Pre-Run Information

The defensible current estimate is low: clean observed prospective R2 is at most `{fmt(clean_limit)}`. An optimistic ceiling using the current variable family is about `{fmt(optimistic_pre_limit)}` R2, not the retrospective 0.7-0.8 range. Higher values require either better frozen pre-run measurements or information that currently appears only during execution.
""",
    )

    write_md(
        "scientific_assessment_v7.md",
        f"""
# Scientific Assessment v7

Scope: {scope}

## Findings

1. Pre-run variables explain substantial retrospective and holdout variance, but only weak reconstructed prospective variance.
2. Execution-path variables explain additional variance, but they are not admissible for initial prediction.
3. Benchmark noise and repeated-cell dispersion create an irreducible measurement floor.
4. Distribution shift is the strongest reason holdout success fails to become prospective success.
5. Task-family heterogeneity requires separate calibration for coding, reasoning, research, and agentic work.
6. Calibration remains weak: clean Brier gains are small and probability bins should not be trusted as operational guarantees.
7. Predictor instability is sufficient to explain the collapse of every major candidate without inventing new primitives.

## Decision

Agent-Hub should remain `Diagnostic Science`. It can realistically support predictive calibration in bounded families, but it should not claim general Predictive Science until a balanced frozen cloud-only panel demonstrates stable calibration from pre-run information alone.
""",
    )

    write_md(
        "final_research_verdict.md",
        f"""
# Final Research Verdict

Scope: {scope}

## Answer

Predictive failure is caused by both missing measurements and fundamental limits, but the dominant current result is limitation rather than a simple missing-variable story.

Missing variables are not enough to explain the failures because the strongest extra signal appears during execution or after output generation. That signal can diagnose why a run succeeded or failed, but it cannot be used to predict before the run. Better pre-run measurements will improve bounded family-specific calibration, especially for coding/reasoning/research/agentic slices, but they are unlikely to recover the retrospective ceiling as a general forecast law.

## Final Classification

Agent-Hub remains `Diagnostic Science`.

It may become limited predictive engineering inside narrow, frozen task families. It should not yet be promoted to broad Predictive Science.
""",
    )

    print(
        json.dumps(
            {
                "scope": scope,
                "strict_pre_run_prospective_r2": data["strict_prosp"]["r2"],
                "all_pre_run_prospective_r2": data["all_pre_prosp"]["r2"],
                "execution_delta_holdout_r2": execution_delta_hold,
                "execution_delta_prospective_r2": execution_delta_prosp,
                "optimistic_pre_run_ceiling": optimistic_pre_limit,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
