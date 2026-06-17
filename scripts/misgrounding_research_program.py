from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import grounding_research_program as grounding
from scripts import measurement_science_program as m


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"


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


def failed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if f(row, "success") < 0.5]


def succeeded(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if f(row, "success") >= 0.5]


def evidence_available(row: dict[str, Any]) -> bool:
    return f(row, "g_evidence_discovered") >= 0.5 or f(row, "A1_exists") >= 0.5 or f(row, "A2_retrieved") >= 0.25


def evidence_seen(row: dict[str, Any]) -> bool:
    return f(row, "g_evidence_recognized") >= 0.5 or f(row, "A2_retrieved") >= 0.35 or f(row, "A3_surfaced") >= 0.35


def evidence_understood(row: dict[str, Any]) -> bool:
    return f(row, "g_evidence_accepted") >= 0.5 or f(row, "A4_understood") >= 0.45


def evidence_connected(row: dict[str, Any]) -> bool:
    return f(row, "g_evidence_connected") >= 0.5 or f(row, "A5_linked_to_action") >= 0.45


def predicates() -> list[tuple[str, Callable[[dict[str, Any]], bool], str]]:
    return [
        ("evidence not found", lambda r: not evidence_available(r), "no discovered/retrieved evidence signal"),
        (
            "evidence found but ignored",
            lambda r: evidence_seen(r) and not evidence_understood(r) and not evidence_connected(r),
            "recognized evidence fails before acceptance or action linkage",
        ),
        (
            "evidence misinterpreted",
            lambda r: max(f(r, "A2_retrieved"), f(r, "A3_surfaced")) >= 0.45 and f(r, "A4_understood") < 0.35,
            "retrieved/surfaced evidence does not become understood evidence",
        ),
        (
            "evidence partially understood",
            lambda r: (f(r, "A2_retrieved") >= 0.35 or f(r, "A3_surfaced") >= 0.35)
            and 0.25 <= f(r, "A4_understood") < 0.45,
            "retrieved/surfaced evidence receives weak partial understanding but does not cross the strong-understanding threshold",
        ),
        (
            "evidence disconnected from action",
            lambda r: evidence_understood(r) and not evidence_connected(r),
            "accepted evidence does not become an action path",
        ),
        (
            "evidence overridden by prior belief",
            lambda r: evidence_seen(r)
            and f(r, "K") >= 0.70
            and f(r, "grounded_action_ratio") < 0.35
            and f(r, "success") < 0.5,
            "high prior confidence with recognized evidence but low grounded-action ratio",
        ),
        (
            "evidence lost during execution",
            lambda r: evidence_understood(r)
            and (f(r, "state_stuck") >= 0.35 or f(r, "branch_repair") >= 0.35 or f(r, "state_switches") >= 0.60)
            and f(r, "g_grounded_execution") < 0.5,
            "accepted evidence is followed by stuck/switching execution without grounded execution",
        ),
    ]


def taxonomy_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    failures = failed(rows)
    base_failure = len(failures) / len(rows)
    out = []
    for name, predicate, _definition in predicates():
        all_matching = [row for row in rows if predicate(row)]
        matching_failures = [row for row in failures if predicate(row)]
        success_rate = mean(f(row, "success") for row in all_matching) if all_matching else 0.0
        failure_rate = 1.0 - success_rate if all_matching else 0.0
        impact = failure_rate - base_failure
        severity = len(matching_failures) * max(0.0, impact)
        out.append(
            [
                name,
                len(matching_failures),
                round(len(matching_failures) / len(failures), 6) if failures else 0.0,
                len(all_matching),
                round(success_rate, 6) if all_matching else "n/a",
                round(failure_rate, 6) if all_matching else "n/a",
                round(impact, 6),
                round(severity, 6),
            ]
        )
    out.sort(key=lambda row: (int(row[1]), float(row[7])), reverse=True)
    return [[idx + 1, *row] for idx, row in enumerate(out)]


def representative_rows(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool], limit: int = 12) -> list[list[Any]]:
    candidates = [row for row in rows if f(row, "success") < 0.5 and predicate(row)]
    candidates.sort(key=lambda row: (f(row, "grounding_score"), -f(row, "time_to_decisive_evidence")))
    return [
        [
            row.get("row_id", "")[:12],
            row.get("model"),
            row.get("repository"),
            row.get("category"),
            round(f(row, "A2_retrieved"), 3),
            round(f(row, "A3_surfaced"), 3),
            round(f(row, "A4_understood"), 3),
            round(f(row, "A5_linked_to_action"), 3),
            row.get("grounding_trajectory"),
        ]
        for row in candidates[:limit]
    ]


def misinterpretation_rows(rows: list[dict[str, Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
    by_category: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    mis = [predicate for name, predicate, _definition in predicates() if name == "evidence misinterpreted"][0]
    for row in rows:
        if mis(row):
            by_category[str(row.get("category") or "")].append(row)
    aggregate = []
    for category, values in by_category.items():
        failures = failed(values)
        aggregate.append(
            [
                category,
                len(values),
                len(failures),
                round(len(failures) / len(values), 6) if values else 0.0,
                round(mean(f(row, "A2_retrieved") for row in values), 6),
                round(mean(f(row, "A3_surfaced") for row in values), 6),
                round(mean(f(row, "A4_understood") for row in values), 6),
                round(mean(f(row, "success") for row in values), 6),
            ]
        )
    aggregate.sort(key=lambda row: (int(row[2]), float(row[3])), reverse=True)

    success_mis = [row for row in rows if f(row, "success") >= 0.5 and f(row, "A2_retrieved") >= 0.45]
    fail_mis = [row for row in rows if f(row, "success") < 0.5 and mis(row)]
    comparison = [
        [
            "successful runs with retrieved evidence",
            len(success_mis),
            round(mean(f(row, "A2_retrieved") for row in success_mis), 6) if success_mis else "n/a",
            round(mean(f(row, "A3_surfaced") for row in success_mis), 6) if success_mis else "n/a",
            round(mean(f(row, "A4_understood") for row in success_mis), 6) if success_mis else "n/a",
            round(mean(f(row, "A5_linked_to_action") for row in success_mis), 6) if success_mis else "n/a",
            round(mean(f(row, "grounded_action_ratio") for row in success_mis), 6) if success_mis else "n/a",
        ],
        [
            "failed misinterpretation rows",
            len(fail_mis),
            round(mean(f(row, "A2_retrieved") for row in fail_mis), 6) if fail_mis else "n/a",
            round(mean(f(row, "A3_surfaced") for row in fail_mis), 6) if fail_mis else "n/a",
            round(mean(f(row, "A4_understood") for row in fail_mis), 6) if fail_mis else "n/a",
            round(mean(f(row, "A5_linked_to_action") for row in fail_mis), 6) if fail_mis else "n/a",
            round(mean(f(row, "grounded_action_ratio") for row in fail_mis), 6) if fail_mis else "n/a",
        ],
    ]
    return aggregate, comparison


def action_disconnect_rows(rows: list[dict[str, Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
    disconnect = [predicate for name, predicate, _definition in predicates() if name == "evidence disconnected from action"][0]
    disconnected = [row for row in rows if disconnect(row)]
    connected = [row for row in rows if evidence_understood(row) and evidence_connected(row)]
    summary = []
    for name, values in [("accepted/understood and connected", connected), ("accepted/understood but disconnected", disconnected)]:
        summary.append(
            [
                name,
                len(values),
                round(mean(f(row, "success") for row in values), 6) if values else "n/a",
                round(mean(f(row, "A4_understood") for row in values), 6) if values else "n/a",
                round(mean(f(row, "A5_linked_to_action") for row in values), 6) if values else "n/a",
                round(mean(f(row, "grounded_action_ratio") for row in values), 6) if values else "n/a",
                round(mean(f(row, "evidence_to_action_latency") for row in values), 6) if values else "n/a",
            ]
        )

    by_action = defaultdict(list)
    for row in disconnected:
        if f(row, "edited_files") > 0:
            action = "edited despite weak linkage"
        elif f(row, "tests_or_verifiers") > 0:
            action = "verified without grounded edit/action"
        elif f(row, "state_stuck") >= 0.35:
            action = "stuck after understanding"
        elif f(row, "state_switches") >= 0.60:
            action = "switched path and lost linkage"
        else:
            action = "no concrete grounded action"
        by_action[action].append(row)
    action_rows = []
    for action, values in by_action.items():
        action_rows.append(
            [
                action,
                len(values),
                round(len(failed(values)) / len(values), 6) if values else 0.0,
                round(mean(f(row, "A4_understood") for row in values), 6),
                round(mean(f(row, "A5_linked_to_action") for row in values), 6),
                round(mean(f(row, "grounded_action_ratio") for row in values), 6),
            ]
        )
    action_rows.sort(key=lambda row: int(row[1]), reverse=True)
    return summary, action_rows


def chain_for(row: dict[str, Any]) -> str:
    if not evidence_available(row):
        return "evidence not found -> no grounding -> failure"
    if evidence_seen(row) and max(f(row, "A2_retrieved"), f(row, "A3_surfaced")) >= 0.45 and f(row, "A4_understood") < 0.35:
        return "evidence found -> misinterpreted -> wrong/no action -> failure"
    if evidence_understood(row) and not evidence_connected(row):
        return "evidence found -> understood -> not connected to action -> failure"
    if evidence_seen(row) and not evidence_understood(row):
        return "evidence found -> ignored -> no correction -> failure"
    if evidence_understood(row) and f(row, "g_grounded_execution") < 0.5:
        return "evidence found -> understood -> lost during execution -> failure"
    if evidence_seen(row) and f(row, "K") >= 0.70 and f(row, "grounded_action_ratio") < 0.35:
        return "evidence found -> overridden by prior belief -> failure"
    return "mixed/other misgrounding -> failure"


def chain_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    buckets: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in failed(rows):
        buckets[chain_for(row)].append(row)
    out = []
    for chain, values in buckets.items():
        out.append(
            [
                chain,
                len(values),
                round(len(values) / len(failed(rows)), 6) if failed(rows) else 0.0,
                round(mean(f(row, "grounding_score") for row in values), 6),
                round(mean(f(row, "time_to_decisive_evidence") for row in values), 6),
                round(mean(f(row, "evidence_to_action_latency") for row in values), 6),
            ]
        )
    out.sort(key=lambda row: int(row[1]), reverse=True)
    return [[idx + 1, *row] for idx, row in enumerate(out)]


def trajectory_compare(rows: list[dict[str, Any]]) -> list[list[Any]]:
    groups = [("success", succeeded(rows)), ("failure", failed(rows))]
    out = []
    for name, values in groups:
        out.append(
            [
                name,
                len(values),
                round(mean(f(row, "time_to_decisive_evidence") for row in values), 6),
                round(mean(f(row, "grounding_latency") for row in values), 6),
                round(mean(f(row, "grounded_action_ratio") for row in values), 6),
                round(mean(f(row, "evidence_to_action_latency") for row in values), 6),
                round(mean(f(row, "g_grounded_execution") for row in values), 6),
                round(mean(f(row, "grounding_score") for row in values), 6),
            ]
        )
    return out


def trajectory_family_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    buckets: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("grounding_trajectory") or "none")].append(row)
    out = []
    for trajectory, values in buckets.items():
        out.append(
            [
                trajectory,
                len(values),
                round(mean(f(row, "success") for row in values), 6),
                round(mean(f(row, "time_to_decisive_evidence") for row in values), 6),
                round(mean(f(row, "grounded_action_ratio") for row in values), 6),
                round(mean(f(row, "evidence_to_action_latency") for row in values), 6),
            ]
        )
    out.sort(key=lambda row: int(row[1]), reverse=True)
    return out[:16]


def preventable(rows: list[dict[str, Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
    failure_rows = failed(rows)
    pred = {name: predicate for name, predicate, _definition in predicates()}
    mis = [row for row in failure_rows if pred["evidence misinterpreted"](row)]
    disc = [row for row in failure_rows if pred["evidence disconnected from action"](row)]
    either = {id(row): row for row in [*mis, *disc]}
    full_chain = [row for row in rows if evidence_seen(row) and evidence_understood(row) and evidence_connected(row)]
    chain_success = mean(f(row, "success") for row in full_chain) if full_chain else mean(f(row, "success") for row in rows)
    current_mis_success = mean(f(row, "success") for row in rows if pred["evidence misinterpreted"](row))
    current_disc_success = mean(f(row, "success") for row in rows if pred["evidence disconnected from action"](row))

    def estimate(label: str, candidates: list[dict[str, Any]], current_success: float) -> list[Any]:
        low = len(candidates) * max(0.0, min(0.35, chain_success - current_success))
        central = len(candidates) * max(0.0, min(0.75, chain_success - current_success))
        high = len(candidates) * max(0.0, min(0.95, chain_success))
        return [
            label,
            len(candidates),
            round(current_success, 6),
            round(chain_success, 6),
            round(low, 1),
            round(central, 1),
            round(high, 1),
            round(central / len(failure_rows), 6) if failure_rows else 0.0,
        ]

    rows_out = [
        estimate("interpretation corrected", mis, current_mis_success),
        estimate("action linkage corrected", disc, current_disc_success),
        estimate("interpretation or action linkage corrected", list(either.values()), min(current_mis_success, current_disc_success)),
    ]

    overlap = [
        ["failed rows", len(failure_rows), 1.0],
        ["misinterpreted", len(mis), round(len(mis) / len(failure_rows), 6) if failure_rows else 0.0],
        ["disconnected", len(disc), round(len(disc) / len(failure_rows), 6) if failure_rows else 0.0],
        [
            "misinterpreted or disconnected",
            len(either),
            round(len(either) / len(failure_rows), 6) if failure_rows else 0.0,
        ],
        [
            "not in either dominant pathway",
            len(failure_rows) - len(either),
            round((len(failure_rows) - len(either)) / len(failure_rows), 6) if failure_rows else 0.0,
        ],
    ]
    return rows_out, overlap


def dominant_pathways(rows: list[dict[str, Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
    taxonomy = taxonomy_rows(rows)
    common = [[row[0], row[1], row[2], row[3], row[8]] for row in taxonomy]
    damaging = sorted(taxonomy, key=lambda row: (float(row[8]), int(row[2])), reverse=True)
    return common, [[row[0], row[1], row[2], row[3], row[8]] for row in damaging]


def main() -> int:
    rows, excluded, prospective = grounding.prepare()
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."
    failures = failed(rows)
    taxonomy = taxonomy_rows(rows)
    mis_by_category, mis_comparison = misinterpretation_rows(rows)
    action_summary, action_mismatch = action_disconnect_rows(rows)
    chains = chain_rows(rows)
    trajectory_summary = trajectory_compare(rows)
    trajectory_families = trajectory_family_rows(rows)
    preventable_rows, preventable_overlap = preventable(rows)
    common, damaging = dominant_pathways(rows)
    pred = {name: predicate for name, predicate, _definition in predicates()}

    write_md(
        "misgrounding_taxonomy.md",
        f"""
# Misgrounding Taxonomy

Scope: {scope}

Rules honored: cloud models only; no primitive search; no interaction search; no new theory generation. The taxonomy below is an operational measurement of why available evidence fails to become grounded action.

## Ranked Frequency and Impact

{table(["rank", "category", "failed rows", "share of failures", "all rows", "success rate when present", "failure rate when present", "failure lift vs base", "impact score"], taxonomy)}

## Operational Definitions

{table(["category", "definition"], [[name, definition] for name, _predicate, definition in predicates()])}

## Reading

The two dominant mechanisms are evidence misinterpretation and evidence disconnected from action. Together they cover {fmt(preventable_overlap[3][2])} of failed rows when counted as a union. Evidence absence exists, but it is not the main failure source in the cloud-only aligned set.
""",
    )

    write_md(
        "evidence_misinterpretation.md",
        f"""
# Evidence Misinterpretation

Scope: {scope}

## Available Evidence vs Interpretation

{table(["category", "rows", "failed rows", "failure rate", "mean A2 retrieved", "mean A3 surfaced", "mean A4 understood", "success rate"], mis_by_category)}

## Difference From Successful Runs

{table(["group", "rows", "mean A2 retrieved", "mean A3 surfaced", "mean A4 understood", "mean A5 linked", "mean grounded-action ratio"], mis_comparison)}

## Representative Failed Rows

{table(["row", "model", "repo", "category", "A2", "A3", "A4", "A5", "trajectory"], representative_rows(rows, pred["evidence misinterpreted"]))}

## Determination

The available evidence was usually retrieved or surfaced: the failure signature is not zero access, but low `A4_understood` after nontrivial `A2/A3`. Successful rows with retrieved evidence convert that same evidence into higher understanding, higher action linkage, and a much higher grounded-action ratio.
""",
    )

    write_md(
        "action_disconnect_analysis.md",
        f"""
# Action Disconnect Analysis

Scope: {scope}

## Accepted Evidence vs Action

{table(["group", "rows", "success rate", "mean A4 understood", "mean A5 linked", "mean grounded-action ratio", "mean evidence-to-action latency"], action_summary)}

## Action Mismatch Classes

{table(["action chosen / mismatch", "rows", "failure rate", "mean A4 understood", "mean A5 linked", "mean grounded-action ratio"], action_mismatch)}

## Representative Failed Rows

{table(["row", "model", "repo", "category", "A2", "A3", "A4", "A5", "trajectory"], representative_rows(rows, pred["evidence disconnected from action"]))}

## Determination

The disconnect class crosses the accepted-evidence threshold, but the chosen action does not preserve the evidence link. In this dataset acceptance can come from the decisive-evidence signal even when the generated-output `A4_understood` marker remains low. The mismatch is visible as low `A5_linked_to_action`, low grounded-action ratio, high evidence-to-action latency, and often path-switching execution.
""",
    )

    write_md(
        "grounding_failure_chains.md",
        f"""
# Grounding Failure Chains

Scope: {scope}

## Ranked Chains

{table(["rank", "failure chain", "failed rows", "share of failures", "mean grounding score", "mean decisive evidence timing", "mean evidence-to-action latency"], chains)}

## Chain Reading

The most common chain is `{chains[0][1] if chains else "n/a"}`. The highest-impact chains are the ones that pass evidence availability but fail before action: they are preventable in principle because the evidence was already inside the run.
""",
    )

    write_md(
        "success_vs_failure_trajectories.md",
        f"""
# Success vs Failure Trajectories

Scope: {scope}

## Core Trajectory Metrics

{table(["outcome", "rows", "decisive evidence timing", "grounding latency", "grounded-action ratio", "evidence-to-action latency", "grounded execution rate", "grounding score"], trajectory_summary)}

## Dominant Trajectory Families

{table(["trajectory", "rows", "success rate", "decisive evidence timing", "grounded-action ratio", "evidence-to-action latency"], trajectory_families)}

## Measurement

Successful trajectories find decisive evidence earlier, ground earlier, keep a higher grounded-action ratio, and convert evidence to action faster. Failure trajectories often reach `discovered>recognized>accepted`, but do not reach `connected>executed`.
""",
    )

    write_md(
        "preventable_failure_estimates.md",
        f"""
# Preventable Failure Estimates

Scope: {scope}

## Counterfactual Estimates

{table(["counterfactual", "candidate failed rows", "current success rate for mode", "success rate for full grounded chain", "low prevented", "central prevented", "high prevented", "central share of all failures"], preventable_rows)}

## Overlap Accounting

{table(["bucket", "rows", "share of failures"], preventable_overlap)}

## Estimate

Central estimate: correcting interpretation or evidence-to-action linkage would remove about {fmt(preventable_rows[2][5])} of {len(failures)} failures, or {fmt(preventable_rows[2][7])} of all failures. This is an estimate, not a causal proof: overlapping mechanisms are counted once in the union row.
""",
    )

    write_md(
        "grounding_failure_assessment.md",
        f"""
# Grounding Failure Assessment

Scope: {scope}

## Answers

1. Why does grounding fail? Evidence usually fails after access: it is misinterpreted, partially understood, disconnected from action, overridden by high prior confidence, or lost during execution.
2. Most common failure chain: `{chains[0][1] if chains else "n/a"}`.
3. Most damaging failure mechanism: `{damaging[0][1] if damaging else "n/a"}` by impact score.
4. Preventable failure percentage: central estimate {fmt(preventable_rows[2][7])}, with low/high counts {fmt(preventable_rows[2][4])}/{fmt(preventable_rows[2][6])} failed rows.
5. Is misgrounding dominant? Yes for this cloud-only aligned set: misinterpretation or action disconnect covers {fmt(preventable_overlap[3][2])} of failures, and grounding variables account for the large incremental diagnostic signal reported in the prior grounding assessment.

## Ranked By Frequency

{table(["rank", "mechanism", "failed rows", "share of failures", "impact score"], common)}

## Ranked By Damage

{table(["rank", "mechanism", "failed rows", "share of failures", "impact score"], damaging)}

## Contribution to Overall Failure

{table(["mechanism", "share of all failures", "estimated contribution"], [[row[1], row[3], "dominant" if idx < 2 else "secondary" if float(row[3]) >= 0.03 else "minor"] for idx, row in enumerate(taxonomy)])}

## Final Determination

Misgrounding is the dominant measured cause of failure under the requested scope. The principal failure is not evidence absence. The principal failure is evidence failing to become grounded action, especially through misinterpretation and action disconnect.
""",
    )

    print(
        json.dumps(
            {
                "scope": scope,
                "failures": len(failures),
                "top_frequency": common[0] if common else None,
                "top_damage": damaging[0] if damaging else None,
                "preventable_central_share": preventable_rows[2][7],
                "outputs": [
                    "misgrounding_taxonomy.md",
                    "evidence_misinterpretation.md",
                    "action_disconnect_analysis.md",
                    "grounding_failure_chains.md",
                    "success_vs_failure_trajectories.md",
                    "preventable_failure_estimates.md",
                    "grounding_failure_assessment.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
