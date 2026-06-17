from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_hub.config import HubConfig, RouteRule, load_config
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubRequest, HubResponse
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
    MAX_MODEL_ATTEMPTS,
    certify_configured_cloud_providers,
    certify_execution_summary,
    cloud_agents,
    cloud_provider_certification_markdown,
    cost_quota_preflight_markdown,
    dashboard_status,
    dashboard_status_markdown,
    estimate_execution_preflight,
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
    if args.execute:
        exhausted = [row["agent"] for row in provider_certification if row.get("quota_status") in {"exhausted", "rate_limited"}]
        if exhausted:
            preflight["blockers"].append("insufficient quota for: " + ",".join(exhausted))
            preflight["abort"] = True
        if preflight["abort"]:
            write_static_reports(args.output_dir, preflight=preflight, provider_certification=provider_certification)
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
    router = cloud_only_router(args.config) if args.execute else None
    for row in selected_rows:
        row_id = str(row.get("row_id") or "")
        if row_id in accepted_row_ids:
            result = load_row_result(args.output_dir, row_id)
            if result is None:
                accepted_row_ids.remove(row_id)
            else:
                summary["rows"].append({**result, "resumed_from_checkpoint": True})
                continue
        if row_id in quarantined_row_ids:
            summary["rows"].append({"row_id": row_id, "status": "quarantined", "skipped_from_checkpoint": True, "valid_instrumentation": False})
            continue
        result = execute_row(row, output_dir=args.output_dir, router=router, dry_run=not args.execute)
        if result.get("status") == "completed" and result.get("valid_instrumentation"):
            accepted_row_ids.add(row_id)
        elif result.get("status") == "quarantined":
            quarantined_row_ids.add(row_id)
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
    summary["certification"] = certify_execution_summary(
        summary,
        require_execute_mode=args.execute,
        expected_rows=len(selected_rows),
    )
    summary["valid_for_evidence_collection"] = panel_ready(summary)
    (args.output_dir / "panel_execution_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (args.output_dir / "execution_dashboard_status.json").write_text(json.dumps(summary["dashboard"], indent=2, sort_keys=True), encoding="utf-8")
    write_final_reports(args.output_dir, summary)
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


def cloud_only_router(config_path: Path) -> AgentRouter:
    config = load_config(config_path, auto_detect=False)
    agents = cloud_agents(config)
    if not agents:
        raise RuntimeError("No enabled cloud-only agents are configured.")
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
            run_instrumented_provider_calls(row, recorder, router, raw_trace, output_dir=output_dir)
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
        max_tokens=900,
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
) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(1, MAX_MODEL_ATTEMPTS + 1):
        attempt_messages = messages if attempt == 1 else repair_messages(row, phase=phase, previous_errors=errors)
        try:
            response = call_model(router, row, phase=phase, messages=attempt_messages, max_tokens=max_tokens, attempt=attempt)
        except Exception as exc:
            errors.append(f"provider_failure:{type(exc).__name__}:{exc}")
            if attempt >= MAX_MODEL_ATTEMPTS:
                raise
            continue
        validation = validate_structured_output(response["text"], phase=phase)
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
) -> dict[str, Any]:
    started = time.perf_counter()
    response: HubResponse = router.route(
        HubRequest(
            session_id=f"{row.get('trial_id')}-{row.get('row_id')}-{phase}",
            route="gct-frozen-panel",
            preferred_agent=str(row.get("cloud_model_family") or "") or None,
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


def pre_commit_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "Emit JSON only. Do not make a final answer or commitment in this phase."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": row.get("prompt"),
                    "required_events": [
                        "evidence_discovery",
                        "evidence_recognition",
                        "evidence_interpretation",
                        "branch_creation",
                        "uncertainty_estimate",
                    ],
                    "evidence_units_required": row.get("evidence_units_required") or [],
                    "schema": EVENT_SCHEMA_PROMPT,
                },
                sort_keys=True,
            ),
        },
    ]


def commitment_messages(row: dict[str, Any], pre_commit_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "Emit JSON only. Use only branches and evidence already named in the pre-commit trace."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": row.get("prompt"),
                    "pre_commit_trace": pre_commit_text,
                    "required_events": ["branch_selection", "justification_event", "commitment_event"],
                    "schema": EVENT_SCHEMA_PROMPT,
                },
                sort_keys=True,
            ),
        },
    ]


def repair_messages(row: dict[str, Any], *, phase: str, previous_errors: list[str]) -> list[dict[str, str]]:
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
                    "required_events": required_events,
                    "schema": EVENT_SCHEMA_PROMPT,
                    "repair_instruction": "Return a corrected events array satisfying the schema. Do not include commitment_event during pre_commit.",
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


def ingest_declared_events(payload: dict[str, Any] | str, recorder: GCTRunRecorder, *, default_phase: str) -> None:
    if isinstance(payload, str):
        payload = extract_json_object(payload)
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise RuntimeError("Provider response did not contain an events array.")
    known_ids: dict[str, str] = event_aliases(events_for_run(recorder.ledger.path, recorder.run_id))
    for item in events:
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
            payload=item.get("payload") if isinstance(item.get("payload"), dict) else {},
        )
        declared_id = str(item.get("id") or item.get("event_id") or "")
        if declared_id:
            known_ids[declared_id] = event.event_id
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
    return summary.get("mode") == "execute" and bool(rows) and all(row.get("valid_instrumentation") for row in rows)


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
