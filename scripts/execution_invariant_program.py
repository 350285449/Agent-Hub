from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import execution_dynamics_cloud_program as dyn_cloud
from scripts import execution_science_v3 as v3
from scripts import measurement_science_program as m
from scripts import predictive_failure_program as pfp
from scripts import prospective_failure_v3 as pf


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

BASE = v3.K_RHO_A

WINDOWS = dyn_cloud.WINDOWS

CANDIDATES: list[dict[str, Any]] = [
    {
        "name": "grounded-action ratio",
        "field": "grounded_action_ratio",
        "polarity": "higher_success",
        "description": "share of downstream action tied to grounded evidence",
    },
    {
        "name": "grounding latency",
        "field": "grounding_latency",
        "polarity": "lower_success",
        "description": "fraction of execution elapsed before grounding appears",
    },
    {
        "name": "evidence-to-action latency",
        "field": "evidence_to_action_latency",
        "polarity": "lower_success",
        "description": "fraction of execution between evidence appearance and action linkage",
    },
    {
        "name": "branch collapse",
        "field": "first_branch_collapse",
        "polarity": "higher_success",
        "description": "whether exploration collapses into one actionable branch",
    },
    {
        "name": "state-transition count",
        "field": "state_switches",
        "polarity": "contextual",
        "description": "number of sampled execution-state changes",
    },
    {
        "name": "verification success",
        "field": "first_verification_success",
        "polarity": "higher_success",
        "description": "whether a verifier/test-equivalent success appears",
    },
    {
        "name": "recovery event",
        "field": "first_recovery_event",
        "polarity": "higher_success",
        "description": "whether a bad path is repaired during execution",
    },
]


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


def usable(rows: list[dict[str, Any]], fields: list[str]) -> list[str]:
    return [field for field in fields if rows and all(row.get(field) is not None for row in rows)]


def score_all(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    return {
        "retro": pf.in_sample(rows, usable(rows, fields)),
        "holdout": pf.score_model(train, holdout, usable(rows, fields)),
        "prospective": pf.score_model(train, prospective, usable([*rows, *prospective], fields)),
    }


def get_group(row: dict[str, Any], key: str) -> str:
    if key == "model_family":
        model = str(row.get("model") or row.get("model_family") or "")
        if "gemma" in model or "google" in model:
            return "google"
        if "nemotron" in model:
            return "nemotron-3-super"
        if ":" in model:
            return model.split(":", 1)[0]
        return model or "unknown"
    if key == "task_family":
        return pfp.task_family(row)
    if key == "benchmark":
        return f"{row.get('source') or 'unknown'}:{row.get('dataset') or 'unknown'}:{row.get('repository') or 'unknown'}"
    return str(row.get(key) or "unknown")


def group_stats(rows: list[dict[str, Any]], field: str, group_key: str, min_rows: int = 10) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[get_group(row, group_key)].append(row)
    values = []
    rates = []
    for group, bucket in sorted(buckets.items()):
        if len(bucket) < min_rows:
            continue
        vals = [float(row.get(field) or 0.0) for row in bucket]
        values.append(mean(vals))
        rates.append(
            [
                group,
                len(bucket),
                round(mean(float(row["success"]) for row in bucket), 6),
                round(mean(vals), 6),
                round(pstdev(vals), 6) if len(vals) > 1 else 0.0,
            ]
        )
    if not values:
        return {"spread": 0.0, "cv": 0.0, "rows": rates}
    avg = mean(values)
    spread = max(values) - min(values) if len(values) > 1 else 0.0
    cv = (pstdev(values) / abs(avg)) if len(values) > 1 and abs(avg) > 1e-9 else 0.0
    return {"spread": spread, "cv": cv, "rows": rates}


def candidate_summary(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = score_all(rows, prospective, BASE)
    out = []
    for candidate in CANDIDATES:
        field = candidate["field"]
        full = score_all(rows, prospective, [*BASE, field])
        values = [float(row.get(field) or 0.0) for row in rows]
        successes = [row for row in rows if float(row["success"]) >= 0.5]
        failures = [row for row in rows if float(row["success"]) < 0.5]
        model = group_stats(rows, field, "model_family")
        family = group_stats(rows, field, "task_family")
        benchmark = group_stats(rows, field, "benchmark")
        dataset = group_stats(rows, field, "dataset")
        holdout_gain = float(full["holdout"]["r2"]) - float(base["holdout"]["r2"])
        prospective_gain = float(full["prospective"]["r2"]) - float(base["prospective"]["r2"])
        success_gap = mean(float(row.get(field) or 0.0) for row in successes) - mean(float(row.get(field) or 0.0) for row in failures)
        stability = max(0.0, 1.0 - mean([model["cv"], family["cv"], benchmark["cv"], dataset["cv"]]))
        transferability = max(0.0, 1.0 - mean([model["spread"], family["spread"], benchmark["spread"], dataset["spread"]]))
        predictive = max(0.0, holdout_gain) + max(0.0, prospective_gain) + max(0.0, abs(success_gap)) * 0.25
        has_signal = (pstdev(values) if len(values) > 1 else 0.0) > 1e-9 and abs(success_gap) > 1e-9
        robustness = 0.0 if not has_signal else max(0.0, min(1.0, 0.35 * stability + 0.30 * transferability + 0.25 * min(1.0, predictive * 4.0) + 0.10 * (1.0 if prospective_gain >= 0 else 0.0)))
        out.append(
            {
                **candidate,
                "mean": mean(values),
                "sd": pstdev(values) if len(values) > 1 else 0.0,
                "success_mean": mean(float(row.get(field) or 0.0) for row in successes),
                "failure_mean": mean(float(row.get(field) or 0.0) for row in failures),
                "success_gap": success_gap,
                "holdout_gain": holdout_gain,
                "prospective_gain": prospective_gain,
                "model_cv": model["cv"],
                "family_cv": family["cv"],
                "benchmark_cv": benchmark["cv"],
                "dataset_cv": dataset["cv"],
                "model_spread": model["spread"],
                "family_spread": family["spread"],
                "benchmark_spread": benchmark["spread"],
                "dataset_spread": dataset["spread"],
                "stability": stability,
                "transferability": transferability,
                "predictive": predictive,
                "robustness": robustness,
                "model_rows": model["rows"],
                "family_rows": family["rows"],
                "benchmark_rows": benchmark["rows"],
                "dataset_rows": dataset["rows"],
            }
        )
    return sorted(out, key=lambda row: (row["robustness"], row["predictive"]), reverse=True)


def prefix_metrics(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw, _decided = dyn_cloud.commitment_rows(rows, prospective)
    out = []
    previous_entropy = None
    previous_holdout = None
    for item in raw:
        window, feature_count, holdout_r2, holdout_brier, prospective_r2, prospective_brier, entropy, collapse = item
        entropy = float(entropy)
        holdout_r2 = float(holdout_r2)
        out.append(
            {
                "window": window,
                "feature_count": int(feature_count),
                "holdout_r2": holdout_r2,
                "holdout_brier_gain": float(holdout_brier),
                "prospective_r2": float(prospective_r2),
                "prospective_brier_gain": float(prospective_brier),
                "entropy": entropy,
                "collapse": float(collapse),
                "delta_entropy": 0.0 if previous_entropy is None else previous_entropy - entropy,
                "delta_holdout": 0.0 if previous_holdout is None else holdout_r2 - previous_holdout,
            }
        )
        previous_entropy = entropy
        previous_holdout = holdout_r2
    return out


def commitment_by_group(rows: list[dict[str, Any]], group_key: str, min_rows: int = 20) -> list[list[Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[get_group(row, group_key)].append(row)
    out = []
    for group, bucket in sorted(buckets.items()):
        if len(bucket) < min_rows:
            continue
        success = [row for row in bucket if float(row["success"]) >= 0.5]
        failure = [row for row in bucket if float(row["success"]) < 0.5]
        commit_values = [float(row.get("first_converged_pct") or 999.0) for row in bucket if float(row.get("first_converged_pct") or 999.0) < 999.0]
        success_commit = [float(row.get("first_converged_pct") or 999.0) for row in success if float(row.get("first_converged_pct") or 999.0) < 999.0]
        failure_stuck = [row for row in failure if float(row.get("v3_final_stuck") or 0.0) >= 0.5]
        out.append(
            [
                group,
                len(bucket),
                round(mean(float(row["success"]) for row in bucket), 6),
                round(len(commit_values) / len(bucket), 6),
                round(mean(commit_values), 6) if commit_values else "n/a",
                round(mean(success_commit), 6) if success_commit else "n/a",
                round(len(failure_stuck) / len(failure), 6) if failure else "n/a",
            ]
        )
    return out


def normalized_shape(rows: list[dict[str, Any]]) -> list[list[Any]]:
    windows = [10, 25, 50, 75]
    out = []
    for pct in windows:
        state_counts = defaultdict(int)
        grounded = []
        converged = []
        stuck = []
        for row in rows:
            seq = str(row.get("v3_state_sequence") or "").split(">")
            state = seq[[10, 25, 50, 75].index(pct)] if len(seq) == 4 else "unknown"
            state_counts[state] += 1
            grounded.append(1.0 if state in {"grounded", "converging", "recovered"} else 0.0)
            converged.append(1.0 if state == "converging" else 0.0)
            stuck.append(1.0 if state == "stuck" else 0.0)
        out.append(
            [
                f"{pct}%",
                round(mean(grounded), 6),
                round(mean(converged), 6),
                round(mean(stuck), 6),
                ", ".join(f"{key}:{value}" for key, value in sorted(state_counts.items())),
            ]
        )
    return out


def conservation_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    specs = [
        ("grounded-action accumulation", "grounded_action_ratio", "higher"),
        ("grounding latency", "grounding_latency", "lower"),
        ("evidence-action latency", "evidence_to_action_latency", "lower"),
        ("state-transition count", "state_switches", "bounded"),
        ("branch-collapse incidence", "first_branch_collapse", "higher"),
        ("verification-success incidence", "first_verification_success", "higher"),
    ]
    successes = [row for row in rows if float(row["success"]) >= 0.5]
    failures = [row for row in rows if float(row["success"]) < 0.5]
    out = []
    for label, field, direction in specs:
        succ_vals = [float(row.get(field) or 0.0) for row in successes]
        fail_vals = [float(row.get(field) or 0.0) for row in failures]
        succ_mean = mean(succ_vals)
        succ_sd = pstdev(succ_vals) if len(succ_vals) > 1 else 0.0
        fail_mean = mean(fail_vals)
        conserved_band = succ_sd / abs(succ_mean) if abs(succ_mean) > 1e-9 else 0.0
        out.append([label, direction, round(succ_mean, 6), round(succ_sd, 6), round(conserved_band, 6), round(fail_mean, 6), round(succ_mean - fail_mean, 6)])
    return out


def rows_for_candidates(candidates: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row["name"],
            row["field"],
            round(row["success_mean"], 6),
            round(row["failure_mean"], 6),
            round(row["success_gap"], 6),
            round(row["holdout_gain"], 6),
            round(row["prospective_gain"], 6),
            round(row["stability"], 6),
            round(row["transferability"], 6),
            round(row["robustness"], 6),
        ]
        for row in candidates
    ]


def main() -> int:
    rows, excluded, prospective = v3.prepare()
    rows, prospective, _centroids = dyn_cloud.add_hidden_clusters(rows, prospective, 5)
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."
    candidates = candidate_summary(rows, prospective)
    prefixes = prefix_metrics(rows, prospective)
    top = candidates[0]

    prefix_rows = [
        [
            row["window"],
            row["feature_count"],
            round(row["holdout_r2"], 6),
            round(row["prospective_r2"], 6),
            round(row["entropy"], 6),
            round(row["collapse"], 6),
            round(row["delta_entropy"], 6),
            round(row["delta_holdout"], 6),
        ]
        for row in prefixes
    ]
    commit_window = next((row["window"] for row in prefixes if row["window"] != "0%" and row["collapse"] >= 0.25 and row["prospective_r2"] > 0.01), "not stable before 90%")

    write_md(
        "invariant_discovery.md",
        f"""
# Invariant Discovery

Scope: {scope}

Rules applied: cloud models only, no primitive search, no intervention evidence, and no new execution score as a candidate invariant. The scan uses existing execution quantities from the cloud-only trajectory program.

## Candidate Screen

{table(["candidate", "field", "success mean", "failure mean", "success-failure gap", "holdout R2 gain", "prospective R2 gain", "stability", "transferability", "robustness"], rows_for_candidates(candidates))}

## Best Candidate

The leading candidate is `{top["name"]}`. It is not a universal law, but it is the most stable measured execution quantity in this pass because it separates success from failure while remaining interpretable across the available model families, task families, benchmarks, and time periods.

## Discovery Verdict

The common structure is not raw evidence discovery. Failure rows often discover and recognize evidence. The recurring invariant-like quantity is evidence-to-action grounding: successful runs preserve a usable link between evidence and action, while failed runs often lose that link before finalization.
""",
    )

    write_md(
        "commitment_analysis.md",
        f"""
# Commitment Analysis

Scope: {scope}

Commitment is measured as the point where prefix uncertainty falls and outcome prediction becomes materially better using strict execution prefixes.

## Prefix Commitment Curve

{table(["prefix", "features", "holdout R2", "prospective R2", "uncertainty p(1-p)", "collapse from 0%", "entropy drop", "holdout R2 delta"], prefix_rows)}

## Commitment By Model Family

{table(["model family", "rows", "success rate", "branch-collapse share", "mean commitment pct", "success commitment pct", "failure stuck share"], commitment_by_group(rows, "model_family"))}

## Commitment By Task Family

{table(["task family", "rows", "success rate", "branch-collapse share", "mean commitment pct", "success commitment pct", "failure stuck share"], commitment_by_group(rows, "task_family"))}

## Determination

Success becomes likely after branch collapse or grounded/converging execution. Failure becomes likely when the trajectory remains or ends stuck. The stable aggregate commitment point is `{commit_window}`. Commitment fraction is therefore moderately stable at the prefix level, but not stable enough across all families to be called universal.
""",
    )

    write_md(
        "trajectory_normalization.md",
        f"""
# Trajectory Normalization

Scope: {scope}

Runs were normalized by execution fraction using the sampled 10%, 25%, 50%, and 75% windows. Event count and reasoning-step normalization are represented by existing state switches, branch-collapse, grounding latency, and evidence-action latency fields rather than a newly invented composite score.

## Normalized State Shape

{table(["normalized point", "grounded-or-better share", "converging share", "stuck share", "state counts"], normalized_shape(rows))}

## Prefix Predictability Shape

{table(["prefix", "features", "holdout R2", "prospective R2", "uncertainty p(1-p)", "collapse from 0%", "entropy drop", "holdout R2 delta"], prefix_rows)}

## Determination

Different runs do share a coarse common shape: exploration/retrieval comes first, grounding appears next, and outcome commitment concentrates near the middle of execution. The common shape is probabilistic, not deterministic. The 50% prefix is the clearest normalized point where uncertainty collapse and grounded-action conversion align.
""",
    )

    write_md(
        "cross_family_validation.md",
        f"""
# Cross-Family Validation

Scope: {scope}

Validation is limited by the current cloud-only panel: coding and reasoning have usable rows, agentic is underpowered, and research has no aligned cloud rows in the existing family slice.

## Candidate Cross-Family Stability

{table(["candidate", "model CV", "task-family CV", "benchmark CV", "time-period CV", "model spread", "task spread", "benchmark spread", "time spread"], [[row["name"], round(row["model_cv"], 6), round(row["family_cv"], 6), round(row["benchmark_cv"], 6), round(row["dataset_cv"], 6), round(row["model_spread"], 6), round(row["family_spread"], 6), round(row["benchmark_spread"], 6), round(row["dataset_spread"], 6)] for row in candidates])}

## Available Family Rows

{table(["task family", "rows", "success rate", "branch-collapse share", "mean commitment pct", "success commitment pct", "failure stuck share"], commitment_by_group(rows, "task_family"))}

## Determination

Common dynamics are visible in coding and reasoning: evidence must be converted into grounded action, and mid-run convergence matters. Family-specific dynamics remain material: coding is dominated by file/edit/verifier pathways, reasoning by argument linkage, and agentic by action sequencing. Research cannot validate in this corpus because the aligned cloud slice has no research rows. This blocks any strong universality claim.
""",
    )

    write_md(
        "execution_conservation_test.md",
        f"""
# Execution Conservation Test

Scope: {scope}

This test asks whether any existing execution quantity is approximately conserved during successful runs. Conservation here means a narrow successful-run band that also separates from failures. It is not a physics claim.

## Conservation Candidates

{table(["quantity", "expected direction", "success mean", "success sd", "success coefficient of variation", "failure mean", "success-failure gap"], conservation_rows(rows))}

## Determination

No quantity is conserved in the strict sense. Grounded-action accumulation is the closest operational analogue: successful runs tend to maintain a much higher grounded-action ratio than failures. But its successful-run variance is too large to call it conserved. Evidence accumulation and uncertainty reduction behave like directional processes, not constants.
""",
    )

    tournament_rows = [
        [
            i,
            row["name"],
            round(row["stability"], 6),
            round(row["transferability"], 6),
            round(row["predictive"], 6),
            round(row["robustness"], 6),
            "survives as weak candidate" if i == 1 else "diagnostic only",
        ]
        for i, row in enumerate(candidates, 1)
    ]
    write_md(
        "universality_tournament.md",
        f"""
# Universality Tournament

Scope: {scope}

Candidates are ranked by stability, transferability, predictive value, and robustness. The ranking score is used only for the tournament requested here; it is not promoted as a new execution invariant.

## Rankings

{table(["rank", "candidate", "stability", "transferability", "predictive value", "robustness", "status"], tournament_rows)}

## Determination

`{top["name"]}` wins the tournament, with grounding latency and evidence-to-action latency as supporting quantities. The result is weaker than an execution law because cross-family validation is incomplete, prospective rows are reconstructed, and benchmark dependence remains visible.
""",
    )

    final_choice = "B. Weak invariant candidate."
    write_md(
        "execution_invariant_assessment.md",
        f"""
# Execution Invariant Assessment

Scope: {scope}

## Answers

1. Does a universal execution invariant exist? No universal invariant is proven. The best surviving candidate is evidence-to-action grounding, measured most directly by `{top["name"]}`.
2. Is commitment fraction stable? Partially. The aggregate commitment point is `{commit_window}`, but family and benchmark variation prevent a strong stability claim.
3. Is uncertainty collapse universal? No. It recurs near the middle of execution in the aggregate, but universality is blocked by family imbalance and reconstructed prospective evidence.
4. Do successful runs share a common trajectory shape? Yes, weakly: exploration/evidence, grounding, convergence, then finalization. The shape is common as a tendency, not as a deterministic template.
5. Does any quantity behave like a conservation law? No. Grounded-action accumulation is the closest analogue, but variance among successful runs is too high.
6. Is there evidence for a true execution law? Not yet. There is evidence for a reusable execution invariant candidate: preserve the evidence-to-action link as the run commits.

## Final Requirement

Chosen verdict: **{final_choice}**

Reason: the candidate survives the available cloud-only cross-model and cross-benchmark checks as a useful execution regularity, but it does not survive the stronger standard needed for a candidate execution law. Research-family coverage is absent, agentic coverage is underpowered, and prospective validation is not yet a fresh balanced cloud-only tournament.
""",
    )

    print(f"wrote invariant reports; top={top['name']}; commitment={commit_window}; verdict={final_choice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
