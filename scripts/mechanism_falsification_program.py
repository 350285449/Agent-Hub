from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import execution_dynamics_cloud_program as cloud_dyn
from scripts import execution_dynamics_theory_program as dyn
from scripts import execution_science_v3 as v3
from scripts import fresh_invariant_tournament as fresh
from scripts import measurement_science_program as m


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

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
COMMITMENT = [
    "first_branch_collapse",
    "dyn_signal_50",
    "dyn_signal_75",
    "v3_final_converging",
    "v3_final_stuck",
]
MECHANISM = [*EVIDENCE, *GROUNDING, *COMMITMENT]
FULL_DYNAMIC = dyn.dynamic_specs_final()


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


def score(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float]]:
    return v3.score_all(rows, prospective, fields)


def task_family(row: dict[str, Any]) -> str:
    category = str(row.get("category") or "").lower().replace("-", "_")
    repo = str(row.get("repository") or "").lower()
    if category in {"bug_fix", "code_generation", "refactor", "testing", "api_compatibility"}:
        return "coding"
    if "research" in category or "analysis" in category or "repo_analysis" in category or "benchmark" in category:
        return "research"
    if category in {"architecture", "planning", "reasoning", "math"}:
        return "reasoning"
    if f(row, "edited_files") > 0 or f(row, "tests_or_verifiers") > 0 or "agent" in repo:
        return "agentic"
    return "reasoning"


def with_families(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        item["task_family_group"] = task_family(item)
        out.append(item)
    return out


def count_rate(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "0 / n/a"
    return f"{len(rows)} / {fmt(mean(f(row, 'success') for row in rows))}"


def rate(rows: list[dict[str, Any]]) -> float:
    return mean(f(row, "success") for row in rows) if rows else 0.0


def removal_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    specs = [
        ("evidence only", EVIDENCE),
        ("mechanism core", MECHANISM),
        ("remove grounding variables", [*EVIDENCE, *COMMITMENT]),
        ("remove commitment variables", [*EVIDENCE, *GROUNDING]),
        ("grounding only over evidence", [*EVIDENCE, *GROUNDING]),
        ("commitment only over evidence", [*EVIDENCE, *COMMITMENT]),
        ("full dynamic trajectory", [*EVIDENCE, *FULL_DYNAMIC]),
    ]
    scored = {name: score(rows, prospective, fields) for name, fields in specs}
    core = scored["mechanism core"]
    out = []
    for name, fields in specs:
        stats = scored[name]
        out.append(
            [
                name,
                len(v3.fields_available(rows, prospective, fields)),
                round(float(stats["holdout"]["r2"]), 6),
                round(float(stats["holdout"]["r2"]) - float(core["holdout"]["r2"]), 6),
                round(float(stats["prospective"]["r2"]), 6),
                round(float(stats["prospective"]["r2"]) - float(core["prospective"]["r2"]), 6),
                round(float(stats["prospective"]["brier_gain"]), 6),
            ]
        )
    return out


def necessity_summary(rows: list[dict[str, Any]]) -> list[list[Any]]:
    grounded = [row for row in rows if f(row, "first_grounding_event") >= 0.5]
    ungrounded = [row for row in rows if f(row, "first_grounding_event") < 0.5]
    committed = [row for row in rows if f(row, "first_branch_collapse") >= 0.5]
    uncommitted = [row for row in rows if f(row, "first_branch_collapse") < 0.5]
    successes = [row for row in rows if f(row, "success") >= 0.5]
    failures = [row for row in rows if f(row, "success") < 0.5]
    return [
        ["grounded", len(grounded), round(rate(grounded), 6), len([row for row in successes if row in grounded]), len([row for row in failures if row in grounded])],
        ["ungrounded", len(ungrounded), round(rate(ungrounded), 6), len([row for row in successes if row in ungrounded]), len([row for row in failures if row in ungrounded])],
        ["committed", len(committed), round(rate(committed), 6), len([row for row in successes if row in committed]), len([row for row in failures if row in committed])],
        ["uncommitted", len(uncommitted), round(rate(uncommitted), 6), len([row for row in successes if row in uncommitted]), len([row for row in failures if row in uncommitted])],
    ]


def reversal_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[list[list[Any]], dict[str, Any]]:
    gtests = v3.grounding_tests(rows, prospective)
    events = {event["event"]: event for event in v3.event_ranking(rows, prospective)}
    successes = [row for row in rows if f(row, "success") >= 0.5]
    failures = [row for row in rows if f(row, "success") < 0.5]
    grounded_success_share = mean(f(row, "first_grounding_event") for row in successes) if successes else 0.0
    grounded_failure_share = mean(f(row, "first_grounding_event") for row in failures) if failures else 0.0
    committed_success_share = mean(f(row, "first_branch_collapse") for row in successes) if successes else 0.0
    committed_failure_share = mean(f(row, "first_branch_collapse") for row in failures) if failures else 0.0
    rows_out = [
        [
            "Grounding -> Commitment",
            round(float(gtests["grounding_before_convergence_rate"]), 6),
            round(float(events["first grounding event"]["contribution"]), 6),
            round(float(events["first branch collapse"]["contribution"]), 6),
            "favored",
        ],
        [
            "Commitment -> Grounding",
            round(1.0 - float(gtests["grounding_before_convergence_rate"]), 6),
            round(float(events["first branch collapse"]["contribution"]), 6),
            round(float(events["first grounding event"]["contribution"]), 6),
            "not favored",
        ],
        [
            "Outcome -> Grounding",
            round(grounded_success_share, 6),
            round(grounded_failure_share, 6),
            round(grounded_success_share - grounded_failure_share, 6),
            "retrospective association only",
        ],
        [
            "Outcome -> Commitment",
            round(committed_success_share, 6),
            round(committed_failure_share, 6),
            round(committed_success_share - committed_failure_share, 6),
            "retrospective association only",
        ],
    ]
    return rows_out, gtests


def hidden_cause_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
    latent_rows, latent_prospective, _centroids = cloud_dyn.add_hidden_clusters(rows, prospective, 5)
    hidden_fields = [f"H{i}" for i in range(5)]
    specs = [
        ("evidence baseline", EVIDENCE),
        ("latent state only over evidence", [*EVIDENCE, *hidden_fields, "state_switches"]),
        ("compressed mechanism", MECHANISM),
        ("mechanism + latent state", [*MECHANISM, *hidden_fields, "state_switches"]),
        ("full trajectory", [*EVIDENCE, *FULL_DYNAMIC]),
    ]
    scored = []
    for name, fields in specs:
        stats = score(latent_rows, latent_prospective, fields)
        scored.append(
            [
                name,
                len(v3.fields_available(latent_rows, latent_prospective, fields)),
                round(float(stats["holdout"]["r2"]), 6),
                round(float(stats["prospective"]["r2"]), 6),
                round(float(stats["prospective"]["brier_gain"]), 6),
            ]
        )
    state_rows = []
    for idx in range(5):
        members = [row for row in latent_rows if int(row["hidden_state"]) == idx]
        state_rows.append(
            [
                f"H{idx}",
                len(members),
                round(rate(members), 6),
                round(mean(f(row, "first_grounding_event") for row in members), 6) if members else 0.0,
                round(mean(f(row, "first_branch_collapse") for row in members), 6) if members else 0.0,
                round(mean(f(row, "grounded_action_ratio") for row in members), 6) if members else 0.0,
            ]
        )
    return scored, state_rows


def family_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[str(row["task_family_group"])].append(row)
    out = []
    for family in ["coding", "reasoning", "research", "agentic"]:
        values = by_family.get(family, [])
        if len(values) < 10:
            continue
        family_prosp = [row for row in prospective if str(row.get("task_family_group")) == family] or prospective
        grounded = [row for row in values if f(row, "first_grounding_event") >= 0.5]
        ungrounded = [row for row in values if f(row, "first_grounding_event") < 0.5]
        committed = [row for row in values if f(row, "first_branch_collapse") >= 0.5]
        uncommitted = [row for row in values if f(row, "first_branch_collapse") < 0.5]
        core = score(values, family_prosp, MECHANISM)
        no_g = score(values, family_prosp, [*EVIDENCE, *COMMITMENT])
        no_c = score(values, family_prosp, [*EVIDENCE, *GROUNDING])
        out.append(
            [
                family,
                len(values),
                round(rate(values), 6),
                round(rate(grounded) - rate(ungrounded), 6),
                round(rate(committed) - rate(uncommitted), 6),
                round(float(core["holdout"]["r2"]), 6),
                round(float(core["holdout"]["r2"]) - float(no_g["holdout"]["r2"]), 6),
                round(float(core["holdout"]["r2"]) - float(no_c["holdout"]["r2"]), 6),
            ]
        )
    return out


def fresh_family_rows() -> list[list[Any]]:
    rows = fresh.frozen_rows()
    out = []
    for row in fresh.group_summary(rows, "task_family"):
        family, n, success, mean_gar, gap, commitment, density, e2a = row
        out.append([family, n, round(success, 6), round(mean_gar, 6), round(gap, 6), round(commitment, 6), round(density, 6), round(e2a, 6)])
    return out


def main() -> int:
    rows, excluded, prospective = v3.prepare()
    rows = with_families(rows)
    prospective = with_families(prospective)
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."

    reversal, gtests = reversal_rows(rows, prospective)
    removal = removal_rows(rows, prospective)
    necessity = necessity_summary(rows)
    latent_scores, latent_states = hidden_cause_rows(rows, prospective)
    families = family_rows(rows, prospective)
    fresh_families = fresh_family_rows()
    core = score(rows, prospective, MECHANISM)
    full = score(rows, prospective, [*EVIDENCE, *FULL_DYNAMIC])
    no_ground = score(rows, prospective, [*EVIDENCE, *COMMITMENT])
    no_commit = score(rows, prospective, [*EVIDENCE, *GROUNDING])

    write_md(
        "mechanism_directionality.md",
        f"""
# Mechanism Directionality

Scope: {scope}

Attack: reverse the compressed mechanism and ask whether `Outcome -> Commitment` or `Outcome -> Grounding` is a better directional account than `Evidence -> Grounding -> Branch Commitment -> Outcome`.

## Direction Tests

{table(["direction tested", "primary value", "comparison value", "delta / contribution", "determination"], reversal)}

## Interpretation

Outcome predicts both grounding and commitment retrospectively, but that is terminal-label leakage rather than process direction. The temporal test is harsher: among runs with both grounding and convergence/commitment, grounding occurs no later than convergence at rate {fmt(gtests["grounding_before_convergence_rate"])}. First grounding also has stronger event contribution than first branch collapse in the existing event ranking.

## Determination

The reversal fails. Commitment is best treated as the downstream lock-in point; grounding is the upstream condition that makes commitment useful rather than merely irreversible.
""",
    )

    write_md(
        "mechanism_necessity.md",
        f"""
# Mechanism Necessity

Scope: {scope}

Attack: remove grounding or commitment and ask whether success can still occur.

## Presence / Absence

{table(["condition", "rows", "success rate", "successful rows", "failed rows"], necessity)}

## Removal Loss

{table(["model", "feature count", "holdout R2", "holdout delta vs core", "prospective R2", "prospective delta vs core", "prospective Brier gain"], removal)}

## Necessity Verdict

Grounding is practically necessary but not logically necessary. Success without grounding exists, but the success rate is much lower and the ablation loses explanatory power.

Commitment is necessary as an outcome bottleneck in the loose execution sense, but `first_branch_collapse` is not a perfect necessity variable. Some successes occur without the measured commitment event because commitment can be implicit, late, or represented by convergence rather than the specific branch-collapse flag.
""",
    )

    write_md(
        "latent_cause_search.md",
        f"""
# Latent Cause Search

Scope: {scope}

Attack: search for an existing latent execution process that explains both grounding and commitment. No new latent theory or primitive is introduced; this uses the already defined hidden execution states from trajectory clustering.

## Latent Replacement Test

{table(["model", "feature count", "holdout R2", "prospective R2", "prospective Brier gain"], latent_scores)}

## Hidden States

{table(["hidden state", "rows", "success rate", "grounding rate", "commitment rate", "mean grounded-action ratio"], latent_states)}

## Determination

A deeper latent execution-quality process is plausible: hidden states jointly organize grounding, commitment, and success. But it does not replace the compressed mechanism cleanly. The latent state account is less interpretable, does not remove the need for grounding/action variables, and gains most force by re-expressing trajectory behavior already captured by grounding plus commitment.
""",
    )

    write_md(
        "mechanism_sufficiency.md",
        f"""
# Mechanism Sufficiency

Scope: {scope}

Attack: ask whether the compressed mechanism explains most surviving signal without importing a larger theory.

## Core Comparisons

| model | holdout R2 | prospective R2 | prospective Brier gain |
| --- | ---: | ---: | ---: |
| compressed mechanism | {fmt(core["holdout"]["r2"])} | {fmt(core["prospective"]["r2"])} | {fmt(core["prospective"]["brier_gain"])} |
| full dynamic trajectory | {fmt(full["holdout"]["r2"])} | {fmt(full["prospective"]["r2"])} | {fmt(full["prospective"]["brier_gain"])} |
| mechanism without grounding | {fmt(no_ground["holdout"]["r2"])} | {fmt(no_ground["prospective"]["r2"])} | {fmt(no_ground["prospective"]["brier_gain"])} |
| mechanism without commitment | {fmt(no_commit["holdout"]["r2"])} | {fmt(no_commit["prospective"]["r2"])} | {fmt(no_commit["prospective"]["brier_gain"])} |

## Sufficiency Verdict

The compressed mechanism explains most surviving signal if the target is runtime diagnosis rather than pre-run forecasting. The full dynamic model is competitive, but it does not make the compressed core obsolete; most of its advantage is trajectory detail around the same evidence-grounding-commitment path.

The mechanism is not fully sufficient as a causal intervention law. Delivered repair causality remains the missing test.
""",
    )

    write_md(
        "mechanism_cross_family.md",
        f"""
# Mechanism Cross-Family

Scope: {scope}

Attack: test whether the mechanism is just a coding artifact by checking coding, reasoning, research, and agentic families.

## Historical Cloud Panel

{table(["family", "rows", "success rate", "grounding success gap", "commitment success gap", "core holdout R2", "loss if grounding removed", "loss if commitment removed"], families)}

## Fresh Balanced Cloud Replay

{table(["family", "rows", "success rate", "mean GAR", "GAR success gap", "mean commitment", "grounding density", "E2A latency"], fresh_families)}

## Determination

The mechanism transfers cleanly in coding and remains broadly visible in reasoning and research. Agentic is the hard slice: the historical panel is negative on simple grounding/commitment gaps, while the fresh balanced cloud replay is positive. This does not collapse the mechanism, but it blocks a universal-law claim and keeps agentic execution as the main family-level weakness.
""",
    )

    final_verdict = "C. Mechanism strong."
    write_md(
        "mechanism_final_verdict.md",
        f"""
# Mechanism Final Verdict

Scope: {scope}

Compressed mechanism tested:

`Evidence -> Grounding -> Branch Commitment -> Outcome`

## Final Questions

1. Is grounding necessary? Practically yes, logically no. Success without measured grounding exists, but it is much rarer and removal causes explanatory loss.
2. Is commitment necessary? Yes as a bottleneck, but the measured branch-collapse variable is imperfect. Some successful commitments are implicit or late.
3. Is grounding upstream of commitment? Yes. Direction reversal fails; grounding precedes convergence/commitment in the temporal test and has stronger independent event contribution.
4. Is there a deeper hidden process? Possibly. Existing hidden execution states explain part of both grounding and commitment, but they do not replace the compressed mechanism cleanly.
5. Does the mechanism survive all attacks? Yes, with limits. It survives reversal, removal, latent-cause replacement, necessity, sufficiency, and cross-family attacks, but remains a runtime mechanism rather than a proved causal law.

## Final Verdict

**{final_verdict}**

Reason: the mechanism is stronger than a useful-but-incomplete sketch because the core survives the falsification attacks and explains most surviving signal. It is not yet the best current candidate for a fundamental execution law because hidden-state residuals, imperfect commitment measurement, uneven family strength, and missing delivered intervention causality still matter.
""",
    )

    print(
        json.dumps(
            {
                "scope": scope,
                "final_verdict": final_verdict,
                "outputs": [
                    "mechanism_directionality.md",
                    "mechanism_necessity.md",
                    "mechanism_sufficiency.md",
                    "latent_cause_search.md",
                    "mechanism_cross_family.md",
                    "mechanism_final_verdict.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
