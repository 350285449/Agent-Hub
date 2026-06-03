from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .config import (
    cloud_route_agent_names,
    config_to_dict,
    default_agent_names,
    free_local_config,
)
from .config_migration import migrate_config_file
from .payloads import request_from_payload
from .provider_presets import FREE_PROVIDER_PRESETS, agent_dict_from_preset


def _cloud_provider_defaults(provider: str) -> tuple[str, str, str]:
    normalized = provider.lower()
    if normalized in {"openai", "codex"}:
        return "codex", "openai", "OPENAI_API_KEY"
    if normalized == "chatgpt":
        return "chatgpt", "chatgpt", "OPENAI_API_KEY"
    if normalized in {"claude", "anthropic"}:
        return "claude", "claude", "ANTHROPIC_API_KEY"
    return "gemini", "gemini", "GEMINI_API_KEY"


def _load_or_default_config_dict(config_path: Path) -> dict[str, Any]:
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit(f"{config_path} does not contain a JSON object.")
        return data
    return config_to_dict(free_local_config())


def _write_config_dict(config_path: Path, data: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _upsert_agent(data: dict[str, Any], agent: dict[str, Any], *, replace_existing: bool = True) -> bool:
    agents = data.setdefault("agents", [])
    if not isinstance(agents, list):
        data["agents"] = agents = []
    for index, existing in enumerate(agents):
        if isinstance(existing, dict) and existing.get("name") == agent.get("name"):
            if replace_existing:
                merged = {**existing, **agent}
                agents[index] = _drop_empty(merged)
            return False
    agents.append(_drop_empty(agent))
    return True


def _append_agent_to_route(data: dict[str, Any], route_name: str, agent_name: str) -> None:
    routes = data.setdefault("routes", [])
    if not isinstance(routes, list):
        data["routes"] = routes = []
    route = next(
        (item for item in routes if isinstance(item, dict) and item.get("name") == route_name),
        None,
    )
    if route is None:
        route = {"name": route_name, "keywords": [], "agents": []}
        routes.append(route)
    agents = route.setdefault("agents", [])
    if not isinstance(agents, list):
        route["agents"] = agents = []
    if agent_name not in agents:
        agents.append(agent_name)


def _agent_name_from_provider_model(provider_type: str, model: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{provider_type}-{model}".lower()).strip("-")
    return slug[:80] or provider_type


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if value is not None and value != {} and value != []
    }


def _ensure_cloud_routes(data: dict[str, Any]) -> None:
    routes = data.setdefault("routes", [])
    if not isinstance(routes, list):
        data["routes"] = routes = []

    _ensure_route(
        routes,
        "hybrid-agent",
        default_agent_names(),
    )
    _ensure_route(
        routes,
        "cloud-agent",
        cloud_route_agent_names(),
    )


def _ensure_route(routes: list[Any], name: str, agents: list[str]) -> None:
    route = next(
        (item for item in routes if isinstance(item, dict) and item.get("name") == name),
        None,
    )
    if route is None:
        routes.append({"name": name, "keywords": [], "agents": agents})
        return
    route_agents = route.setdefault("agents", [])
    if not isinstance(route_agents, list):
        route["agents"] = route_agents = []
    for agent_name in agents:
        if agent_name not in route_agents:
            route_agents.append(agent_name)


def _move_agent_to_front(data: dict[str, Any], route_name: str, agent_name: str) -> None:
    routes = data.get("routes", [])
    if not isinstance(routes, list):
        return
    for route in routes:
        if not isinstance(route, dict) or route.get("name") != route_name:
            continue
        agents = route.get("agents")
        if not isinstance(agents, list):
            return
        route["agents"] = [agent_name, *[name for name in agents if name != agent_name]]
        return


def _init_config(path: str, force: bool = False, with_cloud_examples: bool = False) -> int:
    config_path = Path(path)
    if config_path.exists() and not force:
        print(f"{config_path} already exists. Use --force to overwrite it.")
        return 1

    data = config_to_dict(free_local_config())
    data["cloud_control_selection"] = {
        "route_mode": "ollama-cloud",
        "api_key_models_enabled": False,
    }
    if with_cloud_examples:
        _merge_agent_examples(data, _cloud_example_agents())
        _merge_agent_examples(data, [agent_dict_from_preset(preset) for preset in FREE_PROVIDER_PRESETS])
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {config_path}")
    print("Start Ollama for cloud model routing, or set provider API keys, then run: agent-hub doctor")
    return 0


def _cloud_example_agents() -> list[dict[str, Any]]:
    return [
        {
            "name": "chatgpt",
            "provider": "chatgpt",
            "model": "gpt-4o-mini",
            "enabled": False,
            "free": True,
            "api_key_env": "OPENAI_API_KEY",
            "context_window": 128000,
        },
        {
            "name": "gemini",
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "enabled": False,
            "free": True,
            "api_key_env": "GEMINI_API_KEY",
            "context_window": 1000000,
        },
        {
            "name": "claude",
            "provider": "claude",
            "model": "claude-3-5-haiku-latest",
            "enabled": False,
            "free": True,
            "api_key_env": "ANTHROPIC_API_KEY",
            "context_window": 200000,
        },
        {
            "name": "gemma-local",
            "provider": "gemma",
            "model": "your-gemma-model",
            "enabled": False,
            "free": True,
            "base_url": "http://127.0.0.1:8000",
            "context_window": 8192,
        },
    ]


def _merge_agent_examples(data: dict[str, Any], examples: list[dict[str, Any]]) -> None:
    agents = data.setdefault("agents", [])
    if not isinstance(agents, list):
        data["agents"] = agents = []
    existing = {
        item.get("name")
        for item in agents
        if isinstance(item, dict)
    }
    for example in examples:
        if example.get("name") not in existing:
            agents.append(example)
            existing.add(example.get("name"))


def _inspect_request(path: str | None, *, api_shape: str, as_json: bool) -> int:
    try:
        if path:
            payload_text = Path(path).read_text(encoding="utf-8")
        else:
            payload_text = sys.stdin.read()
        payload = json.loads(payload_text)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read request JSON: {exc}")
        return 1
    if not isinstance(payload, dict):
        print("Request JSON must be an object.")
        return 1
    request = request_from_payload(payload, api_shape=api_shape)
    request_context_diagnostics = getattr(
        __import__("agent_hub.context", fromlist=["request_context_diagnostics"]),
        "request_context_diagnostics",
    )
    diagnostics = request_context_diagnostics(request)
    report = {
        "api_shape": api_shape,
        "session_id": request.session_id,
        "route": request.route,
        "preferred_agent": request.preferred_agent,
        "message_count": len(request.messages),
        "metadata_keys": sorted(request.metadata),
        "diagnostics": diagnostics,
    }
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"API shape: {api_shape}")
        print(f"Session: {request.session_id}")
        print(f"Route: {request.route or '(auto)'}")
        print(f"Messages: {len(request.messages)}")
        print("Context diagnostics:")
        for key in (
            "incoming_token_count",
            "compacted_token_count",
            "protected_token_count",
            "dropped_messages",
            "dropped_token_count",
            "preserved_tool_calls",
            "preserved_tool_results",
            "preserved_todo_count",
            "active_files_detected",
            "task_progress_present",
            "structured_content_messages",
            "cline_compatibility_mode",
            "suspiciously_empty",
        ):
            print(f"- {key}: {diagnostics.get(key)}")
        if diagnostics.get("suspiciously_empty"):
            print()
            print("Warning: context looks empty. Check that the client is sending messages, task_progress, and active file metadata.")
    return 0


def _migrate_config(path: str, *, write: bool, output: str | None, as_json: bool) -> int:
    try:
        report = migrate_config_file(path, output_path=output, write=write)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Could not migrate config: {exc}")
        return 1
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    migrations = report["migrations"]
    if not migrations:
        print("No deprecated config keys detected.")
        return 0
    print(f"Detected {len(migrations)} config migration(s):")
    for migration in migrations:
        status = "applied" if migration["applied"] else "suggested"
        print(f"- {migration['old_key']} -> {migration['new_key']} ({status})")
    if write:
        print(f"Wrote migrated config: {report['output_path']}")
    else:
        print("Run with migrate-config --write to save the migrated config.")
    return 0
