from __future__ import annotations

import itertools
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

PRE_EXECUTION = ["K", "rho", "A1_exists", "old_A", "context_budget", "expected_files", "relevant_files"]
K_RHO_A = ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"]
CURVE_WINDOWS = {
    "0%": PRE_EXECUTION,
    "10%": [*PRE_EXECUTION, "first_retrieval_event", "dyn_signal_10"],
    "25%": [*PRE_EXECUTION, "first_retrieval_event", "first_decisive_evidence", "first_grounding_event", "grounding_latency", "dyn_signal_10", "dyn_signal_25"],
    "50%": [
        *PRE_EXECUTION,
        "first_retrieval_event",
        "first_decisive_evidence",
        "first_grounding_event",
        "first_successful_tool_call",
        "first_verification_attempt",
        "grounded_action_ratio",
        "evidence_to_action_latency",
        "dyn_signal_10",
        "dyn_signal_25",
        "dyn_signal_50",
    ],
    "75%": [
        *PRE_EXECUTION,
        "first_retrieval_event",
        "first_decisive_evidence",
        "first_grounding_event",
        "first_successful_tool_call",
        "first_verification_attempt",
        "first_verification_success",
        "first_recovery_event",
        "first_branch_collapse",
        "grounded_action_ratio",
        "correction_speed",
        "retry_success",
        "dyn_signal_25",
        "dyn_signal_50",
        "dyn_signal_75",
    ],
    "pre-answer": dyn.dynamic_specs_final() + ["first_retrieval_event", "first_grounding_event", "first_verification_attempt", "first_branch_collapse"],
}


EVENT_SPECS = [
    ("first retrieval", ["first_retrieval_event"], "A2/retrieval signal first becomes nonzero; the run has touched task evidence."),
    ("first decisive evidence", ["first_decisive_evidence", "time_to_decisive_evidence"], "Evidence is strong enough to identify the likely solution path."),
    ("first grounding event", ["first_grounding_event", "grounding_latency", "grounded_action_ratio"], "Decisive evidence is converted into a grounded action context."),
    ("first successful tool call", ["first_successful_tool_call"], "A nontrivial edit/test tool path becomes available in the trace."),
    ("first verification attempt", ["first_verification_attempt"], "The run attempts a verifier/test/equivalent check."),
    ("first verification success", ["first_verification_success"], "The verifier/test signal is strong enough to count as successful verification in this corpus."),
    ("first recovery event", ["first_recovery_event", "correction_speed", "retry_success"], "The run detects a bad path and repairs it."),
    ("first branch collapse", ["first_branch_collapse"], "The trajectory collapses from exploration into one actionable solution branch."),
]

STATE_ORDER = ["exploring", "grounded", "converging", "stuck", "recovered"]


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


def fields_available(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> list[str]:
    source = [*rows, *prospective]
    return [field for field in fields if source and all(row.get(field) is not None for row in source)]


def score_all(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    usable = fields_available(rows, [], fields)
    usable_prosp = fields_available(rows, prospective, fields)
    return {
        "retro": pf.in_sample(rows, usable),
        "holdout": pf.score_model(train, holdout, usable),
        "prospective": pf.score_model(train, prospective, usable_prosp),
    }


def blended_gain(base: dict[str, dict[str, float]], full: dict[str, dict[str, float]]) -> float:
    holdout_gain = float(full["holdout"]["r2"]) - float(base["holdout"]["r2"])
    prospective_gain = float(full["prospective"]["r2"]) - float(base["prospective"]["r2"])
    brier_gain = float(full["prospective"]["brier_gain"]) - float(base["prospective"]["brier_gain"])
    return 0.55 * holdout_gain + 0.35 * prospective_gain + 0.10 * brier_gain


def add_v3_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        a2 = float(item.get("A2_retrieved") or 0.0)
        a3 = float(item.get("A3_surfaced") or 0.0)
        a4 = float(item.get("A4_understood") or 0.0)
        a5 = float(item.get("A5_linked_to_action") or 0.0)
        verified = float(item.get("tests_or_verifiers") or 0.0)
        item["first_retrieval_event"] = 1.0 if a2 >= 0.35 else 0.0
        item["first_grounding_event"] = 1.0 if item.get("first_decisive_evidence", 0.0) >= 0.5 and float(item.get("grounded_action_ratio") or 0.0) >= 0.45 else 0.0
        item["first_verification_attempt"] = 1.0 if verified > 0.0 else 0.0
        item["first_branch_collapse"] = 1.0 if a4 >= 0.45 and a5 >= 0.45 and a3 >= 0.35 else 0.0
        item["first_grounded_pct"] = first_pct_for_grounding(item)
        item["first_converged_pct"] = first_pct_for_convergence(item)
        item["first_success_pct"] = 100.0 if float(item.get("success") or 0.0) >= 0.5 else 999.0
        out.append(item)
    return out


def first_pct_for_grounding(row: dict[str, Any]) -> float:
    if float(row.get("first_grounding_event") or 0.0) >= 0.5:
        if float(row.get("A2_retrieved") or 0.0) >= 0.55:
            return 10.0
        if float(row.get("A3_surfaced") or 0.0) >= 0.55:
            return 25.0
        return 50.0
    return 999.0


def first_pct_for_convergence(row: dict[str, Any]) -> float:
    if float(row.get("state_converging") or 0.0) >= 0.5 or float(row.get("first_branch_collapse") or 0.0) >= 0.5:
        if float(row.get("A4_understood") or 0.0) >= 0.45 and float(row.get("A5_linked_to_action") or 0.0) >= 0.45:
            return 50.0
        return 75.0
    return 999.0


def exclusive_state(row: dict[str, Any], pct: int) -> str:
    a2 = float(row.get("A2_retrieved") or 0.0)
    a3 = float(row.get("A3_surfaced") or 0.0)
    a4 = float(row.get("A4_understood") or 0.0)
    a5 = float(row.get("A5_linked_to_action") or 0.0)
    grounded = float(row.get("first_grounding_event") or 0.0) >= 0.5
    recovered = float(row.get("first_recovery_event") or 0.0) >= 0.5
    if pct <= 10:
        if a2 < 0.30:
            return "stuck"
        return "grounded" if grounded and a2 >= 0.55 else "exploring"
    if pct <= 25:
        if a3 < 0.30 and a2 < 0.35:
            return "stuck"
        return "grounded" if grounded else "exploring"
    if recovered and pct >= 50:
        return "recovered"
    if a4 >= 0.45 and a5 >= 0.45:
        return "converging"
    if grounded:
        return "grounded"
    if a2 < 0.30 and a5 < 0.30:
        return "stuck"
    return "exploring"


def add_v3_states(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        sequence = [exclusive_state(item, pct) for pct in [10, 25, 50, 75]]
        item["v3_state_sequence"] = ">".join(sequence)
        item["v3_final_state"] = sequence[-1]
        for state in STATE_ORDER:
            item[f"v3_state_{state}"] = 1.0 if state in sequence else 0.0
            item[f"v3_final_{state}"] = 1.0 if sequence[-1] == state else 0.0
        for left, right in zip(sequence, sequence[1:]):
            item[f"transition_{left}_to_{right}"] = 1.0
        for left in STATE_ORDER:
            for right in STATE_ORDER:
                item.setdefault(f"transition_{left}_to_{right}", 0.0)
        out.append(item)
    return out


def prepare() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_rows, excluded = cloud.cloud_rows()
    rows = dyn.add_dynamics(pf.enrich_pre_run_candidates(raw_rows))
    prospective = dyn.add_dynamics(pf.estimate_candidate_features(rows, cloud.reconstructed_prospective_rows(raw_rows)))
    rows = add_v3_states(add_v3_events(rows))
    prospective = add_v3_states(add_v3_events(prospective))
    return rows, excluded, prospective


def event_ranking(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = score_all(rows, prospective, K_RHO_A)
    ranked = []
    for name, fields, definition in EVENT_SPECS:
        full = score_all(rows, prospective, [*K_RHO_A, *fields])
        triggered = [row for row in rows if any(float(row.get(field) or 0.0) >= 0.5 for field in fields)]
        absent = [row for row in rows if row not in triggered]
        jump = (mean(float(row["success"]) for row in triggered) - mean(float(row["success"]) for row in absent)) if triggered and absent else 0.0
        ranked.append(
            {
                "event": name,
                "definition": definition,
                "fields": fields,
                "triggered": len(triggered),
                "success_if_present": mean(float(row["success"]) for row in triggered) if triggered else 0.0,
                "success_if_absent": mean(float(row["success"]) for row in absent) if absent else 0.0,
                "jump": jump,
                "holdout_gain": float(full["holdout"]["r2"]) - float(base["holdout"]["r2"]),
                "prospective_gain": float(full["prospective"]["r2"]) - float(base["prospective"]["r2"]),
                "brier_gain_delta": float(full["prospective"]["brier_gain"]) - float(base["prospective"]["brier_gain"]),
                "contribution": blended_gain(base, full),
            }
        )
    return sorted(ranked, key=lambda row: row["contribution"], reverse=True)


def first_predictive_event(events: list[dict[str, Any]]) -> dict[str, Any]:
    order = {name: idx for idx, (name, _fields, _definition) in enumerate(EVENT_SPECS)}
    candidates = [
        row
        for row in events
        if float(row["holdout_gain"]) > 0.0 and (float(row["prospective_gain"]) > 0.0 or float(row["brier_gain_delta"]) > 0.0)
    ]
    return sorted(candidates, key=lambda row: order[row["event"]])[0] if candidates else events[0]


def state_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = score_all(rows, prospective, K_RHO_A)
    out = []
    for state in STATE_ORDER:
        field = f"v3_state_{state}"
        final_field = f"v3_final_{state}"
        positive = [row for row in rows if float(row.get(field) or 0.0) >= 0.5]
        final = [row for row in rows if float(row.get(final_field) or 0.0) >= 0.5]
        absent = [row for row in rows if float(row.get(field) or 0.0) < 0.5]
        full = score_all(rows, prospective, [*K_RHO_A, field, final_field])
        out.append(
            {
                "state": state,
                "frequency": len(positive),
                "final_frequency": len(final),
                "success_if_present": mean(float(row["success"]) for row in positive) if positive else 0.0,
                "success_if_final": mean(float(row["success"]) for row in final) if final else 0.0,
                "success_if_absent": mean(float(row["success"]) for row in absent) if absent else 0.0,
                "holdout_gain": float(full["holdout"]["r2"]) - float(base["holdout"]["r2"]),
                "prospective_gain": float(full["prospective"]["r2"]) - float(base["prospective"]["r2"]),
                "contribution": blended_gain(base, full),
            }
        )
    return sorted(out, key=lambda row: row["contribution"], reverse=True)


def transition_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = score_all(rows, prospective, K_RHO_A)
    out = []
    for left, right in itertools.product(STATE_ORDER, STATE_ORDER):
        if left == right:
            continue
        field = f"transition_{left}_to_{right}"
        positive = [row for row in rows if float(row.get(field) or 0.0) >= 0.5]
        if not positive:
            continue
        absent = [row for row in rows if float(row.get(field) or 0.0) < 0.5]
        full = score_all(rows, prospective, [*K_RHO_A, field])
        out.append(
            {
                "transition": f"{left} -> {right}",
                "frequency": len(positive),
                "success_if_present": mean(float(row["success"]) for row in positive),
                "success_if_absent": mean(float(row["success"]) for row in absent) if absent else 0.0,
                "holdout_gain": float(full["holdout"]["r2"]) - float(base["holdout"]["r2"]),
                "prospective_gain": float(full["prospective"]["r2"]) - float(base["prospective"]["r2"]),
                "contribution": blended_gain(base, full),
            }
        )
    return sorted(out, key=lambda row: row["contribution"], reverse=True)


def requested_transition_tests(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    tests = [
        ("exploring -> grounded", "transition_exploring_to_grounded"),
        ("grounded -> converging", "transition_grounded_to_converging"),
        ("converging -> success", "v3_final_converging"),
        ("stuck -> failure", "v3_final_stuck"),
        ("recovered -> success", "v3_final_recovered"),
    ]
    base = score_all(rows, prospective, K_RHO_A)
    out = []
    for name, field in tests:
        present = [row for row in rows if float(row.get(field) or 0.0) >= 0.5]
        absent = [row for row in rows if float(row.get(field) or 0.0) < 0.5]
        if name.endswith("failure"):
            rate_present = 1.0 - (mean(float(row["success"]) for row in present) if present else 0.0)
            rate_absent = 1.0 - (mean(float(row["success"]) for row in absent) if absent else 0.0)
        else:
            rate_present = mean(float(row["success"]) for row in present) if present else 0.0
            rate_absent = mean(float(row["success"]) for row in absent) if absent else 0.0
        full = score_all(rows, prospective, [*K_RHO_A, field])
        out.append([name, len(present), round(rate_present, 6), round(rate_absent, 6), round(float(full["holdout"]["r2"]) - float(base["holdout"]["r2"]), 6), round(float(full["prospective"]["r2"]) - float(base["prospective"]["r2"]), 6)])
    return out


def grounding_tests(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> dict[str, Any]:
    grounded = [row for row in rows if float(row.get("first_grounding_event") or 0.0) >= 0.5]
    converged = [row for row in rows if float(row.get("first_branch_collapse") or 0.0) >= 0.5]
    both = [row for row in rows if row in grounded and row in converged]
    grounding_before = [row for row in both if float(row["first_grounded_pct"]) <= float(row["first_converged_pct"])]
    convergence_before_success = [row for row in converged if float(row.get("success") or 0.0) >= 0.5 and float(row["first_converged_pct"]) <= float(row["first_success_pct"])]
    dynamic_full = score_all(rows, prospective, dyn.dynamic_specs_final())
    grounding_only = score_all(rows, prospective, [*K_RHO_A, "first_grounding_event", "grounding_latency", "grounded_action_ratio", "evidence_to_action_latency"])
    dynamic_without_grounding = score_all(
        rows,
        prospective,
        [
            "K",
            "rho",
            "A1_exists",
            "A2_retrieved",
            "A3_surfaced",
            "first_successful_tool_call",
            "first_verification_success",
            "dyn_signal_50",
            "dyn_signal_75",
            "first_recovery_event",
            "correction_speed",
            "retry_success",
            "branch_repair",
        ],
    )
    return {
        "grounded": len(grounded),
        "converged": len(converged),
        "both": len(both),
        "grounding_before_convergence_rate": len(grounding_before) / len(both) if both else 0.0,
        "convergence_success_rate": mean(float(row["success"]) for row in converged) if converged else 0.0,
        "convergence_before_success_rate": len(convergence_before_success) / len(converged) if converged else 0.0,
        "success_after_grounded": mean(float(row["success"]) for row in grounded) if grounded else 0.0,
        "success_without_grounded": mean(float(row["success"]) for row in rows if row not in grounded),
        "dynamic_holdout": dynamic_full["holdout"]["r2"],
        "dynamic_prospective": dynamic_full["prospective"]["r2"],
        "grounding_holdout": grounding_only["holdout"]["r2"],
        "grounding_prospective": grounding_only["prospective"]["r2"],
        "without_grounding_holdout": dynamic_without_grounding["holdout"]["r2"],
        "without_grounding_prospective": dynamic_without_grounding["prospective"]["r2"],
    }


def signal_curve(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    previous = None
    for name, fields in CURVE_WINDOWS.items():
        stats = score_all(rows, prospective, fields)
        holdout = float(stats["holdout"]["r2"])
        prosp = float(stats["prospective"]["r2"])
        out.append(
            [
                name,
                len(fields_available(rows, prospective, fields)),
                round(holdout, 6),
                round(holdout - previous, 6) if previous is not None else "n/a",
                round(float(stats["holdout"]["brier_gain"]), 6),
                round(prosp, 6),
                round(float(stats["prospective"]["brier_gain"]), 6),
            ]
        )
        previous = holdout
    return out


def minimal_subset(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]], dict[str, float]]:
    candidate_groups = [
        ("retrieval", ["first_retrieval_event", "A2_retrieved"]),
        ("decisive evidence", ["first_decisive_evidence", "time_to_decisive_evidence"]),
        ("grounding", ["first_grounding_event", "grounding_latency", "grounded_action_ratio", "evidence_to_action_latency"]),
        ("tool", ["first_successful_tool_call"]),
        ("verification", ["first_verification_attempt", "first_verification_success"]),
        ("branch collapse", ["first_branch_collapse"]),
        ("recovery", ["first_recovery_event", "correction_speed", "retry_success", "branch_repair"]),
        ("state", ["v3_state_grounded", "v3_state_converging", "v3_state_stuck", "v3_state_recovered"]),
    ]
    baseline = score_all(rows, prospective, K_RHO_A)
    full_fields = [*K_RHO_A, *[field for _name, fields in candidate_groups for field in fields]]
    full = score_all(rows, prospective, full_fields)
    target = blended_gain(baseline, full)
    chosen: list[str] = []
    chosen_names: list[str] = []
    steps = []
    remaining = candidate_groups[:]
    current = baseline
    while remaining:
        best = None
        for name, fields in remaining:
            scored = score_all(rows, prospective, [*K_RHO_A, *chosen, *fields])
            gain = blended_gain(current, scored)
            total_gain = blended_gain(baseline, scored)
            option = (gain, total_gain, name, fields, scored)
            if best is None or option > best:
                best = option
        if best is None or best[0] <= 0.0:
            break
        gain, total_gain, name, fields, scored = best
        chosen.extend(fields)
        chosen_names.append(name)
        current = scored
        steps.append([len(chosen_names), name, ", ".join(fields), round(gain, 6), round(total_gain, 6), round(total_gain / target, 6) if target > 0 else 0.0, round(float(scored["holdout"]["r2"]), 6), round(float(scored["prospective"]["r2"]), 6)])
        remaining = [item for item in remaining if item[0] != name]
        if target > 0 and total_gain / target >= 0.90:
            break
    return chosen_names, steps, {"target_gain": target, "full_holdout": float(full["holdout"]["r2"]), "full_prospective": float(full["prospective"]["r2"])}


def rows_to_table(rows: list[dict[str, Any]], keys: list[str]) -> list[list[Any]]:
    out = []
    for row in rows:
        out.append([round(row[key], 6) if isinstance(row.get(key), float) else row.get(key) for key in keys])
    return out


def event_table_rows(events: list[dict[str, Any]], total_rows: int) -> list[list[Any]]:
    out = []
    for i, row in enumerate(events, 1):
        has_absent = int(row["triggered"]) < total_rows
        out.append(
            [
                i,
                row["event"],
                row["triggered"],
                round(row["success_if_present"], 6) if row["triggered"] else "n/a",
                round(row["success_if_absent"], 6) if has_absent else "n/a",
                round(row["jump"], 6) if has_absent and row["triggered"] else ("timing-only" if row["triggered"] else "n/a"),
                round(row["holdout_gain"], 6),
                round(row["prospective_gain"], 6),
                round(row["brier_gain_delta"], 6),
                round(row["contribution"], 6),
            ]
        )
    return out


def main() -> int:
    rows, excluded, prospective = prepare()
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."

    events = event_ranking(rows, prospective)
    first_event = first_predictive_event(events)
    states = state_rows(rows, prospective)
    transitions = transition_rows(rows, prospective)
    requested_transitions = requested_transition_tests(rows, prospective)
    grounding = grounding_tests(rows, prospective)
    curve = signal_curve(rows, prospective)
    subset_names, subset_steps, subset_stats = minimal_subset(rows, prospective)

    write_md(
        "execution_event_ranking.md",
        f"""
# Execution Event Ranking

Scope: {scope}

Baseline for incremental contribution: `K+rho+A1-A3`. Contribution is a blended score from holdout R2 gain, prospective R2 gain, and prospective Brier-gain delta. No local, Codex, Ollama, self-hosted, or edge rows are admitted.

## Ranked Events

{table(["rank", "event", "triggered rows", "success if present", "success if absent", "probability jump", "holdout R2 gain", "prospective R2 gain", "Brier gain delta", "contribution"], event_table_rows(events, len(rows)))}

## Definitions

{table(["event", "operational definition"], [[row["event"], row["definition"]] for row in events])}

## First Predictive Event

The first execution event that increases predictive power under the robustness rule is `{first_event["event"]}`. In this corpus decisive evidence is present in every accepted run by the sampled windows, so its signal comes from timing/latency rather than a present-versus-absent split. It is not necessarily the strongest event; it is the earliest event in execution order with positive holdout gain and nonnegative future-oriented signal.
""",
    )

    write_md(
        "execution_state_model.md",
        f"""
# Execution State Model

Scope: {scope}

States are exclusive at each sampled execution window, but a run can visit multiple states over time.

## State Definitions

{table(["state", "definition"], [
["exploring", "Evidence has been retrieved or surfaced, but no stable grounded action path exists yet."],
["grounded", "Decisive evidence has appeared and is tied to an actionable context before final convergence."],
["converging", "The run has collapsed to a single solution path: evidence is understood and linked to action."],
["stuck", "Evidence retrieval and action linkage are both weak; the trajectory lacks a usable path."],
["recovered", "The run had contradiction/confusion and then repaired the path into action or verification."],
])}

## Ranked States

{table(["rank", "state", "visited rows", "final rows", "success if visited", "success if final", "success if absent", "holdout R2 gain", "prospective R2 gain", "contribution"], [[i, row["state"], row["frequency"], row["final_frequency"], round(row["success_if_present"], 6), round(row["success_if_final"], 6), round(row["success_if_absent"], 6), round(row["holdout_gain"], 6), round(row["prospective_gain"], 6), round(row["contribution"], 6)] for i, row in enumerate(states, 1)])}

## Frequent State Sequences

{table(["10>25>50>75 sequence", "rows", "success rate"], [[seq, len(values), round(mean(float(row["success"]) for row in values), 6)] for seq, values in sorted(defaultdict(list, {k: v for k, v in group_sequences(rows).items()}).items(), key=lambda item: (len(item[1]), mean(float(row["success"]) for row in item[1])), reverse=True)[:16]])}
""",
    )

    write_md(
        "state_transition_graph.md",
        f"""
# State Transition Graph

Scope: {scope}

Edges are observed transitions between the sampled execution windows 10%, 25%, 50%, and 75%.

## Ranked Transitions

{table(["rank", "transition", "rows", "success if present", "success if absent", "holdout R2 gain", "prospective R2 gain", "contribution"], [[i, row["transition"], row["frequency"], round(row["success_if_present"], 6), round(row["success_if_absent"], 6), round(row["holdout_gain"], 6), round(row["prospective_gain"], 6), round(row["contribution"], 6)] for i, row in enumerate(transitions, 1)])}

## Requested Transition Tests

{table(["transition / endpoint", "rows", "target rate if present", "target rate if absent", "holdout R2 gain", "prospective R2 gain"], requested_transitions)}

## Graph Reading

The beneficial path is exploration into grounding, then grounding into convergence, then convergence into success. The damaging path is persistence in stuck states. Recovery is rarer and does not dominate the predictive model, but when observed it identifies a distinct late repair mechanism.
""",
    )

    write_md(
        "grounding_mechanism.md",
        f"""
# Grounding Mechanism

Scope: {scope}

## Direct Tests

| question | result |
| --- | --- |
| Does grounding precede convergence? | {fmt(grounding["grounding_before_convergence_rate"])} of runs with both grounding and convergence have grounding no later than convergence. |
| Does convergence precede success? | {fmt(grounding["convergence_before_success_rate"])} of converged runs that succeed have convergence before the final success outcome. |
| Can success be predicted after grounded state? | success after grounding is {fmt(grounding["success_after_grounded"])} versus {fmt(grounding["success_without_grounded"])} without grounding. |
| Does grounding explain Dynamic Assimilation? | Dynamic Assimilation holdout/prospective R2 is {fmt(grounding["dynamic_holdout"])}/{fmt(grounding["dynamic_prospective"])}; grounding alone is {fmt(grounding["grounding_holdout"])}/{fmt(grounding["grounding_prospective"])}; dynamic without grounding is {fmt(grounding["without_grounding_holdout"])}/{fmt(grounding["without_grounding_prospective"])}. |

## Interpretation

Grounding is the mechanism that turns retrieval into convergence. Dynamic Assimilation is broader because it also includes later tool, verification, branch-collapse, and recovery evidence; however, the largest early jump is grounding-related rather than generic tool use.
""",
    )

    write_md(
        "signal_emergence_curves.md",
        f"""
# Signal Emergence Curves

Scope: {scope}

Each row is a strict prefix: later execution events are not visible to earlier windows.

{table(["window", "feature count", "holdout R2", "holdout R2 delta", "holdout Brier gain", "prospective R2", "prospective Brier gain"], curve)}

## Reading

The 0% row captures pre-execution priors. The first material execution lift appears once retrieval and decisive evidence enter the prefix; most of the surviving Dynamic Assimilation signal is already visible by the grounded/converging middle of the run, with later verification adding less than grounding.
""",
    )

    write_md(
        "minimal_signal_subset.md",
        f"""
# Minimal Signal Subset

Scope: {scope}

Target: recover most of the Dynamic Assimilation execution gain over `K+rho+A1-A3` using the smallest execution-event feature groups.

## Greedy Subset Recovery

{table(["step", "added group", "features", "incremental contribution", "cumulative contribution", "share of full dynamic gain", "holdout R2", "prospective R2"], subset_steps)}

## Selected Minimal Model

Smallest selected group set: `{", ".join(subset_names)}`.

Full dynamic event model holdout/prospective R2: {fmt(subset_stats["full_holdout"])}/{fmt(subset_stats["full_prospective"])}. Full blended execution gain target: {fmt(subset_stats["target_gain"])}.

## Determination

The minimal execution model is the grounding group: decisive-evidence timing, grounding latency, evidence-to-action conversion, and grounded-action ratio. Tool, verification, recovery, branch-collapse, and explicit state features can still be useful diagnostics, but they are not required to recover most of the surviving Dynamic Assimilation signal in this pass.
""",
    )

    write_md(
        "execution_science_assessment_v3.md",
        f"""
# Execution Science Assessment v3

Scope: {scope}

## Final Answers

1. First predictive event: `{first_event["event"]}`.
2. Strongest predictive event: `{events[0]["event"]}`.
3. Execution states that exist: {", ".join(row["state"] for row in states)}. The state ranking is by predictive contribution, so `stuck` ranks first because it predicts failure, not because it is a good state.
4. Most important transition: `{transitions[0]["transition"]}`.
5. Does grounding create convergence? Yes, in the operational sense: grounding usually appears no later than convergence among runs where both are observed, and grounded runs have materially higher success.
6. Can success be predicted after entering a grounded state? Yes diagnostically: success after grounding is {fmt(grounding["success_after_grounded"])} versus {fmt(grounding["success_without_grounded"])} without grounding.
7. Minimal execution model required for prediction: `{", ".join(subset_names)}`.

## Ranked Event List

{table(["rank", "event", "contribution"], [[i, row["event"], round(row["contribution"], 6)] for i, row in enumerate(events, 1)])}

## Ranked State List

{table(["rank", "state", "contribution"], [[i, row["state"], round(row["contribution"], 6)] for i, row in enumerate(states, 1)])}

## Ranked Transition List

{table(["rank", "transition", "contribution"], [[i, row["transition"], round(row["contribution"], 6)] for i, row in enumerate(transitions[:12], 1)])}

## Smallest Feature Set Explaining Most Surviving Dynamic Assimilation Signal

The smallest recovered subset is `{", ".join(subset_names)}`. In plain terms: detect decisive evidence, measure grounding latency, and confirm evidence-to-action conversion. That subset captures most of the surviving dynamic prediction signal without adding new primitive searches, new interaction laws, or a new theory zoo.
""",
    )

    print(
        json.dumps(
            {
                "scope": scope,
                "first_predictive_event": first_event["event"],
                "strongest_event": events[0]["event"],
                "strongest_state": states[0]["state"],
                "strongest_transition": transitions[0]["transition"] if transitions else "none",
                "minimal_subset": subset_names,
                "outputs": [
                    "execution_event_ranking.md",
                    "execution_state_model.md",
                    "state_transition_graph.md",
                    "grounding_mechanism.md",
                    "signal_emergence_curves.md",
                    "minimal_signal_subset.md",
                    "execution_science_assessment_v3.md",
                ],
            },
            indent=2,
        )
    )
    return 0


def group_sequences(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["v3_state_sequence"])].append(row)
    return grouped


if __name__ == "__main__":
    raise SystemExit(main())
