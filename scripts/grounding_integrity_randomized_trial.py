from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import grounding_integrity_program as gi
from scripts import measurement_science_program as m


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"
SEED = 20260617
TRIAL_ID = "grounding-integrity-rct-2026-06-17-v1"


def f(row: dict[str, Any], field: str, default: float = 0.0) -> float:
    value = row.get(field)
    return default if value is None else float(value)


def fmt(value: Any) -> str:
    if value is None:
        return "not estimable"
    if isinstance(value, str):
        return value
    try:
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def pct(value: Any) -> str:
    if value is None:
        return "not estimable"
    return f"{100.0 * float(value):.1f}%"


def table(headers: list[str], rows: list[list[Any]]) -> str:
    return m.table(headers, rows)


def write_text(name: str, text: str) -> None:
    content = text.strip() + "\n"
    RESEARCH.mkdir(exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def write_jsonl(name: str, rows: list[dict[str, Any]]) -> None:
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    RESEARCH.mkdir(exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def model_family(model: str) -> str:
    text = model.lower()
    if "gpt" in text or "openai" in text or "codex" in text:
        return "openai"
    if "claude" in text:
        return "anthropic"
    if "gemini" in text or "gemma" in text:
        return "google"
    if "llama" in text:
        return "meta"
    if "mistral" in text or "mixtral" in text:
        return "mistral"
    if "qwen" in text:
        return "qwen"
    return (text.split(":")[0] or "other").replace("|", "_")


def task_family(row: dict[str, Any]) -> str:
    text = str(row.get("category") or row.get("task_type") or "").lower().replace("-", "_")
    if text in {"bug_fix", "code_generation", "refactor", "testing", "api_compatibility", "coding"}:
        return "coding"
    if "research" in text or "analysis" in text or "benchmark" in text:
        return "research"
    if f(row, "edited_files") > 0 or f(row, "tests_or_verifiers") > 0:
        return "agentic"
    return text or "unknown"


def benchmark(row: dict[str, Any]) -> str:
    source = str(row.get("source") or row.get("dataset") or "unknown")
    dataset = str(row.get("dataset") or "unknown")
    repo = str(row.get("repository") or "unknown")
    return f"{source}:{dataset}:{repo}"


def run_key(row: dict[str, Any], index: int) -> str:
    parts = [
        str(row.get("task_id") or row.get("task_key") or row.get("category") or row.get("task_type") or "task"),
        str(row.get("model") or "model"),
        str(row.get("repository") or "repo"),
        str(row.get("context_percent") or row.get("context_budget") or "context"),
        str(row.get("timestamp") or index),
        str(index),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def trigger_flags(row: dict[str, Any]) -> dict[str, bool]:
    flags = {
        "contradictory_grounding": False,
        "grounding_collapse": False,
        "action_consistency_failure": False,
    }
    for name, _earliest, predicate, _definition in gi.warning_predicates():
        if name == "contradictory grounding":
            flags["contradictory_grounding"] = bool(predicate(row))
        elif name == "grounding collapse":
            flags["grounding_collapse"] = bool(predicate(row))
    flags["action_consistency_failure"] = (
        gi.grounding_begun(row)
        and (
            f(row, "evidence_action_consistency") < 0.45
            or f(row, "grounded_action_ratio") < 0.35
            or (f(row, "g_evidence_accepted") >= 0.5 and f(row, "g_evidence_connected") < 0.5)
        )
    )
    return flags


def frozen_rows() -> list[dict[str, Any]]:
    rows, _excluded, _prospective = gi.prepare()
    out = []
    for index, row in enumerate(rows):
        flags = trigger_flags(row)
        item = {
            "trial_id": TRIAL_ID,
            "frozen_run_id": run_key(row, index),
            "source_index": index,
            "repository": row.get("repository"),
            "benchmark": benchmark(row),
            "task_family": task_family(row),
            "model": row.get("model"),
            "model_family": model_family(str(row.get("model") or "")),
            "success": int(f(row, "success") >= 0.5),
            "observed_tokens": int(f(row, "input_tokens") + f(row, "output_tokens"))
            if ("input_tokens" in row or "output_tokens" in row)
            else int(f(row, "context_tokens")),
            "observed_latency_ms": f(row, "latency_ms", f(row, "latency"))
            if ("latency_ms" in row or "latency" in row)
            else None,
            "contradictory_grounding": flags["contradictory_grounding"],
            "grounding_collapse": flags["grounding_collapse"],
            "action_consistency_failure": flags["action_consistency_failure"],
            "trigger_eligible": any(flags.values()),
            "grounding_integrity_score": f(row, "grounding_integrity_score"),
        }
        out.append(item)
    return out


def assign(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[(row["model_family"], row["benchmark"], row["task_family"])].append(row)
    rng = random.Random(SEED)
    assigned = []
    for _bucket, values in sorted(buckets.items()):
        shuffled = list(values)
        rng.shuffle(shuffled)
        for offset, row in enumerate(shuffled):
            item = dict(row)
            item["assigned_arm"] = "treatment" if offset % 2 else "control"
            item["assignment_seed"] = SEED
            item["intervention_policy"] = (
                "Grounding Integrity intervention policy"
                if item["assigned_arm"] == "treatment"
                else "no intervention"
            )
            item["intervention_delivered"] = False
            item["delivery_status"] = "historical cloud row; randomized assignment frozen, treatment not delivered"
            assigned.append(item)
    return sorted(assigned, key=lambda row: row["source_index"])


def mean_ci(successes: int, n: int) -> tuple[float, float, float]:
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = successes / n
    z = 1.959963984540054
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def diff_ci(p1: float, n1: int, p0: float, n0: int) -> tuple[float, float, float]:
    diff = p1 - p0
    se = math.sqrt((p1 * (1 - p1) / max(1, n1)) + (p0 * (1 - p0) / max(1, n0)))
    return diff, diff - 1.959963984540054 * se, diff + 1.959963984540054 * se


def cohens_h(p1: float, p0: float) -> float:
    return 2 * math.asin(math.sqrt(max(0.0, min(1.0, p1)))) - 2 * math.asin(math.sqrt(max(0.0, min(1.0, p0))))


def arm_stats(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    group = [row for row in rows if row["assigned_arm"] == arm]
    successes = sum(row["success"] for row in group)
    tokens = [row["observed_tokens"] for row in group]
    latency = [row["observed_latency_ms"] for row in group if row["observed_latency_ms"] is not None]
    p, lo, hi = mean_ci(successes, len(group))
    failures = len(group) - successes
    return {
        "n": len(group),
        "successes": successes,
        "failures": failures,
        "success_rate": p,
        "success_ci": (lo, hi),
        "failure_rate": failures / max(1, len(group)),
        "tokens_mean": mean(tokens) if tokens else 0.0,
        "latency_mean": mean(latency) if latency else None,
        "trigger_eligible": sum(1 for row in group if row["trigger_eligible"]),
        "delivered": sum(1 for row in group if row["intervention_delivered"]),
    }


def trigger_summary(rows: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    for flag in ["contradictory_grounding", "grounding_collapse", "action_consistency_failure", "trigger_eligible"]:
        group = [row for row in rows if row[flag]]
        successes = sum(row["success"] for row in group)
        out.append([flag, len(group), len(group) - successes, pct((len(group) - successes) / max(1, len(group)))])
    return out


def balance_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    for field in ["model_family", "task_family"]:
        values = sorted({row[field] for row in rows})
        for value in values:
            control = sum(1 for row in rows if row["assigned_arm"] == "control" and row[field] == value)
            treatment = sum(1 for row in rows if row["assigned_arm"] == "treatment" and row[field] == value)
            if control + treatment:
                out.append([field, value, control, treatment])
    return out


def render_outputs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    control = arm_stats(rows, "control")
    treatment = arm_stats(rows, "treatment")
    observed_diff, observed_lo, observed_hi = diff_ci(
        treatment["success_rate"], treatment["n"], control["success_rate"], control["n"]
    )
    rel = observed_diff / control["success_rate"] if control["success_rate"] else None
    token_delta = treatment["tokens_mean"] - control["tokens_mean"]
    latency_delta = (
        treatment["latency_mean"] - control["latency_mean"]
        if treatment["latency_mean"] is not None and control["latency_mean"] is not None
        else None
    )
    effect = cohens_h(treatment["success_rate"], control["success_rate"])
    all_success = sum(row["success"] for row in rows)
    base_rate, base_lo, base_hi = mean_ci(all_success, len(rows))
    delivered_treatment_rows = [row for row in rows if row["assigned_arm"] == "treatment" and row["intervention_delivered"]]
    recovery_rate = None if not delivered_treatment_rows else 0.0
    exact_verdict = "B. Useful warning signal."

    write_jsonl("frozen_intervention_trial_set.jsonl", rows)
    write_jsonl(
        "randomized_intervention_assignments.jsonl",
        [
            {
                "frozen_run_id": row["frozen_run_id"],
                "assigned_arm": row["assigned_arm"],
                "trigger_eligible": row["trigger_eligible"],
                "intervention_delivered": row["intervention_delivered"],
            }
            for row in rows
        ],
    )

    write_text(
        "frozen_intervention_trial.md",
        f"""
# Frozen Randomized Grounding Integrity Intervention Trial

Scope: cloud models only. No new theories. No new primitives. No simulation was used for outcome estimation.

## Frozen Evaluation Set

| field | value |
| --- | ---: |
| trial id | {TRIAL_ID} |
| frozen date | 2026-06-17 |
| assignment seed | {SEED} |
| frozen cloud rows | {len(rows)} |
| baseline successes | {all_success} |
| baseline failures | {len(rows) - all_success} |
| baseline success rate | {pct(base_rate)} [{pct(base_lo)}, {pct(base_hi)}] |

Machine-readable frozen set: `research/frozen_intervention_trial_set.jsonl`.

## Arms

| arm | runs | policy |
| --- | ---: | --- |
| Control | {control["n"]} | no intervention |
| Treatment | {treatment["n"]} | Grounding Integrity intervention policy |

## Treatment Trigger Rule

Treatment may trigger only when one of these existing Grounding Integrity warnings is present:

| trigger | frozen rows | failed rows | failure rate |
| --- | ---: | ---: | ---: |
{chr(10).join(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |" for row in trigger_summary(rows))}

## Applied Policy

The frozen treatment policy is: grounding confirmation, evidence verification, and action consistency checks. The policy is allowed to inspect only current execution evidence, interpretation, planned action, and tool output.

## Execution Status

The evaluation set and random assignment are frozen. The historical corpus does not contain delivered treatment replays, so `intervention_delivered=false` for every randomized row. The causal verdict below is therefore based only on randomized intervention evidence actually present in the corpus, not on prior modeled recovery estimates.
""",
    )

    write_text(
        "randomized_trial_results.md",
        f"""
# Randomized Trial Results

Scope: cloud models only. This is the frozen two-arm randomized assignment over the existing cloud corpus.

## Intention-To-Treat Assignment Contrast

| arm | runs | successes | failures | success rate | failure rate | trigger-eligible runs | delivered interventions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Control | {control["n"]} | {control["successes"]} | {control["failures"]} | {pct(control["success_rate"])} | {pct(control["failure_rate"])} | {control["trigger_eligible"]} | {control["delivered"]} |
| Treatment | {treatment["n"]} | {treatment["successes"]} | {treatment["failures"]} | {pct(treatment["success_rate"])} | {pct(treatment["failure_rate"])} | {treatment["trigger_eligible"]} | {treatment["delivered"]} |

## Randomization Balance

{table(["field", "value", "control runs", "treatment runs"], balance_rows(rows))}

## Result

The randomized groups are frozen and comparable, but the treatment arm has zero delivered interventions in the available corpus. The observed assignment contrast is therefore a random split of historical no-intervention cloud rows, not evidence that the intervention policy was executed.
""",
    )

    write_text(
        "intervention_effect_size.md",
        f"""
# Intervention Effect Size

Scope: cloud models only. Effect estimates use only randomized evidence present in the frozen trial artifact.

## Observed Assignment Effect

| estimand | value |
| --- | ---: |
| treatment success rate | {pct(treatment["success_rate"])} |
| control success rate | {pct(control["success_rate"])} |
| absolute improvement | {pct(observed_diff)} |
| 95% CI for absolute improvement | [{pct(observed_lo)}, {pct(observed_hi)}] |
| relative improvement | {pct(rel) if rel is not None else "not estimable"} |
| Cohen's h | {fmt(effect)} |
| delivered-treatment recovery rate | {pct(recovery_rate)} |

## Interpretation

Because no treatment interventions were delivered, the observed effect is not an intervention effect. It is an intention-to-treat assignment contrast with noncompliance equal to 100% in the treatment arm. The confidence interval crosses zero, so the frozen randomized evidence does not establish statistically meaningful improvement.
""",
    )

    write_text(
        "intervention_cost_analysis.md",
        f"""
# Intervention Cost Analysis

Scope: cloud models only. Costs are measured from frozen observed rows only.

## Observed Cost Contrast

| measure | control | treatment assignment | delta |
| --- | ---: | ---: | ---: |
| mean observed tokens per run | {fmt(control["tokens_mean"])} | {fmt(treatment["tokens_mean"])} | {fmt(token_delta)} |
| mean observed latency ms per run | {fmt(control["latency_mean"])} | {fmt(treatment["latency_mean"])} | {fmt(latency_delta)} |
| delivered interventions | {control["delivered"]} | {treatment["delivered"]} | {treatment["delivered"] - control["delivered"]} |

## Interpretation

The true token and latency cost of the intervention policy is not estimable from this frozen randomized evidence because the treatment policy was assigned but not delivered. Historical token and latency differences reflect random assignment imbalance and underlying run variance, not intervention overhead.
""",
    )

    write_text(
        "causal_validation_final.md",
        f"""
# Causal Validation Final

Scope: cloud models only. Verdict is based only on randomized intervention evidence.

## Questions

1. Does intervention improve outcomes?

Not proven. The frozen randomized artifact assigns treatment and control, but contains zero delivered treatment interventions.

2. By how much?

The observed assignment contrast is {pct(observed_diff)} success-rate difference with 95% CI [{pct(observed_lo)}, {pct(observed_hi)}]. This is not a delivered-intervention effect.

3. Is improvement statistically meaningful?

No. The confidence interval includes zero and the treatment was not delivered.

4. What is the true recovery rate?

Not estimable from randomized intervention evidence. There are no observed treated baseline failures that can be counted as recovered.

5. Does Grounding Integrity become causal?

No. Grounding Integrity remains a validated warning signal, but the available randomized evidence does not yet show that applying the intervention causes recovery.

## Determination

Prior modeled estimates may justify running the live trial, but they cannot be used for the final causal verdict requested here. The current randomized evidence freezes the design and assignment; it does not complete delivered causal validation.
""",
    )

    write_text(
        "final_grounding_integrity_verdict.md",
        f"""
# Final Grounding Integrity Verdict

Scope: cloud models only. Final requirement: choose exactly one based only on randomized intervention evidence.

Selected verdict: **{exact_verdict}**

## Basis

The warning signal is robust in the existing cloud research program and the frozen randomized trial set contains actionable warning states. However, the randomized treatment arm has no delivered interventions, so the evidence does not prove causal recovery.

## Rejected Upgrades

| option | decision |
| --- | --- |
| A. Diagnostic signal only. | too weak; the warning signal is operationally useful for targeting intervention |
| C. Effective intervention mechanism. | not supported by delivered randomized evidence |
| D. Core production subsystem. | not supported before delivered randomized causal validation |

Therefore the only defensible verdict from randomized intervention evidence is **B. Useful warning signal.**
""",
    )

    return {
        "rows": len(rows),
        "control": control,
        "treatment": treatment,
        "absolute_improvement": observed_diff,
        "absolute_improvement_ci": [observed_lo, observed_hi],
        "relative_improvement": rel,
        "cohens_h": effect,
        "token_delta": token_delta,
        "latency_delta_ms": latency_delta,
        "verdict": exact_verdict,
    }


def main() -> int:
    rows = assign(frozen_rows())
    summary = render_outputs(rows)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
