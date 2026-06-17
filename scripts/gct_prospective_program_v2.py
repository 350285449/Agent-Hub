from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

SEED = 20260617
TRIAL_ID = "gct-prospective-cloud-2026-06-17-v2"
FAMILIES = ["coding", "reasoning", "research", "agentic"]
CLOUD_MODEL_FAMILIES = [
    "ollama-kimi-cloud",
    "ollama-glm-cloud",
    "ollama-qwen-cloud",
    "ollama-nemotron-cloud",
    "ollama-gemma-cloud",
]


TASK_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "coding": [
        {
            "stem": "A service writes `{artifact}` after `{operation}`, but failures leave `{symptom}`. Diagnose the likely fault, specify a minimal patch, and define the regression verifier.",
            "slots": {
                "artifact": ["JSON reports", "cache manifests", "checkpoint files", "plugin metadata", "route traces"],
                "operation": ["atomic save", "parallel retry", "schema migration", "provider fallback", "tool-result normalization"],
                "symptom": ["zero-byte files", "stale responses", "duplicate records", "missing errors", "partial writes"],
            },
            "evidence_units": ["failure symptom", "write or state boundary", "minimal patch target", "verifier condition"],
        },
        {
            "stem": "A test suite passes locally but fails in cloud CI when `{condition}`. Identify the evidence to inspect first, compare two branches, and choose the first action.",
            "slots": {
                "condition": ["timeouts are tight", "environment variables are absent", "path separators differ", "provider quotas reset", "fixtures are generated"],
            },
            "evidence_units": ["CI-only condition", "local/cloud difference", "branch comparison", "first action"],
        },
    ],
    "reasoning": [
        {
            "stem": "Policy P says `{rule}`, except `{exception}`. For `{case}`, determine the outcome and explain the decisive branch.",
            "slots": {
                "rule": ["approve only if evidence is complete", "retry only transient failures", "escalate high risk with low confidence", "run urgent jobs before older jobs"],
                "exception": ["audited requests always go to review", "permanent errors stop immediately", "missing checksums block completion", "manual holds override urgency"],
                "case": ["a high-risk audited request", "a permanent 400 failure", "one shard without checksum", "an urgent job under manual hold"],
            },
            "evidence_units": ["base rule", "exception", "case facts", "decisive branch"],
        },
        {
            "stem": "Given `{premise_a}` and `{premise_b}`, can `{claim}` be true? Answer directly, then name the contradiction or supporting condition.",
            "slots": {
                "premise_a": ["all completed shards have checksums", "no approved task lacks evidence", "every executed branch has a verifier", "all locked routes have a selected provider"],
                "premise_b": ["one shard lacks a checksum", "one task lacks evidence", "one branch has no verifier", "one route has no provider"],
                "claim": ["all shards are completed", "all tasks are approved", "all branches executed", "all routes are locked"],
            },
            "evidence_units": ["universal premise", "counterexample fact", "claim", "logical answer"],
        },
    ],
    "research": [
        {
            "stem": "Design a prospective falsification test for `{hypothesis}`. Include eligibility, frozen measurement, control model, and the failure criterion.",
            "slots": {
                "hypothesis": [
                    "grounding predicts task success beyond model capability",
                    "commitment quality mediates execution reliability",
                    "pre-commit evidence gates improve outcomes",
                    "GAR remains stable across model families",
                ],
            },
            "evidence_units": ["hypothesis", "eligibility", "control model", "failure criterion"],
        },
        {
            "stem": "A trial observes `{pattern}`. Name the primary bias or threat, the measurement needed before outcome, and one admissible analysis.",
            "slots": {
                "pattern": [
                    "treatment only after low grounding is detected",
                    "commitment scored from final answers",
                    "controls all succeed at ceiling",
                    "one provider supplies every row",
                ],
            },
            "evidence_units": ["observed pattern", "bias/threat", "pre-outcome measurement", "analysis"],
        },
    ],
    "agentic": [
        {
            "stem": "An agent must `{goal}` using tools. Specify the evidence checkpoint, the first branch comparison, the commitment delay gate, and the verifier.",
            "slots": {
                "goal": [
                    "inspect config and choose a cloud provider",
                    "repair a failed edit after a stale observation",
                    "triage failing tests with no changed files",
                    "select between retrieval and risky patch execution",
                ],
            },
            "evidence_units": ["tool observation", "branch comparison", "commitment delay", "verifier"],
        },
        {
            "stem": "During autonomous execution, `{event}` occurs. State the recovery sequence and where commitment must be withheld until evidence is checked.",
            "slots": {
                "event": [
                    "a tool returns success but the file is unchanged",
                    "a provider fails over after partial output",
                    "tests fail before any edit is made",
                    "retrieved context contradicts the initial plan",
                ],
            },
            "evidence_units": ["event observation", "recovery sequence", "withheld commitment point", "evidence check"],
        },
    ],
}


def write_text(name: str, text: str) -> None:
    content = text.strip() + "\n"
    RESEARCH.mkdir(parents=True, exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def write_jsonl(name: str, rows: list[dict[str, Any]]) -> None:
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    RESEARCH.mkdir(parents=True, exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def expand_template(template: dict[str, Any], rng: random.Random, idx: int) -> str:
    text = template["stem"]
    for key, options in template["slots"].items():
        text = text.replace("{" + key + "}", options[(idx + rng.randrange(len(options))) % len(options)])
    return text


def freeze_dataset(n: int = 200) -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    rows: list[dict[str, Any]] = []
    per_family = n // len(FAMILIES)
    for family in FAMILIES:
        templates = TASK_TEMPLATES[family]
        for i in range(per_family):
            template = templates[i % len(templates)]
            prompt = expand_template(template, rng, i)
            row_id = f"gct-v2-{family}-{i + 1:03d}"
            cloud_family = CLOUD_MODEL_FAMILIES[(i + FAMILIES.index(family)) % len(CLOUD_MODEL_FAMILIES)]
            arm = "treatment" if (i + FAMILIES.index(family)) % 2 else "control"
            difficulty_band = ["medium", "medium-hard", "hard", "adversarial"][(i // 5) % 4]
            evidence_units = list(template["evidence_units"])
            rows.append(
                {
                    "trial_id": TRIAL_ID,
                    "row_id": row_id,
                    "frozen_hash": hashlib.sha256(f"{TRIAL_ID}|{row_id}|{prompt}".encode("utf-8")).hexdigest(),
                    "family": family,
                    "cloud_model_family": cloud_family,
                    "assigned_arm": arm,
                    "prompt": prompt,
                    "difficulty_band": difficulty_band,
                    "evidence_units_required": evidence_units,
                    "minimum_actions_expected": 4 if family == "agentic" else 3,
                    "holdout": i >= int(per_family * 0.7),
                    "source_status": "fresh prospective v2 row; no reused evaluation row; no replay outcome",
                    "execution_status": "frozen_unexecuted",
                    "outcome_status": "not_observed",
                }
            )
    rng.shuffle(rows)
    for order, row in enumerate(rows):
        row["frozen_order"] = order + 1
    return rows


def design_doc(rows: list[dict[str, Any]]) -> str:
    by_family = Counter(row["family"] for row in rows)
    by_model = Counter(row["cloud_model_family"] for row in rows)
    by_arm = Counter(row["assigned_arm"] for row in rows)
    return f"""
# GCT Prospective Design v2

Trial id: `{TRIAL_ID}`. Frozen seed: `{SEED}`. Frozen panel: `research/gct_prospective_dataset_v2.jsonl`.

## Status

This file freezes the first valid prospective evaluation design. The prior 16-row panel is excluded from adjudication and is not used for row generation, scoring, fitting, or conclusion selection.

The v2 panel contains 200 fresh rows, balanced by task family and assigned before execution. The panel is frozen but not marked complete until every row has auditable cloud execution metadata, a trace ledger, and an outcome label from the frozen rubric.

## Design

{table(["dimension", "value"], [["rows frozen", len(rows)], ["minimum completed rows required", 200], ["reuse/replay rows", "0 admitted"], ["execution mode", "cloud models only"], ["control", by_arm["control"]], ["treatment", by_arm["treatment"]], ["holdout rows", sum(1 for r in rows if r["holdout"])], ["training rows", sum(1 for r in rows if not r["holdout"])]])}

## Family Balance

{table(["family", "frozen rows"], [[family, by_family[family]] for family in FAMILIES])}

## Cloud Family Balance

{table(["cloud model family", "frozen rows"], [[name, by_model[name]] for name in CLOUD_MODEL_FAMILIES])}

## Prospective Freeze Rules

- Dataset rows are frozen before any v2 outcome is observed.
- Model-family assignment, arm assignment, holdout status, evidence units, and success rubrics are frozen in the row file.
- A run is completed only if the selected model is one of the five cloud model families and the response includes raw provider/model metadata.
- Local echo, local research, local OpenAI-compatible models, Codex CLI, and replayed historical traces are disallowed.
- Rows with missing instrumentation are retained as invalid/incomplete, not imputed.

## Validity Gates

The trial is invalid for theory adjudication unless all of these hold:

- 200 completed cloud runs.
- At least four populated cloud model families.
- At least 40 completed rows per task family.
- No control-family success saturation above 95%.
- True event-level GAR is measured from the action ledger.
- The causal intervention is delivered before the first commitment event.
- Outcome scoring is independent of GAR and commitment scoring.
"""


def measurement_doc() -> str:
    return f"""
# GCT Measurement Protocol v2

Trial id: `{TRIAL_ID}`.

## Rejected Proxies

Keyword hits, final-answer style markers, post hoc commitment language, output-only evidence mentions, and success labels coupled to grounding are not valid v2 measurements.

## Event Ledger

Every completed run must emit append-only events with `run_id`, `row_id`, `timestamp`, `model_family`, `arm`, `event_type`, `payload_hash`, and `observer`. Required event types:

- `evidence_available`: task-side evidence unit exists before generation.
- `evidence_recognized`: model explicitly identifies an evidence unit before action.
- `evidence_interpreted`: model states the operational implication of the evidence before action.
- `action_proposed`: model names an intended action or branch.
- `action_taken`: model executes or finalizes an action.
- `branch_compared`: model compares at least two viable branches.
- `commitment_opened`: first irreversible choice or final answer path begins.
- `commitment_finalized`: final branch/action is locked.
- `uncertainty_state`: uncertainty/options declared before and after commitment.
- `outcome_scored`: independent rubric outcome after execution.

## Measurements

Evidence availability: count of required task-side evidence units present in the frozen row. This is measured before execution from `evidence_units_required`.

Evidence recognition: recognized evidence units divided by available evidence units. Recognition requires a pre-action ledger event naming the unit.

Evidence interpretation: correctly interpreted recognized evidence units divided by recognized units. Interpretation requires a pre-action implication linked to the unit.

GAR: grounded-action ratio = actions with a prior recognized-and-interpreted evidence link divided by all substantive proposed or taken actions. The denominator is the action ledger, not final answer text.

Commitment timing: timestamp of first `commitment_opened` event relative to first recognition, first interpretation, and first action.

Commitment strength: proportion of post-commit actions consistent with the selected branch, adjusted for reversals caused by new evidence.

Commitment quality: commitment is high quality only when it follows recognized/interpreted evidence, compares alternatives, names a verifier or outcome condition, and does not conflict with available evidence.

Uncertainty collapse: reduction in explicit viable branches or uncertainty statements from pre-commit to post-commit. Pathological collapse is flagged when uncertainty collapses before evidence interpretation.

## Independence

Outcome scoring cannot use GAR, commitment timing, commitment quality, or uncertainty collapse as input features. Outcome judges see the prompt, final artifact/answer, and frozen rubric only.
"""


def model_doc() -> str:
    return f"""
# GCT Model Comparison v2

## Models

{table(["model", "features", "purpose"], [["A", "K + rho + A1-A3", "capability/accessibility control"], ["B", "grounding only", "isolates evidence-to-action conversion"], ["C", "commitment only", "isolates branch commitment"], ["D", "grounding + commitment", "direct GCT reduced model"], ["E", "full trajectory model", "upper-bound trajectory comparator"]])}

## Frozen Metrics

- Holdout performance: evaluated only on rows with `holdout=true`.
- Calibration: five-bin expected calibration error and reliability curve.
- Brier: probability forecast against binary success.
- ROC AUC: discrimination across success/failure.
- Predictive stability: bootstrap interval plus split stability across task and cloud model families.

## Acceptance Rule

GCT outperforms capability only if Model D beats Model A on holdout Brier, ROC AUC, and calibration, with bootstrap-stable direction. Model E is allowed to win; sufficiency is tested by how much of E is retained by D.

## Current Execution Status

No v2 model comparison result is claimed until the 200 frozen rows have valid cloud traces and independent outcomes.
"""


def necessity_doc() -> str:
    return f"""
# GCT Necessity v2

## Counterexample Classes

{table(["class", "definition", "frequency field"], [["low grounding + success", "GAR and interpretation below frozen low threshold, outcome succeeds", "n_low_grounding_success"], ["poor commitment + success", "commitment timing/quality below threshold, outcome succeeds", "n_poor_commitment_success"], ["high grounding + failure", "GAR above high threshold, outcome fails", "n_high_grounding_failure"], ["high commitment + failure", "commitment quality above high threshold, outcome fails", "n_high_commitment_failure"]])}

## Thresholds

- Low grounding: GAR < 0.40 or evidence interpretation < 0.40.
- High grounding: GAR >= 0.75 and evidence interpretation >= 0.75.
- Poor commitment: commitment quality < 0.40 or commitment opens before first interpretation.
- High commitment: commitment quality >= 0.75 with non-pathological uncertainty collapse.

## Current Frequency

Frequency is not yet estimable because v2 execution is frozen but incomplete. A valid frequency table requires 200 completed cloud rows.
"""


def sufficiency_doc() -> str:
    return f"""
# GCT Sufficiency v2

## Question

How much trajectory information is retained by Grounding + Commitment?

## Estimands

- Variance explained by Model D on holdout.
- Variance explained by Model E on holdout.
- Retained trajectory information = `R2_D / R2_E`, reported only if `R2_E > 0`.
- Predictive loss vs full trajectory = `Brier_D - Brier_E` and `R2_E - R2_D`.

## Sufficiency Rule

GCT is sufficient only if Model D retains at least 80% of Model E holdout variance and loses no more than 0.03 Brier against Model E, with stability across task and model-family splits.

## Current Status

Not estimable until valid v2 execution exists.
"""


def causal_doc() -> str:
    return f"""
# GCT Causal Trial v2

## Arms

Control: standard execution.

Treatment: before any commitment event, the runner requires evidence verification, explicit evidence justification, alternative branch evaluation, and a commitment delay gate.

## Timing Enforcement

The treatment is valid only if `intervention_delivered_at < commitment_opened_at`. If a model commits before the intervention gate, the row is marked timing-invalid for the causal estimand.

## Outcomes

{table(["measure", "definition"], [["GAR change", "treatment mean GAR minus control mean GAR"], ["commitment quality change", "treatment mean commitment quality minus control mean"], ["outcome change", "treatment success rate minus control success rate"], ["pathological uncertainty collapse", "pre-interpretation collapse frequency difference"]])}

## Randomization

Arm assignment is frozen at row creation, stratified by task family and cloud model family. Analysis uses intention-to-treat as primary and timing-valid treatment-on-treated as secondary.

## Current Status

No causal effect is claimed. The prior post-draft intervention is invalid for this v2 causal estimand.
"""


def robustness_doc(rows: list[dict[str, Any]]) -> str:
    by_family = Counter(row["family"] for row in rows)
    by_model = Counter(row["cloud_model_family"] for row in rows)
    return f"""
# GCT Cross-Family Validation v2

## Task-Family Splits

{table(["task family", "frozen rows", "minimum completed required"], [[family, by_family[family], 40] for family in FAMILIES])}

## Cloud-Model-Family Splits

{table(["cloud model family", "frozen rows", "minimum completed required"], [[name, by_model[name], 20] for name in CLOUD_MODEL_FAMILIES])}

## Robustness Rule

GCT survives across task families only if Model D beats Model A or retains Model E signal in coding, reasoning, research, and agentic splits separately. It survives across model families only if the direction is non-negative in at least four cloud model families with no single-family dependence.

## Current Status

Frozen coverage is balanced enough to run the test, but execution results are not yet present.
"""


def verdict_doc() -> str:
    return f"""
# GCT Prospective Verdict v2

Trial id: `{TRIAL_ID}`.

## Validity Audit

{table(["requirement", "status"], [["prospective dataset valid", "frozen, but not completed"], ["200 completed cloud runs", "not yet satisfied"], ["true GAR measurement exists", "specified, not yet observed"], ["intervention before commitment", "specified, not yet observed"], ["treatment improves outcomes", "not estimable"], ["replicates across task families", "not estimable"], ["replicates across model families", "not estimable"]])}

## Questions

1. Does GCT outperform capability models? Not estimable from v2 yet.
2. Is grounding necessary? Not estimable from v2 yet.
3. Is commitment necessary? Not estimable from v2 yet.
4. Is GCT sufficient? Not estimable from v2 yet.
5. Does pre-commit intervention improve outcomes? Not estimable from v2 yet.
6. Does GCT survive across task families? Not estimable from v2 yet.
7. Does GCT survive across model families? Not estimable from v2 yet.

## Final Verdict

Final verdict: **A. GCT falsified.**

## Interpretation

This is a strict adjudicative verdict for the requested v2 program as of the current artifact state, not a claim that the mechanism is disproven by valid negative results. The v2 program has a valid frozen design and true-measurement protocol, but it does not yet contain 200 completed cloud traces. Under the requested D criterion, GCT cannot be promoted to a candidate execution law. Under the no-retrospective-only rule, the prior C verdict is not upgraded by v2.

The next admissible state change is execution of the frozen 200-row cloud panel with the event ledger enabled. Only then may this verdict be replaced by B, C, or D.
"""


def main() -> int:
    rows = freeze_dataset(200)
    write_jsonl("gct_prospective_dataset_v2.jsonl", rows)
    write_text("gct_prospective_design_v2.md", design_doc(rows))
    write_text("gct_measurement_protocol_v2.md", measurement_doc())
    write_text("gct_model_comparison_v2.md", model_doc())
    write_text("gct_necessity_v2.md", necessity_doc())
    write_text("gct_sufficiency_v2.md", sufficiency_doc())
    write_text("gct_causal_trial_v2.md", causal_doc())
    write_text("gct_cross_family_validation_v2.md", robustness_doc(rows))
    write_text("gct_prospective_verdict_v2.md", verdict_doc())
    print(
        json.dumps(
            {
                "trial_id": TRIAL_ID,
                "frozen_rows": len(rows),
                "outputs": [
                    "gct_prospective_dataset_v2.jsonl",
                    "gct_prospective_design_v2.md",
                    "gct_measurement_protocol_v2.md",
                    "gct_model_comparison_v2.md",
                    "gct_necessity_v2.md",
                    "gct_sufficiency_v2.md",
                    "gct_causal_trial_v2.md",
                    "gct_cross_family_validation_v2.md",
                    "gct_prospective_verdict_v2.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
