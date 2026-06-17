from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.providers.errors import classify_provider_error


STRUCTURED_OUTPUT_SCHEMA_VERSION = 1
MAX_REPAIR_ATTEMPTS = 1
MAX_MODEL_ATTEMPTS = 2
CLOUD_PROVIDER_TYPES = {"ollama-cloud", "openai", "anthropic", "gemini", "openrouter"}
RETRYABLE_PROVIDER_ERROR_TYPES = {
    "temporary_rate_limit",
    "overloaded",
    "timeout",
    "connection_error",
    "server_error",
}

PRE_COMMIT_EVENT_TYPES = {
    "evidence_discovery",
    "evidence_recognition",
    "evidence_interpretation",
    "branch_creation",
    "uncertainty_estimate",
}
COMMITMENT_EVENT_TYPES = {
    "branch_selection",
    "branch_switching",
    "justification_event",
    "commitment_event",
}
ALL_EVENT_TYPES = PRE_COMMIT_EVENT_TYPES | COMMITMENT_EVENT_TYPES
EVENT_REQUIRED_KEYS = {"event_type", "phase", "payload"}
EVENT_OPTIONAL_KEYS = {
    "id",
    "event_id",
    "branch_id",
    "selected_branch_id",
    "previous_branch_id",
    "evidence_unit",
    "evidence_refs",
    "local_grounding",
    "uncertainty",
    "commitment_strength",
    "lock_in",
}
STRUCTURED_OUTPUT_CONTRACT = {
    "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
    "root_type": "object",
    "required_root_keys": ["events"],
    "optional_root_keys": ["final_answer"],
    "event_required_keys": sorted(EVENT_REQUIRED_KEYS),
    "event_optional_keys": sorted(EVENT_OPTIONAL_KEYS),
    "pre_commit_event_types": sorted(PRE_COMMIT_EVENT_TYPES),
    "commitment_event_types": sorted(COMMITMENT_EVENT_TYPES),
    "repair_attempts_allowed": MAX_REPAIR_ATTEMPTS,
}


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    payload: dict[str, Any] | None = None
    repaired: bool = False
    errors: list[str] = field(default_factory=list)


def is_cloud_agent(agent: AgentConfig) -> bool:
    provider_type = str(agent.provider_type or agent.provider or "").lower()
    model = str(agent.model or "").lower()
    if getattr(agent, "local_only", False):
        return False
    return provider_type in CLOUD_PROVIDER_TYPES or model.endswith(":cloud") or "-cloud" in agent.name.lower()


def cloud_agents(config: HubConfig) -> dict[str, AgentConfig]:
    return {name: agent for name, agent in config.agents.items() if agent.enabled and is_cloud_agent(agent)}


def validate_frozen_panel_rows(rows: list[dict[str, Any]], *, expected_rows: int = 200) -> dict[str, Any]:
    row_ids = [str(row.get("row_id") or "") for row in rows]
    hashes = [str(row.get("frozen_hash") or "") for row in rows]
    orders = [row.get("frozen_order") for row in rows]
    replay_rows = [
        row.get("row_id")
        for row in rows
        if _affirmative_marker(str(row.get("source_status") or ""), "replay")
        or str(row.get("execution_status") or "").lower() not in {"frozen_unexecuted", "completed"}
    ]
    synthetic_rows = [
        row.get("row_id")
        for row in rows
        if _affirmative_marker(str(row.get("source_status") or ""), "synthetic")
        or _affirmative_marker(str(row.get("source_status") or ""), "simulated")
    ]
    missing = [
        row.get("row_id")
        for row in rows
        if not row.get("trial_id")
        or not row.get("row_id")
        or not row.get("prompt")
        or not row.get("frozen_hash")
        or not isinstance(row.get("evidence_units_required"), list)
        or not row.get("cloud_model_family")
    ]
    return {
        "expected_rows": expected_rows,
        "actual_rows": len(rows),
        "row_count_valid": len(rows) == expected_rows,
        "duplicate_row_ids": sorted({item for item in row_ids if row_ids.count(item) > 1}),
        "duplicate_hashes": sorted({item for item in hashes if item and hashes.count(item) > 1}),
        "duplicate_frozen_orders": sorted({item for item in orders if orders.count(item) > 1}),
        "replay_rows": replay_rows,
        "synthetic_rows": synthetic_rows,
        "missing_required_fields": missing,
        "valid": (
            len(rows) == expected_rows
            and len(set(row_ids)) == len(row_ids)
            and len(set(hashes)) == len(hashes)
            and len(set(orders)) == len(orders)
            and not replay_rows
            and not synthetic_rows
            and not missing
        ),
    }


def validate_structured_output(text: str, *, phase: str) -> ValidationResult:
    payload_result = parse_or_repair_json(text)
    if not payload_result.valid or payload_result.payload is None:
        return payload_result
    payload = payload_result.payload
    errors = _schema_errors(payload, phase=phase)
    return ValidationResult(
        valid=not errors,
        payload=payload if not errors else None,
        repaired=payload_result.repaired,
        errors=errors,
    )


def parse_or_repair_json(text: str) -> ValidationResult:
    errors: list[str] = []
    for candidate, repaired in _json_candidates(text):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(f"json_decode:{exc.msg}")
            continue
        if isinstance(payload, dict):
            return ValidationResult(valid=True, payload=payload, repaired=repaired)
        errors.append("json_root_not_object")
    return ValidationResult(valid=False, errors=errors or ["no_json_object"])


def quarantine_malformed_output(
    output_dir: Path,
    *,
    row_id: str,
    run_id: str,
    phase: str,
    attempt: int,
    text: str,
    errors: list[str],
    provider_call: dict[str, Any] | None = None,
) -> Path:
    quarantine_dir = output_dir / "_quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    path = quarantine_dir / f"{row_id}-{phase}-attempt-{attempt}.json"
    payload = {
        "object": "gct.malformed_output_quarantine",
        "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
        "row_id": row_id,
        "run_id": run_id,
        "phase": phase,
        "attempt": attempt,
        "errors": list(errors),
        "provider_call": dict(provider_call or {}),
        "text": text,
        "quarantined_at": time.time(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def certify_execution_summary(
    summary: dict[str, Any],
    *,
    require_execute_mode: bool = True,
    expected_rows: int = 200,
) -> dict[str, Any]:
    rows = [row for row in summary.get("rows") or [] if isinstance(row, dict)]
    provider_names = {
        call.get("agent")
        for row in rows
        for call in row.get("provider_calls", [])
        if isinstance(call, dict) and call.get("agent")
    }
    failures = [
        row
        for row in rows
        if row.get("status") != "completed"
        or not row.get("valid_instrumentation")
        or row.get("malformed_output_accepted")
        or row.get("synthetic_or_replay")
    ]
    blockers: list[str] = []
    if require_execute_mode and summary.get("mode") != "execute":
        blockers.append("full readiness requires execute mode, not dry_run")
    if len(rows) != expected_rows:
        blockers.append(f"expected {expected_rows} rows, observed {len(rows)}")
    if failures:
        blockers.append(f"{len(failures)} rows failed completion, validation, or instrumentation gates")
    if len(provider_names) < 2:
        blockers.append("multi-provider cloud support not demonstrated by completed rows")
    return {
        "ready": not blockers,
        "row_count": len(rows),
        "provider_count": len(provider_names),
        "providers": sorted(provider for provider in provider_names if provider),
        "blockers": blockers,
    }


def certify_cloud_provider(agent: AgentConfig, *, timeout_seconds: float = 4.0) -> dict[str, Any]:
    audit = _audit_agent(agent, timeout_seconds=timeout_seconds)
    auth_ok = audit.get("authenticated") is not False
    quota_ok = audit.get("quota_status") not in {"exhausted", "rate_limited"}
    availability_ok = bool(agent.enabled) and bool(agent.model)
    structured_ok = bool(agent.supports_json or agent.supports_function_calling)
    timeout_ok = float(agent.timeout_seconds or 0.0) > 0.0
    retry_ok = bool(agent.cooldown_seconds is not None and agent.cooldown_seconds >= 0)
    audit.update(
        {
            "auth_check": _status(auth_ok, "missing_or_rejected_auth" if not auth_ok else ""),
            "quota_check": _status(quota_ok, str(audit.get("quota_status") or "unknown")),
            "model_availability_check": _status(availability_ok, "missing_model_or_disabled" if not availability_ok else ""),
            "structured_output_compliance_check": _status(structured_ok, "json_or_function_calling_not_declared" if not structured_ok else ""),
            "timeout_behavior_check": _status(timeout_ok, "timeout_seconds_not_positive" if not timeout_ok else ""),
            "retry_behavior_check": _status(retry_ok, "cooldown_seconds_missing" if not retry_ok else ""),
        }
    )
    audit["certified"] = all(
        audit[key]["passed"]
        for key in (
            "auth_check",
            "quota_check",
            "model_availability_check",
            "structured_output_compliance_check",
            "timeout_behavior_check",
            "retry_behavior_check",
        )
    )
    return audit


def certify_configured_cloud_providers(config: HubConfig, *, timeout_seconds: float = 4.0) -> list[dict[str, Any]]:
    return [certify_cloud_provider(agent, timeout_seconds=timeout_seconds) for agent in cloud_agents(config).values()]


def estimate_execution_preflight(rows: list[dict[str, Any]], agents: dict[str, AgentConfig]) -> dict[str, Any]:
    total_rows = len(rows)
    phases_per_row = 2
    total_runs = total_rows * phases_per_row
    input_tokens_per_phase = 1_200
    output_tokens_per_phase = 900
    expected_input_tokens = total_runs * input_tokens_per_phase
    expected_output_tokens = total_runs * output_tokens_per_phase
    expected_total_tokens = expected_input_tokens + expected_output_tokens
    expected_cost = 0.0
    cost_known = False
    provider_estimates: list[dict[str, Any]] = []
    for agent in agents.values():
        input_cost = agent.cost_per_million_input
        output_cost = agent.cost_per_million_output
        if input_cost is not None or output_cost is not None:
            cost_known = True
        agent_cost = ((expected_input_tokens / 1_000_000) * float(input_cost or 0.0)) + (
            (expected_output_tokens / 1_000_000) * float(output_cost or 0.0)
        )
        expected_cost = max(expected_cost, agent_cost)
        provider_estimates.append(
            {
                "agent": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "context_window": agent.context_window,
                "estimated_tokens": expected_total_tokens,
                "estimated_cost": round(agent_cost, 6) if cost_known else None,
                "quota_state": "unknown",
            }
        )
    blockers: list[str] = []
    if not agents:
        blockers.append("no cloud providers configured")
    return {
        "object": "gct.cost_quota_preflight",
        "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
        "total_rows": total_rows,
        "total_runs": total_runs,
        "expected_input_tokens": expected_input_tokens,
        "expected_output_tokens": expected_output_tokens,
        "expected_token_usage": expected_total_tokens,
        "expected_cost": round(expected_cost, 6) if cost_known else None,
        "cost_known": cost_known,
        "available_quota": "unknown",
        "provider_estimates": provider_estimates,
        "blockers": blockers,
        "abort": bool(blockers),
    }


def dashboard_status(summary: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in summary.get("rows") or [] if isinstance(row, dict)]
    completed = [row for row in rows if row.get("status") == "completed"]
    failed = [row for row in rows if row.get("status") == "failed"]
    quarantined = [row for row in rows if row.get("status") == "quarantined"]
    provider_failures = 0
    parser_failures = 0
    provider_names: set[str] = set()
    for row in rows:
        if row.get("failure"):
            failure_text = json.dumps(row.get("failure"), sort_keys=True)
            if "structured output" in failure_text or "No valid structured output" in failure_text:
                parser_failures += 1
            else:
                provider_failures += 1
        for call in row.get("provider_calls") or []:
            if isinstance(call, dict) and call.get("agent"):
                provider_names.add(str(call["agent"]))
    instrumentation_valid = sum(1 for row in completed if row.get("valid_instrumentation"))
    coverage = (instrumentation_valid / len(rows)) if rows else 0.0
    preflight = summary.get("preflight") if isinstance(summary.get("preflight"), dict) else {}
    expected_cost = preflight.get("expected_cost")
    remaining_cost = None
    if isinstance(expected_cost, (int, float)) and rows:
        remaining = max(0, int(summary.get("row_count") or len(rows)) - len(completed))
        remaining_cost = round(float(expected_cost) * (remaining / max(1, int(summary.get("row_count") or len(rows)))), 6)
    return {
        "object": "gct.execution_dashboard_status",
        "completed_rows": len(completed),
        "failed_rows": len(failed),
        "quarantined_rows": len(quarantined),
        "provider_failures": provider_failures,
        "parser_failures": parser_failures,
        "instrumentation_coverage": round(coverage, 4),
        "estimated_remaining_cost": remaining_cost,
        "providers_observed": sorted(provider_names),
    }


def audit_configured_providers(config: HubConfig, *, timeout_seconds: float = 4.0) -> list[dict[str, Any]]:
    return [_audit_agent(agent, timeout_seconds=timeout_seconds) for agent in config.agents.values()]


def provider_audit_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Provider Audit",
        "",
        "Scope: every configured provider in `agent-hub.config.json`. Authentication and quota are inferred from configured keys, HTTP status, and provider error text; no theory verdict is made.",
        "",
        "| agent | provider_type | model | enabled | cloud | reachable | authenticated | quota_status | subscription | JSON | structured output | notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {agent} | {provider_type} | {model} | {enabled} | {cloud} | {reachable} | {authenticated} | {quota_status} | {subscription} | {json} | {structured} | {notes} |".format(
                agent=_md(row.get("agent")),
                provider_type=_md(row.get("provider_type")),
                model=_md(row.get("model")),
                enabled=_md(row.get("enabled")),
                cloud=_md(row.get("cloud")),
                reachable=_md(row.get("reachable")),
                authenticated=_md(row.get("authenticated")),
                quota_status=_md(row.get("quota_status")),
                subscription=_md(row.get("subscription_requirements")),
                json=_md(row.get("json_compliance")),
                structured=_md(row.get("structured_output_capability")),
                notes=_md("; ".join(row.get("notes") or [])),
            )
        )
    return "\n".join(lines) + "\n"


def cloud_provider_certification_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Cloud Provider Certification",
        "",
        "Scope: configured cloud providers only. Checks cover auth, quota, model availability, structured-output compliance, timeout behavior, and retry behavior.",
        "",
        "| agent | model | auth | quota | model | structured output | timeout | retry | certified | notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {agent} | {model} | {auth} | {quota} | {availability} | {structured} | {timeout} | {retry} | {certified} | {notes} |".format(
                agent=_md(row.get("agent")),
                model=_md(row.get("model")),
                auth=_md(_check_label(row.get("auth_check"))),
                quota=_md(_check_label(row.get("quota_check"))),
                availability=_md(_check_label(row.get("model_availability_check"))),
                structured=_md(_check_label(row.get("structured_output_compliance_check"))),
                timeout=_md(_check_label(row.get("timeout_behavior_check"))),
                retry=_md(_check_label(row.get("retry_behavior_check"))),
                certified=_md(row.get("certified")),
                notes=_md("; ".join(row.get("notes") or [])),
            )
        )
    return "\n".join(lines) + "\n"


def schema_enforcement_markdown() -> str:
    return "\n".join(
        [
            "# Provider-Neutral Schema Enforcement",
            "",
            f"Schema version: `{STRUCTURED_OUTPUT_SCHEMA_VERSION}`.",
            "",
            "Contract applies to every configured provider through the frozen panel executor. Provider responses are parsed as JSON, validated against one event schema, and accepted only when strict phase gates pass.",
            "",
            "- Required root key: `events`.",
            "- Required event keys: `" + "`, `".join(sorted(EVENT_REQUIRED_KEYS)) + "`.",
            "- Repair policy: one malformed JSON repair candidate and one provider re-prompt are allowed.",
            "- Quarantine policy: malformed outputs are written under `_quarantine` with row, phase, attempt, errors, and raw provider call.",
            "- Ingestion policy: invalid payloads are never passed to the event ledger.",
            "",
            "```json",
            json.dumps(STRUCTURED_OUTPUT_CONTRACT, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )


def cost_quota_preflight_markdown(preflight: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Cost/Quota Preflight",
            "",
            f"Total rows: `{preflight.get('total_rows')}`.",
            f"Total provider runs: `{preflight.get('total_runs')}`.",
            f"Expected token usage: `{preflight.get('expected_token_usage')}`.",
            f"Expected cost: `{preflight.get('expected_cost') if preflight.get('expected_cost') is not None else 'unknown'}`.",
            f"Available quota: `{preflight.get('available_quota')}`.",
            f"Abort: `{preflight.get('abort')}`.",
            "",
            "Blockers: " + (", ".join(preflight.get("blockers") or []) or "none"),
            "",
        ]
    )


def dashboard_status_markdown(status: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Execution Dashboard Status",
            "",
            f"Completed rows: `{status.get('completed_rows')}`.",
            f"Failed rows: `{status.get('failed_rows')}`.",
            f"Quarantined rows: `{status.get('quarantined_rows')}`.",
            f"Provider failures: `{status.get('provider_failures')}`.",
            f"Parser failures: `{status.get('parser_failures')}`.",
            f"Instrumentation coverage: `{status.get('instrumentation_coverage')}`.",
            f"Estimated remaining cost: `{status.get('estimated_remaining_cost')}`.",
            "",
        ]
    )


def _audit_agent(agent: AgentConfig, *, timeout_seconds: float) -> dict[str, Any]:
    notes: list[str] = []
    reachable: bool | None = None
    authenticated: bool | None = None
    quota_status = "unknown"
    subscription = "not declared"
    if agent.api_key_env and not agent.resolved_api_key:
        authenticated = False
        notes.append(f"missing env {agent.api_key_env}")
    elif agent.api_key_env:
        authenticated = True
    if agent.base_url:
        probe = _probe_base_url(agent, timeout_seconds=timeout_seconds)
        reachable = probe["reachable"]
        notes.extend(probe["notes"])
        if probe.get("error_type") == "authentication_error":
            authenticated = False
        elif probe.get("status_code") and int(probe["status_code"]) < 500 and authenticated is None:
            authenticated = True
        if probe.get("error_type") == "quota_exhausted":
            quota_status = "exhausted"
        elif probe.get("error_type") == "temporary_rate_limit":
            quota_status = "rate_limited"
        elif reachable:
            quota_status = "not_exhausted_by_probe"
    elif agent.provider in {"echo", "local-research", "codex-cli"}:
        reachable = bool(agent.enabled)
        authenticated = True
        quota_status = "not_applicable"
    elif authenticated is None:
        authenticated = bool(agent.resolved_api_key) if agent.api_key_env else None
    if str(agent.provider_type or agent.provider).lower() == "ollama-cloud":
        subscription = "requires local Ollama with cloud model access"
    elif agent.api_key_env:
        subscription = f"requires {agent.api_key_env}"
    return {
        "agent": agent.name,
        "provider": agent.provider,
        "provider_type": agent.provider_type or agent.provider,
        "model": agent.model,
        "enabled": agent.enabled,
        "cloud": is_cloud_agent(agent),
        "reachable": reachable,
        "authenticated": authenticated,
        "quota_status": quota_status,
        "subscription_requirements": subscription,
        "json_compliance": bool(agent.supports_json),
        "structured_output_capability": _structured_output_capability(agent),
        "notes": notes,
    }


def _probe_base_url(agent: AgentConfig, *, timeout_seconds: float) -> dict[str, Any]:
    candidates = []
    base = str(agent.base_url or "").rstrip("/") + "/"
    if str(agent.provider_type or "").lower() == "ollama-cloud" or "ollama" in base:
        candidates.extend([urljoin(base, "api/tags"), urljoin(base, "v1/models")])
    else:
        candidates.append(urljoin(base, "v1/models"))
    headers = {}
    if agent.resolved_api_key:
        headers["Authorization"] = f"Bearer {agent.resolved_api_key}"
    for url in candidates:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status = int(response.status)
                return {"reachable": status < 500, "status_code": status, "notes": [f"probe {url} -> {status}"]}
        except urllib.error.HTTPError as exc:
            error_type = classify_provider_error(exc.read().decode("utf-8", errors="replace"), status_code=exc.code)
            return {"reachable": exc.code < 500, "status_code": exc.code, "error_type": error_type, "notes": [f"probe {url} -> HTTP {exc.code} {error_type}"]}
        except Exception as exc:
            last = f"probe {url} failed: {type(exc).__name__}: {exc}"
    return {"reachable": False, "notes": [last]}


def _structured_output_capability(agent: AgentConfig) -> str:
    if agent.supports_function_calling:
        return "native_tools_or_functions"
    if agent.supports_json:
        return "json_mode_or_prompt_enforced"
    return "not_declared"


def _schema_errors(payload: dict[str, Any], *, phase: str) -> list[str]:
    errors: list[str] = []
    root_allowed = {"events", "final_answer"}
    extra_root = sorted(set(payload) - root_allowed)
    if extra_root:
        errors.append("unexpected_root_keys:" + ",".join(extra_root))
    if phase == "pre_commit" and "final_answer" in payload:
        errors.append("pre_commit_final_answer_disallowed")
    if phase == "commitment" and "final_answer" in payload and not isinstance(payload.get("final_answer"), str):
        errors.append("final_answer_not_string")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        return ["events_missing_or_empty"]
    allowed = PRE_COMMIT_EVENT_TYPES if phase == "pre_commit" else ALL_EVENT_TYPES
    required = PRE_COMMIT_EVENT_TYPES if phase == "pre_commit" else {"branch_selection", "justification_event", "commitment_event"}
    observed: set[str] = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append(f"events[{index}] not object")
            continue
        extra_event = sorted(set(event) - (EVENT_REQUIRED_KEYS | EVENT_OPTIONAL_KEYS))
        if extra_event:
            errors.append(f"events[{index}].unexpected_keys:" + ",".join(extra_event))
        missing_event_keys = sorted(EVENT_REQUIRED_KEYS - set(event))
        if missing_event_keys:
            errors.append(f"events[{index}].missing_keys:" + ",".join(missing_event_keys))
        event_type = str(event.get("event_type") or "")
        observed.add(event_type)
        if event_type not in allowed:
            errors.append(f"events[{index}].event_type disallowed:{event_type}")
        event_phase = str(event.get("phase") or "")
        if event_phase != phase:
            errors.append(f"events[{index}].phase mismatch:{event_phase}")
        if event_type == "commitment_event" and phase == "pre_commit":
            errors.append("pre_commit emitted commitment_event")
        for key in ("local_grounding", "uncertainty", "commitment_strength"):
            if key in event and event[key] is not None and not _is_number_01(event[key]):
                errors.append(f"events[{index}].{key} outside_0_1")
        if "evidence_refs" in event and not isinstance(event.get("evidence_refs"), list):
            errors.append(f"events[{index}].evidence_refs not list")
        if "payload" in event and not isinstance(event.get("payload"), dict):
            errors.append(f"events[{index}].payload not object")
        for key in ("branch_id", "selected_branch_id", "previous_branch_id", "evidence_unit"):
            if key in event and event[key] is not None and not isinstance(event[key], str):
                errors.append(f"events[{index}].{key} not string")
        if "lock_in" in event and event["lock_in"] is not None and not isinstance(event["lock_in"], bool):
            errors.append(f"events[{index}].lock_in not bool")
    missing = sorted(required - observed)
    if missing:
        errors.append("missing_required_events:" + ",".join(missing))
    return errors


def _json_candidates(text: str) -> list[tuple[str, bool]]:
    candidates = [(text.strip(), False)] if text and text.strip() else []
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append((fenced.group(1).strip(), True))
    match = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
    if match:
        candidates.append((match.group(0).strip(), True))
    repaired: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for candidate, was_repaired in candidates:
        for value in (candidate, _strip_trailing_commas(candidate)):
            if value not in seen:
                seen.add(value)
                repaired.append((value, was_repaired or value != candidate))
    return repaired[: 1 + MAX_REPAIR_ATTEMPTS]


def _strip_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _is_number_01(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return 0.0 <= number <= 1.0


def _affirmative_marker(text: str, marker: str) -> bool:
    lowered = text.lower()
    if marker not in lowered:
        return False
    negated = (f"no {marker}", f"not {marker}", f"non-{marker}", f"without {marker}")
    return not any(term in lowered for term in negated)


def _md(value: Any) -> str:
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if text else "-"


def _status(passed: bool, reason: str = "") -> dict[str, Any]:
    return {"passed": bool(passed), "reason": reason}


def _check_label(value: Any) -> str:
    if not isinstance(value, dict):
        return "-"
    return "pass" if value.get("passed") else f"fail:{value.get('reason') or 'unknown'}"
