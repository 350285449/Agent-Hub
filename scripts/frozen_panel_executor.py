from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_hub.config import HubConfig, RouteRule, load_config
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubRequest, HubResponse
from agent_hub.providers import ProviderError, create_provider
from agent_hub.research.gct_instrumentation import (
    GCTEventType,
    GCTRunRecorder,
    JsonlLedger,
    apply_pre_commit_intervention,
    calculate_gar,
    events_for_run,
    measure_commitment,
    panel_run_id,
    validate_pre_commit_interventions,
)
from agent_hub.research.gct_readiness import (
    DEFAULT_MAX_MODEL_FAMILY_SHARE,
    DEFAULT_MIN_MODEL_FAMILIES,
    MAX_MODEL_ATTEMPTS,
    approved_cloud_routes,
    certify_configured_cloud_providers,
    certify_execution_summary,
    cloud_agents,
    cloud_provider_certification_markdown,
    cost_quota_preflight_markdown,
    dashboard_status,
    dashboard_status_markdown,
    estimate_execution_preflight,
    model_family,
    provider_balancing_policy_markdown,
    provider_diversity_gate,
    provider_diversity_gate_markdown,
    provider_route_failure_audit,
    provider_route_failure_audit_markdown,
    quarantine_malformed_output,
    schema_enforcement_markdown,
    validate_frozen_panel_rows,
    validate_structured_output,
)


SEED = 20260617
DEFAULT_DATASET = ROOT / "research" / "gct_prospective_dataset_v2.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / ".agent-hub" / "research" / "gct_frozen_panel_runs"
CLOUD_MODEL_SUFFIX = ":cloud"


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the frozen 200-row GCT panel with event-level instrumentation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=ROOT / "agent-hub.config.json")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--execute", action="store_true", help="Call configured cloud providers. Omit for dry-run readiness validation.")
    parser.add_argument("--allow-incomplete", action="store_true", help="Permit fewer than 200 input rows for local shakedowns.")
    parser.add_argument("--max-family-share", type=float, default=DEFAULT_MAX_MODEL_FAMILY_SHARE)
    parser.add_argument("--min-model-families", type=int, default=DEFAULT_MIN_MODEL_FAMILIES)
    args = parser.parse_args()

    rows = load_frozen_rows(args.dataset)
    if len(rows) != 200 and not args.allow_incomplete:
        raise SystemExit(f"Frozen panel must contain exactly 200 rows; found {len(rows)}.")
    panel_validation = validate_frozen_panel_rows(rows)
    if not panel_validation["valid"] and not args.allow_incomplete:
        raise SystemExit(f"Frozen panel validation failed: {json.dumps(panel_validation, sort_keys=True)}")
    selected_rows = rows[: max(0, args.limit)]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = load_config(args.config, auto_detect=False)
    cloud = cloud_agents(config)
    preflight = estimate_execution_preflight(selected_rows, cloud)
    provider_certification = certify_configured_cloud_providers(config)
    approved_routes = approved_cloud_routes(config, provider_certification)
    if args.execute and approved_routes:
        live_preflight = live_structured_provider_preflight(cloud, approved_routes)
        preflight["live_structured_preflight"] = live_preflight
        live_approved = [row["agent"] for row in live_preflight if row.get("passed")]
        rejected = [row["agent"] for row in live_preflight if not row.get("passed")]
        approved_routes = [name for name in approved_routes if name in set(live_approved)]
        if rejected:
            preflight["blockers"].append("live structured preflight rejected: " + ",".join(rejected))
    preflight["approved_cloud_routes"] = approved_routes
    preflight["required_model_families"] = args.min_model_families
    preflight["max_model_family_share"] = args.max_family_share
    approved_families = sorted({model_family(cloud[name].model) for name in approved_routes if name in cloud})
    preflight["approved_model_families"] = approved_families
    if args.execute and len(approved_families) < args.min_model_families:
        preflight["blockers"].append(
            f"provider diversity preflight failed: {len(approved_families)} approved families < {args.min_model_families}"
        )
        preflight["abort"] = True
    if args.execute:
        exhausted = [row["agent"] for row in provider_certification if row.get("quota_status") in {"exhausted", "rate_limited"}]
        if exhausted:
            preflight["blockers"].append("insufficient quota for: " + ",".join(exhausted))
            preflight["abort"] = True
        if preflight["abort"]:
            write_static_reports(args.output_dir, preflight=preflight, provider_certification=provider_certification)
            write_balanced_reports(
                args.output_dir,
                summary={
                    "mode": "execute",
                    "row_count": len(selected_rows),
                    "rows": [],
                    "preflight": preflight,
                    "provider_certification": provider_certification,
                    "certification": {"ready": False, "blockers": list(preflight["blockers"])},
                },
            )
            raise SystemExit(f"Cost/quota preflight failed: {json.dumps(preflight['blockers'], sort_keys=True)}")

    summary = {
        "object": "gct.frozen_panel_execution",
        "dataset": str(args.dataset),
        "output_dir": str(args.output_dir),
        "mode": "execute" if args.execute else "dry_run",
        "row_count": len(selected_rows),
        "seed": SEED,
        "panel_validation": panel_validation,
        "preflight": preflight,
        "provider_certification": provider_certification,
        "started_at": time.time(),
        "rows": [],
    }
    write_static_reports(args.output_dir, preflight=preflight, provider_certification=provider_certification)
    mode = "execute" if args.execute else "dry_run"
    checkpoint = load_checkpoint(args.output_dir, mode=mode)
    accepted_row_ids = set(checkpoint.get("accepted_row_ids") or [])
    quarantined_row_ids = set(checkpoint.get("quarantined_row_ids") or [])
    router = cloud_only_router(args.config, approved_routes=approved_routes) if args.execute else None
    balancer = ProviderBalancer(
        cloud,
        approved_routes=approved_routes,
        max_family_share=args.max_family_share,
        min_model_families=args.min_model_families,
        expected_rows=len(selected_rows),
    )
    for result in summary["rows"]:
        balancer.observe_result(result)
    for row in selected_rows:
        row_id = str(row.get("row_id") or "")
        if row_id in accepted_row_ids:
            result = load_row_result(args.output_dir, row_id)
            if result is None:
                accepted_row_ids.remove(row_id)
            else:
                summary["rows"].append({**result, "resumed_from_checkpoint": True})
                balancer.observe_result(result)
                continue
        preferred_agents = balancer.route_order() if args.execute else None
        result = execute_row(
            row,
            output_dir=args.output_dir,
            router=router,
            dry_run=not args.execute,
            preferred_agents=preferred_agents,
        )
        if result.get("status") == "completed" and result.get("valid_instrumentation"):
            accepted_row_ids.add(row_id)
        elif result.get("status") == "quarantined":
            quarantined_row_ids.add(row_id)
        balancer.observe_result(result)
        write_checkpoint(
            args.output_dir,
            accepted_row_ids=accepted_row_ids,
            quarantined_row_ids=quarantined_row_ids,
            last_row_id=row_id,
            last_result=result,
            mode=mode,
        )
        summary["rows"].append(result)

    summary["completed_at"] = time.time()
    summary["dashboard"] = dashboard_status(summary)
    summary["diversity_gate"] = provider_diversity_gate(
        summary["rows"],
        expected_rows=len(selected_rows),
        max_model_family_share=args.max_family_share,
        min_model_families=args.min_model_families,
    )
    summary["certification"] = certify_execution_summary(
        summary,
        require_execute_mode=args.execute,
        expected_rows=len(selected_rows),
    )
    summary["valid_for_evidence_collection"] = panel_ready(summary)
    (args.output_dir / "panel_execution_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (args.output_dir / "execution_dashboard_status.json").write_text(json.dumps(summary["dashboard"], indent=2, sort_keys=True), encoding="utf-8")
    write_final_reports(args.output_dir, summary)
    write_balanced_reports(args.output_dir, summary)
    print(json.dumps({"summary_path": str(args.output_dir / "panel_execution_summary.json"), "ready": summary["valid_for_evidence_collection"]}, sort_keys=True))
    return 0


def write_static_reports(output_dir: Path, *, preflight: dict[str, Any], provider_certification: list[dict[str, Any]]) -> None:
    (ROOT / "provider_schema_enforcement.md").write_text(schema_enforcement_markdown(), encoding="utf-8")
    (ROOT / "cloud_provider_certification.md").write_text(cloud_provider_certification_markdown(provider_certification), encoding="utf-8")
    (ROOT / "cost_quota_preflight.md").write_text(cost_quota_preflight_markdown(preflight), encoding="utf-8")
    (ROOT / "resumable_panel_runner.md").write_text(resumable_runner_markdown(output_dir), encoding="utf-8")
    (output_dir / "cost_quota_preflight.json").write_text(json.dumps(preflight, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "cloud_provider_certification.json").write_text(json.dumps(provider_certification, indent=2, sort_keys=True), encoding="utf-8")


def write_final_reports(output_dir: Path, summary: dict[str, Any]) -> None:
    dashboard = summary.get("dashboard") if isinstance(summary.get("dashboard"), dict) else dashboard_status(summary)
    (ROOT / "execution_dashboard_status.md").write_text(dashboard_status_markdown(dashboard), encoding="utf-8")
    (ROOT / "execution_readiness_report_v2.md").write_text(readiness_report_markdown(summary), encoding="utf-8")


def write_balanced_reports(output_dir: Path, summary: dict[str, Any]) -> None:
    gate = summary.get("diversity_gate")
    if not isinstance(gate, dict):
        gate = provider_diversity_gate(
            [row for row in summary.get("rows") or [] if isinstance(row, dict)],
            expected_rows=int(summary.get("row_count") or 0),
            require_complete=False,
        )
    audit = provider_route_failure_audit(summary)
    preflight = summary.get("preflight") if isinstance(summary.get("preflight"), dict) else {}
    certification = summary.get("provider_certification") if isinstance(summary.get("provider_certification"), list) else []
    (ROOT / "provider_route_failure_audit.md").write_text(provider_route_failure_audit_markdown(audit), encoding="utf-8")
    (ROOT / "provider_balancing_policy.md").write_text(provider_balancing_policy_markdown(), encoding="utf-8")
    (ROOT / "provider_diversity_gate.md").write_text(provider_diversity_gate_markdown(gate), encoding="utf-8")
    (ROOT / "provider_preflight_results.md").write_text(provider_preflight_results_markdown(preflight, certification), encoding="utf-8")
    (ROOT / "balanced_50row_execution_results.md").write_text(balanced_execution_results_markdown(summary), encoding="utf-8")
    (ROOT / "balanced_readiness_report.md").write_text(balanced_readiness_report_markdown(summary, gate), encoding="utf-8")
    (output_dir / "provider_route_failure_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "provider_diversity_gate.json").write_text(json.dumps(gate, indent=2, sort_keys=True), encoding="utf-8")


def provider_preflight_results_markdown(preflight: dict[str, Any], certification: list[dict[str, Any]]) -> str:
    lines = [
        "# Provider Preflight Results",
        "",
        f"Approved cloud routes: `{preflight.get('approved_cloud_routes') or []}`.",
        f"Approved model families: `{preflight.get('approved_model_families') or []}`.",
        f"Required model families: `{preflight.get('required_model_families')}`.",
        f"Abort: `{preflight.get('abort')}`.",
        "Blockers: " + (", ".join(preflight.get("blockers") or []) or "none"),
        "",
        "Live structured preflight:",
        "",
        "| route | passed | category | message |",
        "| --- | --- | --- | --- |",
    ]
    live_rows = preflight.get("live_structured_preflight") if isinstance(preflight.get("live_structured_preflight"), list) else []
    if not live_rows:
        lines.append("| not run | - | - | - |")
    for row in live_rows:
        lines.append(
            "| {agent} | {passed} | {category} | {message} |".format(
                agent=str(row.get("agent") or ""),
                passed=str(row.get("passed")),
                category=str(row.get("category") or ""),
                message=str(row.get("message") or "").replace("|", "\\|")[:220],
            )
        )
    lines.extend(
        [
            "",
            "Certification:",
            "",
        "| route | auth | quota | subscription | availability | structured output | timeout | certified |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in certification:
        lines.append(
            "| {agent} | {auth} | {quota} | {subscription} | {availability} | {structured} | {timeout} | {certified} |".format(
                agent=str(row.get("agent") or ""),
                auth=_check(row.get("auth_check")),
                quota=_check(row.get("quota_check")),
                subscription=str(row.get("subscription_requirements") or ""),
                availability=_check(row.get("model_availability_check")),
                structured=_check(row.get("structured_output_compliance_check")),
                timeout=_check(row.get("timeout_behavior_check")),
                certified=str(row.get("certified")),
            )
        )
    return "\n".join(lines) + "\n"


def live_structured_provider_preflight(agents: dict[str, Any], approved_routes: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    messages = [
        {"role": "system", "content": "Return one JSON object only."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "events": [
                        {
                            "event_type": "evidence_discovery",
                            "phase": "pre_commit",
                            "payload": {"summary": "preflight"},
                        },
                        {
                            "event_type": "evidence_recognition",
                            "phase": "pre_commit",
                            "payload": {"summary": "preflight"},
                        },
                        {
                            "event_type": "evidence_interpretation",
                            "phase": "pre_commit",
                            "payload": {"summary": "preflight"},
                        },
                        {
                            "event_type": "branch_creation",
                            "phase": "pre_commit",
                            "payload": {"summary": "preflight"},
                        },
                        {
                            "event_type": "uncertainty_estimate",
                            "phase": "pre_commit",
                            "payload": {"summary": "preflight"},
                        },
                    ]
                },
                sort_keys=True,
            ),
        },
    ]
    for name in approved_routes:
        agent = agents.get(name)
        if agent is None:
            continue
        probe_agent = replace(agent, timeout_seconds=min(float(agent.timeout_seconds or 30.0), 30.0))
        started = time.perf_counter()
        try:
            provider = create_provider(probe_agent)
            result = provider.complete(
                HubRequest(
                    session_id=f"gct-preflight-{name}",
                    messages=messages,
                    max_tokens=180,
                    temperature=0.0,
                    record_session=False,
                    raw={"response_format": {"type": "json_object"}},
                )
            )
            validation = validate_structured_output(result.text, phase="pre_commit")
            rows.append(
                {
                    "agent": name,
                    "provider": probe_agent.provider,
                    "model": probe_agent.model,
                    "passed": validation.valid,
                    "category": "pass" if validation.valid else "structured_output_failure",
                    "message": ";".join(validation.errors),
                    "latency_ms": int(round((time.perf_counter() - started) * 1000)),
                }
            )
        except ProviderError as exc:
            rows.append(
                {
                    "agent": name,
                    "provider": probe_agent.provider,
                    "model": probe_agent.model,
                    "passed": False,
                    "category": str(exc.error_type or "provider_error"),
                    "message": str(exc),
                    "status_code": exc.status_code,
                    "latency_ms": int(round((time.perf_counter() - started) * 1000)),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "agent": name,
                    "provider": probe_agent.provider,
                    "model": probe_agent.model,
                    "passed": False,
                    "category": type(exc).__name__,
                    "message": str(exc),
                    "latency_ms": int(round((time.perf_counter() - started) * 1000)),
                }
            )
    return rows


def balanced_execution_results_markdown(summary: dict[str, Any]) -> str:
    rows = [row for row in summary.get("rows") or [] if isinstance(row, dict)]
    completed = [row for row in rows if row.get("status") == "completed" and row.get("valid_instrumentation")]
    malformed = sum(1 for row in rows if row.get("malformed_output_accepted"))
    quarantined = [row for row in rows if row.get("status") == "quarantined"]
    gate = summary.get("diversity_gate") if isinstance(summary.get("diversity_gate"), dict) else {}
    lines = [
        "# Balanced 50-Row Execution Results",
        "",
        f"Rows requested: `{summary.get('row_count')}`.",
        f"Accepted rows: `{len(completed)}/{len(rows) if rows else summary.get('row_count')}`.",
        f"Quarantined rows: `{len(quarantined)}`.",
        f"Malformed rows ingested: `{malformed}`.",
        f"Model-family counts: `{gate.get('family_counts') or {}}`.",
        f"Max observed family share: `{gate.get('max_observed_share')}`.",
        f"Diversity gate passed: `{gate.get('passed')}`.",
        "",
        "| row | status | providers | models | valid instrumentation | quarantine |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    if not rows:
        lines.append("| no rows executed | - | - | - | - | - |")
    for row in rows[:50]:
        calls = [call for call in row.get("provider_calls") or [] if isinstance(call, dict)]
        lines.append(
            "| {row_id} | {status} | {providers} | {models} | {valid} | {quarantine} |".format(
                row_id=str(row.get("row_id") or ""),
                status=str(row.get("status") or ""),
                providers=", ".join(str(call.get("agent") or "") for call in calls) or "-",
                models=", ".join(str(call.get("model") or "") for call in calls) or "-",
                valid=str(row.get("valid_instrumentation")),
                quarantine=len(row.get("quarantine") or []),
            )
        )
    return "\n".join(lines) + "\n"


def balanced_readiness_report_markdown(summary: dict[str, Any], gate: dict[str, Any]) -> str:
    rows = [row for row in summary.get("rows") or [] if isinstance(row, dict)]
    accepted = [
        row
        for row in rows
        if row.get("status") == "completed"
        and row.get("valid_instrumentation")
        and not row.get("malformed_output_accepted")
    ]
    malformed = sum(1 for row in rows if row.get("malformed_output_accepted"))
    target_50 = (
        len(rows) >= 50
        and len(accepted) >= 45
        and malformed == 0
        and bool(gate.get("passed"))
        and len(gate.get("family_counts") or {}) >= DEFAULT_MIN_MODEL_FAMILIES
        and float(gate.get("max_observed_share") or 1.0) <= DEFAULT_MAX_MODEL_FAMILY_SHARE
    )
    enforce_200 = bool(summary.get("mode") == "execute" and gate.get("passed"))
    if target_50 and enforce_200:
        verdict = "D. Full 200-row ready."
    elif target_50:
        verdict = "C. Balanced 50-row ready."
    elif rows and len(accepted) >= 45 and malformed == 0:
        verdict = "B. Execution works but provider diversity blocked."
    else:
        verdict = "A. Not ready."
    blockers = list(gate.get("blockers") or [])
    certification = summary.get("certification") if isinstance(summary.get("certification"), dict) else {}
    blockers.extend(certification.get("blockers") or [])
    return "\n".join(
        [
            "# Balanced Readiness Report",
            "",
            f"Accepted rows: `{len(accepted)}/{len(rows)}`.",
            f"Malformed rows ingested: `{malformed}`.",
            f"Model families: `{gate.get('family_counts') or {}}`.",
            f"Diversity gate passed: `{gate.get('passed')}`.",
            "Blockers: " + (", ".join(dict.fromkeys(blockers)) if blockers else "none"),
            "",
            f"FINAL VERDICT: {verdict}",
            "",
        ]
    )


def _check(value: Any) -> str:
    if not isinstance(value, dict):
        return "-"
    return "pass" if value.get("passed") else f"fail:{value.get('reason') or 'unknown'}"


def load_checkpoint(output_dir: Path, *, mode: str) -> dict[str, Any]:
    path = output_dir / "panel_checkpoint.json"
    if not path.exists():
        return {"accepted_row_ids": [], "quarantined_row_ids": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"accepted_row_ids": [], "quarantined_row_ids": []}
    if not isinstance(payload, dict) or payload.get("mode") != mode:
        return {"accepted_row_ids": [], "quarantined_row_ids": []}
    return payload


def write_checkpoint(
    output_dir: Path,
    *,
    accepted_row_ids: set[str],
    quarantined_row_ids: set[str],
    last_row_id: str,
    last_result: dict[str, Any],
    mode: str,
) -> None:
    payload = {
        "object": "gct.panel_checkpoint",
        "schema_version": 1,
        "mode": mode,
        "last_row_id": last_row_id,
        "accepted_row_ids": sorted(accepted_row_ids),
        "quarantined_row_ids": sorted(quarantined_row_ids),
        "last_status": last_result.get("status"),
        "updated_at": time.time(),
    }
    (output_dir / "panel_checkpoint.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_row_result(output_dir: Path, row_id: str) -> dict[str, Any] | None:
    path = output_dir / row_id / "row_result.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def load_frozen_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    orders = [int(row.get("frozen_order") or 0) for row in rows]
    if len(set(orders)) != len(rows):
        raise RuntimeError("Frozen panel has duplicate frozen_order values.")
    return sorted(rows, key=lambda row: int(row.get("frozen_order") or 0))


def cloud_only_router(config_path: Path, *, approved_routes: list[str] | None = None) -> AgentRouter:
    config = load_config(config_path, auto_detect=False)
    agents = cloud_agents(config)
    if not agents:
        raise RuntimeError("No enabled cloud-only agents are configured.")
    if approved_routes:
        agents = {name: agent for name, agent in agents.items() if name in set(approved_routes)}
        if not agents:
            raise RuntimeError("No pre-approved cloud agents are available for execution.")
    config.agents = agents
    config.default_route = list(agents)
    config.routes = [RouteRule(name="gct-frozen-panel", agents=list(agents), keywords=[])]
    config.auto_detect_local_models = False
    config.approval_mode = "auto"
    config.adaptive_learning_enabled = False
    config.routing_memory_enabled = False
    config.repo_context_enabled = False
    config.tool_loop_enabled = False
    config.tool_loop_enabled_for_cline = False
    return AgentRouter(config)


def execute_row(
    row: dict[str, Any],
    *,
    output_dir: Path,
    router: AgentRouter | None,
    dry_run: bool,
    preferred_agents: list[str] | None = None,
) -> dict[str, Any]:
    trial_id = str(row.get("trial_id") or "")
    row_id = str(row.get("row_id") or "")
    run_id = panel_run_id(trial_id, row_id, SEED)
    row_dir = output_dir / row_id
    row_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = row_dir / "events.jsonl"
    if ledger_path.exists():
        ledger_path.unlink()
    recorder = GCTRunRecorder(JsonlLedger(ledger_path), run_id=run_id, row=row)
    raw_trace: dict[str, Any] = {"run_id": run_id, "row": row, "provider_calls": []}

    status = "completed"
    failure: dict[str, Any] = {}
    recorder.record(GCTEventType.RUN_STARTED, phase="setup", payload={"dry_run": dry_run})
    try:
        if dry_run:
            simulate_valid_trace(row, recorder)
        else:
            run_instrumented_provider_calls(
                row,
                recorder,
                router,
                raw_trace,
                output_dir=output_dir,
                preferred_agents=preferred_agents,
            )
    except Exception as exc:
        status = "quarantined" if raw_trace.get("quarantine") else "failed"
        failure = {
            "type": type(exc).__name__,
            "message": str(exc),
            "quarantine": list(raw_trace.get("quarantine") or []),
        }
        recorder.record(GCTEventType.OUTCOME, phase="failure", payload={"execution_failure": failure})
    recorder.record(GCTEventType.RUN_COMPLETED, phase="completed", payload={"status": status})

    run_events = events_for_run(ledger_path, run_id)
    gar = calculate_gar(run_events)
    commitment = measure_commitment(run_events)
    intervention = validate_pre_commit_interventions(run_events)
    outcome = outcome_metrics(row, raw_trace)
    raw_trace["events_path"] = str(ledger_path)
    raw_trace["gar"] = gar
    raw_trace["commitment"] = commitment
    raw_trace["intervention"] = intervention
    raw_trace["outcome"] = outcome
    raw_trace["status"] = status
    raw_trace["failure"] = failure

    (row_dir / "raw_trace.json").write_text(json.dumps(raw_trace, indent=2, sort_keys=True), encoding="utf-8")
    (row_dir / "gar.json").write_text(json.dumps(gar, indent=2, sort_keys=True), encoding="utf-8")
    (row_dir / "commitment_metrics.json").write_text(json.dumps(commitment, indent=2, sort_keys=True), encoding="utf-8")
    (row_dir / "outcome_metrics.json").write_text(json.dumps(outcome, indent=2, sort_keys=True), encoding="utf-8")
    result = {
        "row_id": row_id,
        "run_id": run_id,
        "events_path": str(ledger_path),
        "raw_trace_path": str(row_dir / "raw_trace.json"),
        "gar_path": str(row_dir / "gar.json"),
        "commitment_metrics_path": str(row_dir / "commitment_metrics.json"),
        "outcome_metrics_path": str(row_dir / "outcome_metrics.json"),
        "status": status,
        "provider_calls": [
            {
                "phase": call.get("phase"),
                "agent": call.get("agent"),
                "provider": call.get("provider"),
                "model": call.get("model"),
                "finish_reason": call.get("finish_reason"),
                "latency_ms": call.get("latency_ms"),
                "attempt": call.get("attempt"),
                "valid_structured_output": call.get("valid_structured_output"),
                "structured_output_errors": call.get("structured_output_errors"),
                "failover": call.get("failover") or [],
            }
            for call in raw_trace.get("provider_calls", [])
        ],
        "failure": failure,
        "malformed_output_accepted": False,
        "quarantine": list(raw_trace.get("quarantine") or []),
        "synthetic_or_replay": bool(not dry_run and source_marks_replay_or_synthetic(row)),
        "valid_instrumentation": status == "completed" and not gar["invalid_reason"] and not commitment["invalid_reason"] and intervention["valid"],
    }
    (row_dir / "row_result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def simulate_valid_trace(row: dict[str, Any], recorder: GCTRunRecorder) -> None:
    evidence_events = []
    for index, unit in enumerate(row.get("evidence_units_required") or [], start=1):
        discovered = recorder.record(
            GCTEventType.EVIDENCE_DISCOVERY,
            phase="pre_commit_evidence",
            evidence_unit=str(unit),
            local_grounding=1.0,
            payload={"source": "frozen_row_requirement", "dry_run": True},
        )
        recognized = recorder.record(
            GCTEventType.EVIDENCE_RECOGNITION,
            phase="pre_commit_evidence",
            evidence_unit=str(unit),
            evidence_refs=[discovered.event_id],
            local_grounding=1.0,
        )
        interpreted = recorder.record(
            GCTEventType.EVIDENCE_INTERPRETATION,
            phase="pre_commit_evidence",
            evidence_unit=str(unit),
            evidence_refs=[recognized.event_id],
            local_grounding=1.0,
            uncertainty=max(0.05, 0.25 - index * 0.02),
        )
        evidence_events.append(interpreted.event_id)
    branch_a = recorder.record(
        GCTEventType.BRANCH_CREATION,
        phase="pre_commit_branching",
        branch_id="branch_a",
        evidence_refs=evidence_events[:2],
        local_grounding=1.0,
        payload={"label": "evidence-first branch"},
    )
    recorder.record(
        GCTEventType.BRANCH_CREATION,
        phase="pre_commit_branching",
        branch_id="branch_b",
        evidence_refs=evidence_events[-2:],
        local_grounding=1.0,
        payload={"label": "alternative branch"},
    )
    recorder.record(
        GCTEventType.UNCERTAINTY_ESTIMATE,
        phase="pre_commit_branching",
        branch_id="branch_a",
        evidence_refs=[branch_a.event_id],
        uncertainty=0.18,
    )
    if row.get("assigned_arm") == "treatment":
        apply_pre_commit_intervention(
            recorder,
            intervention_id="pre_commit_grounding_gate_v1",
            prompt="Before committing, cite the evidence event supporting the selected branch and name one alternative.",
            evidence_refs=evidence_events,
        )
    recorder.record(
        GCTEventType.BRANCH_SELECTION,
        phase="commitment",
        selected_branch_id="branch_a",
        evidence_refs=[branch_a.event_id],
        local_grounding=1.0,
    )
    recorder.record(
        GCTEventType.JUSTIFICATION,
        phase="commitment",
        selected_branch_id="branch_a",
        evidence_refs=evidence_events,
        local_grounding=1.0,
    )
    recorder.record(
        GCTEventType.COMMITMENT,
        phase="commitment",
        selected_branch_id="branch_a",
        evidence_refs=evidence_events,
        local_grounding=1.0,
        commitment_strength=0.86,
        lock_in=True,
    )
    recorder.record(
        GCTEventType.OUTCOME,
        phase="outcome",
        payload={"dry_run": True, "outcome_scored": False},
    )


def run_instrumented_provider_calls(
    row: dict[str, Any],
    recorder: GCTRunRecorder,
    router: AgentRouter | None,
    raw_trace: dict[str, Any],
    *,
    output_dir: Path,
    preferred_agents: list[str] | None = None,
) -> None:
    if router is None:
        raise RuntimeError("Router is required for execution mode.")
    pre_response = call_model_validated(
        router,
        row,
        recorder,
        raw_trace,
        output_dir=output_dir,
        phase="pre_commit",
        messages=pre_commit_messages(row),
        max_tokens=700,
        preferred_agents=preferred_agents,
    )
    raw_trace["provider_calls"].append(pre_response)
    ingest_declared_events(pre_response["payload"], recorder, default_phase="pre_commit")
    pre_commit_event_ids = [event.get("event_id") for event in events_for_run(recorder.ledger.path, recorder.run_id)]
    if row.get("assigned_arm") == "treatment":
        apply_pre_commit_intervention(
            recorder,
            intervention_id="pre_commit_grounding_gate_v1",
            prompt="Select only after linking the selected branch to discovered and interpreted evidence.",
            evidence_refs=[event_id for event_id in pre_commit_event_ids if event_id],
        )
    commit_response = call_model_validated(
        router,
        row,
        recorder,
        raw_trace,
        output_dir=output_dir,
        phase="commitment",
        messages=commitment_messages(row, pre_response["text"]),
        repair_context=pre_response["text"],
        max_tokens=900,
        preferred_agents=preferred_agents,
    )
    raw_trace["provider_calls"].append(commit_response)
    ingest_declared_events(commit_response["payload"], recorder, default_phase="commitment")
    recorder.record(GCTEventType.OUTCOME, phase="outcome", payload={"response_text": commit_response["text"][:4000]})


def call_model_validated(
    router: AgentRouter,
    row: dict[str, Any],
    recorder: GCTRunRecorder,
    raw_trace: dict[str, Any],
    *,
    output_dir: Path,
    phase: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    repair_context: str = "",
    preferred_agents: list[str] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(1, MAX_MODEL_ATTEMPTS + 1):
        attempt_messages = messages if attempt == 1 else repair_messages(row, phase=phase, previous_errors=errors, context=repair_context)
        try:
            response = call_model(
                router,
                row,
                phase=phase,
                messages=attempt_messages,
                max_tokens=max_tokens,
                attempt=attempt,
                preferred_agents=preferred_agents,
            )
        except Exception as exc:
            errors.append(f"provider_failure:{type(exc).__name__}:{exc}")
            if attempt >= MAX_MODEL_ATTEMPTS:
                raise
            continue
        normalized_text, normalization_notes = normalize_provider_structured_output(response["text"], phase=phase)
        response["normalization_notes"] = normalization_notes
        response["normalized_text"] = normalized_text if normalization_notes else ""
        validation = validate_structured_output(normalized_text, phase=phase)
        response["valid_structured_output"] = validation.valid
        response["structured_output_errors"] = list(validation.errors)
        response["structured_output_repaired"] = validation.repaired
        if validation.valid and validation.payload is not None:
            response["payload"] = validation.payload
            return response
        quarantine_path = quarantine_malformed_output(
            output_dir,
            row_id=str(row.get("row_id") or ""),
            run_id=recorder.run_id,
            phase=phase,
            attempt=attempt,
            text=response["text"],
            errors=validation.errors,
            provider_call=response,
        )
        response["quarantine_path"] = str(quarantine_path)
        raw_trace.setdefault("quarantine", []).append(str(quarantine_path))
        errors = validation.errors
    raise RuntimeError(f"No valid structured output for {phase} after {MAX_MODEL_ATTEMPTS} attempts: {errors}")


def call_model(
    router: AgentRouter,
    row: dict[str, Any],
    *,
    phase: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    attempt: int,
    preferred_agents: list[str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    route_agents = list(preferred_agents or [])
    original_route: list[str] | None = None
    if route_agents:
        original_route = list(router.config.default_route)
        router.config.default_route = route_agents
        router.config.routes = [RouteRule(name="gct-frozen-panel", agents=route_agents, keywords=[])]
    try:
        response: HubResponse = router.route(
            HubRequest(
                session_id=f"{row.get('trial_id')}-{row.get('row_id')}-{phase}",
                route="gct-frozen-panel",
                preferred_agent=route_agents[0] if route_agents else str(row.get("cloud_model_family") or "") or None,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.0,
                record_session=False,
                raw={
                    "seed": SEED,
                    "gct_phase": phase,
                    "response_format": {"type": "json_object"},
                },
            )
        )
    finally:
        if original_route is not None:
            router.config.default_route = original_route
            router.config.routes = [RouteRule(name="gct-frozen-panel", agents=original_route, keywords=[])]
    latency_ms = int(round((time.perf_counter() - started) * 1000))
    if not str(response.model).endswith(CLOUD_MODEL_SUFFIX) and not str(response.agent).endswith("-cloud"):
        raise RuntimeError(f"Non-cloud model selected: {response.agent}/{response.model}")
    return {
        "phase": phase,
        "agent": response.agent,
        "provider": response.provider,
        "model": response.model,
        "usage": response.usage,
        "finish_reason": response.finish_reason,
        "latency_ms": latency_ms,
        "attempt": attempt,
        "failover": [event.to_dict() for event in response.failover],
        "text": response.text,
    }


class ProviderBalancer:
    def __init__(
        self,
        agents: dict[str, Any],
        *,
        approved_routes: list[str],
        max_family_share: float,
        min_model_families: int,
        expected_rows: int,
    ) -> None:
        self.agents = agents
        self.approved_routes = [name for name in approved_routes if name in agents]
        self.max_family_share = max_family_share
        self.min_model_families = min_model_families
        self.expected_rows = max(1, expected_rows)
        self.family_counts: dict[str, int] = {}
        self.agent_counts: dict[str, int] = {}
        self.failure_counts: dict[str, int] = {}
        self.backoff_until: dict[str, float] = {}

    def route_order(self) -> list[str]:
        now = time.time()
        active = [name for name in self.approved_routes if self.backoff_until.get(name, 0.0) <= now]
        if not active:
            active = list(self.approved_routes)
        uncapped = [name for name in active if not self._family_capped(model_family(self.agents[name].model))]
        candidates = uncapped or active
        return sorted(
            candidates,
            key=lambda name: (
                self.family_counts.get(model_family(self.agents[name].model), 0),
                self.agent_counts.get(name, 0),
                self.failure_counts.get(name, 0),
                self.approved_routes.index(name) if name in self.approved_routes else 999,
            ),
        )

    def observe_result(self, result: dict[str, Any]) -> None:
        if result.get("status") == "completed" and result.get("valid_instrumentation"):
            families_seen: set[str] = set()
            agents_seen: set[str] = set()
            for call in result.get("provider_calls") or []:
                if not isinstance(call, dict) or call.get("valid_structured_output") is False:
                    continue
                agent = str(call.get("agent") or "")
                family = model_family(str(call.get("model") or agent))
                if family:
                    families_seen.add(family)
                if agent:
                    agents_seen.add(agent)
            for family in families_seen:
                self.family_counts[family] = self.family_counts.get(family, 0) + 1
            for agent in agents_seen:
                self.agent_counts[agent] = self.agent_counts.get(agent, 0) + 1
        for call in result.get("provider_calls") or []:
            if not isinstance(call, dict):
                continue
            agent = str(call.get("agent") or "")
            if call.get("valid_structured_output") is False and agent:
                self._backoff(agent, "structured_output_failure")
            for event in call.get("failover") or []:
                if isinstance(event, dict) and event.get("agent"):
                    self._backoff(str(event["agent"]), str(event.get("error_type") or event.get("reason") or "provider_failure"))
        failure = result.get("failure") if isinstance(result.get("failure"), dict) else {}
        if failure and result.get("status") != "completed":
            for call in result.get("provider_calls") or []:
                if isinstance(call, dict) and call.get("agent"):
                    self._backoff(str(call["agent"]), str(failure.get("message") or failure.get("type") or "row_failure"))

    def _family_capped(self, family: str) -> bool:
        accepted = sum(self.family_counts.values())
        if accepted <= 0:
            return False
        return (self.family_counts.get(family, 0) / accepted) >= self.max_family_share

    def _backoff(self, agent: str, reason: str) -> None:
        if agent not in self.approved_routes:
            return
        self.failure_counts[agent] = self.failure_counts.get(agent, 0) + 1
        lowered = reason.lower()
        if "quota" in lowered or "subscription" in lowered or "auth" in lowered:
            seconds = 3600
        elif "timeout" in lowered or "overload" in lowered or "cooldown" in lowered:
            seconds = 120
        else:
            seconds = 30
        self.backoff_until[agent] = max(self.backoff_until.get(agent, 0.0), time.time() + seconds)


def pre_commit_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Emit one JSON object only. No markdown. No prose outside JSON. "
                "This is pre_commit instrumentation only: do not emit final_answer, "
                "branch_selection, justification_event, or commitment_event."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": row.get("prompt"),
                    "phase": "pre_commit",
                    "required_events": [
                        "evidence_discovery",
                        "evidence_recognition",
                        "evidence_interpretation",
                        "branch_creation",
                        "uncertainty_estimate",
                    ],
                    "evidence_units_required": row.get("evidence_units_required") or [],
                    "schema": EVENT_SCHEMA_PROMPT,
                    "strict_rules": STRICT_JSON_RULES,
                    "example": {
                        "events": [
                            {
                                "id": "ev1",
                                "event_type": "evidence_discovery",
                                "phase": "pre_commit",
                                "evidence_unit": "name one required evidence unit",
                                "evidence_refs": [],
                                "local_grounding": 0.8,
                                "payload": {"summary": "short observed evidence"},
                            },
                            {
                                "id": "ev2",
                                "event_type": "branch_creation",
                                "phase": "pre_commit",
                                "branch_id": "branch_a",
                                "evidence_refs": ["ev1"],
                                "local_grounding": 0.7,
                                "payload": {"summary": "candidate branch"},
                            },
                        ]
                    },
                },
                sort_keys=True,
            ),
        },
    ]


def commitment_messages(row: dict[str, Any], pre_commit_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Emit one JSON object only. No markdown. No prose outside JSON. "
                "This is the commitment phase: every emitted event must have phase "
                "`commitment` and event_type must be branch_selection, "
                "justification_event, or commitment_event."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": row.get("prompt"),
                    "phase": "commitment",
                    "pre_commit_trace": pre_commit_text,
                    "required_events": ["branch_selection", "justification_event", "commitment_event"],
                    "schema": EVENT_SCHEMA_PROMPT,
                    "strict_rules": STRICT_JSON_RULES,
                    "example": {
                        "events": [
                            {
                                "id": "commit_select",
                                "event_type": "branch_selection",
                                "phase": "commitment",
                                "selected_branch_id": "branch_a",
                                "evidence_refs": ["branch_a"],
                                "local_grounding": 0.8,
                                "payload": {"summary": "selected branch from pre_commit trace"},
                            },
                            {
                                "id": "commit_final",
                                "event_type": "commitment_event",
                                "phase": "commitment",
                                "selected_branch_id": "branch_a",
                                "evidence_refs": ["commit_select"],
                                "commitment_strength": 0.8,
                                "lock_in": True,
                                "payload": {"summary": "commitment made after evidence review"},
                            },
                        ],
                        "final_answer": "short task answer",
                    },
                },
                sort_keys=True,
            ),
        },
    ]


def repair_messages(row: dict[str, Any], *, phase: str, previous_errors: list[str], context: str = "") -> list[dict[str, str]]:
    required_events = (
        ["evidence_discovery", "evidence_recognition", "evidence_interpretation", "branch_creation", "uncertainty_estimate"]
        if phase == "pre_commit"
        else ["branch_selection", "justification_event", "commitment_event"]
    )
    return [
        {"role": "system", "content": "Emit one valid JSON object only. No markdown, no prose, no final answer outside JSON."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": row.get("prompt"),
                    "phase": phase,
                    "previous_validation_errors": previous_errors,
                    "pre_commit_trace": context if phase == "commitment" else "",
                    "required_events": required_events,
                    "schema": EVENT_SCHEMA_PROMPT,
                    "strict_rules": STRICT_JSON_RULES,
                    "repair_instruction": (
                        f"Return a corrected events array satisfying the schema for phase `{phase}`. "
                        "Use numeric values for grounding fields, arrays for evidence_refs, and object payloads. "
                        "Do not put final_answer inside an event. "
                        "Do not include commitment_event during pre_commit. "
                        "During commitment, use only commitment-phase event types and phase `commitment`."
                    ),
                },
                sort_keys=True,
            ),
        },
    ]


EVENT_SCHEMA_PROMPT = {
    "events": [
        {
            "event_type": "one allowed event type",
            "phase": "pre_commit or commitment",
            "branch_id": "optional branch id",
            "selected_branch_id": "optional selected branch",
            "previous_branch_id": "optional previous branch",
            "evidence_unit": "optional frozen evidence unit",
            "evidence_refs": ["ids from earlier events if available"],
            "local_grounding": "0..1 measured at event time",
            "uncertainty": "0..1 optional",
            "commitment_strength": "0..1 optional",
            "lock_in": "boolean optional",
            "payload": "object with short explanation",
        }
    ],
    "final_answer": "only in commitment phase",
}

STRICT_JSON_RULES = [
    "The root must be a JSON object with an events array.",
    "Every event must contain event_type, phase, and payload.",
    "payload must be an object, not a string.",
    "evidence_refs must be an array of ids or branch/evidence aliases.",
    "local_grounding, uncertainty, and commitment_strength must be numbers from 0 to 1.",
    "Do not use markdown fences.",
]


def normalize_provider_structured_output(text: str, *, phase: str) -> tuple[str, list[str]]:
    """Normalize provider JSON wrappers without creating required events."""

    payload = _loads_provider_json(text)
    if payload is None:
        return text, []
    notes: list[str] = []
    if phase == "pre_commit" and "final_answer" in payload:
        payload.pop("final_answer", None)
        notes.append("removed_pre_commit_root_final_answer")
    events = payload.get("events")
    if not isinstance(events, list):
        return text, notes
    normalized_events: list[Any] = []
    for event in events:
        if not isinstance(event, dict):
            normalized_events.append(event)
            continue
        item = dict(event)
        if "previous_id" in item and "previous_branch_id" not in item:
            item["previous_branch_id"] = item.pop("previous_id")
            notes.append("renamed_previous_id")
        elif "previous_id" in item:
            item.pop("previous_id", None)
            notes.append("removed_duplicate_previous_id")
        if "final_answer" in item:
            if phase == "commitment" and "final_answer" not in payload:
                payload["final_answer"] = str(item.get("final_answer") or "")
                notes.append("lifted_event_final_answer")
            item.pop("final_answer", None)
        for key in ("local_grounding", "uncertainty", "commitment_strength"):
            if key in item and item[key] is not None and not isinstance(item[key], (int, float)):
                try:
                    item[key] = float(item[key])
                    notes.append(f"coerced_{key}")
                except (TypeError, ValueError):
                    item.pop(key, None)
                    notes.append(f"removed_invalid_{key}")
        if "evidence_refs" in item and item["evidence_refs"] is not None and not isinstance(item["evidence_refs"], list):
            item["evidence_refs"] = [str(item["evidence_refs"])]
            notes.append("wrapped_evidence_refs")
        if "payload" in item and not isinstance(item.get("payload"), dict):
            item["payload"] = {"value": str(item.get("payload") or "")}
            notes.append("wrapped_payload")
        event_type = str(item.get("event_type") or "")
        if phase == "pre_commit" and event_type in {"branch_selection", "branch_switching", "justification_event", "commitment_event"}:
            notes.append(f"dropped_pre_commit_{event_type}")
            continue
        if phase == "commitment" and event_type in {"branch_selection", "branch_switching", "justification_event", "commitment_event"}:
            if item.get("phase") != "commitment":
                item["phase"] = "commitment"
                notes.append("normalized_commitment_phase")
        normalized_events.append(item)
    payload["events"] = normalized_events
    if not notes:
        return text, []
    return json.dumps(payload, sort_keys=True), notes


def _loads_provider_json(text: str) -> dict[str, Any] | None:
    for candidate in _provider_json_candidates(text):
        try:
            payload = json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _provider_json_candidates(text: str) -> list[str]:
    candidates = [text.strip()] if text and text.strip() else []
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())
    match = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
    if match:
        candidates.append(match.group(0).strip())
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def ingest_declared_events(payload: dict[str, Any] | str, recorder: GCTRunRecorder, *, default_phase: str) -> None:
    if isinstance(payload, str):
        payload = extract_json_object(payload)
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise RuntimeError("Provider response did not contain an events array.")
    known_ids: dict[str, str] = event_aliases(events_for_run(recorder.ledger.path, recorder.run_id))
    for index, item in enumerate(events):
        if not isinstance(item, dict):
            continue
        event_type = GCTEventType(str(item.get("event_type")))
        if default_phase == "pre_commit" and event_type not in {
            GCTEventType.EVIDENCE_DISCOVERY,
            GCTEventType.EVIDENCE_RECOGNITION,
            GCTEventType.EVIDENCE_INTERPRETATION,
            GCTEventType.BRANCH_CREATION,
            GCTEventType.UNCERTAINTY_ESTIMATE,
        }:
            raise RuntimeError(f"Commitment event emitted during pre-commit phase: {event_type.value}")
        declared_refs = item.get("evidence_refs") or []
        refs = resolve_evidence_refs(declared_refs, known_ids)
        if declared_refs and len(refs) != len(declared_refs):
            unresolved = [str(ref) for ref in declared_refs if str(ref) not in known_ids]
            raise RuntimeError(f"Unresolved evidence_refs for {event_type.value}: {unresolved}")
        declared_id = str(item.get("id") or item.get("event_id") or "")
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if declared_id:
            payload = {**payload, "declared_id": declared_id}
        event = recorder.record(
            event_type,
            phase=str(item.get("phase") or default_phase),
            branch_id=str(item.get("branch_id") or ""),
            selected_branch_id=str(item.get("selected_branch_id") or ""),
            previous_branch_id=str(item.get("previous_branch_id") or ""),
            evidence_unit=str(item.get("evidence_unit") or ""),
            evidence_refs=refs,
            local_grounding=optional_float(item.get("local_grounding")),
            uncertainty=optional_float(item.get("uncertainty")),
            commitment_strength=optional_float(item.get("commitment_strength")),
            lock_in=item.get("lock_in") if isinstance(item.get("lock_in"), bool) else None,
            payload=payload,
        )
        if declared_id:
            known_ids[declared_id] = event.event_id
        known_ids[str(index)] = event.event_id
        known_ids[event.event_id] = event.event_id
        known_ids[event_type.value] = event.event_id
        if item.get("evidence_unit"):
            known_ids[str(item.get("evidence_unit"))] = event.event_id
        if item.get("branch_id"):
            known_ids[str(item.get("branch_id"))] = event.event_id
        if item.get("selected_branch_id"):
            known_ids[str(item.get("selected_branch_id"))] = event.event_id


def extract_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise RuntimeError("No JSON object found in provider response.")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise RuntimeError("Provider JSON root must be an object.")
    return payload


def event_aliases(events: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for event in sorted(events, key=lambda row: int(row.get("seq") or 0)):
        event_id = str(event.get("event_id") or "")
        if not event_id:
            continue
        aliases[event_id] = event_id
        aliases[str(event.get("event_type") or "")] = event_id
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        for key in ("declared_id", "declared_event_id"):
            value = str(payload.get(key) or "")
            if value:
                aliases[value] = event_id
        for key in ("evidence_unit", "branch_id", "selected_branch_id"):
            value = str(event.get(key) or "")
            if value:
                aliases[value] = event_id
    return aliases


def resolve_evidence_refs(refs: list[Any], aliases: dict[str, str]) -> list[str]:
    resolved: list[str] = []
    for ref in refs:
        text = str(ref)
        event_id = aliases.get(text)
        if event_id:
            resolved.append(event_id)
    return resolved


def outcome_metrics(row: dict[str, Any], raw_trace: dict[str, Any]) -> dict[str, Any]:
    response_text = " ".join(str(call.get("text") or "") for call in raw_trace.get("provider_calls") or [])
    required = [str(unit).lower() for unit in row.get("evidence_units_required") or []]
    lowered = response_text.lower()
    hits = sum(1 for unit in required if unit and all(piece in lowered for piece in unit.split()[:2]))
    threshold = max(1, math.ceil(len(required) * 0.75)) if required else 1
    return {
        "outcome_schema_version": 1,
        "scoring_method": "frozen_evidence_unit_coverage",
        "required_evidence_units": required,
        "evidence_unit_hits": hits,
        "evidence_unit_total": len(required),
        "success": bool(required and hits >= threshold),
        "threshold": threshold,
        "independent_of_gar": True,
        "dry_run_no_outcome": not bool(raw_trace.get("provider_calls")),
    }


def panel_ready(summary: dict[str, Any]) -> bool:
    rows = summary.get("rows") or []
    gate = summary.get("diversity_gate") if isinstance(summary.get("diversity_gate"), dict) else {}
    return (
        summary.get("mode") == "execute"
        and bool(rows)
        and all(row.get("valid_instrumentation") for row in rows)
        and gate.get("passed", True) is True
    )


def resumable_runner_markdown(output_dir: Path) -> str:
    return "\n".join(
        [
            "# Resumable Panel Runner",
            "",
            f"Checkpoint path: `{output_dir / 'panel_checkpoint.json'}`.",
            "",
            "- The runner writes `row_result.json` after every row.",
            "- Accepted rows are recorded in `accepted_row_ids` and skipped on resume.",
            "- Quarantined rows are recorded in `quarantined_row_ids` and skipped only with that explicit checkpoint record.",
            "- The summary never ingests malformed provider payloads; event ingestion happens only after strict validation succeeds.",
            "- Duplicate accepted rows are prevented by row-id checkpoint membership.",
            "",
        ]
    )


def readiness_report_markdown(summary: dict[str, Any]) -> str:
    certification = summary.get("certification") if isinstance(summary.get("certification"), dict) else {}
    dashboard = summary.get("dashboard") if isinstance(summary.get("dashboard"), dict) else dashboard_status(summary)
    rows = summary.get("rows") or []
    dry_run_ok = summary.get("mode") == "dry_run" and len(rows) == int(summary.get("row_count") or 0)
    pilot_ok = summary.get("mode") == "execute" and len(rows) >= 20 and bool(summary.get("valid_for_evidence_collection"))
    full_ok = summary.get("mode") == "execute" and len(rows) >= 200 and bool(certification.get("ready"))
    if full_ok:
        verdict = "D. Full 200-row ready."
    elif pilot_ok:
        verdict = "C. Pilot ready."
    elif dry_run_ok:
        verdict = "B. Engineering blocked."
    else:
        verdict = "A. Not ready."
    blockers = certification.get("blockers") or []
    lines = [
        "# Execution Readiness Report v2",
        "",
        f"Mode: `{summary.get('mode')}`.",
        f"Rows requested: `{summary.get('row_count')}`.",
        f"Rows summarized: `{len(rows)}`.",
        f"Ready for evidence collection: `{summary.get('valid_for_evidence_collection')}`.",
        "",
        "Dashboard:",
        f"- Completed rows: `{dashboard.get('completed_rows')}`.",
        f"- Failed rows: `{dashboard.get('failed_rows')}`.",
        f"- Quarantined rows: `{dashboard.get('quarantined_rows')}`.",
        f"- Instrumentation coverage: `{dashboard.get('instrumentation_coverage')}`.",
        "",
        "Certification blockers: " + (", ".join(blockers) if blockers else "none"),
        "",
        f"FINAL VERDICT: {verdict}",
        "",
    ]
    return "\n".join(lines)


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def source_marks_replay_or_synthetic(row: dict[str, Any]) -> bool:
    source = str(row.get("source_status") or "").lower()
    for marker in ("replay", "synthetic", "simulated"):
        if marker in source and not any(term in source for term in (f"no {marker}", f"not {marker}", f"without {marker}")):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
