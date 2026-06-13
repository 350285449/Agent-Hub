from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import normalize_provider
from .core.router import AgentRouter
from .dependency_audit import dependency_install_checks
from .payloads import request_from_payload
from .permissions import TRUSTED_CLOUD, provider_trust_level
from .version import backend_version
from .commands_provider import _agent_rows, _health_rows, _local_models_report
from .output import _print_table
from .runtime_usability import (
    runtime_route_smoke,
    runtime_usability_body,
    save_runtime_usability_record,
)


LOCAL_URL_PREFIXES = (
    "http://127.0.0.1",
    "https://127.0.0.1",
    "http://localhost",
    "https://localhost",
    "http://[::1]",
    "https://[::1]",
)
BACKEND_HEALTH_TIMEOUT_SECONDS = 0.75


def _doctor_report(
    config: Any,
    config_path: str,
    *,
    backend_status: dict[str, Any] | None = None,
    local_servers: list[dict[str, Any]] | None = None,
    local_model_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = _agent_rows(config)
    router = AgentRouter(config)
    provider_health = router.health_snapshot()
    recommendations = router.recommend(
        request_from_payload(
            {
                "session_id": f"doctor-{uuid.uuid4().hex}",
                "route": "cloud-agent",
                "task": "Select the best model for a coding-agent workflow.",
                "use_session_history": False,
                "record_session": False,
            }
        ),
        limit=5,
        needs_tools=True,
        include_unavailable=True,
    )
    warnings: list[str] = []
    usable = [
        row
        for row in rows
        if row["allowed"] and row["status"] in {"ready", "configured"}
    ]
    if config.free_only:
        warnings.append("free_only is enabled; paid providers are skipped unless an agent is marked free=true.")
    init_report = getattr(config, "initialization_report", {}) or {}
    if init_report.get("created_default_config"):
        warnings.append("Created a default config automatically because none existed.")
    enabled_from_env = init_report.get("enabled_from_environment")
    if isinstance(enabled_from_env, list) and enabled_from_env:
        names = ", ".join(str(item.get("agent")) for item in enabled_from_env if isinstance(item, dict))
        warnings.append(f"Enabled provider agent(s) from environment variables: {names}.")
    added_presets = init_report.get("added_provider_presets")
    if isinstance(added_presets, list) and added_presets:
        names = ", ".join(str(item.get("agent")) for item in added_presets if isinstance(item, dict))
        warnings.append(f"Added free provider preset agent(s) from detected API keys: {names}.")
    free_cloud_agents = init_report.get("free_cloud_route_agents")
    if isinstance(free_cloud_agents, list) and free_cloud_agents:
        warnings.append(
            "Free cloud route candidates: "
            + ", ".join(str(name) for name in free_cloud_agents)
            + "."
        )
    selected_models = init_report.get("selected_local_models")
    if isinstance(selected_models, dict) and selected_models:
        pairs = ", ".join(f"{name}={model}" for name, model in selected_models.items())
        warnings.append(f"Selected detected local model ID(s): {pairs}.")
    if not usable:
        warnings.append(
            "No usable model is available. Enable a provider, set a missing API key, or start Ollama/LM Studio."
        )
    for row in rows:
        if row["enabled"] and row["status"].startswith("missing"):
            warnings.append(f"{row['name']}: {row['status']}.")
        if row["enabled"] and row["status"] == "configured":
            warnings.append(
                f"{row['name']}: config looks usable; first request will confirm {row['base_url']} is running."
            )

    if (
        isinstance(backend_status, dict)
        and isinstance(local_servers, list)
        and isinstance(local_model_rows, list)
    ):
        pass
    else:
        with ThreadPoolExecutor(max_workers=3) as executor:
            backend_future = (
                None
                if isinstance(backend_status, dict)
                else executor.submit(_backend_reachability, config)
            )
            servers_future = (
                None
                if isinstance(local_servers, list)
                else executor.submit(_local_endpoint_status)
            )
            models_future = (
                None
                if isinstance(local_model_rows, list)
                else executor.submit(_local_models_report, config)
            )
            if backend_future is not None:
                backend_status = backend_future.result()
            if servers_future is not None:
                local_servers = servers_future.result()
            if models_future is not None:
                local_model_rows = models_future.result()
    backend_status = backend_status if isinstance(backend_status, dict) else {}
    local_servers = local_servers if isinstance(local_servers, list) else []
    local_model_rows = local_model_rows if isinstance(local_model_rows, list) else []
    runtime_usability = runtime_usability_body(
        config,
        provider_health,
        backend_reachable=backend_status,
        local_servers=local_servers,
        local_model_rows=local_model_rows,
    )
    install_checks = _doctor_install_checks(
        config,
        config_path,
        rows,
        local_servers,
        backend_status,
    )
    likely_problems = _doctor_likely_problems(config, rows, local_servers, install_checks, backend_status)
    fixes = _doctor_exact_fixes(config, rows, likely_problems)
    return {
        "config": config_path,
        "config_path": str(Path(config_path).resolve()),
        "backend_version": backend_version(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "host": config.host,
        "port": config.port,
        "cline_endpoint": f"http://{config.host}:{config.port}/v1",
        "claude_endpoint": f"http://{config.host}:{config.port}/v1/messages",
        "free_only": config.free_only,
        "shell_command_policy": config.shell_command_policy,
        "approval_mode": config.approval_mode,
        "safe_mode": config.approval_mode == "safe",
        "readonly_mode": config.approval_mode == "readonly",
        "token_optimization_mode": config.context_mode,
        "cline_compatibility_mode": config.cline_compatibility_mode,
        "default_route": config.default_route,
        "initialization": init_report,
        "agents": rows,
        "enabled_providers": [row["name"] for row in rows if row["enabled"]],
        "missing_api_keys": _missing_api_key_rows(rows),
        "install_checks": install_checks,
        "dependency_checks": [row for row in install_checks if row.get("category") == "dependency"],
        "config_exists": any(row.get("id") == "config_file" and row.get("ok") for row in install_checks),
        "providers_available": bool(usable),
        "backend_reachable": backend_status,
        "release_checks": [row for row in install_checks if row.get("category") == "release"],
        "version_checks": [row for row in install_checks if row.get("category") == "version"],
        "local_servers": local_servers,
        "local_models": local_model_rows,
        "runtime_usability": runtime_usability,
        "provider_health": provider_health,
        "recommendations": recommendations,
        "context_diagnostics": {
            "mode": config.context_mode,
            "budget_tokens": config.agent_context_budget_tokens,
            "compaction_enabled": config.agent_context_compaction_enabled,
            "cline_compatibility_mode": config.cline_compatibility_mode,
        },
        "likely_problems": likely_problems,
        "exact_fixes": fixes,
        "warnings": warnings,
    }


def _checkup_report(
    config: Any,
    config_path: str,
    *,
    fix_safe: bool,
    verify: bool,
) -> dict[str, Any]:
    local_models = _local_models_report(config) if fix_safe else []
    fix_report = None
    if fix_safe:
        fix_report = _doctor_fix_safe(config_path, local_model_rows=local_models)
        if fix_report.get("changed"):
            from .config import load_config

            config = load_config(config_path)
            config.ensure_dirs()
            local_models = _local_models_report(config)

    route_smoke = {}
    if verify:
        route_smoke = _run_checkup_route_smoke(config)

    doctor = _doctor_report(
        config,
        config_path,
        local_model_rows=local_models if fix_safe else None,
    )
    if isinstance(doctor.get("local_models"), list):
        local_models = doctor["local_models"]
    provider_health = doctor.get("provider_health") if isinstance(doctor.get("provider_health"), dict) else {}
    runtime_usability = runtime_usability_body(
        config,
        provider_health,
        backend_reachable=doctor.get("backend_reachable") if isinstance(doctor.get("backend_reachable"), dict) else None,
        local_servers=doctor.get("local_servers") if isinstance(doctor.get("local_servers"), list) else [],
        local_model_rows=local_models,
        route_smoke=route_smoke if route_smoke else None,
    )
    if verify:
        save_runtime_usability_record(
            config,
            {
                "object": "agent_hub.runtime_usability_record",
                "recorded_at": time.time(),
                "route_smoke": route_smoke,
                "runtime_usability": runtime_usability,
            },
        )
    return {
        "object": "agent_hub.checkup",
        "ok": runtime_usability.get("state") == "ready",
        "fix_safe": fix_report,
        "verify": bool(verify),
        "doctor": doctor,
        "local_models": local_models,
        "route_smoke": route_smoke,
        "runtime_usability": runtime_usability,
        "next_step": runtime_usability.get("next_step"),
    }


def _run_checkup_route_smoke(config: Any) -> dict[str, Any]:
    router = AgentRouter(config)
    research_ok = False
    coding_ok = False
    research_agent = "local-research"
    coding_agent = ""
    coding_error = ""
    try:
        research_response = router.route(
            request_from_payload(
                {
                    "session_id": f"checkup-research-{uuid.uuid4().hex}",
                    "route": "research",
                    "preferred_agent": "local-research",
                    "messages": [{"role": "user", "content": ""}],
                    "max_tokens": 32,
                    "use_session_history": False,
                    "record_session": False,
                }
            )
        )
        research_ok = bool(research_response.text)
        research_agent = research_response.agent or research_agent
    except Exception:
        research_ok = False

    health = router.health_snapshot()
    runtime_before_coding = runtime_usability_body(
        config,
        health,
        local_servers=_local_endpoint_status(),
        local_model_rows=_local_models_report(config),
    )
    verified = runtime_before_coding.get("verified_coding_providers")
    if isinstance(verified, list) and verified:
        try:
            coding_response = router.route(
                request_from_payload(
                    {
                        "session_id": f"checkup-coding-{uuid.uuid4().hex}",
                        "route": "coding",
                        "messages": [{"role": "user", "content": "Reply with OK."}],
                        "max_tokens": 16,
                        "use_session_history": False,
                        "record_session": False,
                    }
                )
            )
            coding_ok = bool(coding_response.text)
            coding_agent = coding_response.agent
        except Exception as exc:
            coding_error = str(exc)
    else:
        coding_error = "No verified coding-capable provider is available for a safe route smoke."
    return runtime_route_smoke(
        research_ok=research_ok,
        coding_ok=coding_ok,
        research_agent=research_agent,
        coding_agent=coding_agent,
        coding_error=coding_error,
    )


def _print_checkup(report: dict[str, Any]) -> None:
    runtime = report.get("runtime_usability") if isinstance(report.get("runtime_usability"), dict) else {}
    print("Agent-Hub checkup")
    print(f"ok: {report.get('ok')}")
    print(f"runtime_usability: {runtime.get('score', 0)}/100 ({runtime.get('state', 'unknown')})")
    next_step = runtime.get("next_step") if isinstance(runtime.get("next_step"), dict) else {}
    if next_step:
        print(f"next_step: {next_step.get('label')} - {next_step.get('detail')}")
        if next_step.get("command"):
            print(f"command: {next_step.get('command')}")
    fix = report.get("fix_safe") if isinstance(report.get("fix_safe"), dict) else {}
    if fix:
        print(f"fix_safe_changed: {fix.get('changed')}")
        if fix.get("backup_path"):
            print(f"backup: {fix.get('backup_path')}")
    smoke = report.get("route_smoke") if isinstance(report.get("route_smoke"), dict) else {}
    if smoke:
        print(f"research_smoke: {_dict(smoke.get('research')).get('ok')}")
        print(f"coding_smoke: {_dict(smoke.get('coding')).get('ok')}")


def _doctor_fix_safe(config_path: str, *, local_model_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "object": "agent_hub.doctor_fix_safe",
            "ok": False,
            "path": str(path),
            "changes": [],
            "errors": ["Config file does not exist."],
        }
    except json.JSONDecodeError as exc:
        return {
            "object": "agent_hub.doctor_fix_safe",
            "ok": False,
            "path": str(path),
            "changes": [],
            "errors": [f"Config is not valid JSON: {exc}"],
        }
    if not isinstance(data, dict):
        return {
            "object": "agent_hub.doctor_fix_safe",
            "ok": False,
            "path": str(path),
            "changes": [],
            "errors": ["Config root must be a JSON object."],
        }

    changes: list[str] = []
    errors: list[str] = []
    agents = data.get("agents")
    agent_names: set[str] = set()
    if isinstance(agents, list):
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            name = str(agent.get("name") or "").strip()
            if name:
                agent_names.add(name)
    if not agent_names:
        errors.append("No named agents are available for safe route cleanup.")

    default_route = data.get("default_route")
    if isinstance(default_route, list) and agent_names:
        cleaned = _known_route_agents(default_route, agent_names)
        if cleaned != default_route:
            data["default_route"] = cleaned
            changes.append("Removed unknown agents from default_route.")

    fallback_route = data.get("default_route") if isinstance(data.get("default_route"), list) else []
    routes = data.get("routes")
    if isinstance(routes, list) and agent_names:
        for route in routes:
            if not isinstance(route, dict):
                continue
            names = route.get("agents")
            if not isinstance(names, list):
                continue
            cleaned = _known_route_agents(names, agent_names)
            if not cleaned and fallback_route:
                cleaned = _known_route_agents(fallback_route, agent_names)
            if cleaned != names:
                route["agents"] = cleaned
                changes.append(f"Cleaned unknown agents from route {route.get('name') or '?'}.")

    if data.get("allow_shell_tools") is True and str(data.get("shell_command_policy") or "deny").lower() == "deny":
        data["allow_shell_tools"] = False
        changes.append("Set allow_shell_tools=false because shell_command_policy=deny.")

    if data.get("free_only") is not True:
        data["free_only"] = True
        changes.append("Set free_only=true for free-first routing.")
    if str(data.get("approval_mode") or "").lower() != "safe":
        data["approval_mode"] = "safe"
        changes.append("Set approval_mode=safe for guarded default execution.")
    if data.get("allow_shell_tools") is not False:
        data["allow_shell_tools"] = False
        changes.append("Set allow_shell_tools=false for safe default execution.")

    routes = data.get("routes")
    if isinstance(routes, list) and agent_names:
        _ensure_route_prefix(routes, "research", ["local-research"], agent_names, changes)
        _ensure_route_contains(routes, "local-agent", ["ollama-local", "lm-studio"], agent_names, changes)
        _ensure_route_order(
            routes,
            "cloud-agent",
            ["codex-cli", "ollama-kimi-cloud", "ollama-glm-cloud", "ollama-qwen-cloud", "ollama-nemotron-cloud", "ollama-gemma-cloud"],
            agent_names,
            changes,
        )

    if local_model_rows:
        _apply_detected_local_models(data, local_model_rows, changes)

    if changes and not errors:
        backup_path = _backup_config(path)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        backup_path = None
    return {
        "object": "agent_hub.doctor_fix_safe",
        "ok": not errors,
        "path": str(path),
        "backup_path": str(backup_path) if backup_path else None,
        "changed": bool(changes and not errors),
        "changes": changes,
        "errors": errors,
    }


def _known_route_agents(names: list[Any], agent_names: set[str]) -> list[str]:
    cleaned: list[str] = []
    for name in names:
        text = str(name or "")
        if text and text in agent_names and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _backup_config(path: Path) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%S")
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    index = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.{stamp}.{index}.bak")
        index += 1
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def _route_by_name(routes: list[Any], name: str) -> dict[str, Any] | None:
    return next((route for route in routes if isinstance(route, dict) and route.get("name") == name), None)


def _ensure_route_prefix(
    routes: list[Any],
    route_name: str,
    desired: list[str],
    agent_names: set[str],
    changes: list[str],
) -> None:
    route = _route_by_name(routes, route_name)
    if route is None:
        present = [name for name in desired if name in agent_names]
        if present:
            routes.append({"name": route_name, "keywords": [], "agents": present})
            changes.append(f"Created route {route_name}.")
        return
    agents = route.get("agents")
    if not isinstance(agents, list):
        agents = []
    prefix = [name for name in desired if name in agent_names]
    next_agents = [*prefix, *[name for name in agents if name not in prefix]]
    if next_agents != agents:
        route["agents"] = next_agents
        changes.append(f"Moved {', '.join(prefix)} to the front of route {route_name}.")


def _ensure_route_contains(
    routes: list[Any],
    route_name: str,
    desired: list[str],
    agent_names: set[str],
    changes: list[str],
) -> None:
    route = _route_by_name(routes, route_name)
    present = [name for name in desired if name in agent_names]
    if route is None:
        if present:
            routes.append({"name": route_name, "keywords": [], "agents": present})
            changes.append(f"Created route {route_name}.")
        return
    agents = route.get("agents")
    if not isinstance(agents, list):
        agents = []
    next_agents = list(agents)
    for name in present:
        if name not in next_agents:
            next_agents.append(name)
    if next_agents != agents:
        route["agents"] = next_agents
        changes.append(f"Added local model providers to route {route_name}.")


def _ensure_route_order(
    routes: list[Any],
    route_name: str,
    desired_order: list[str],
    agent_names: set[str],
    changes: list[str],
) -> None:
    route = _route_by_name(routes, route_name)
    if route is None:
        present = [name for name in desired_order if name in agent_names]
        if present:
            routes.append({"name": route_name, "keywords": [], "agents": present})
            changes.append(f"Created route {route_name}.")
        return
    agents = route.get("agents")
    if not isinstance(agents, list):
        agents = []
    ordered = [name for name in desired_order if name in agent_names and name in agents]
    remaining = [name for name in agents if name not in ordered]
    next_agents = [*ordered, *remaining]
    if next_agents != agents:
        route["agents"] = next_agents
        changes.append(f"Normalized free-first hybrid order for route {route_name}.")


def _apply_detected_local_models(
    data: dict[str, Any],
    local_model_rows: list[dict[str, Any]],
    changes: list[str],
) -> None:
    agents = data.get("agents")
    if not isinstance(agents, list):
        return
    detected = {
        str(row.get("name")): str((row.get("models") or [""])[0] or "")
        for row in local_model_rows
        if row.get("online") and isinstance(row.get("models"), list) and row.get("models")
    }
    if not detected:
        return
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        name = str(agent.get("name") or "")
        model = detected.get(name)
        if model and agent.get("model") != model:
            agent["model"] = model
            changes.append(f"Updated {name} model to detected local model {model}.")


def _missing_api_key_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("status") or "")
        if not status.startswith("missing"):
            continue
        missing.append(
            {
                "agent": row.get("name"),
                "provider": row.get("provider"),
                "api_key_env": row.get("api_key_env"),
            }
        )
    return missing


def _local_endpoint_status() -> list[dict[str, Any]]:
    endpoints = [
        ("Ollama", "http://127.0.0.1:11434/api/tags"),
        ("LM Studio", "http://127.0.0.1:1234/v1/models"),
    ]
    with ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
        return list(executor.map(lambda item: _local_endpoint_row(*item), endpoints))


def _local_endpoint_row(name: str, url: str) -> dict[str, Any]:
    ok = False
    detail = ""
    try:
        with urllib.request.urlopen(url, timeout=0.6) as response:
            ok = 200 <= int(response.status) < 300
            detail = f"HTTP {response.status}"
    except Exception as exc:
        detail = str(exc)
    return {"name": name, "url": url, "running": ok, "detail": detail}


def _doctor_install_checks(
    config: Any,
    config_path: str,
    rows: list[dict[str, Any]],
    local_servers: list[dict[str, Any]],
    backend_status: dict[str, Any],
) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[1]
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = Path.cwd() / config_file
    checks: list[dict[str, Any]] = [
        {
            "id": "python_version",
            "category": "runtime",
            "ok": sys.version_info >= (3, 11),
            "detail": f"{sys.version.split()[0]} at {sys.executable}",
        },
        {
            "id": "config_file",
            "category": "config",
            "ok": config_file.exists(),
            "detail": str(config_file.resolve()),
        },
        _config_validity_check(config, config_file),
        {
            "id": "providers_available",
            "category": "provider",
            "ok": any(row["allowed"] and row["status"] in {"ready", "configured"} for row in rows),
            "detail": ", ".join(row["name"] for row in rows if row["enabled"]) or "no enabled providers",
        },
        _provider_config_check(rows),
        _provider_reachability_check(config, rows, local_servers),
        {
            "id": "server_health",
            "category": "server",
            "ok": bool(backend_status.get("ok")),
            "detail": f"{backend_status.get('url', '')}: {backend_status.get('detail', '')}",
        },
    ]
    with ThreadPoolExecutor(max_workers=3) as executor:
        dependency_future = executor.submit(_dependency_checks, root)
        snapshot_future = executor.submit(_backend_snapshot_check, root)
        release_future = executor.submit(_release_validation_check, root)
        checks.extend(dependency_future.result())
        checks.append(_dependencies_installed_check(checks))
        checks.extend(_vscode_extension_setup_checks(root))
        checks.append(snapshot_future.result())
        checks.append(_version_alignment_check(root))
        checks.append(release_future.result())
    checks.append(
        {
            "id": "vscode_extension_connected",
            "category": "extension",
            "ok": False,
            "optional": True,
            "detail": "Cannot be proven from CLI; use Agent Hub: Check Health inside VS Code.",
        }
    )
    return checks


def _dependency_checks(root: Path) -> list[dict[str, Any]]:
    return dependency_install_checks(root)


def _dependencies_installed_check(checks: list[dict[str, Any]]) -> dict[str, Any]:
    dependency_rows = [
        row
        for row in checks
        if row.get("category") == "dependency" and str(row.get("id", "")).startswith("dependency:")
    ]
    failed = [row for row in dependency_rows if not row.get("ok")]
    return {
        "id": "dependencies_installed",
        "category": "dependency",
        "ok": not failed,
        "detail": (
            "all runtime dependencies importable"
            if not failed
            else "missing: " + ", ".join(str(row.get("id", "")).split(":", 1)[-1] for row in failed)
        ),
    }


def _config_validity_check(config: Any, config_file: Path) -> dict[str, Any]:
    issues: list[str] = []
    if not str(getattr(config, "host", "") or "").strip():
        issues.append("host is empty")
    try:
        port = int(getattr(config, "port", 0))
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        issues.append("port must be 1-65535")
    agent_names = set(getattr(config, "agents", {}) or {})
    for name in getattr(config, "default_route", []) or []:
        if name not in agent_names:
            issues.append(f"default_route references unknown agent {name}")
    for route in getattr(config, "routes", []) or []:
        route_name = getattr(route, "name", "")
        if not route_name:
            issues.append("route has empty name")
        for agent_name in getattr(route, "agents", []) or []:
            if agent_name not in agent_names:
                issues.append(f"route {route_name or '?'} references unknown agent {agent_name}")
    for key, agent in (getattr(config, "agents", {}) or {}).items():
        if getattr(agent, "name", key) != key:
            issues.append(f"agent key {key} does not match agent.name {getattr(agent, 'name', '')}")
        if not getattr(agent, "provider", ""):
            issues.append(f"agent {key} has empty provider")
        if not getattr(agent, "model", ""):
            issues.append(f"agent {key} has empty model")
    return {
        "id": "config_valid",
        "category": "config",
        "ok": not issues,
        "detail": "valid" if not issues else "; ".join(issues[:5]),
        "path": str(config_file.resolve()),
    }


def _provider_reachability_check(
    config: Any,
    rows: list[dict[str, Any]],
    local_servers: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = [
        row
        for row in rows
        if row.get("enabled") and row.get("allowed") and row.get("status") in {"ready", "configured"}
    ]
    if not candidates:
        return {
            "id": "provider_reachable",
            "category": "provider",
            "ok": False,
            "detail": "no enabled allowed provider is configured",
        }
    local_running = [row for row in local_servers if row.get("running")]
    for row in candidates:
        if normalize_provider(str(row.get("provider") or "")) == "echo":
            return {
                "id": "provider_reachable",
                "category": "provider",
                "ok": True,
                "detail": f"{row.get('name')} uses the built-in echo provider",
            }
        base_url = str(row.get("base_url") or "")
        if _is_local_url(base_url) and local_running:
            names = ", ".join(str(item.get("name")) for item in local_running)
            return {
                "id": "provider_reachable",
                "category": "provider",
                "ok": True,
                "detail": f"local server reachable: {names}",
            }
        if base_url and not _is_local_url(base_url):
            return {
                "id": "provider_reachable",
                "category": "provider",
                "ok": True,
                "detail": f"{row.get('name')} has a configured remote endpoint; live model call skipped",
            }
        if row.get("api_key_env") and row.get("status") == "ready":
            return {
                "id": "provider_reachable",
                "category": "provider",
                "ok": True,
                "detail": f"{row.get('name')} has credentials; live model call skipped",
            }
    return {
        "id": "provider_reachable",
        "category": "provider",
        "ok": False,
        "detail": "no local provider endpoint responded and no remote provider is configured",
    }


def _provider_config_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    enabled = [row for row in rows if row.get("enabled")]
    issues: list[str] = []
    for row in enabled:
        if not row.get("provider"):
            issues.append(f"{row.get('name')}: missing provider")
        if not row.get("model"):
            issues.append(f"{row.get('name')}: missing model")
        status = str(row.get("status") or "")
        if status.startswith("missing"):
            issues.append(f"{row.get('name')}: {status}")
    return {
        "id": "provider_config",
        "category": "provider",
        "ok": bool(enabled) and not issues,
        "detail": (
            "enabled provider configs have provider/model values"
            if enabled and not issues
            else "; ".join(issues[:5]) if issues else "no enabled providers"
        ),
    }


def _vscode_extension_setup_checks(root: Path) -> list[dict[str, Any]]:
    manifest_path = root / "vscode-extension" / "package.json"
    extension_path = root / "vscode-extension" / "extension.js"
    prepare_script = ""
    prepublish_script = ""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    scripts = manifest.get("scripts") if isinstance(manifest, dict) else {}
    if isinstance(scripts, dict):
        prepare_script = str(scripts.get("prepare-backend") or "")
        prepublish_script = str(scripts.get("vscode:prepublish") or "")
    return [
        {
            "id": "vscode_extension_manifest",
            "category": "extension",
            "ok": manifest_path.exists() and bool(manifest),
            "detail": manifest_path.as_posix(),
        },
        {
            "id": "vscode_extension_entrypoint",
            "category": "extension",
            "ok": extension_path.exists(),
            "detail": extension_path.as_posix(),
        },
        {
            "id": "vscode_extension_prepare_backend",
            "category": "extension",
            "ok": "scripts/prepare-backend.js" in prepare_script,
            "detail": prepare_script or "prepare-backend script missing",
        },
        {
            "id": "vscode_extension_prepublish_backend",
            "category": "extension",
            "ok": "prepare-backend" in prepublish_script and "validate-backend-drift" in prepublish_script,
            "detail": prepublish_script or "vscode:prepublish script missing",
        },
        _backend_gitignore_check(root),
    ]


def _backend_gitignore_check(root: Path) -> dict[str, Any]:
    gitignore = root / ".gitignore"
    try:
        patterns = {
            line.strip().replace("\\", "/")
            for line in gitignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    except OSError:
        patterns = set()
    return {
        "id": "vscode_backend_gitignored",
        "category": "extension",
        "ok": "vscode-extension/backend/" in patterns or "vscode-extension/backend" in patterns,
        "detail": "vscode-extension/backend/ is generated during packaging",
    }


def _backend_snapshot_check(root: Path) -> dict[str, Any]:
    snapshot = root / "vscode-extension" / "backend" / "SNAPSHOT.json"
    failures = _validate_backend_snapshot(root)
    return {
        "id": "backend_snapshot",
        "category": "extension",
        "ok": snapshot.exists() and not failures,
        "detail": (
            "generated and current"
            if snapshot.exists() and not failures
            else "; ".join(failures[:3]) if failures else "run npm run prepare-backend before packaging"
        ),
        "path": snapshot.as_posix(),
    }


def _version_alignment_check(root: Path) -> dict[str, Any]:
    versions = _version_sources(root)
    present = {key: value for key, value in versions.items() if value}
    normalized: dict[str, str] = {}
    invalid: list[str] = []
    for key, value in present.items():
        normalized_value = _normalize_release_version(value)
        if normalized_value is None:
            invalid.append(f"{key}={value}")
        else:
            normalized[key] = normalized_value
    unique = {str(value) for value in normalized.values()}
    ok = bool(present) and not invalid and len(unique) <= 1
    if ok:
        detail = "all versions match: " + next(iter(unique), "")
    elif invalid:
        detail = "invalid versions: " + ", ".join(invalid)
    else:
        detail = ", ".join(f"{key}={value}" for key, value in sorted(versions.items()))
    return {
        "id": "extension_backend_versions",
        "category": "version",
        "ok": ok,
        "detail": detail,
        "versions": versions,
    }


def _normalize_release_version(value: Any) -> str | None:
    match = re.fullmatch(
        r"\s*[vV]?(\d+)\.(\d+)\.(\d+)([-+][0-9A-Za-z][0-9A-Za-z.-]*)?\s*",
        str(value),
    )
    if match is None:
        return None
    release = ".".join(str(int(part)) for part in match.groups()[:3])
    suffix = str(match.group(4) or "").lower()
    return release + suffix


def _release_validation_check(root: Path) -> dict[str, Any]:
    try:
        from scripts.validate_release import (
            read_backend_base_version,
            read_json,
            read_toml,
            read_toml_version,
            validate_backend_generation_documented,
            validate_backend_snapshot_generation,
            validate_extension_packaging_scripts,
            validate_pyproject_metadata,
            validate_release_docs,
            validate_release_metadata,
            validate_version_consistency,
        )
    except Exception as exc:
        return {
            "id": "release_validation",
            "category": "release",
            "ok": False,
            "optional": True,
            "detail": f"release validation unavailable: {exc}",
        }
    release = read_json(root / "release.json")
    package = read_json(root / "vscode-extension" / "package.json")
    lock = read_json(root / "vscode-extension" / "package-lock.json")
    pyproject = read_toml(root / "pyproject.toml")
    failures: list[str] = []
    failures.extend(validate_release_metadata(release))
    failures.extend(validate_pyproject_metadata(pyproject))
    failures.extend(validate_extension_packaging_scripts(package))
    failures.extend(validate_backend_generation_documented(root))
    failures.extend(validate_backend_snapshot_generation(root))
    failures.extend(
        validate_version_consistency(
            release=release,
            package=package,
            lock=lock,
            pyproject_version=read_toml_version(root / "pyproject.toml"),
            backend_base_version=read_backend_base_version(root / "agent_hub" / "version.py"),
        )
    )
    failures.extend(validate_release_docs(root))
    return {
        "id": "release_validation",
        "category": "release",
        "ok": not failures,
        "detail": "passed" if not failures else "; ".join(failures[:5]),
        "failures": failures,
    }


def _validate_backend_snapshot(root: Path) -> list[str]:
    try:
        from scripts.backend_snapshot import validate_snapshot
    except Exception as exc:
        return [f"snapshot validation unavailable: {exc}"]
    return validate_snapshot(root)


def _version_sources(root: Path) -> dict[str, str]:
    return {
        "pyproject": _read_pyproject_version(root / "pyproject.toml"),
        "backend": _read_backend_base_version(root / "agent_hub" / "version.py"),
        "extension": _read_json_string(root / "vscode-extension" / "package.json", "version"),
        "extension_lock": _read_json_string(root / "vscode-extension" / "package-lock.json", "version"),
        "release_backend": _read_json_string(root / "release.json", "backend_version"),
        "release_extension": _read_json_string(root / "release.json", "extension_version"),
        "snapshot_backend": _read_json_string(root / "vscode-extension" / "backend" / "SNAPSHOT.json", "backend_version"),
        "snapshot_extension": _read_json_string(root / "vscode-extension" / "backend" / "SNAPSHOT.json", "extension_version"),
    }


def _read_json_string(path: Path, key: str) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    value = data.get(key) if isinstance(data, dict) else ""
    return str(value) if value else ""


def _read_pyproject_version(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def _read_backend_base_version(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^\s*BASE_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def _is_local_url(value: str) -> bool:
    return any(value.startswith(prefix) for prefix in LOCAL_URL_PREFIXES)


def _backend_reachability(config: Any) -> dict[str, Any]:
    url = f"http://{config.host}:{config.port}/health"
    try:
        with urllib.request.urlopen(url, timeout=BACKEND_HEALTH_TIMEOUT_SECONDS) as response:
            return {"ok": 200 <= int(response.status) < 300, "url": url, "detail": f"HTTP {response.status}"}
    except Exception as exc:
        return {"ok": False, "url": url, "detail": str(exc)}


def _doctor_likely_problems(
    config: Any,
    rows: list[dict[str, Any]],
    local_servers: list[dict[str, Any]],
    install_checks: list[dict[str, Any]],
    backend_status: dict[str, Any],
) -> list[str]:
    problems: list[str] = []
    if not any(row.get("enabled") and row.get("allowed") and row.get("status") in {"ready", "configured"} for row in rows):
        problems.append("no_usable_model")
    if _missing_api_key_rows(rows):
        problems.append("missing_api_key")
    if not any(row.get("running") for row in local_servers):
        problems.append("no_local_server_detected")
    if config.approval_mode == "deny" or (
        config.approval_mode == "auto"
        and not _auto_approval_expected_for_ide_cloud_routes(config, rows)
    ):
        problems.append("approval_mode_review_recommended")
    if not config.cline_compatibility_mode:
        problems.append("cline_compatibility_disabled")
    if not backend_status.get("ok"):
        problems.append("backend_not_reachable")
    for row in install_checks:
        if row.get("optional"):
            continue
        if not row.get("ok"):
            problems.append(f"install_check_failed:{row.get('id')}")
    return problems


def _doctor_exact_fixes(
    config: Any,
    rows: list[dict[str, Any]],
    problems: list[str],
) -> list[str]:
    fixes: list[str] = []
    if "no_usable_model" in problems:
        fixes.append("Enable a provider in the Agent Hub sidebar, set its API key, or start Ollama/LM Studio before sending a request.")
    missing = _missing_api_key_rows(rows)
    for row in missing:
        env_name = row.get("api_key_env") or "the provider API key"
        fixes.append(f"Set {env_name} for {row.get('agent')} or disable that provider.")
    if "no_local_server_detected" in problems:
        fixes.append("Start Ollama on http://127.0.0.1:11434 or LM Studio on http://127.0.0.1:1234 for local fallback.")
    if "approval_mode_review_recommended" in problems:
        if config.approval_mode == "auto":
            fixes.append(
                "approval_mode=auto is intended for non-interactive Cline/cloud routes; "
                "use ask or safe for local-only or publishable setups."
            )
        elif config.approval_mode == "deny":
            fixes.append("approval_mode=deny blocks privileged actions; use readonly for demos or safe/ask for interactive use.")
        else:
            fixes.append("Use approval_mode=ask or safe for publishable setups; readonly is best for demos.")
    if "cline_compatibility_disabled" in problems:
        fixes.append("Set cline_compatibility_mode=true in agent-hub.config.json.")
    if "backend_not_reachable" in problems:
        fixes.append(f"Start the backend with agent-hub serve, or click Start in VS Code, then check http://{config.host}:{config.port}/health.")
    if any(problem == "install_check_failed:backend_snapshot" for problem in problems):
        fixes.append("Run npm run prepare-backend from vscode-extension before packaging the VSIX.")
    if any(problem == "install_check_failed:config_file" for problem in problems):
        fixes.append("Run agent-hub init or confirm --config points at the intended agent-hub.config.json.")
    fixes.append(f"Cline: base URL http://{config.host}:{config.port}/v1, model agent-hub-coding, API key any non-empty placeholder.")
    fixes.append(f"Claude Code: Anthropic base URL http://{config.host}:{config.port}, model agent-hub-coding.")
    return fixes


def _auto_approval_expected_for_ide_cloud_routes(
    config: Any,
    rows: list[dict[str, Any]],
) -> bool:
    if not getattr(config, "cline_compatibility_mode", False):
        return False
    allowed_names = {
        str(row.get("name") or "")
        for row in rows
        if row.get("enabled") and row.get("allowed") and row.get("status") in {"ready", "configured"}
    }
    routed_names = set(str(name) for name in getattr(config, "default_route", []) or [])
    for route in getattr(config, "routes", []) or []:
        route_name = str(getattr(route, "name", "") or "")
        if route_name in {"coding", "cloud-agent", "hybrid-agent", "research"}:
            routed_names.update(str(name) for name in getattr(route, "agents", []) or [])
    for name in routed_names:
        if name not in allowed_names:
            continue
        agent = getattr(config, "agents", {}).get(name)
        if agent is not None and provider_trust_level(agent) == TRUSTED_CLOUD:
            return True
    return False


def _print_doctor(report: dict[str, Any]) -> None:
    print(f"Config: {report['config']}")
    print(f"Resolved config: {report['config_path']}")
    print(f"Backend version: {report['backend_version']}")
    print(f"Python: {report['python_version']} ({report['python_executable']})")
    print(f"Server: http://{report['host']}:{report['port']}")
    print(f"Cline endpoint: {report['cline_endpoint']}")
    print(f"Claude endpoint: {report['claude_endpoint']}")
    print(f"free_only: {report['free_only']}")
    print(f"shell_command_policy: {report['shell_command_policy']}")
    print(f"approval_mode: {report['approval_mode']} (safe={report['safe_mode']}, readonly={report['readonly_mode']})")
    print(f"token_optimization_mode: {report['token_optimization_mode']}")
    print(f"cline_compatibility_mode: {report['cline_compatibility_mode']}")
    print(f"default_route: {', '.join(report['default_route'])}")
    backend = report.get("backend_reachable") or {}
    print(f"backend_reachable: {backend.get('ok')} ({backend.get('url', '')})")
    runtime = report.get("runtime_usability") if isinstance(report.get("runtime_usability"), dict) else {}
    if runtime:
        print(
            "runtime_usability: "
            f"{runtime.get('score', 0)}/100 ({runtime.get('state', 'unknown')})"
        )
    print()
    install_checks = report.get("install_checks")
    if isinstance(install_checks, list) and install_checks:
        print("Install checks:")
        _print_table(install_checks, ["id", "category", "ok", "detail"])
        print()
    _print_table(report["agents"], ["name", "provider", "model", "enabled", "free", "allowed", "tokens", "status"])
    health_rows = _health_rows(report.get("provider_health", {}))
    if health_rows:
        print()
        print("Provider health:")
        _print_table(
            health_rows,
            ["name", "available", "degraded", "reliability", "avg_ms", "cooldown", "quota", "requests", "status"],
        )
    recommendations = report.get("recommendations")
    if isinstance(recommendations, list) and recommendations:
        print()
        print("Best cloud-agent candidates:")
        _print_table(
            recommendations[:5],
            ["rank", "agent", "provider", "model", "score", "available", "why"],
        )
    if report["warnings"]:
        print()
        print("Notes:")
        for warning in report["warnings"]:
            print(f"- {warning}")
    local_servers = report.get("local_servers")
    if isinstance(local_servers, list) and local_servers:
        print()
        print("Local model servers:")
        _print_table(local_servers, ["name", "running", "url", "detail"])
    if report.get("likely_problems"):
        print()
        print("Likely problems:")
        for problem in report["likely_problems"]:
            print(f"- {problem}")
    if report.get("exact_fixes"):
        print()
        print("Exact fixes:")
        for fix in report["exact_fixes"]:
            print(f"- {fix}")
    provider_types = report.get("provider_types")
    if isinstance(provider_types, list) and provider_types:
        print()
        print("Known provider types:")
        _print_table(provider_types, ["provider_type", "display_name", "api_key_env", "free"])
