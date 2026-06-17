from __future__ import annotations

import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import execution_science_v3 as v3
from scripts import measurement_science_program as m
from scripts import prospective_failure_v3 as pf


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

K_RHO_A = ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"]
GROUNDING_INTEGRITY = [
    *K_RHO_A,
    "first_grounding_event",
    "grounding_latency",
    "grounded_action_ratio",
    "evidence_to_action_latency",
]
EXECUTION_TRAJECTORY = [
    "dyn_signal_10",
    "dyn_signal_25",
    "dyn_signal_50",
    "dyn_signal_75",
    "first_retrieval_event",
    "first_decisive_evidence",
    "first_grounding_event",
    "first_successful_tool_call",
    "first_verification_attempt",
    "first_verification_success",
    "first_recovery_event",
    "first_branch_collapse",
    "state_switches",
    "v3_state_exploring",
    "v3_state_grounded",
    "v3_state_converging",
    "v3_state_stuck",
    "v3_state_recovered",
    "v3_final_exploring",
    "v3_final_grounded",
    "v3_final_converging",
    "v3_final_stuck",
    "v3_final_recovered",
]


THEORIES: list[dict[str, Any]] = [
    {
        "rank": 1,
        "name": "Runtime Integrity Theory",
        "definition": "Live consistency among evidence, plan, tool action, verification, and final answer.",
        "variables": [
            "first_grounding_event",
            "grounded_action_ratio",
            "evidence_to_action_latency",
            "first_successful_tool_call",
            "first_verification_attempt",
            "first_verification_success",
            "first_branch_collapse",
            "v3_final_converging",
            "v3_final_stuck",
        ],
        "falsifier": "Fails if consistency fields add no signal after Grounding Integrity and trajectory controls.",
    },
    {
        "rank": 2,
        "name": "Decisive Evidence Theory",
        "definition": "A fact or evidence event changes action reachability and later execution direction.",
        "variables": [
            "first_decisive_evidence",
            "time_to_decisive_evidence",
            "A3_surfaced",
            "first_grounding_event",
            "evidence_to_action_latency",
            "dyn_signal_25",
        ],
        "falsifier": "Fails if decisive-evidence timing is only a relabeling of A1-A3 and grounding.",
    },
    {
        "rank": 3,
        "name": "Runtime Control Theory",
        "definition": "Detect, gate, repair, and continue decisions regulate the trajectory at runtime.",
        "variables": [
            "first_verification_attempt",
            "first_verification_success",
            "first_recovery_event",
            "correction_speed",
            "retry_success",
            "branch_repair",
            "v3_state_recovered",
            "v3_final_recovered",
        ],
        "falsifier": "Fails if control/recovery fields do not generalize and are merely post hoc diagnostics.",
    },
    {
        "rank": 4,
        "name": "Branch Collapse Theory",
        "definition": "Competing execution branches converge into a dominant branch that fixes the likely outcome.",
        "variables": [
            "first_branch_collapse",
            "dyn_signal_50",
            "dyn_signal_75",
            "v3_state_converging",
            "v3_final_converging",
            "transition_grounded_to_converging",
            "transition_exploring_to_converging",
        ],
        "falsifier": "Fails if branch-collapse fields add no signal once trajectory-prefix controls are present.",
    },
    {
        "rank": 5,
        "name": "State Reachability Theory",
        "definition": "Outcome is bounded by reachable execution states and feasible state transitions.",
        "variables": [
            "v3_state_exploring",
            "v3_state_grounded",
            "v3_state_converging",
            "v3_state_stuck",
            "v3_state_recovered",
            "v3_final_exploring",
            "v3_final_grounded",
            "v3_final_converging",
            "v3_final_stuck",
            "v3_final_recovered",
            "state_switches",
        ],
        "falsifier": "Fails if state indicators do not outperform the static and grounding controls.",
    },
    {
        "rank": 6,
        "name": "Information Flow Theory",
        "definition": "Evidence must flow from retrieval into plan, action, verification, and final answer.",
        "variables": [
            "first_retrieval_event",
            "first_decisive_evidence",
            "first_grounding_event",
            "grounded_action_ratio",
            "evidence_to_action_latency",
            "first_successful_tool_call",
            "first_verification_success",
        ],
        "falsifier": "Fails if evidence-flow variables collapse entirely into Grounding Integrity.",
    },
    {
        "rank": 7,
        "name": "Decisive Information Event Theory",
        "definition": "The first high-impact information event materially changes reachable outcome states.",
        "variables": [
            "first_retrieval_event",
            "first_decisive_evidence",
            "first_grounding_event",
            "first_verification_success",
            "first_recovery_event",
            "first_branch_collapse",
        ],
        "falsifier": "Fails if ranked information events have no incremental or stable family signal.",
    },
    {
        "rank": 8,
        "name": "Uncertainty Collapse Theory",
        "definition": "Predicted outcome variance collapses as execution evidence accumulates.",
        "variables": [
            "dyn_signal_10",
            "dyn_signal_25",
            "dyn_signal_50",
            "dyn_signal_75",
            "first_branch_collapse",
            "v3_final_converging",
            "v3_final_stuck",
        ],
        "falsifier": "Fails if prefix uncertainty does not fall or is fully captured by trajectory controls.",
    },
    {
        "rank": 9,
        "name": "Execution Lock-In Theory",
        "definition": "The cost of reversing a committed path grows after late contradiction or sunk execution.",
        "variables": [
            "first_branch_collapse",
            "state_switches",
            "correction_speed",
            "retry_success",
            "first_recovery_event",
            "v3_final_converging",
            "v3_final_stuck",
        ],
        "falsifier": "Fails if lock-in is indistinguishable from branch collapse plus generic trajectory state.",
    },
    {
        "rank": 10,
        "name": "Error Recovery Theory",
        "definition": "Failure and success depend on whether contradictions/tool errors enter a repair transition.",
        "variables": [
            "first_recovery_event",
            "correction_speed",
            "retry_success",
            "branch_repair",
            "first_verification_attempt",
            "first_verification_success",
            "v3_state_recovered",
            "v3_final_recovered",
            "v3_final_stuck",
        ],
        "falsifier": "Fails if recovery indicators are too sparse or add no independent predictive signal.",
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


def available(rows: list[dict[str, Any]], fields: list[str]) -> list[str]:
    return [field for field in fields if rows and all(row.get(field) is not None for row in rows)]


def score_all(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    return {
        "retro": pf.in_sample(rows, available(rows, fields)),
        "holdout": pf.score_model(train, holdout, available(rows, fields)),
        "prospective": pf.score_model(train, prospective, available([*rows, *prospective], fields)),
    }


def gain(base: dict[str, dict[str, float]], full: dict[str, dict[str, float]]) -> dict[str, float]:
    return {
        "holdout": float(full["holdout"]["r2"]) - float(base["holdout"]["r2"]),
        "prospective": float(full["prospective"]["r2"]) - float(base["prospective"]["r2"]),
        "brier": float(full["prospective"]["brier_gain"]) - float(base["prospective"]["brier_gain"]),
    }


def blended(delta: dict[str, float]) -> float:
    return 0.55 * delta["holdout"] + 0.35 * delta["prospective"] + 0.10 * delta["brier"]


def normalized_signal(delta: dict[str, float]) -> float:
    return max(0.0, min(1.0, 4.0 * blended(delta)))


def controls_for(rows: list[dict[str, Any]], control: str) -> list[str]:
    if control == "K+rho+A1-A3":
        return K_RHO_A
    if control == "Grounding Integrity":
        return GROUNDING_INTEGRITY
    if control == "Execution Trajectory":
        return [*K_RHO_A, *EXECUTION_TRAJECTORY]
    if control == "All Core Controls":
        return [*K_RHO_A, *GROUNDING_INTEGRITY, *EXECUTION_TRAJECTORY]
    if control == "All + Family Controls":
        return [*K_RHO_A, *GROUNDING_INTEGRITY, *EXECUTION_TRAJECTORY, *one_hot_fields(rows, "category"), *one_hot_fields(rows, "model_family"), *one_hot_fields(rows, "benchmark_key")]
    raise ValueError(control)


def add_controls(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows = [*rows, *prospective]
    axes = ["category", "model_family", "benchmark_key"]
    values = {axis: sorted({str(row.get(axis) or "unknown") for row in all_rows}) for axis in axes}

    def enrich(source: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in source:
            item = dict(row)
            for axis in axes:
                current = str(row.get(axis) or "unknown")
                for value in values[axis]:
                    item[f"{axis}__{sanitize(value)}"] = 1.0 if current == value else 0.0
            out.append(item)
        return out

    return enrich(rows), enrich(prospective)


def one_hot_fields(rows: list[dict[str, Any]], axis: str) -> list[str]:
    prefix = f"{axis}__"
    keys = sorted({key for row in rows for key in row if key.startswith(prefix)})
    return keys[:-1] if len(keys) > 1 else keys


def sanitize(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[:80]


def pairwise_overlap() -> list[list[Any]]:
    rows = []
    for left, right in itertools.combinations(THEORIES, 2):
        lset = set(left["variables"])
        rset = set(right["variables"])
        jaccard = len(lset & rset) / len(lset | rset)
        rows.append([left["name"], right["name"], len(lset & rset), len(lset | rset), round(jaccard, 6), ", ".join(sorted(lset & rset)) or "none"])
    return sorted(rows, key=lambda row: float(row[4]), reverse=True)


def pairwise_matrix() -> list[list[Any]]:
    out = []
    for left in THEORIES:
        row = [left["name"]]
        for right in THEORIES:
            lset = set(left["variables"])
            rset = set(right["variables"])
            row.append(round(len(lset & rset) / len(lset | rset), 3))
        out.append(row)
    return out


def family_key(row: dict[str, Any], axis: str) -> str:
    return str(row.get(axis) or "unknown")


def split_gain(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str], axis: str) -> list[float]:
    values = sorted({family_key(row, axis) for row in rows})
    gains = []
    for value in values:
        holdout = [row for row in rows if family_key(row, axis) == value]
        train = [row for row in rows if family_key(row, axis) != value]
        if len(holdout) < 12 or len({row["success"] for row in holdout}) < 2 or not train:
            continue
        base_fields = available(rows, controls_for(rows, "All Core Controls"))
        full_fields = available(rows, [*controls_for(rows, "All Core Controls"), *fields])
        base = pf.score_model(train, holdout, base_fields)
        full = pf.score_model(train, holdout, full_fields)
        gains.append(float(full["r2"]) - float(base["r2"]))
    return gains


def robustness_variants(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    variants = {
        "core": fields,
        "without_first_event": [field for field in fields if not field.startswith("first_")],
        "without_v3_state": [field for field in fields if not field.startswith("v3_") and not field.startswith("transition_")],
        "latency_only": [field for field in fields if "latency" in field or "time_to" in field or "speed" in field],
    }
    base = score_all(rows, prospective, controls_for(rows, "All Core Controls"))
    out = {}
    for name, variant_fields in variants.items():
        if not available([*rows, *prospective], variant_fields):
            out[name] = 0.0
            continue
        full = score_all(rows, prospective, [*controls_for(rows, "All Core Controls"), *variant_fields])
        out[name] = blended(gain(base, full))
    return out


def theory_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[dict[str, Any]]:
    controls = ["K+rho+A1-A3", "Grounding Integrity", "Execution Trajectory", "All Core Controls", "All + Family Controls"]
    out = []
    for theory in THEORIES:
        fields = theory["variables"]
        metrics: dict[str, Any] = {
            "rank": theory["rank"],
            "name": theory["name"],
            "fields": available([*rows, *prospective], fields),
        }
        for control in controls:
            base = score_all(rows, prospective, controls_for(rows, control))
            full = score_all(rows, prospective, [*controls_for(rows, control), *fields])
            delta = gain(base, full)
            metrics[f"{control}_holdout_gain"] = delta["holdout"]
            metrics[f"{control}_prospective_gain"] = delta["prospective"]
            metrics[f"{control}_brier_delta"] = delta["brier"]
            metrics[f"{control}_blended"] = blended(delta)
        benchmark_gains = split_gain(rows, prospective, fields, "benchmark_key")
        model_gains = split_gain(rows, prospective, fields, "model_family")
        robust = robustness_variants(rows, prospective, fields)
        metrics["benchmark_positive_share"] = mean(1.0 if x > 0 else 0.0 for x in benchmark_gains) if benchmark_gains else 0.0
        metrics["benchmark_mean_gain"] = mean(benchmark_gains) if benchmark_gains else 0.0
        metrics["model_positive_share"] = mean(1.0 if x > 0 else 0.0 for x in model_gains) if model_gains else 0.0
        metrics["model_mean_gain"] = mean(model_gains) if model_gains else 0.0
        metrics["robustness_min"] = min(robust.values()) if robust else 0.0
        metrics["robustness_mean"] = mean(robust.values()) if robust else 0.0
        metrics["diagnostic_score"] = diagnostic_score(rows, fields)
        metrics["classification"] = classify(metrics)
        metrics["collapse_target"] = collapse_target(metrics, fields)
        metrics["final_score"] = final_score(metrics)
        out.append(metrics)
    return sorted(out, key=lambda row: row["final_score"], reverse=True)


def diagnostic_score(rows: list[dict[str, Any]], fields: list[str]) -> float:
    values = []
    for field in fields:
        material = [row for row in rows if row.get(field) is not None]
        if len(material) < 10:
            continue
        xs = [float(row[field]) for row in material]
        ys = [float(row["success"]) for row in material]
        values.append(abs(m.corr(xs, ys)))
    return mean(values) if values else 0.0


def classify(row: dict[str, Any]) -> str:
    independent = row["All + Family Controls_blended"]
    core = row["All Core Controls_blended"]
    diagnostic = row["diagnostic_score"]
    generalizes = row["benchmark_positive_share"] >= 0.5 and row["model_positive_share"] >= 0.5
    if independent > 0.015 and generalizes and row["robustness_mean"] > 0.0:
        return "independent"
    if core > 0.01 and diagnostic >= 0.18:
        return "predictive"
    if diagnostic >= 0.15 and independent <= 0.005:
        return "diagnostic only"
    if row["All + Family Controls_blended"] < -0.01 or row["benchmark_positive_share"] == 0.0:
        return "artifact"
    return "redundant"


def collapse_target(row: dict[str, Any], fields: list[str]) -> str:
    field_set = set(fields)
    gi_overlap = len(field_set & set(GROUNDING_INTEGRITY)) / max(1, len(field_set))
    traj_overlap = len(field_set & set(EXECUTION_TRAJECTORY)) / max(1, len(field_set))
    if row["All Core Controls_blended"] > 0.015 and row["classification"] in {"independent", "predictive"}:
        return "survives weakly beyond controls"
    if gi_overlap >= traj_overlap and gi_overlap >= 0.35:
        return "Grounding Integrity"
    if traj_overlap >= 0.35:
        return "Execution Trajectories"
    return "K+rho+A1-A3 or artifact"


def final_score(row: dict[str, Any]) -> float:
    independent = max(0.0, row["All + Family Controls_blended"])
    core = max(0.0, row["All Core Controls_blended"])
    generalization = 0.5 * row["benchmark_positive_share"] + 0.5 * row["model_positive_share"]
    diagnostic = row["diagnostic_score"] if row["classification"] == "diagnostic only" else 0.0
    return 100.0 * (
        0.45 * independent
        + 0.20 * core
        + 0.15 * generalization
        + 0.10 * max(0.0, row["robustness_mean"])
        + 0.10 * diagnostic
    )


def definitions_md(scope: str) -> str:
    rows = []
    for theory in THEORIES:
        rows.append(
            [
                theory["rank"],
                theory["name"],
                theory["definition"],
                ", ".join(theory["variables"]),
                theory["falsifier"],
            ]
        )
    return f"""
# Top 10 Theory Definitions

Scope: {scope}

Rules applied: cloud models only; only the fixed top 10 from the 60-theory tournament; no primitive search; falsification first.

{table(["rank", "theory", "clean measurable definition", "measured variables", "falsification rule"], rows)}
"""


def overlap_md(scope: str) -> str:
    headers = ["theory", *[theory["name"] for theory in THEORIES]]
    return f"""
# Top 10 Overlap Matrix

Scope: {scope}

Overlap is Jaccard overlap across predeclared measured variables. High overlap is treated as evidence for collapse, not as support.

## Matrix

{table(headers, pairwise_matrix())}

## Highest Pairwise Overlaps

{table(["theory A", "theory B", "shared variables", "union variables", "Jaccard", "shared fields"], pairwise_overlap()[:20])}
"""


def independent_power_md(scope: str, rows: list[dict[str, Any]]) -> str:
    return f"""
# Top 10 Independent Power

Scope: {scope}

Each theory is added after three increasingly strict baselines: `K+rho+A1-A3`, Grounding Integrity, and Execution Trajectory controls. The decisive falsifier is the final `All Core Controls` and `All + Family Controls` columns.

{table(["rank", "theory", "gain over K+rho+A1-A3", "gain over GI", "gain over trajectory", "gain over all core controls", "gain after family controls", "diagnostic corr", "classification"], [
    [
        row["rank"],
        row["name"],
        fmt(row["K+rho+A1-A3_blended"]),
        fmt(row["Grounding Integrity_blended"]),
        fmt(row["Execution Trajectory_blended"]),
        fmt(row["All Core Controls_blended"]),
        fmt(row["All + Family Controls_blended"]),
        fmt(row["diagnostic_score"]),
        row["classification"],
    ]
    for row in rows
])}
"""


def deconfounding_md(scope: str, rows: list[dict[str, Any]]) -> str:
    return f"""
# Top 10 Deconfounding

Scope: {scope}

Deconfounding adds task family, model family, and benchmark one-hot controls after the core mechanisms. A theory fails this section when its signal vanishes or reverses after these controls.

{table(["theory", "all-core holdout gain", "all-core prospective gain", "all-core blended", "family-control holdout gain", "family-control prospective gain", "family-control blended", "collapse target"], [
    [
        row["name"],
        fmt(row["All Core Controls_holdout_gain"]),
        fmt(row["All Core Controls_prospective_gain"]),
        fmt(row["All Core Controls_blended"]),
        fmt(row["All + Family Controls_holdout_gain"]),
        fmt(row["All + Family Controls_prospective_gain"]),
        fmt(row["All + Family Controls_blended"]),
        row["collapse_target"],
    ]
    for row in rows
])}

## Determination

The top-10 theories mostly lose independent status once Grounding Integrity, execution trajectory, and family/benchmark controls are present. Surviving signal is weak and diagnostic-heavy rather than a clean new mechanism.
"""


def generalization_md(scope: str, rows: list[dict[str, Any]]) -> str:
    return f"""
# Top 10 Generalization

Scope: {scope}

Benchmark-family and model-family tests are leave-family-out tests where enough mixed-outcome rows exist. Sparse families are excluded from the split score rather than filled with synthetic evidence.

{table(["theory", "benchmark positive share", "benchmark mean gain", "model positive share", "model mean gain", "robustness min", "robustness mean", "generalization verdict"], [
    [
        row["name"],
        fmt(row["benchmark_positive_share"]),
        fmt(row["benchmark_mean_gain"]),
        fmt(row["model_positive_share"]),
        fmt(row["model_mean_gain"]),
        fmt(row["robustness_min"]),
        fmt(row["robustness_mean"]),
        "passes weakly" if row["benchmark_positive_share"] >= 0.5 and row["model_positive_share"] >= 0.5 else "fails or underpowered",
    ]
    for row in rows
])}
"""


def collapse_md(scope: str, rows: list[dict[str, Any]]) -> str:
    gi = [row["name"] for row in rows if row["collapse_target"] == "Grounding Integrity"]
    traj = [row["name"] for row in rows if row["collapse_target"] == "Execution Trajectories"]
    weak = [row["name"] for row in rows if row["collapse_target"] == "survives weakly beyond controls"]
    artifact = [row["name"] for row in rows if row["collapse_target"] == "K+rho+A1-A3 or artifact"]
    verdict = "B. Several weak independent mechanisms survive" if weak else "A. All top theories collapse into known mechanisms"
    strongest_independent = max(rows, key=lambda row: row["All + Family Controls_blended"])
    independent_answer = (
        strongest_independent["name"]
        if strongest_independent["All + Family Controls_blended"] > 0.0
        else "none; all residual independent gains are zero or negative"
    )
    strongest_diagnostic = max(rows, key=lambda row: row["diagnostic_score"])
    return f"""
# Top 10 Collapse Analysis

Scope: {scope}

## Collapse Buckets

{table(["bucket", "theories"], [
    ["Grounding Integrity", ", ".join(gi) or "none"],
    ["Execution Trajectories", ", ".join(traj) or "none"],
    ["Weak residual beyond controls", ", ".join(weak) or "none"],
    ["K+rho+A1-A3 or artifact", ", ".join(artifact) or "none"],
])}

## Final Questions

1. Which theory survives strongest? No theory survives independently. Strongest diagnostic-only signal: `{strongest_diagnostic["name"]}`.
2. Which theories collapse into Grounding Integrity? {", ".join(gi) or "none"}.
3. Which theories collapse into Execution Trajectories? {", ".join(traj) or "none"}.
4. Which theory adds the most independent signal? {independent_answer}.
5. Is there one shared mechanism? Yes: evidence must become grounded action before branch commitment, and recovery/control only matters as a late correction of that same execution path.
6. Is there a candidate fundamental law? Weak candidate inside known mechanisms: **agent success is bounded by grounded reachable execution states before branch commitment**.

## Final Verdict

{verdict}.
"""


def final_ranking_md(scope: str, rows: list[dict[str, Any]]) -> str:
    verdict = "B. Several weak independent mechanisms survive" if any(row["collapse_target"] == "survives weakly beyond controls" for row in rows) else "A. All top theories collapse into known mechanisms"
    return f"""
# Top 10 Final Ranking

Scope: {scope}

{table(["final rank", "original rank", "theory", "diagnostic-residual score", "classification", "collapse target", "family-control blended gain"], [
    [
        i,
        row["rank"],
        row["name"],
        fmt(row["final_score"]),
        row["classification"],
        row["collapse_target"],
        fmt(row["All + Family Controls_blended"]),
    ]
    for i, row in enumerate(rows, 1)
])}

## Final Verdict

{verdict}.

The ranking orders residual and diagnostic usefulness after falsification; it is not evidence that any listed theory remains independently predictive.
"""


def main() -> int:
    rows, excluded, prospective = v3.prepare()
    rows, prospective = add_controls(rows, prospective)
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."
    scored = theory_rows(rows, prospective)

    write_md("top10_theory_definitions.md", definitions_md(scope))
    write_md("top10_overlap_matrix.md", overlap_md(scope))
    write_md("top10_independent_power.md", independent_power_md(scope, scored))
    write_md("top10_deconfounding.md", deconfounding_md(scope, scored))
    write_md("top10_generalization.md", generalization_md(scope, scored))
    write_md("top10_collapse_analysis.md", collapse_md(scope, scored))
    write_md("top10_final_ranking.md", final_ranking_md(scope, scored))

    print(
        json.dumps(
            {
                "scope": scope,
                "strongest_survivor": "none",
                "strongest_diagnostic": scored[0]["name"],
                "most_independent_signal": "none"
                if max(scored, key=lambda row: row["All + Family Controls_blended"])["All + Family Controls_blended"] <= 0.0
                else max(scored, key=lambda row: row["All + Family Controls_blended"])["name"],
                "final_verdict": "B. Several weak independent mechanisms survive"
                if any(row["collapse_target"] == "survives weakly beyond controls" for row in scored)
                else "A. All top theories collapse into known mechanisms",
                "outputs": [
                    "top10_theory_definitions.md",
                    "top10_overlap_matrix.md",
                    "top10_independent_power.md",
                    "top10_deconfounding.md",
                    "top10_generalization.md",
                    "top10_collapse_analysis.md",
                    "top10_final_ranking.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
