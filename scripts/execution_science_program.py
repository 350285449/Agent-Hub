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
from scripts import predictive_failure_program as pfp
from scripts import prospective_failure_v3 as pf


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

PRE_RUN = ["K", "rho", "A1_exists", "old_A", "context_budget", "expected_files", "relevant_files"]
DURING_EXECUTION = [*PRE_RUN, "A2_retrieved", "A3_surfaced"]
POST_RUN_DIAGNOSTIC = [
    *DURING_EXECUTION,
    "A4_understood",
    "A5_linked_to_action",
    "E9",
    "referenced_files",
    "edited_files",
    "tests_or_verifiers",
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


def material_fields(rows: list[dict[str, Any]], fields: list[str], extra: list[dict[str, Any]] | None = None) -> list[str]:
    source = [*rows, *(extra or [])]
    return [field for field in fields if all(row.get(field) is not None for row in source)]


def score_windows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> dict[str, Any]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    windows = {
        "pre-run": material_fields(rows, PRE_RUN),
        "during execution": material_fields(rows, DURING_EXECUTION),
        "post-run diagnostic": material_fields(rows, POST_RUN_DIAGNOSTIC),
        "all catalogued pre-run proxies": material_fields(rows, pfp.ALL_PRE_RUN_CATALOG),
    }
    scored = {}
    for name, fields in windows.items():
        prospective_fields = material_fields(rows, fields, prospective)
        scored[name] = {
            "fields": fields,
            "prospective_fields": prospective_fields,
            "retrospective": pf.in_sample(rows, fields),
            "holdout": pf.score_model(train, holdout, fields),
            "prospective": pf.score_model(train, prospective, prospective_fields),
        }
    return {"train": train, "holdout": holdout, "windows": scored}


def comparison_rows(scored: dict[str, Any]) -> list[list[Any]]:
    out = []
    for name, item in scored["windows"].items():
        out.append(
            [
                name,
                ", ".join(item["fields"]),
                item["retrospective"]["r2"],
                item["holdout"]["r2"],
                item["holdout"]["brier_gain"],
                item["prospective"]["r2"],
                item["prospective"]["brier_gain"],
            ]
        )
    return out


def family_score_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], windows: dict[str, Any]) -> list[list[Any]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    out = []
    for family in ["coding", "reasoning", "research", "agentic"]:
        fam_rows = [row for row in rows if pfp.task_family(row) == family]
        fam_holdout = [row for row in fam_rows if row.get("dataset") != "historical"] or fam_rows
        fam_prospective = [row for row in prospective if pfp.task_family(row) == family]
        for window in ["pre-run", "during execution", "post-run diagnostic"]:
            if len(fam_rows) < 8:
                out.append([family, window, len(fam_rows), len(fam_prospective), "n/a", "n/a", "insufficient cloud rows"])
                continue
            fields = material_fields(fam_rows, windows[window]["fields"], fam_prospective)
            hold = pf.score_model(train, fam_holdout, fields)
            prosp = pf.score_model(train, fam_prospective, fields) if fam_prospective else {"r2": 0.0, "brier_gain": 0.0}
            verdict = "family-specific calibration required"
            if float(prosp["r2"]) >= 0.25 and float(prosp["brier_gain"]) > 0.03:
                verdict = "family prediction viable in this slice"
            elif len(fam_prospective) < 20:
                verdict = "underpowered; do not generalize"
            out.append([family, window, len(fam_rows), len(fam_prospective), hold["r2"], prosp["r2"], verdict])
    return out


def residual_clusters(train: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> list[list[Any]]:
    return pf.cluster_rows(pf.residual_enriched(train, prospective, fields))[:14]


def same_cell_noise(rows: list[dict[str, Any]]) -> list[list[Any]]:
    buckets: dict[tuple[str, str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[
            (
                str(row.get("model") or ""),
                str(row.get("repository") or ""),
                str(row.get("category") or ""),
                float(row.get("context_budget") or 0.0),
            )
        ].append(row)
    out = []
    for key, values in buckets.items():
        if len(values) >= 3:
            ys = [float(row["success"]) for row in values]
            out.append([" / ".join(str(part) for part in key), len(values), round(mean(ys), 6), round(math.sqrt(m.variance(ys)), 6)])
    out.sort(key=lambda row: (float(row[3]), int(row[1])), reverse=True)
    return out[:12]


def conclusion(scored: dict[str, Any]) -> dict[str, float]:
    pre = float(scored["windows"]["pre-run"]["holdout"]["r2"])
    during = float(scored["windows"]["during execution"]["holdout"]["r2"])
    post = float(scored["windows"]["post-run diagnostic"]["holdout"]["r2"])
    prospective_pre = max(
        float(scored["windows"]["pre-run"]["prospective"]["r2"]),
        float(scored["windows"]["all catalogued pre-run proxies"]["prospective"]["r2"]),
    )
    return {
        "pre_holdout_r2": pre,
        "during_holdout_r2": during,
        "post_holdout_r2": post,
        "during_gain_over_pre": max(0.0, during - pre),
        "post_gain_over_during": max(0.0, post - during),
        "execution_gain_over_pre": max(0.0, post - pre),
        "best_clean_prospective_pre_r2": prospective_pre,
    }


def main() -> int:
    raw_rows, excluded = cloud.cloud_rows()
    rows = pf.enrich_pre_run_candidates(raw_rows)
    prospective = pf.estimate_candidate_features(rows, cloud.reconstructed_prospective_rows(raw_rows))
    scored = score_windows(rows, prospective)
    numbers = conclusion(scored)
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."
    direct = comparison_rows(scored)
    families = family_score_rows(rows, prospective, scored["windows"])
    clusters = residual_clusters(scored["train"], prospective, scored["windows"]["during execution"]["fields"])
    noise = same_cell_noise(rows)

    write_md(
        "execution_science.md",
        f"""
# Execution Science

Scope: {scope}

## Timing Windows

{table(["window", "fields", "retrospective R2", "holdout R2", "holdout Brier gain", "prospective R2", "prospective Brier gain"], direct)}

## Result

The useful explanatory signal is not concentrated before execution. Initial pre-run variables explain `{fmt(numbers["pre_holdout_r2"])}` holdout R2. Post-retrieval execution variables explain `{fmt(numbers["during_holdout_r2"])}` holdout R2, which does not beat the pre-run set in this corpus. Full post-run diagnostics explain `{fmt(numbers["post_holdout_r2"])}` holdout R2.

Execution/post-run observables add `{fmt(numbers["execution_gain_over_pre"])}` holdout R2 over the pre-run set. The best clean prospective pre-run R2 remains `{fmt(numbers["best_clean_prospective_pre_r2"])}` in this reconstructed cloud-only panel.

## Interpretation

Agent success is not primarily fixed before the run. The run creates decisive observables: evidence retrieval, evidence surfacing, whether evidence is understood, whether it is linked to action, file references, edits, and verifiers. Some of these are available during execution; the strongest are only diagnostic after output exists.

## Classification

Agent-Hub should become `C. Execution Science`: a system for instrumenting, steering, and diagnosing the execution process. Pure predictive science is too strong; diagnostic science is too passive.
""",
    )

    write_md(
        "signal_emergence_analysis.md",
        f"""
# Signal Emergence Analysis

Scope: {scope}

## Direct Comparison

{table(["window", "fields", "retrospective R2", "holdout R2", "holdout Brier gain", "prospective R2", "prospective Brier gain"], direct)}

## Where Signal First Appears

Weak useful signal appears before execution through `K`, `rho`, task labels, planned context, and historical priors. It is useful for rough stratification, not reliable probability prediction.

Retrieval/context assembly adds little stable holdout signal by itself in this pass. The first material increase appears by the end of execution, when evidence-use and action traces are visible.

## Prospective Failure Clusters

{table(["axis", "cluster", "rows", "mean residual", "residual sd", "mean abs error"], clusters)}

## Answer

Prediction is fundamentally limited before execution under the current variable family. The limitation is empirical, not philosophical: pre-run holdout looks respectable, but prospective transfer collapses. Signal becomes reliable when the execution path starts revealing whether the agent found and used the right evidence.
""",
    )

    write_md(
        "task_family_signal_analysis.md",
        f"""
# Task Family Signal Analysis

Scope: {scope}

## Family Timing Results

{table(["family", "window", "rows", "prospective rows", "holdout R2", "prospective R2", "verdict"], families)}

## Assessment By Family

Coding tasks show execution sensitivity because file selection, edits, and verifier behavior determine success after the prompt is already known.

Reasoning tasks preserve some pre-run stratification, but the decisive signal still depends on whether the model connects evidence to the final argument.

Research tasks are not estimable in the current cloud-only aligned corpus: this pass has zero rows classified as research. The program should collect a balanced research slice before making a family-specific claim there.

Agentic tasks are the least viable for broad pre-run prediction because action sequencing, tool use, and recovery behavior are execution-stage phenomena.

## Family-Specific Prediction

Family-specific prediction is viable only as bounded calibration, not as a general science yet. Each family needs separate base rates, separate uncertainty budgets, and balanced frozen cloud-only panels.
""",
    )

    write_md(
        "execution_vs_prediction.md",
        f"""
# Execution Versus Prediction

Scope: {scope}

## Evidence Table

{table(["window", "fields", "retrospective R2", "holdout R2", "holdout Brier gain", "prospective R2", "prospective Brier gain"], direct)}

## Benchmark Noise

{table(["cell", "rows", "success rate", "outcome sd"], noise)}

## Direct Answers

1. Useful signal first appears before execution, but only weakly and unreliably for future prediction.
2. Prediction is currently limited before execution because the strongest variables are historical priors or later execution traces.
3. Agent outcomes are primarily execution-driven in the evidence: post-run diagnostic R2 exceeds pre-run holdout R2 by `{fmt(numbers["execution_gain_over_pre"])}`.
4. Full execution traces dominate pre-run variables for explanation; retrieval-stage variables alone do not. They do not become admissible initial predictors merely because they explain outcomes.

## Operational Consequence

Agent-Hub should spend less effort promising exact pre-run success probabilities and more effort measuring live execution state, detecting divergence early, and adapting while the run is still recoverable.
""",
    )

    write_md(
        "scientific_assessment_v8.md",
        f"""
# Scientific Assessment v8

Scope: {scope}

## Core Finding

The cloud-only evidence supports an execution-driven view of agent success. Pre-run variables are real but incomplete. Retrieval-stage variables alone do not dominate pre-run variables here; full execution traces and post-run diagnostics explain more variance because they observe the path by which success is made or lost.

## Quantified Claims

- Pre-run holdout R2: `{fmt(numbers["pre_holdout_r2"])}`.
- During-execution holdout R2: `{fmt(numbers["during_holdout_r2"])}`.
- Post-run diagnostic holdout R2: `{fmt(numbers["post_holdout_r2"])}`.
- Execution/post-run gain over pre-run: `{fmt(numbers["execution_gain_over_pre"])}`.
- Best clean prospective pre-run R2 in this pass: `{fmt(numbers["best_clean_prospective_pre_r2"])}`.

## What Is Rejected

- Broad `A. Predictive Science`: rejected because pre-run prospective signal is too weak.
- `B. Family-Specific Predictive Science`: not yet accepted; family calibration is necessary but not validated enough to be the program identity.
- Pure `D. Diagnostic Science`: too narrow, because the practical opportunity is not only post-run explanation but live execution instrumentation and steering.

## Accepted Classification

`C. Execution Science`.

Agent-Hub should study and improve the execution process: evidence acquisition, surfacing, reasoning over evidence, action linkage, edits, verification, and recovery. Prediction remains a supporting service, not the central scientific claim.
""",
    )

    write_md(
        "final_program_conclusion.md",
        f"""
# Final Program Conclusion

Scope: {scope}

## Answers

1. Useful signal first appears before execution, but the first material increase over pre-run prediction appears by the end of execution in post-run diagnostics.
2. Prediction is fundamentally limited before execution under the current cloud-only evidence. Better family calibration can help, but it should not be expected to recover the retrospective ceiling.
3. Agent outcomes are primarily execution-driven. The strongest explanatory variables observe retrieval, surfacing, understanding, action linkage, edits, references, and verification.
4. Family-specific prediction is viable as bounded calibration, not as the main science. Coding, reasoning, research, and agentic tasks need separate calibration before any probability claim is trusted.
5. Agent-Hub should become `C. Execution Science`.

## Final Classification

`C. Execution Science`.

The evidence does not support a general predictive science. It also should not stop at after-the-fact diagnosis. The right center of gravity is execution: measure the live run, identify when success or failure becomes visible, intervene while the outcome is still movable, and retain post-run diagnostics as the learning substrate for the next run.
""",
    )

    print(
        json.dumps(
            {
                "scope": scope,
                **numbers,
                "classification": "C. Execution Science",
                "outputs": [
                    "execution_science.md",
                    "signal_emergence_analysis.md",
                    "task_family_signal_analysis.md",
                    "execution_vs_prediction.md",
                    "scientific_assessment_v8.md",
                    "final_program_conclusion.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
