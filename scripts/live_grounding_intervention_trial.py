from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_hub.config import HubConfig, RouteRule, load_config
from agent_hub.context import estimate_message_tokens, estimate_text_tokens
from agent_hub.core.router import AgentRouter, RouterError
from agent_hub.models import HubRequest, HubResponse


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"
SEED = 20260617
TRIAL_ID = "grounding-integrity-live-rct-2026-06-17-v1"
GROUNDING_RATIO_THRESHOLD = 0.42
CLOUD_PROVIDER_TYPES = {"ollama-cloud"}
CLOUD_MODEL_SUFFIX = ":cloud"
TASK_FILES = [
    ROOT / "benchmarks" / "coding" / "tasks.jsonl",
    ROOT / "benchmarks" / "debugging" / "tasks.jsonl",
    ROOT / "benchmarks" / "refactoring" / "tasks.jsonl",
    ROOT / "benchmarks" / "test-generation" / "tasks.jsonl",
]


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


def table(headers: list[str], rows: list[list[Any]]) -> str:
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        out.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(out)


def load_source_tasks(limit: int) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for path in TASK_FILES:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                row["source_file"] = path.relative_to(ROOT).as_posix()
                tasks.append(row)
    rng = random.Random(SEED)
    rng.shuffle(tasks)
    frozen: list[dict[str, Any]] = []
    for index, row in enumerate(tasks[:limit]):
        task_id = str(row.get("id") or f"live-{index:03d}")
        frozen_id = hashlib.sha256(f"{TRIAL_ID}|{task_id}|{index}".encode("utf-8")).hexdigest()[:16]
        frozen.append(
            {
                "trial_id": TRIAL_ID,
                "frozen_task_id": frozen_id,
                "source_task_id": task_id,
                "source_file": row.get("source_file"),
                "task_type": row.get("type") or row.get("category") or "unknown",
                "prompt": row.get("prompt") or "",
                "expected_keywords": list(row.get("expected_keywords") or []),
                "frozen_order": index,
                "frozen_seed": SEED,
            }
        )
    return frozen


def assign_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    assigned = []
    for row in tasks:
        item = dict(row)
        item["assigned_arm"] = "treatment" if rng.random() < 0.5 else "control"
        item["assignment_seed"] = SEED
        assigned.append(item)
    if len({row["assigned_arm"] for row in assigned}) == 1 and len(assigned) > 1:
        assigned[-1]["assigned_arm"] = "control" if assigned[0]["assigned_arm"] == "treatment" else "treatment"
    return assigned


def cloud_only_config(path: Path) -> HubConfig:
    config = load_config(path, auto_detect=False)
    cloud_agents = {
        name: agent
        for name, agent in config.agents.items()
        if str(agent.model).endswith(CLOUD_MODEL_SUFFIX)
        and str(agent.provider_type or "").lower() in CLOUD_PROVIDER_TYPES
        and agent.enabled
    }
    if not cloud_agents:
        raise RuntimeError("No enabled cloud-only agents are configured.")
    config.agents = cloud_agents
    config.default_route = list(cloud_agents)
    config.routes = [RouteRule(name="live-grounding-trial", agents=list(cloud_agents), keywords=[])]
    config.routing = dict(config.routing)
    config.routing["max_provider_attempts"] = max(5, int(config.routing.get("max_provider_attempts") or 5))
    config.routing["continue_after_output_limit"] = False
    config.enable_load_balancing = False
    config.auto_detect_local_models = False
    config.adaptive_learning_enabled = False
    config.routing_memory_enabled = False
    config.repo_context_enabled = False
    config.approval_mode = "auto"
    config.tool_loop_enabled = False
    config.tool_loop_enabled_for_cline = False
    config.compatibility_mode = dict(config.compatibility_mode)
    config.compatibility_mode["emulate_tools"] = False
    config.compatibility_mode["minimal_tool_schema"] = False
    return config


def base_messages(task: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are running a frozen Agent-Hub benchmark task. "
                "Answer directly with a minimal patch plan and regression test. "
                "Do not mention this benchmark protocol."
            ),
        },
        {"role": "user", "content": str(task["prompt"])},
    ]


def usage_tokens(response: HubResponse, messages: list[dict[str, str]]) -> int:
    usage = response.usage or {}
    for key in ("total_tokens", "total", "tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            return value
    prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
    output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
    if isinstance(prompt_tokens, int) and isinstance(output_tokens, int):
        return prompt_tokens + output_tokens
    return estimate_message_tokens(messages) + estimate_text_tokens(response.text)


def call_cloud(
    router: AgentRouter,
    task: dict[str, Any],
    messages: list[dict[str, str]],
    *,
    phase: str,
    preferred_agent: str | None = None,
    max_tokens: int = 520,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = router.route(
        HubRequest(
            session_id=f"{TRIAL_ID}-{task['frozen_task_id']}-{phase}",
            route="live-grounding-trial",
            preferred_agent=preferred_agent,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.0,
            record_session=False,
            raw={"seed": SEED},
        )
    )
    latency_ms = int(round((time.perf_counter() - started) * 1000))
    if not str(response.model).endswith(CLOUD_MODEL_SUFFIX) and not str(response.agent).endswith("-cloud"):
        raise RuntimeError(f"Non-cloud model selected: {response.agent}/{response.model}")
    return {
        "ok": True,
        "agent": response.agent,
        "model": response.model,
        "provider": response.provider,
        "text": response.text,
        "tokens": usage_tokens(response, messages),
        "latency_ms": latency_ms,
        "failover": [event.to_dict() for event in response.failover],
    }


def keyword_hits(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if str(keyword).lower() in lowered)


def evaluate(text: str, keywords: list[str]) -> dict[str, Any]:
    hits = keyword_hits(text, keywords)
    needed = max(1, min(len(keywords), math.ceil(len(keywords) * 0.75)))
    contradiction_terms = ["not sure", "cannot determine", "impossible to know", "contradiction"]
    contradiction_penalty = any(term in text.lower() for term in contradiction_terms)
    success = hits >= needed and not contradiction_penalty
    return {
        "success": int(success),
        "keyword_hits": hits,
        "keyword_total": len(keywords),
        "keyword_threshold": needed,
        "contradiction_penalty": contradiction_penalty,
    }


def detect_triggers(text: str, keywords: list[str]) -> dict[str, Any]:
    lowered = text.lower()
    hits = keyword_hits(text, keywords)
    ratio = hits / max(1, len(keywords))
    contradictory = any(term in lowered for term in ["must not", "but also", "contradicts", "inconsistent"])
    mismatch = hits < max(1, math.ceil(len(keywords) * 0.5)) or "test" not in lowered
    collapse = any(term in lowered for term in ["cannot", "unsure", "unknown"]) and hits < len(keywords)
    ratio_low = ratio < GROUNDING_RATIO_THRESHOLD
    triggers = {
        "contradictory_grounding": contradictory,
        "evidence_action_mismatch": mismatch,
        "grounding_collapse": collapse,
        "grounded_action_ratio_below_threshold": ratio_low,
    }
    return {
        "triggered": any(triggers.values()),
        "grounded_action_ratio": round(ratio, 6),
        "triggers": triggers,
    }


def intervention_type(trigger_info: dict[str, Any]) -> str:
    triggers = trigger_info["triggers"]
    if triggers.get("contradictory_grounding"):
        return "evidence recheck"
    if triggers.get("evidence_action_mismatch"):
        return "action consistency check"
    if triggers.get("grounding_collapse"):
        return "evidence verification"
    return "grounding confirmation"


def intervention_messages(task: dict[str, Any], draft: str, trigger_info: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Grounding Integrity intervention enabled. Perform evidence recheck, "
                "evidence verification, action consistency check, and grounding confirmation. "
                "Revise only if the accepted evidence, interpretation, and action are inconsistent. "
                "Keep the corrected final answer under 140 words."
            ),
        },
        {"role": "user", "content": f"Frozen task:\n{task['prompt']}"},
        {
            "role": "assistant",
            "content": f"Initial answer before intervention:\n{draft}",
        },
        {
            "role": "user",
            "content": (
                "Intervention trigger state: "
                + json.dumps(trigger_info, sort_keys=True)
                + "\nReturn a corrected final answer that explicitly preserves the task evidence and includes the regression test."
            ),
        },
    ]


def execute_trial(config_path: Path, limit: int) -> dict[str, Any]:
    frozen = assign_tasks(load_source_tasks(limit))
    write_jsonl("live_frozen_intervention_batch.jsonl", frozen)
    config = cloud_only_config(config_path)
    router = AgentRouter(config)
    log_rows: list[dict[str, Any]] = []

    for task in frozen:
        row: dict[str, Any] = {
            **task,
            "trial_id": TRIAL_ID,
            "started_at_unix": time.time(),
            "intervention_delivered": False,
            "trigger_event": "none",
            "intervention_type": "none",
            "intervention_timing": "none",
            "token_cost": 0,
            "latency_cost_ms": 0,
            "cloud_only": True,
        }
        try:
            first_messages = base_messages(task)
            first = call_cloud(router, task, first_messages, phase="draft")
            row.update(
                {
                    "draft_agent": first["agent"],
                    "draft_model": first["model"],
                    "draft_tokens": first["tokens"],
                    "draft_latency_ms": first["latency_ms"],
                    "draft_text_sha256": hashlib.sha256(first["text"].encode("utf-8")).hexdigest(),
                    "draft_excerpt": first["text"][:600],
                }
            )
            final_text = first["text"]
            trigger_info = detect_triggers(first["text"], task["expected_keywords"])
            row["grounded_action_ratio"] = trigger_info["grounded_action_ratio"]
            row["trigger_flags"] = trigger_info["triggers"]
            if task["assigned_arm"] == "treatment" and trigger_info["triggered"]:
                messages = intervention_messages(task, first["text"], trigger_info)
                started = time.perf_counter()
                intervention_config = copy.deepcopy(config)
                intervention_config.agents = {first["agent"]: intervention_config.agents[first["agent"]]}
                intervention_config.default_route = [first["agent"]]
                intervention_config.routes = [RouteRule(name="live-grounding-trial", agents=[first["agent"]], keywords=[])]
                intervention_router = AgentRouter(intervention_config)
                second = call_cloud(
                    intervention_router,
                    task,
                    messages,
                    phase="intervention",
                    preferred_agent=first["agent"],
                    max_tokens=320,
                )
                timing = int(round((time.perf_counter() - started) * 1000))
                final_text = second["text"]
                row.update(
                    {
                        "intervention_delivered": True,
                        "trigger_event": ",".join(name for name, enabled in trigger_info["triggers"].items() if enabled),
                        "intervention_type": intervention_type(trigger_info),
                        "intervention_timing": "after initial answer before final outcome",
                        "intervention_agent": second["agent"],
                        "intervention_model": second["model"],
                        "intervention_tokens": second["tokens"],
                        "intervention_latency_ms": second["latency_ms"],
                        "intervention_call_wall_ms": timing,
                        "token_cost": second["tokens"],
                        "latency_cost_ms": second["latency_ms"],
                        "intervention_text_sha256": hashlib.sha256(second["text"].encode("utf-8")).hexdigest(),
                    }
                )
            final = evaluate(final_text, task["expected_keywords"])
            draft_eval = evaluate(first["text"], task["expected_keywords"])
            row.update(
                {
                    "ok": True,
                    "draft_success": draft_eval["success"],
                    "final_success": final["success"],
                    "final_outcome": "success" if final["success"] else "failure",
                    "final_keyword_hits": final["keyword_hits"],
                    "final_keyword_total": final["keyword_total"],
                    "final_text_sha256": hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
                    "final_excerpt": final_text[:600],
                    "completed_at_unix": time.time(),
                }
            )
        except (RouterError, RuntimeError) as exc:
            row.update(
                {
                    "ok": False,
                    "error": str(exc),
                    "final_success": 0,
                    "final_outcome": "execution_error",
                    "completed_at_unix": time.time(),
                }
            )
            if isinstance(exc, RouterError):
                row["failover"] = [event.to_dict() for event in exc.failover]
        log_rows.append(row)
        write_jsonl("live_trial_execution_log.jsonl", log_rows)

    render_reports(frozen, log_rows)
    return summarize(log_rows)


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
    p1 = max(0.0, min(1.0, p1))
    p0 = max(0.0, min(1.0, p0))
    return 2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p0))


def arm_stats(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    group = [row for row in rows if row["assigned_arm"] == arm]
    successes = sum(int(row.get("final_success") or 0) for row in group)
    delivered = [row for row in group if row.get("intervention_delivered")]
    token_costs = [float(row.get("token_cost") or 0) for row in group]
    latency_costs = [float(row.get("latency_cost_ms") or 0) for row in group]
    p, lo, hi = mean_ci(successes, len(group))
    return {
        "n": len(group),
        "successes": successes,
        "failures": len(group) - successes,
        "success_rate": p,
        "success_ci": (lo, hi),
        "failure_rate": (len(group) - successes) / max(1, len(group)),
        "delivered": len(delivered),
        "triggered": sum(1 for row in group if row.get("trigger_event") not in (None, "none")),
        "recovered": sum(1 for row in delivered if int(row.get("draft_success") or 0) == 0 and int(row.get("final_success") or 0) == 1),
        "regressed": sum(1 for row in delivered if int(row.get("draft_success") or 0) == 1 and int(row.get("final_success") or 0) == 0),
        "token_overhead": mean(token_costs) if token_costs else 0.0,
        "latency_overhead_ms": mean(latency_costs) if latency_costs else 0.0,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    control = arm_stats(rows, "control")
    treatment = arm_stats(rows, "treatment")
    diff, lo, hi = diff_ci(treatment["success_rate"], treatment["n"], control["success_rate"], control["n"])
    rel = diff / control["success_rate"] if control["success_rate"] else None
    recovered = treatment["recovered"]
    cost_per_recovered = (
        sum(float(row.get("token_cost") or 0) for row in rows if row.get("assigned_arm") == "treatment") / recovered
        if recovered
        else None
    )
    return {
        "trial_id": TRIAL_ID,
        "rows": len(rows),
        "control": control,
        "treatment": treatment,
        "absolute_success_improvement": diff,
        "absolute_success_improvement_ci": [lo, hi],
        "relative_improvement": rel,
        "effect_size_cohens_h": cohens_h(treatment["success_rate"], control["success_rate"]),
        "cost_per_recovered_failure_tokens": cost_per_recovered,
        "models": dict(Counter(row.get("draft_model") for row in rows if row.get("draft_model"))),
    }


def verdict(summary: dict[str, Any]) -> str:
    treatment = summary["treatment"]
    if treatment["delivered"] <= 0:
        return "B. Useful warning signal"
    improvement = float(summary["absolute_success_improvement"])
    if improvement <= 0 or treatment["recovered"] <= treatment["regressed"]:
        return "B. Useful warning signal"
    if treatment["token_overhead"] > 2500 or treatment["latency_overhead_ms"] > 45000:
        return "B. Useful warning signal"
    return "C. Effective intervention mechanism"


def render_reports(frozen: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    summary = summarize(rows)
    control = summary["control"]
    treatment = summary["treatment"]
    diff = summary["absolute_success_improvement"]
    ci = summary["absolute_success_improvement_ci"]
    final_verdict = verdict(summary)
    trigger_rows = [
        [
            name,
            sum(1 for row in rows if (row.get("trigger_flags") or {}).get(name)),
            sum(1 for row in rows if row.get("assigned_arm") == "treatment" and (row.get("trigger_flags") or {}).get(name)),
            sum(1 for row in rows if row.get("assigned_arm") == "treatment" and row.get("intervention_delivered") and (row.get("trigger_flags") or {}).get(name)),
        ]
        for name in [
            "contradictory_grounding",
            "evidence_action_mismatch",
            "grounding_collapse",
            "grounded_action_ratio_below_threshold",
        ]
    ]
    execution_rows = [
        [
            row["frozen_task_id"],
            row["assigned_arm"],
            row.get("draft_model", ""),
            row.get("trigger_event", "none"),
            row.get("intervention_type", "none"),
            row.get("token_cost", 0),
            row.get("latency_cost_ms", 0),
            row.get("final_outcome"),
        ]
        for row in rows
    ]

    write_text(
        "live_intervention_trial_design.md",
        f"""
# Live Grounding Integrity Intervention Trial Design

Trial id: `{TRIAL_ID}`. Frozen date: 2026-06-17. Assignment seed: `{SEED}`.

## Frozen Live Batch

Machine-readable batch: `research/live_frozen_intervention_batch.jsonl`.

{table(["field", "value"], [["frozen tasks", len(frozen)], ["cloud rule", "enabled agents with provider_type=ollama-cloud and model suffix :cloud"], ["control", "normal Agent-Hub execution"], ["treatment", "Agent-Hub execution plus delivered Grounding Integrity intervention when triggered"], ["threshold", GROUNDING_RATIO_THRESHOLD]])}

## Trigger Rules

{table(["trigger", "rule"], [["contradictory grounding", "draft contains explicit inconsistency markers"], ["evidence-action mismatch", "draft misses at least half of frozen evidence keywords or omits a test action"], ["grounding collapse", "draft expresses inability/unknown while evidence keywords remain missing"], ["grounded-action ratio below threshold", f"keyword-grounded action ratio < {GROUNDING_RATIO_THRESHOLD}"]])}

## Delivered Interventions

Treatment-only triggered rows receive a second cloud call with evidence recheck, evidence verification, action consistency check, and grounding confirmation. Control rows receive no intervention.
""",
    )

    write_text(
        "live_trial_execution_log.md",
        f"""
# Live Trial Execution Log

Machine-readable full log: `research/live_trial_execution_log.jsonl`.

## Trigger And Delivery Summary

{table(["trigger", "all rows", "treatment rows", "delivered rows"], trigger_rows)}

## Run Log

{table(["task", "arm", "model", "trigger event", "intervention type", "token cost", "latency cost ms", "final outcome"], execution_rows)}
""",
    )

    write_text(
        "live_trial_results.md",
        f"""
# Live Trial Results

## Arm Comparison

{table(["arm", "runs", "successes", "failures", "success rate", "failure rate", "triggered", "delivered", "recovered", "regressed"], [["Control", control["n"], control["successes"], control["failures"], pct(control["success_rate"]), pct(control["failure_rate"]), control["triggered"], control["delivered"], control["recovered"], control["regressed"]], ["Treatment", treatment["n"], treatment["successes"], treatment["failures"], pct(treatment["success_rate"]), pct(treatment["failure_rate"]), treatment["triggered"], treatment["delivered"], treatment["recovered"], treatment["regressed"]]])}

## Outcome

Absolute success improvement: {pct(diff)} with 95% CI [{pct(ci[0])}, {pct(ci[1])}].

Relative improvement: {pct(summary["relative_improvement"])}.
""",
    )

    write_text(
        "live_intervention_effect_size.md",
        f"""
# Live Intervention Effect Size

{table(["estimand", "value"], [["control success rate", pct(control["success_rate"])], ["treatment success rate", pct(treatment["success_rate"])], ["absolute success improvement", pct(diff)], ["95% CI", f"[{pct(ci[0])}, {pct(ci[1])}]"], ["relative improvement", pct(summary["relative_improvement"])], ["Cohen's h", fmt(summary["effect_size_cohens_h"])], ["recovery rate among treatment runs", pct(treatment["recovered"] / max(1, treatment["n"]))]])}

This is a live randomized assignment contrast. It is intentionally reported without historical-only causal claims.
""",
    )

    write_text(
        "live_intervention_cost.md",
        f"""
# Live Intervention Cost

{table(["measure", "control", "treatment"], [["mean token overhead per assigned run", fmt(control["token_overhead"]), fmt(treatment["token_overhead"])], ["mean latency overhead ms per assigned run", fmt(control["latency_overhead_ms"]), fmt(treatment["latency_overhead_ms"])], ["delivered interventions", control["delivered"], treatment["delivered"]], ["cost per recovered failure, tokens", "not applicable", fmt(summary["cost_per_recovered_failure_tokens"])]])}

Token cost is the additional treatment intervention call cost. Latency cost is the additional treatment intervention call latency.
""",
    )

    write_text(
        "live_causal_verdict.md",
        f"""
# Live Causal Verdict

Final verdict: **{final_verdict}**

## Basis

{table(["criterion", "result"], [["real delivered interventions", treatment["delivered"]], ["absolute success improvement", pct(diff)], ["95% CI", f"[{pct(ci[0])}, {pct(ci[1])}]"], ["recovered failures", treatment["recovered"]], ["regressions after intervention", treatment["regressed"]], ["mean treatment token overhead", fmt(treatment["token_overhead"])], ["mean treatment latency overhead ms", fmt(treatment["latency_overhead_ms"])]])}

Only C or D is allowed when delivered interventions improve outcomes with acceptable cost. This first live batch does not promote to D because production-core status requires broader replicated evidence.
""",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="agent-hub.config.json")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    summary = execute_trial(Path(args.config), max(2, min(args.limit, 40)))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
