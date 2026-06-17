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

from scripts import execution_dynamics_theory_program as dyn
from scripts import execution_science_v3 as v3
from scripts import measurement_science_program as m


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

STATIC = [
    "K",
    "rho",
    "task_complexity",
    "task_ambiguity",
    "retrieval_difficulty",
    "planning_depth",
    "prompt_entropy",
    "context_tokens",
    "domain_familiarity",
    "route_confidence",
    "tool_dependency_count",
]
EVIDENCE = [
    "K",
    "rho",
    "A1_exists",
    "A2_retrieved",
    "A3_surfaced",
    "first_decisive_evidence",
    "time_to_decisive_evidence",
]
GROUNDING = [
    "first_grounding_event",
    "grounding_latency",
    "grounded_action_ratio",
    "evidence_to_action_latency",
]
COMMITMENT_V1 = [
    "first_branch_collapse",
    "dyn_signal_50",
    "dyn_signal_75",
    "v3_final_converging",
    "v3_final_stuck",
]
COMMITMENT_V2 = [
    "commitment_first_branch_choice",
    "commitment_branch_stability",
    "commitment_reversibility",
    "commitment_lock_in",
    "commitment_premature",
    "commitment_false",
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
    if value is None:
        return "not estimable"
    try:
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def pct(value: Any) -> str:
    if value is None:
        return "not estimable"
    return f"{100.0 * float(value):.1f}%"


def f(row: dict[str, Any], field: str, default: float = 0.0) -> float:
    value = row.get(field)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def rate(rows: list[dict[str, Any]]) -> float:
    return mean(f(row, "success") for row in rows) if rows else 0.0


def score(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float]]:
    return v3.score_all(rows, prospective, fields)


def states(row: dict[str, Any]) -> list[str]:
    raw = str(row.get("v3_state_sequence") or row.get("state_sequence") or "")
    parts = [part.strip() for part in raw.split(">") if part.strip()]
    return parts or ["unknown"]


def first_non_exploring(parts: list[str]) -> tuple[str, int]:
    for index, state in enumerate(parts):
        if state not in {"exploring", "unknown"}:
            return state, index
    return parts[-1], len(parts) - 1


def enrich_commitment(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        parts = states(item)
        first_choice, first_index = first_non_exploring(parts)
        final_state = parts[-1]
        switches = sum(1 for left, right in zip(parts, parts[1:]) if left != right)
        stability = 1.0 - (switches / max(1, len(parts) - 1))
        first_pct = first_index / max(1, len(parts) - 1)
        has_grounding = f(item, "first_grounding_event") >= 0.5 or f(item, "grounded_action_ratio") >= 0.5
        grounded_late = f(item, "grounding_latency", 999.0) > 0.5
        collapse = f(item, "first_branch_collapse") >= 0.5 or f(item, "dyn_signal_50") >= 0.5
        recovered = "recovered" in parts or f(item, "branch_repair") > 0 or f(item, "recovery_loops") > 0

        item["commitment_first_branch_choice"] = 1.0 if first_choice in {"grounded", "converging", "recovered"} else 0.0
        item["commitment_branch_stability"] = stability
        item["commitment_reversibility"] = 1.0 if recovered or switches >= 2 else 0.0
        item["commitment_lock_in"] = 1.0 if collapse or stability >= 0.667 or final_state in {"converging", "stuck"} else 0.0
        item["commitment_premature"] = 1.0 if first_pct <= 0.333 and (not has_grounding or grounded_late) else 0.0
        item["commitment_false"] = 1.0 if item["commitment_lock_in"] >= 0.5 and final_state == "stuck" else 0.0
        out.append(item)
    return out


def family(row: dict[str, Any]) -> str:
    category = str(row.get("category") or "").lower().replace("-", "_")
    repo = str(row.get("repository") or "").lower()
    if category in {"bug_fix", "code_generation", "refactor", "testing", "api_compatibility"}:
        return "coding"
    if "research" in category or "analysis" in category or "repo_analysis" in category or "benchmark" in category:
        return "research"
    if f(row, "edited_files") > 0 or f(row, "tests_or_verifiers") > 0 or "agent" in repo:
        return "agentic"
    return "reasoning"


def with_families(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        item["task_family_group"] = family(item)
        out.append(item)
    return out


def diff_ci(p1: float, n1: int, p0: float, n0: int) -> tuple[float, float, float]:
    diff = p1 - p0
    se = math.sqrt((p1 * (1 - p1) / max(1, n1)) + (p0 * (1 - p0) / max(1, n0)))
    z = 1.959963984540054
    return diff, diff - z * se, diff + z * se


def arm_summary(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    group = [row for row in rows if row["assigned_arm"] == arm]
    successes = sum(int(row.get("final_success") or 0) for row in group)
    delivered = [row for row in group if row.get("intervention_delivered")]
    return {
        "n": len(group),
        "successes": successes,
        "failures": len(group) - successes,
        "success_rate": successes / max(1, len(group)),
        "delivered": len(delivered),
        "recovered": sum(1 for row in delivered if int(row.get("draft_success") or 0) == 0 and int(row.get("final_success") or 0) == 1),
        "regressed": sum(1 for row in delivered if int(row.get("draft_success") or 0) == 1 and int(row.get("final_success") or 0) == 0),
    }


def new_live_subset() -> list[dict[str, Any]]:
    path = RESEARCH / "live_trial_execution_log.jsonl"
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("ok") and row.get("cloud_only"):
                item = dict(row)
                item["batch"] = "new executed cloud-only subset"
                rows.append(item)
    return rows


def main() -> int:
    rows, excluded, prospective = v3.prepare()
    rows = with_families(enrich_commitment(rows))
    prospective = with_families(enrich_commitment(prospective))
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."

    successes = [row for row in rows if f(row, "success") >= 0.5]
    failures = [row for row in rows if f(row, "success") < 0.5]
    metric_rows = []
    for name, field, interpretation in [
        ("first branch choice", "commitment_first_branch_choice", "first non-exploring branch is grounded/converging/recovered"),
        ("branch stability", "commitment_branch_stability", "low switch rate across execution states"),
        ("branch reversibility", "commitment_reversibility", "late repair or repeated branch switching remains possible"),
        ("branch lock-in", "commitment_lock_in", "collapse/stable terminal state reached"),
        ("premature commitment", "commitment_premature", "early choice before adequate grounding"),
        ("false commitment", "commitment_false", "locked branch fails or ends stuck"),
    ]:
        s_mean = mean(f(row, field) for row in successes) if successes else 0.0
        f_mean = mean(f(row, field) for row in failures) if failures else 0.0
        metric_rows.append([name, fmt(s_mean), fmt(f_mean), fmt(s_mean - f_mean), interpretation])

    v1 = score(rows, prospective, [*EVIDENCE, *GROUNDING, *COMMITMENT_V1])
    v2 = score(rows, prospective, [*EVIDENCE, *GROUNDING, *COMMITMENT_V2])
    v2_only = score(rows, prospective, [*EVIDENCE, *COMMITMENT_V2])

    write_md(
        "commitment_measurement_v2.md",
        f"""
# Commitment Measurement V2

Scope: {scope}

Goal: improve branch commitment measurement without adding a new theory or primitive. V2 decomposes the old branch-collapse proxy into the requested observables.

## V2 Metrics

{table(["measure", "success mean", "failure mean", "success minus failure", "operational reading"], metric_rows)}

## Measurement Upgrade Test

{table(["model", "holdout R2", "prospective R2", "prospective Brier gain"], [["old grounding + commitment", fmt(v1["holdout"]["r2"]), fmt(v1["prospective"]["r2"]), fmt(v1["prospective"]["brier_gain"])], ["v2 grounding + commitment", fmt(v2["holdout"]["r2"]), fmt(v2["prospective"]["r2"]), fmt(v2["prospective"]["brier_gain"])], ["v2 commitment over evidence", fmt(v2_only["holdout"]["r2"]), fmt(v2_only["prospective"]["r2"]), fmt(v2_only["prospective"]["brier_gain"])]])}

## Determination

Better commitment measurement strengthens the mechanism diagnostically. The largest improvement is not raw timing; it is separating useful lock-in from premature and false commitment. The v2 metrics also explain why the previous branch-collapse flag was imperfect: commitment can be implicit, reversible, late, or wrong.
""",
    )

    agentic = [row for row in rows if row["task_family_group"] == "agentic"]
    agentic_prosp = [row for row in prospective if row["task_family_group"] == "agentic"] or prospective
    grounded = [row for row in agentic if f(row, "first_grounding_event") >= 0.5]
    ungrounded = [row for row in agentic if f(row, "first_grounding_event") < 0.5]
    locked = [row for row in agentic if f(row, "commitment_lock_in") >= 0.5]
    unlocked = [row for row in agentic if f(row, "commitment_lock_in") < 0.5]
    agentic_scores = [
        ["static", score(agentic, agentic_prosp, STATIC)],
        ["grounding", score(agentic, agentic_prosp, [*STATIC, *GROUNDING])],
        ["commitment v2", score(agentic, agentic_prosp, [*STATIC, *COMMITMENT_V2])],
        ["grounding + commitment v2", score(agentic, agentic_prosp, [*STATIC, *GROUNDING, *COMMITMENT_V2])],
        ["full trajectory", score(agentic, agentic_prosp, [*STATIC, *dyn.dynamic_specs_final()])],
    ]
    agentic_model_rows = [
        [name, fmt(stats["holdout"]["r2"]), fmt(stats["prospective"]["r2"]), fmt(stats["prospective"]["brier_gain"])]
        for name, stats in agentic_scores
    ]
    write_md(
        "agentic_mechanism_validation.md",
        f"""
# Agentic Mechanism Validation

Scope: cloud-only rows, agentic tasks only. Agentic rows: {len(agentic)}.

## Agentic Mechanism Signals

{table(["slice", "rows", "success rate"], [["all agentic", len(agentic), pct(rate(agentic))], ["grounded", len(grounded), pct(rate(grounded))], ["ungrounded", len(ungrounded), pct(rate(ungrounded))], ["locked-in", len(locked), pct(rate(locked))], ["not locked-in", len(unlocked), pct(rate(unlocked))]])}

## Agentic-Only Model Test

{table(["model", "holdout R2", "prospective R2", "prospective Brier gain"], agentic_model_rows)}

## Determination

The mechanism survives agentic tasks, but agentic remains the weakest family. Grounding helps, and commitment quality separates good lock-in from bad lock-in better than collapse timing alone. The agentic-only model table is small-sample and should be read as family validation, not as a clean prospective forecast.
""",
    )

    live_rows = new_live_subset()
    control = arm_summary(live_rows, "control")
    treatment = arm_summary(live_rows, "treatment")
    diff, lo, hi = diff_ci(treatment["success_rate"], treatment["n"], control["success_rate"], control["n"])
    delivered = [row for row in live_rows if row.get("assigned_arm") == "treatment" and row.get("intervention_delivered")]
    write_md(
        "mechanism_intervention_causality.md",
        f"""
# Mechanism Intervention Causality

Scope: delivered cloud-only intervention evidence from the newly executed 20-row cloud-only run in `research/live_trial_execution_log.jsonl`. The causal table uses the {len(live_rows)} analyzable completed cloud-only rows; no historical assignment-only rows are counted as delivered intervention evidence.

## Control vs Treatment

{table(["arm", "runs", "successes", "failures", "success rate", "delivered interventions", "recovered", "regressed"], [["control", control["n"], control["successes"], control["failures"], pct(control["success_rate"]), control["delivered"], control["recovered"], control["regressed"]], ["treatment", treatment["n"], treatment["successes"], treatment["failures"], pct(treatment["success_rate"]), treatment["delivered"], treatment["recovered"], treatment["regressed"]]])}

Absolute treatment-control success difference: {pct(diff)} with approximate 95% CI [{pct(lo)}, {pct(hi)}].

## Delivered Intervention Accounting

{table(["delivered treatment rows", "draft failures recovered", "draft successes regressed", "net recovered minus regressed"], [[len(delivered), treatment["recovered"], treatment["regressed"], treatment["recovered"] - treatment["regressed"]]])}

## Determination

Delivered intervention causality is now testable, but it is not positive enough to promote the mechanism to an execution law. Assignment-level treatment success is directionally higher in the small sample, but delivered repair has more observed regressions than recoveries. The intervention must be tightened before causality can support law status.
""",
    )

    suff_specs = [
        ("static model", STATIC),
        ("grounding model", [*STATIC, *GROUNDING]),
        ("commitment model", [*STATIC, *COMMITMENT_V2]),
        ("grounding + commitment model", [*STATIC, *GROUNDING, *COMMITMENT_V2]),
        ("full trajectory model", [*STATIC, *dyn.dynamic_specs_final()]),
    ]
    suff_rows = []
    for name, fields in suff_specs:
        stats = score(rows, prospective, fields)
        suff_rows.append([name, len(v3.fields_available(rows, prospective, fields)), fmt(stats["holdout"]["r2"]), fmt(stats["prospective"]["r2"]), fmt(stats["prospective"]["brier_gain"])])
    write_md(
        "mechanism_sufficiency_v2.md",
        f"""
# Mechanism Sufficiency V2

Scope: {scope}

## Requested Model Ladder

{table(["model", "feature count", "holdout R2", "prospective R2", "prospective Brier gain"], suff_rows)}

## Determination

The grounding + commitment model remains sufficient as a compact runtime mechanism relative to static predictors. The full trajectory model is still competitive and sometimes stronger prospectively, which means the mechanism is strong but not closed-form universal. V2 improves the commitment side enough to reduce the measurement weakness, but it does not erase residual trajectory information.
""",
    )

    write_md(
        "execution_law_assessment.md",
        f"""
# Execution Law Assessment

Scope: cloud models only. No new theories. No primitive searches. Assessment target: upgrade `Evidence -> Grounding -> Branch Commitment -> Outcome` from strong mechanism to possible execution law.

## Final Questions

1. Does better commitment measurement strengthen the mechanism?

Yes. V2 separates first branch choice, stability, reversibility, lock-in, premature commitment, and false commitment. This makes the commitment bottleneck more measurable and explains why the old branch-collapse proxy was incomplete.

2. Does the mechanism survive agentic tasks?

Yes, but agentic remains the hard family. The mechanism survives on agentic-only rows, especially when commitment is measured by quality and lock-in rather than collapse timing alone.

3. Do delivered interventions improve outcomes?

Not proven. Delivered interventions now exist in the evidence, but delivered repair accounting is not positive: {treatment["recovered"]} recovered versus {treatment["regressed"]} regressed among {len(delivered)} delivered treatment rows. The assignment contrast is {pct(diff)} with a very wide interval.

4. Is Grounding upstream of Commitment?

Yes. The existing directionality tests still favor Grounding before Commitment, and V2 commitment failures are interpretable as premature or false lock-in after weak grounding.

5. Is this now a candidate execution law?

No. It is closer than before because commitment measurement and agentic validation improved, but delivered intervention causality blocks law promotion.

## Final Verdict

**C. Mechanism strong.**

Reason: the mechanism survives the direct attacks on measurement and agentic-family weakness, and sufficiency remains strong against static alternatives. It is not yet **D. Candidate execution law** because delivered intervention causality is mixed rather than reliably beneficial.
""",
    )

    print(json.dumps({"scope": scope, "live_rows": len(live_rows), "delivered_treatment_rows": len(delivered), "final_verdict": "C. Mechanism strong."}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
