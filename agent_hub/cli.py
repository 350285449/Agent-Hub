from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Any
from typing import Sequence

from .agent_runner import AgentRunner
from .config import config_to_dict, free_local_config, is_free_agent, load_config, normalize_provider
from .inbox import InboxProcessor
from .payloads import request_from_payload
from .router import AgentRouter
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
        help="Also add disabled ChatGPT, Gemini, Claude, and Gemma examples.",
    )

    agents_parser = subparsers.add_parser("agents", help="List configured agents and routing status.")
    agents_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    doctor_parser = subparsers.add_parser("doctor", help="Explain config and provider readiness.")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

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
    if command == "route":
        payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
        request = request_from_payload(payload, api_shape=args.api_shape)
        router = AgentRouter(config)
        if args.agent_mode or _wants_agent_mode(payload):
            response = AgentRunner(config, router).run(request)
        else:
            response = router.route(request)
        print(json.dumps(response.to_native_dict(), indent=2, ensure_ascii=False))
        return 0
    parser.error(f"Unknown command {command!r}")
    return 2


def _wants_agent_mode(payload: dict) -> bool:
    hub_options = payload.get("agent_hub")
    if isinstance(hub_options, dict) and "agent_mode" in hub_options:
        return bool(hub_options["agent_mode"])
    if "agent_mode" in payload:
        return bool(payload["agent_mode"])
    mode = payload.get("mode")
    return isinstance(mode, str) and mode.lower() == "agent"


def _init_config(path: str, force: bool = False, with_cloud_examples: bool = False) -> int:
    config_path = Path(path)
    if config_path.exists() and not force:
        print(f"{config_path} already exists. Use --force to overwrite it.")
        return 1

    data = config_to_dict(free_local_config())
    if with_cloud_examples:
        data["agents"].extend(_cloud_example_agents())
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {config_path}")
    print("Edit custom-local.base_url/model, then run: agent-hub doctor")
    return 0


def _cloud_example_agents() -> list[dict[str, Any]]:
    return [
        {
            "name": "chatgpt",
            "provider": "chatgpt",
            "model": "your-openai-model",
            "enabled": False,
            "free": False,
            "api_key_env": "OPENAI_API_KEY",
            "max_tokens": 4096,
            "context_window": 128000,
        },
        {
            "name": "gemini",
            "provider": "gemini",
            "model": "your-gemini-model",
            "enabled": False,
            "free": False,
            "api_key_env": "GEMINI_API_KEY",
            "max_tokens": 4096,
            "context_window": 1000000,
        },
        {
            "name": "claude",
            "provider": "claude",
            "model": "your-claude-model",
            "enabled": False,
            "free": False,
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
        warnings.append("free_only is enabled; cloud providers run only if you mark an agent free=true.")
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
