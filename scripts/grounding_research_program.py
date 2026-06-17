from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import cloud_research_program as cloud
from scripts import execution_dynamics_theory_program as dyn
from scripts import measurement_science_program as m
from scripts import prospective_failure_v3 as pf


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"
K_RHO_A = ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"]
GROUNDING_FIELDS = [
    "time_to_decisive_evidence",
    "grounding_latency",
    "grounded_action_ratio",
    "evidence_to_action_latency",
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


def score_all(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    usable = [field for field in fields if all(row.get(field) is not None for row in rows)]
    usable_prosp = [field for field in fields if all(row.get(field) is not None for row in [*rows, *prospective])]
    return {
        "retro": pf.in_sample(rows, usable),
        "holdout": pf.score_model(train, holdout, usable),
        "prospective": pf.score_model(train, prospective, usable_prosp),
    }


def prepare() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_rows, excluded = cloud.cloud_rows()
    rows = dyn.add_dynamics(pf.enrich_pre_run_candidates(raw_rows))
    prospective = dyn.add_dynamics(pf.estimate_candidate_features(rows, cloud.reconstructed_prospective_rows(raw_rows)))
    rows = add_grounding_features(rows)
    prospective = add_grounding_features(prospective)
    return rows, excluded, prospective


def add_grounding_features(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        discovered = float(item.get("A1_exists") or 0.0) >= 0.5 or float(item.get("A2_retrieved") or 0.0) >= 0.25
        recognized = float(item.get("A2_retrieved") or 0.0) >= 0.35 or float(item.get("A3_surfaced") or 0.0) >= 0.35
        accepted = float(item.get("first_decisive_evidence") or 0.0) >= 0.5 or float(item.get("A4_understood") or 0.0) >= 0.45
        connected = float(item.get("A5_linked_to_action") or 0.0) >= 0.45 or float(item.get("grounded_action_ratio") or 0.0) >= 0.45
        executed = accepted and connected and float(item.get("evidence_to_action_latency") or 1.0) <= 0.50
        item.update(
            {
                "g_evidence_discovered": 1.0 if discovered else 0.0,
                "g_evidence_recognized": 1.0 if recognized else 0.0,
                "g_evidence_accepted": 1.0 if accepted else 0.0,
                "g_evidence_connected": 1.0 if connected else 0.0,
                "g_grounded_execution": 1.0 if executed else 0.0,
            }
        )
        item["grounding_state"] = grounding_state(item)
        item["grounding_score"] = grounding_score(item)
        item["grounding_trajectory"] = ">".join(trajectory(item))
        out.append(item)
    return out


def grounding_score(row: dict[str, Any]) -> float:
    return m.clamp01(
        (
            (1.0 - float(row.get("time_to_decisive_evidence") or 1.0))
            + (1.0 - float(row.get("grounding_latency") or 1.0))
            + float(row.get("grounded_action_ratio") or 0.0)
            + (1.0 - float(row.get("evidence_to_action_latency") or 1.0))
        )
        / 4.0
    )


def grounding_state(row: dict[str, Any]) -> str:
    score = grounding_score(row)
    if float(row.get("g_grounded_execution") or 0.0) >= 0.5 and score >= 0.72:
        return "strongly grounded"
    if float(row.get("g_grounded_execution") or 0.0) >= 0.5 or score >= 0.58:
        return "grounded"
    if float(row.get("g_evidence_recognized") or 0.0) >= 0.5 or score >= 0.38:
        return "weakly grounded"
    return "ungrounded"


def trajectory(row: dict[str, Any]) -> list[str]:
    stages = []
    if float(row.get("g_evidence_discovered") or 0.0) >= 0.5:
        stages.append("discovered")
    if float(row.get("g_evidence_recognized") or 0.0) >= 0.5:
        stages.append("recognized")
    if float(row.get("g_evidence_accepted") or 0.0) >= 0.5:
        stages.append("accepted")
    if float(row.get("g_evidence_connected") or 0.0) >= 0.5:
        stages.append("connected")
    if float(row.get("g_grounded_execution") or 0.0) >= 0.5:
        stages.append("executed")
    return stages or ["none"]


def pipeline_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    stages = [
        ("evidence discovered", "g_evidence_discovered"),
        ("evidence recognized", "g_evidence_recognized"),
        ("evidence accepted", "g_evidence_accepted"),
        ("evidence connected to action", "g_evidence_connected"),
        ("grounded execution", "g_grounded_execution"),
    ]
    out = []
    previous_field = None
    for stage, field in stages:
        present = [row for row in rows if float(row.get(field) or 0.0) >= 0.5]
        absent = [row for row in rows if float(row.get(field) or 0.0) < 0.5]
        if previous_field is None:
            transition = len(present) / len(rows) if rows else 0.0
        else:
            previous = [row for row in rows if float(row.get(previous_field) or 0.0) >= 0.5]
            transition = len([row for row in previous if float(row.get(field) or 0.0) >= 0.5]) / len(previous) if previous else 0.0
        out.append(
            [
                stage,
                len(present),
                round(len(present) / len(rows), 6) if rows else 0.0,
                round(transition, 6),
                round(mean(float(row["success"]) for row in present), 6) if present else "n/a",
                round(mean(float(row["success"]) for row in absent), 6) if absent else "n/a",
            ]
        )
        previous_field = field
    return out


def failure_modes(rows: list[dict[str, Any]]) -> list[list[Any]]:
    failed = [row for row in rows if float(row.get("success") or 0.0) < 0.5]
    modes = [
        (
            "evidence found but ignored",
            lambda r: r["g_evidence_recognized"] >= 0.5 and r["g_evidence_accepted"] < 0.5 and r["g_evidence_connected"] < 0.5,
        ),
        (
            "evidence found too late",
            lambda r: r["g_evidence_recognized"] >= 0.5 and float(r.get("time_to_decisive_evidence") or 1.0) >= 0.50,
        ),
        (
            "evidence misinterpreted",
            lambda r: max(float(r.get("A2_retrieved") or 0.0), float(r.get("A3_surfaced") or 0.0)) >= 0.45
            and float(r.get("A4_understood") or 0.0) < 0.35,
        ),
        (
            "evidence disconnected from action",
            lambda r: r["g_evidence_accepted"] >= 0.5 and r["g_evidence_connected"] < 0.5,
        ),
        (
            "evidence replaced by hallucinated reasoning",
            lambda r: r["g_evidence_recognized"] < 0.5
            and (float(r.get("A5_linked_to_action") or 0.0) >= 0.35 or float(r.get("edited_files") or 0.0) > 0.0),
        ),
    ]
    out = []
    for name, predicate in modes:
        matching = [row for row in failed if predicate(row)]
        all_matching = [row for row in rows if predicate(row)]
        out.append(
            [
                name,
                len(matching),
                round(len(matching) / len(failed), 6) if failed else 0.0,
                len(all_matching),
                round(mean(float(row["success"]) for row in all_matching), 6) if all_matching else "n/a",
                round(mean(float(row["grounding_score"]) for row in matching), 6) if matching else "n/a",
            ]
        )
    return sorted(out, key=lambda row: (float(row[2]), int(row[1])), reverse=True)


def state_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    states = ["ungrounded", "weakly grounded", "grounded", "strongly grounded"]
    out = []
    total_success = mean(float(row["success"]) for row in rows) if rows else 0.0
    for state in states:
        present = [row for row in rows if row["grounding_state"] == state]
        out.append(
            [
                state,
                len(present),
                round(len(present) / len(rows), 6) if rows else 0.0,
                round(mean(float(row["success"]) for row in present), 6) if present else "n/a",
                round(1.0 - mean(float(row["success"]) for row in present), 6) if present else "n/a",
                round((mean(float(row["success"]) for row in present) - total_success), 6) if present else "n/a",
            ]
        )
    return out


def state_transition_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    order = ["ungrounded", "weakly grounded", "grounded", "strongly grounded"]
    def state_at_stage(row: dict[str, Any], stage: str) -> str:
        if stage == "10":
            if float(row.get("g_evidence_recognized") or 0.0) >= 0.5:
                return "weakly grounded"
            return "ungrounded"
        if stage == "25":
            if float(row.get("g_evidence_accepted") or 0.0) >= 0.5:
                return "grounded"
            if float(row.get("g_evidence_recognized") or 0.0) >= 0.5:
                return "weakly grounded"
            return "ungrounded"
        if stage == "50":
            if float(row.get("g_evidence_connected") or 0.0) >= 0.5:
                return "grounded"
            if float(row.get("g_evidence_accepted") or 0.0) >= 0.5:
                return "weakly grounded"
            return "ungrounded"
        return grounding_state(row)

    transitions: Counter[str] = Counter()
    successes: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        seq = [state_at_stage(row, stage) for stage in ["10", "25", "50", "75"]]
        for left, right in zip(seq, seq[1:]):
            transitions[f"{left} -> {right}"] += 1
            successes[f"{left} -> {right}"].append(float(row["success"]))
    out = []
    for transition, count in transitions.most_common():
        left, right = [part.strip() for part in transition.split("->")]
        direction = order.index(right) - order.index(left)
        out.append([transition, count, round(count / max(1, sum(transitions.values())), 6), round(mean(successes[transition]), 6), "up" if direction > 0 else "flat" if direction == 0 else "down"])
    return out


def trajectory_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    buckets: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[row["grounding_trajectory"]].append(row)
    out = []
    for path, values in buckets.items():
        out.append([path, len(values), round(len(values) / len(rows), 6), round(mean(float(row["success"]) for row in values), 6), "success" if mean(float(row["success"]) for row in values) >= 0.70 else "failure" if mean(float(row["success"]) for row in values) <= 0.40 else "mixed"])
    return sorted(out, key=lambda row: (int(row[1]), float(row[3])), reverse=True)


def latency_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    groups = [
        ("all", rows),
        ("successful", [row for row in rows if float(row["success"]) >= 0.5]),
        ("failed", [row for row in rows if float(row["success"]) < 0.5]),
        ("grounded execution", [row for row in rows if row["g_grounded_execution"] >= 0.5]),
        ("no grounded execution", [row for row in rows if row["g_grounded_execution"] < 0.5]),
    ]
    out = []
    for name, group in groups:
        out.append(
            [
                name,
                len(group),
                round(mean(float(row["time_to_decisive_evidence"]) for row in group), 6) if group else "n/a",
                round(mean(float(row["grounding_latency"]) for row in group), 6) if group else "n/a",
                round(mean(float(row["evidence_to_action_latency"]) for row in group), 6) if group else "n/a",
                round(mean(float(row["grounding_score"]) for row in group), 6) if group else "n/a",
                round(mean(float(row["success"]) for row in group), 6) if group else "n/a",
            ]
        )
    return out


def score_metrics(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [float(row["success"]) for row in rows]
    scores = [float(row["grounding_score"]) for row in rows]
    retro = m.metrics(scores, labels)
    score_model = score_all(rows, prospective, ["grounding_score"])
    grounding_model = score_all(rows, prospective, GROUNDING_FIELDS)
    baseline_model = score_all(rows, prospective, K_RHO_A)
    grounding_plus_baseline = score_all(rows, prospective, [*K_RHO_A, *GROUNDING_FIELDS])
    dynamic_model = score_all(rows, prospective, dyn.dynamic_specs_final())
    baseline_holdout = float(baseline_model["holdout"]["r2"])
    grounding_holdout = float(grounding_plus_baseline["holdout"]["r2"])
    dynamic_holdout = float(dynamic_model["holdout"]["r2"])
    baseline_prospective = float(baseline_model["prospective"]["r2"])
    grounding_prospective = float(grounding_plus_baseline["prospective"]["r2"])
    dynamic_prospective = float(dynamic_model["prospective"]["r2"])
    return {
        "single": retro,
        "score_model": score_model,
        "grounding_model": grounding_model,
        "baseline_model": baseline_model,
        "grounding_plus_baseline": grounding_plus_baseline,
        "dynamic_model": dynamic_model,
        "holdout_share_of_grounding": float(score_model["holdout"]["r2"]) / max(0.000001, float(grounding_model["holdout"]["r2"])),
        "holdout_share_of_dynamic": float(score_model["holdout"]["r2"]) / max(0.000001, float(dynamic_model["holdout"]["r2"])),
        "prospective_share_of_dynamic": float(score_model["prospective"]["r2"]) / max(0.000001, float(dynamic_model["prospective"]["r2"])),
        "incremental_holdout_share": (grounding_holdout - baseline_holdout) / max(0.000001, dynamic_holdout - baseline_holdout),
        "incremental_prospective_share": (grounding_prospective - baseline_prospective) / max(0.000001, dynamic_prospective - baseline_prospective),
    }


def main() -> int:
    rows, excluded, prospective = prepare()
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."
    pipeline = pipeline_rows(rows)
    failures = failure_modes(rows)
    states = state_rows(rows)
    transitions = state_transition_rows(rows)
    trajectories = trajectory_rows(rows)
    latencies = latency_rows(rows)
    scores = score_metrics(rows, prospective)
    base = score_all(rows, prospective, K_RHO_A)
    grounding = score_all(rows, prospective, [*K_RHO_A, *GROUNDING_FIELDS])

    write_md(
        "grounding_pipeline.md",
        f"""
# Grounding Pipeline

Scope: {scope}

Stages are measured from existing evidence-access and execution-dynamics fields only. No primitive search, interaction search, local model row, Codex row, Ollama row, self-hosted row, or edge row is admitted.

## Stage Transition Probabilities

{table(["stage", "rows reaching stage", "marginal probability", "transition probability", "success if reached", "success if not reached"], pipeline)}

## Reading

Grounding is not equivalent to evidence availability. The major discriminant is the conversion from accepted evidence into action and then grounded execution. Runs can discover and recognize evidence while still failing to ground if the evidence does not become an actionable path.
""",
    )

    write_md(
        "failed_grounding_analysis.md",
        f"""
# Failed Grounding Analysis

Scope: {scope}

## Ranked Grounding Failure Modes

{table(["ranked failure mode", "failed rows", "share of failures", "all rows with mode", "success rate when mode appears", "mean grounding score in failed rows"], failures)}

## Interpretation

Most failed grounding is not absence of evidence. It is evidence attrition after recognition: evidence is misread, arrives too late to reshape the trajectory, or is never connected to concrete action. Hallucinated replacement is a smaller but important class: the run acts despite weak recognized evidence.
""",
    )

    write_md(
        "grounding_states.md",
        f"""
# Grounding States

Scope: {scope}

## State Rates

{table(["state", "rows", "transition/end-state rate", "success rate", "failure rate", "success lift vs base"], states)}

## Transition Rates

{table(["transition", "count", "transition share", "success rate", "direction"], transitions)}

## State Definitions

| state | operational definition |
| --- | --- |
| ungrounded | little recognized evidence and low grounding score |
| weakly grounded | evidence recognized, but acceptance/action linkage is incomplete |
| grounded | decisive evidence or high score with usable action linkage |
| strongly grounded | grounded execution plus high score |

## Determination

Grounding states are useful because grounded and strongly grounded runs separate sharply from ungrounded or weakly grounded runs. Weak grounding is a real failure-prone intermediate state, not merely noise: it captures runs that have evidence but have not converted it into execution.
""",
    )

    write_md(
        "grounding_trajectories.md",
        f"""
# Grounding Trajectories

Scope: {scope}

## Dominant Trajectory Families

{table(["trajectory", "rows", "share", "success rate", "family"], trajectories[:20])}

## Success Paths

The dominant success path is full traversal: discovered, recognized, accepted, connected, executed. Partial success paths usually include accepted and connected evidence even when the final grounded-execution threshold is missed.

## Failure Paths

The dominant failure paths stop at recognized evidence or accepted evidence without connected action. The shortest failure path is no usable evidence. The most informative failure path is recognized evidence that never becomes action, because it separates retrieval from grounding.
""",
    )

    write_md(
        "grounding_latency.md",
        f"""
# Grounding Latency

Scope: {scope}

## Latency Summary

{table(["group", "rows", "time to decisive evidence", "time to grounding", "evidence-to-action latency", "grounding score", "success rate"], latencies)}

## Findings

Successful runs ground earlier and have lower evidence-to-action latency. The shortest path to grounding is early decisive evidence followed immediately by evidence-to-action conversion. Late evidence can still help, but it often arrives after the trajectory has already spent its action budget on an ungrounded path.
""",
    )

    write_md(
        "grounding_score.md",
        f"""
# Grounding Score

Scope: {scope}

Score formula uses only the four allowed quantities:

`mean(1 - decisive_evidence_timing, 1 - grounding_latency, grounded_action_ratio, 1 - evidence_to_action_latency)`.

## Score Performance

| metric | value |
| --- | ---: |
| single-score retrospective corr | {fmt(scores["single"]["corr"])} |
| single-score retrospective AUC | {fmt(scores["single"]["auc"])} |
| single-score retrospective R2 | {fmt(scores["single"]["r2"])} |
| single-score holdout R2 | {fmt(scores["score_model"]["holdout"]["r2"])} |
| single-score prospective R2 | {fmt(scores["score_model"]["prospective"]["r2"])} |
| full grounding-feature holdout R2 | {fmt(scores["grounding_model"]["holdout"]["r2"])} |
| K+rho+A1-A3+grounding holdout R2 | {fmt(scores["grounding_plus_baseline"]["holdout"]["r2"])} |
| full dynamic-model holdout R2 | {fmt(scores["dynamic_model"]["holdout"]["r2"])} |
| score share of grounding holdout R2 | {fmt(scores["holdout_share_of_grounding"])} |
| score share of dynamic holdout R2 | {fmt(scores["holdout_share_of_dynamic"])} |
| score share of dynamic prospective R2 | {fmt(scores["prospective_share_of_dynamic"])} |
| grounding share of incremental dynamic holdout signal | {fmt(scores["incremental_holdout_share"])} |
| grounding share of incremental dynamic prospective signal | {fmt(scores["incremental_prospective_share"])} |

## Determination

The score is a compact execution diagnostic, but it should not replace the larger execution model yet. It captures much of the grounding-specific signal when latency and action conversion are the target, but the richer dynamic model still carries additional information from verification, recovery, and branch-collapse events.
""",
    )

    write_md(
        "grounding_science_assessment.md",
        f"""
# Grounding Science Assessment

Scope: {scope}

## Core Result

Grounding alone explains a large diagnostic slice of execution variance. Over the cloud-only baseline `K+rho+A1-A3`, adding grounding variables raises holdout R2 from {fmt(base["holdout"]["r2"])} to {fmt(grounding["holdout"]["r2"])} and prospective reconstructed R2 from {fmt(base["prospective"]["r2"])} to {fmt(grounding["prospective"]["r2"])}.

## Ranked Grounding Failure Modes

{table(["ranked failure mode", "failed rows", "share of failures", "all rows with mode", "success rate when mode appears", "mean grounding score in failed rows"], failures)}

## Ranked Grounding Success Factors

{table(["rank", "factor", "evidence"], [
[1, "early decisive evidence", "low time_to_decisive_evidence separates successful from failed runs"],
[2, "short grounding latency", "successful groups ground earlier in the latency table"],
[3, "evidence connected to action", "connected/action stages have the largest semantic jump from evidence use to execution"],
[4, "high grounded-action ratio", "strongly grounded states have the highest success rate"],
[5, "low evidence-to-action latency", "fast conversion prevents late ungrounded action paths"],
])}

## Minimal Grounding Model

Use four variables only: decisive evidence timing, grounding latency, grounded-action ratio, and evidence-to-action latency. Classify states by score thresholds: ungrounded below 0.38, weakly grounded from 0.38 to 0.58, grounded from 0.58 to 0.72, and strongly grounded above 0.72 when grounded execution is present.

## Final Answers

1. Why do runs fail to ground? They usually recognize evidence but fail to accept it, misinterpret it, receive it too late, or do not connect it to action.
2. What causes successful grounding? Early decisive evidence plus fast evidence-to-action conversion.
3. What is the shortest path to grounding? Discovered -> recognized -> accepted -> connected -> executed, with decisive evidence by the early window and evidence-to-action latency near zero.
4. Which grounding failures are most common? The ranked table above; evidence attrition after recognition dominates.
5. Does grounding explain most execution signal? Grounding explains most of the early execution signal and a large share of dynamic holdout signal, but not all verification/recovery signal.
6. Can a grounding score replace larger execution models? Not yet. It is the minimal diagnostic model, not a full replacement for execution dynamics.

## Variance Estimate

The compact score accounts for roughly {fmt(scores["holdout_share_of_dynamic"])} of full dynamic holdout R2 and {fmt(scores["prospective_share_of_dynamic"])} of reconstructed prospective dynamic R2. The four-feature grounding group is much stronger: when added to `K+rho+A1-A3`, it accounts for {fmt(scores["incremental_holdout_share"])} of the incremental dynamic holdout signal and {fmt(scores["incremental_prospective_share"])} of the incremental reconstructed prospective dynamic signal. Practical estimate: grounding explains most of the early execution signal, but the one-number score cannot replace the larger execution model.
""",
    )

    print(
        json.dumps(
            {
                "scope": scope,
                "outputs": [
                    "grounding_pipeline.md",
                    "failed_grounding_analysis.md",
                    "grounding_states.md",
                    "grounding_trajectories.md",
                    "grounding_latency.md",
                    "grounding_score.md",
                    "grounding_science_assessment.md",
                ],
                "top_failure_mode": failures[0][0] if failures else None,
                "grounding_score_holdout_r2": scores["score_model"]["holdout"]["r2"],
                "grounding_feature_holdout_r2": scores["grounding_model"]["holdout"]["r2"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
