from __future__ import annotations

import argparse
import json
import threading
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from typing import Sequence

from .agent_runner import AgentRunner
from .config import (
    cloud_route_agent_names,
    config_to_dict,
    default_agent_names,
    free_local_config,
    is_free_agent,
    load_config,
    normalize_provider,
)
from .inbox import InboxProcessor
from .payloads import request_from_payload
from .router import AgentRouter, RouterError
from .server import serve


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-hub")
    parser.add_argument(
        "--config",
        default="agent-hub.config.json",
        help="Path to the hub config JSON file.",
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create a friendly starter config.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing config.")
    init_parser.add_argument(
        "--with-cloud-examples",
        action="store_true",
        help="Also add optional provider examples that are not part of the default routes.",
    )

    agents_parser = subparsers.add_parser("agents", help="List configured agents and routing status.")
    agents_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    doctor_parser = subparsers.add_parser("doctor", help="Explain config and provider readiness.")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    local_models_parser = subparsers.add_parser(
        "local-models",
        help="Probe free local OpenAI-compatible model servers.",
    )
    local_models_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    enable_provider_parser = subparsers.add_parser(
        "enable-provider",
        help="Enable or update a cloud provider in the config file.",
    )
    enable_provider_parser.add_argument(
        "provider",
        choices=["openai", "codex", "chatgpt", "claude", "anthropic", "gemini", "google"],
    )
    enable_provider_parser.add_argument("--model", required=True, help="Provider model ID to use.")
    enable_provider_parser.add_argument(
        "--route",
        choices=["cloud-agent", "hybrid-agent"],
        default="cloud-agent",
        help="Route to add the provider to.",
    )
    enable_provider_parser.add_argument(
        "--api-key-env",
        help="Environment variable that contains the provider API key.",
    )
    enable_provider_parser.add_argument(
        "--paid",
        action="store_true",
        help="Mark this provider as paid and disable free_only for the config.",
    )

    serve_parser = subparsers.add_parser("serve", help="Run the local HTTP hub.")
    serve_parser.add_argument("--host", help="Override configured host.")
    serve_parser.add_argument("--port", type=int, help="Override configured port.")
    serve_parser.add_argument(
        "--watch-inbox",
        action="store_true",
        help="Also process JSON files from the configured inbox directory.",
    )

    watch_parser = subparsers.add_parser("watch", help="Process JSON files forever.")
    watch_parser.add_argument("--interval", type=float, default=1.0)

    subparsers.add_parser("once", help="Process the JSON inbox once.")

    agent_parser = subparsers.add_parser("agent", help="Run the workspace coding agent.")
    agent_parser.add_argument("task", nargs="+", help="Task for the agent.")
    agent_parser.add_argument("--route", default="cloud-agent", help="Route to use for agent model calls.")
    agent_parser.add_argument("--max-steps", type=int, default=20, help="Maximum agent tool steps.")
    agent_parser.add_argument(
        "--allow-shell-tools",
        action="store_true",
        help="Allow the agent to run local shell commands.",
    )
    agent_parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="Respect config free_only=false. By default this command forces free_only=true.",
    )

    chat_parser = subparsers.add_parser("chat", help="Open an interactive Codex-style workspace chat.")
    chat_parser.add_argument("--route", default="cloud-agent", help="Route to use for chat turns.")
    chat_parser.add_argument("--session-id", help="Reuse an existing chat session id.")
    chat_parser.add_argument("--max-steps", type=int, default=20, help="Maximum agent tool steps per turn.")
    chat_parser.add_argument(
        "--allow-shell-tools",
        action="store_true",
        help="Allow the chat agent to run local shell commands.",
    )
    chat_parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="Respect config free_only=false. By default chat forces free_only=true.",
    )
    chat_parser.add_argument(
        "--no-agent",
        action="store_true",
        help="Use a single routed model call instead of the workspace agent loop.",
    )

    route_parser = subparsers.add_parser("route", help="Route one JSON file and print the result.")
    route_parser.add_argument("path")
    route_parser.add_argument(
        "--api-shape",
        choices=["native", "openai-chat", "anthropic-messages"],
        default="native",
    )
    route_parser.add_argument(
        "--agent-mode",
        action="store_true",
        help="Run the native agent loop instead of a single model call.",
    )

    args = parser.parse_args(argv)
    command = args.command or "serve"
    if command == "init":
        return _init_config(args.config, force=args.force, with_cloud_examples=args.with_cloud_examples)
    if command == "enable-provider":
        return _enable_cloud_provider(
            args.config,
            provider=args.provider,
            model=args.model,
            route=args.route,
            api_key_env=args.api_key_env,
            paid=args.paid,
        )

    config = load_config(args.config)
    if getattr(args, "host", None):
        config.host = args.host
    if getattr(args, "port", None):
        config.port = args.port
    config.ensure_dirs()

    if command == "agents":
        rows = _agent_rows(config)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            _print_table(rows, ["name", "provider", "model", "enabled", "free", "allowed", "tokens", "status"])
        return 0
    if command == "doctor":
        report = _doctor_report(config, args.config)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _print_doctor(report)
        return 0
    if command == "local-models":
        report = _local_models_report(config)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _print_local_models(report)
        return 0
    if command == "serve":
        if getattr(args, "watch_inbox", False):
            processor = InboxProcessor(config)
            thread = threading.Thread(target=processor.watch, daemon=True)
            thread.start()
        serve(config)
        return 0
    if command == "watch":
        InboxProcessor(config).watch(interval_seconds=args.interval)
        return 0
    if command == "once":
        outputs = InboxProcessor(config).process_once()
        for output in outputs:
            print(output)
        return 0
    if command == "agent":
        if not args.allow_cloud:
            config.free_only = True
        payload: dict[str, Any] = {
            "session_id": f"cli-agent-{uuid.uuid4().hex}",
            "mode": "agent",
            "route": args.route,
            "task": " ".join(args.task),
            "agent_max_steps": args.max_steps,
        }
        if args.allow_shell_tools:
            payload["allow_shell_tools"] = True
        request = request_from_payload(payload)
        try:
            response = AgentRunner(config, AgentRouter(config)).run(request)
        except RouterError as exc:
            _print_route_error(exc)
            return 1
        print(json.dumps(response.to_native_dict(), indent=2, ensure_ascii=False))
        return 0
    if command == "chat":
        if not args.allow_cloud:
            config.free_only = True
        return _chat(config, args)
    if command == "route":
        payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
        request = request_from_payload(payload, api_shape=args.api_shape)
        router = AgentRouter(config)
        try:
            if args.agent_mode or _wants_agent_mode(payload):
                response = AgentRunner(config, router).run(request)
            else:
                response = router.route(request)
        except RouterError as exc:
            _print_route_error(exc)
            return 1
        print(json.dumps(response.to_native_dict(), indent=2, ensure_ascii=False))
        return 0
    parser.error(f"Unknown command {command!r}")
    return 2


def _chat(config: Any, args: argparse.Namespace) -> int:
    session_id = args.session_id or f"cli-chat-{uuid.uuid4().hex}"
    route = args.route
    router = AgentRouter(config)
    runner = AgentRunner(config, router)

    print("Agent-Hub Codex Chat")
    print(f"Session: {session_id}")
    print(f"Route: {route}")
    print("Commands: /exit, /clear, /route <name>, /status")
    print()

    while True:
        try:
            prompt = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not prompt:
            continue
        lowered = prompt.lower()
        if lowered in {"/exit", "/quit", "exit", "quit"}:
            return 0
        if lowered == "/clear":
            session_id = f"cli-chat-{uuid.uuid4().hex}"
            print(f"Started a new session: {session_id}")
            continue
        if lowered == "/status":
            print(f"Session: {session_id}")
            print(f"Route: {route}")
            print(f"free_only: {config.free_only}")
            print(f"allow_shell_tools: {args.allow_shell_tools}")
            continue
        if lowered.startswith("/route "):
            route = prompt.split(None, 1)[1].strip()
            print(f"Route: {route}")
            continue

        payload: dict[str, Any] = {
            "session_id": session_id,
            "mode": "route" if args.no_agent else "agent",
            "route": route,
            "task": _codex_chat_task(prompt),
            "use_session_history": True,
            "agent_max_steps": args.max_steps,
            "workspace_dir": str(config.workspace_dir),
            "metadata": {"source": "cli-chat"},
        }
        if args.allow_shell_tools:
            payload["allow_shell_tools"] = True
        request = request_from_payload(payload)
        try:
            response = router.route(request) if args.no_agent else runner.run(request)
        except RouterError as exc:
            _print_route_error(exc)
            print()
            continue

        print()
        print(f"codex> {response.text}")
        print()


def _codex_chat_task(prompt: str) -> str:
    return "\n".join(
        [
            "Chat with the user as a careful Codex-style coding assistant.",
            "Be conversational and concise. Use workspace tools when inspection or edits are useful.",
            "For direct replies, use the final action; never invent other action names.",
            "",
            prompt,
        ]
    )


def _wants_agent_mode(payload: dict) -> bool:
    hub_options = payload.get("agent_hub")
    if isinstance(hub_options, dict) and "agent_mode" in hub_options:
        return bool(hub_options["agent_mode"])
    if "agent_mode" in payload:
        return bool(payload["agent_mode"])
    mode = payload.get("mode")
    return isinstance(mode, str) and mode.lower() == "agent"


def _enable_cloud_provider(
    path: str,
    *,
    provider: str,
    model: str,
    route: str,
    api_key_env: str | None,
    paid: bool = False,
) -> int:
    config_path = Path(path)
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print(f"{config_path} does not contain a JSON object.")
            return 1
    else:
        data = config_to_dict(free_local_config())
        _merge_agent_examples(data, _cloud_example_agents())

    if paid:
        data["free_only"] = False
    _ensure_cloud_routes(data)

    agent_name, provider_name, default_env = _cloud_provider_defaults(provider)
    agents = data.setdefault("agents", [])
    if not isinstance(agents, list):
        print("Config field 'agents' must be a list.")
        return 1

    agent = next(
        (item for item in agents if isinstance(item, dict) and item.get("name") == agent_name),
        None,
    )
    if agent is None:
        agent = {
            "name": agent_name,
            "provider": provider_name,
            "free": not paid,
            "max_tokens": 4096,
        }
        agents.append(agent)

    agent.update(
        {
            "provider": provider_name,
            "model": model,
            "enabled": True,
            "free": not paid,
            "api_key_env": api_key_env or default_env,
        }
    )

    _move_agent_to_front(data, route, agent_name)
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Enabled {agent_name} on route {route} in {config_path}.")
    print(f"Set {agent['api_key_env']} before starting Agent-Hub.")
    if not paid:
        print("Provider is marked free=true, so it remains eligible while free_only is enabled.")
    print("Restart the Agent-Hub server if it is already running.")
    return 0


def _cloud_provider_defaults(provider: str) -> tuple[str, str, str]:
    normalized = provider.lower()
    if normalized in {"openai", "codex"}:
        return "codex", "openai", "OPENAI_API_KEY"
    if normalized == "chatgpt":
        return "chatgpt", "chatgpt", "OPENAI_API_KEY"
    if normalized in {"claude", "anthropic"}:
        return "claude", "claude", "ANTHROPIC_API_KEY"
    return "gemini", "gemini", "GEMINI_API_KEY"


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


def _print_route_error(error: RouterError) -> None:
    print(f"Agent-Hub route failed: {error}")
    if error.failover:
        print("Failover:")
        for event in error.failover:
            print(f"- {event.agent}: {event.reason}")


def _init_config(path: str, force: bool = False, with_cloud_examples: bool = False) -> int:
    config_path = Path(path)
    if config_path.exists() and not force:
        print(f"{config_path} already exists. Use --force to overwrite it.")
        return 1

    data = config_to_dict(free_local_config())
    if with_cloud_examples:
        _merge_agent_examples(data, _cloud_example_agents())
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {config_path}")
    print("Set cloud provider API keys, or pull a local control model, then run: agent-hub doctor")
    return 0


def _cloud_example_agents() -> list[dict[str, Any]]:
    return [
        {
            "name": "chatgpt",
            "provider": "chatgpt",
            "model": "gpt-4o-mini",
            "enabled": True,
            "free": True,
            "api_key_env": "OPENAI_API_KEY",
            "max_tokens": 4096,
            "context_window": 128000,
        },
        {
            "name": "gemini",
            "provider": "gemini",
            "model": "gemini-2.0-flash",
            "enabled": True,
            "free": True,
            "api_key_env": "GEMINI_API_KEY",
            "max_tokens": 4096,
            "context_window": 1000000,
        },
        {
            "name": "claude",
            "provider": "claude",
            "model": "claude-3-5-haiku-latest",
            "enabled": True,
            "free": True,
            "api_key_env": "ANTHROPIC_API_KEY",
            "max_tokens": 4096,
            "context_window": 200000,
        },
        {
            "name": "gemma-local",
            "provider": "gemma",
            "model": "your-gemma-model",
            "enabled": False,
            "free": True,
            "base_url": "http://127.0.0.1:8000",
            "max_tokens": 4096,
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


def _agent_rows(config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for agent in config.agents.values():
        normalized = normalize_provider(agent.provider)
        free = is_free_agent(agent)
        allowed = agent.enabled and (free or not config.free_only)
        status = _agent_status(agent, free=free, allowed=allowed, normalized=normalized)
        rows.append(
            {
                "name": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "enabled": agent.enabled,
                "free": free,
                "allowed": allowed,
                "tokens": agent.context_window or "?",
                "status": status,
                "base_url": agent.base_url,
                "api_key_env": agent.api_key_env,
            }
        )
    return rows


def _agent_status(agent: Any, *, free: bool, allowed: bool, normalized: str) -> str:
    if not agent.enabled:
        return "disabled"
    if not allowed:
        return "skipped by free_only"
    if normalized in {"openai", "anthropic", "gemini"} and not agent.resolved_api_key:
        return f"missing {agent.api_key_env or 'api key'}"
    if normalized == "openai-compatible":
        if not agent.base_url:
            return "missing base_url"
        return "configured"
    return "ready"


def _doctor_report(config: Any, config_path: str) -> dict[str, Any]:
    rows = _agent_rows(config)
    warnings: list[str] = []
    usable = [
        row
        for row in rows
        if row["allowed"] and row["status"] in {"ready", "configured"}
    ]
    if config.free_only:
        warnings.append("free_only is enabled; paid providers are skipped unless an agent is marked free=true.")
    if not usable:
        warnings.append("No enabled ready agents are currently available.")
    for row in rows:
        if row["enabled"] and row["status"].startswith("missing"):
            warnings.append(f"{row['name']}: {row['status']}.")
        if row["enabled"] and row["status"] == "configured":
            warnings.append(
                f"{row['name']}: config looks usable; first request will confirm {row['base_url']} is running."
            )

    return {
        "config": config_path,
        "host": config.host,
        "port": config.port,
        "free_only": config.free_only,
        "default_route": config.default_route,
        "agents": rows,
        "warnings": warnings,
    }


def _print_doctor(report: dict[str, Any]) -> None:
    print(f"Config: {report['config']}")
    print(f"Server: http://{report['host']}:{report['port']}")
    print(f"free_only: {report['free_only']}")
    print(f"default_route: {', '.join(report['default_route'])}")
    print()
    _print_table(report["agents"], ["name", "provider", "model", "enabled", "free", "allowed", "tokens", "status"])
    if report["warnings"]:
        print()
        print("Notes:")
        for warning in report["warnings"]:
            print(f"- {warning}")


def _local_models_report(config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for agent in config.agents.values():
        if normalize_provider(agent.provider) != "openai-compatible" or not is_free_agent(agent):
            continue
        row = {
            "name": agent.name,
            "base_url": agent.base_url,
            "configured_model": agent.model,
            "online": False,
            "models": [],
            "error": "",
        }
        if not agent.base_url:
            row["error"] = "missing base_url"
            rows.append(row)
            continue
        try:
            models = _fetch_openai_models(agent.base_url, timeout=3.0)
            row["online"] = True
            row["models"] = models
            row["configured_model_available"] = agent.model in models
        except Exception as exc:
            row["error"] = str(exc)
            row["configured_model_available"] = False
        rows.append(row)
    return rows


def _fetch_openai_models(base_url: str, timeout: float) -> list[str]:
    url = _openai_url(base_url, "/v1/models")
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason if hasattr(exc, "reason") else exc)) from exc
    data = json.loads(text) if text else {}
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return sorted(
        item["id"]
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )


def _openai_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        return f"{base}{path[3:]}"
    return f"{base}{path}"


def _print_local_models(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No free local OpenAI-compatible agents are configured.")
        return
    print("Free local model endpoints:")
    for row in rows:
        status = "online" if row["online"] else "offline"
        print(f"- {row['name']} ({status}) {row['base_url']} model={row['configured_model']}")
        if row["online"]:
            models = row.get("models", [])
            if models:
                print(f"  available: {', '.join(models[:10])}")
                if len(models) > 10:
                    print(f"  ...and {len(models) - 10} more")
            else:
                print("  available: endpoint returned no model IDs")
        elif row.get("error"):
            print(f"  error: {row['error']}")


def _print_table(rows: list[dict[str, Any]], columns: list[str]) -> None:
    if not rows:
        print("No agents configured.")
        return
    widths = {
        column: max(len(column), *(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }
    print("  ".join(column.ljust(widths[column]) for column in columns))
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print("  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))
