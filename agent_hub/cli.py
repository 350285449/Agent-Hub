from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import threading
import time
import tomllib
import uuid
import urllib.error
import urllib.request
import zipfile
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
from .config_migration import migrate_config_file
from .context import request_context_diagnostics
from .evaluation import BenchmarkRunner, ProviderScoreStore, default_benchmark_tasks
from .inbox import InboxProcessor
from .observability import STREAM_FILES, recent_events
from .payloads import request_from_payload
from .provider_presets import (
    FREE_PROVIDER_PRESETS,
    agent_dict_from_preset,
    preset_rows,
    provider_metadata,
    provider_metadata_rows,
)
from .core.router import AgentRouter, RouterError
from .team_agent_runner import TeamAgentRunner
from .version import backend_version


ROUTING_PRESETS: dict[str, dict[str, Any]] = {
    "cheap-local": {
        "name": "cheap-local",
        "label": "Cheap local mode",
        "description": "Prefer free local or user-controlled endpoints.",
        "selector": "cheap-local",
        "free_only": True,
        "approval_mode": "ask",
        "free_first": True,
    },
    "best-coding": {
        "name": "best-coding",
        "label": "Best coding mode",
        "description": "Prefer tool-capable agents with strong coding scores.",
        "selector": "best-coding",
        "free_only": False,
        "approval_mode": "ask",
        "free_first": False,
    },
    "private": {
        "name": "private",
        "label": "Private mode",
        "description": "Use local/private endpoints only.",
        "selector": "private",
        "free_only": True,
        "approval_mode": "ask",
        "free_first": True,
    },
    "fastest": {
        "name": "fastest",
        "label": "Fastest mode",
        "description": "Prefer the lowest-latency configured agents.",
        "selector": "fastest",
        "free_only": False,
        "approval_mode": "ask",
        "free_first": False,
    },
    "fallback-safe": {
        "name": "fallback-safe",
        "label": "Fallback-safe mode",
        "description": "Keep broad fallback enabled while using safe approvals.",
        "selector": "fallback-safe",
        "free_only": False,
        "approval_mode": "safe",
        "free_first": True,
    },
}

LOCAL_PROVIDER_TYPES = {
    "echo",
    "local-research",
    "lm-studio",
    "localai",
    "llama-cpp",
    "ollama",
    "ollama-local",
    "vllm",
}
LOCAL_URL_PREFIXES = (
    "http://127.0.0.1",
    "https://127.0.0.1",
    "http://localhost",
    "https://localhost",
    "http://[::1]",
    "https://[::1]",
)
SENSITIVE_KEY_FRAGMENTS = (
    "apikey",
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
    "xapikey",
    "x-api-key",
)


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
    doctor_parser.add_argument("--providers", action="store_true", help="Include known provider metadata.")

    inspect_parser = subparsers.add_parser(
        "inspect-request",
        help="Normalize a request payload and show context-preservation diagnostics.",
    )
    inspect_parser.add_argument("path", nargs="?", help="JSON file to inspect. Reads stdin when omitted.")
    inspect_parser.add_argument(
        "--api-shape",
        choices=["native", "openai-chat", "openai-responses", "anthropic-messages"],
        default="openai-chat",
        help="Compatibility shape used to normalize the payload.",
    )
    inspect_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    migrate_parser = subparsers.add_parser(
        "migrate-config",
        help="Detect deprecated config keys and optionally write a migrated config.",
    )
    migrate_parser.add_argument("--write", action="store_true", help="Write the migrated config.")
    migrate_parser.add_argument("--output", help="Write migrated config to a different path.")
    migrate_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    health_parser = subparsers.add_parser("health", help="Show live provider health and best route candidates.")
    health_parser.add_argument("--route", default="cloud-agent", help="Route to summarize.")
    health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    metrics_parser = subparsers.add_parser("metrics", help="Show persisted provider metrics and failover history.")
    metrics_parser.add_argument("--route", default="cloud-agent", help="Route to summarize.")
    metrics_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    local_models_parser = subparsers.add_parser(
        "local-models",
        help="Probe free local OpenAI-compatible model servers.",
    )
    local_models_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    recommend_parser = subparsers.add_parser(
        "recommend",
        help="Suggest the best configured model for a task without calling a provider.",
    )
    recommend_parser.add_argument("prompt", nargs="*", default=[""], help="Task or prompt to score.")
    recommend_parser.add_argument("--route", default="cloud-agent", help="Route to score.")
    recommend_parser.add_argument("--limit", type=int, default=5, help="Number of suggestions.")
    recommend_parser.add_argument(
        "--prefer",
        choices=["balanced", "coding", "reasoning", "speed"],
        default="balanced",
        help="Recommendation bias.",
    )
    recommend_parser.add_argument(
        "--needs-tools",
        action="store_true",
        help="Prefer models with tool/function-call support.",
    )
    recommend_parser.add_argument(
        "--include-unavailable",
        action="store_true",
        help="Include disabled, cooled down, or skipped agents with reasons.",
    )
    recommend_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    providers_parser = subparsers.add_parser("providers", help="List known provider types.")
    providers_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    presets_parser = subparsers.add_parser("presets", help="List provider and routing presets.")
    presets_parser.add_argument("action", nargs="?", choices=["apply"], help="Apply a routing preset.")
    presets_parser.add_argument("preset_name", nargs="?", help="Preset to apply.")
    presets_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    add_provider_parser = subparsers.add_parser(
        "add-provider",
        help="Add or update a provider/model agent in the config file.",
    )
    add_provider_parser.add_argument("provider", help="Provider type, for example groq or openrouter.")
    add_provider_parser.add_argument("--model", required=True, help="Provider model ID to use.")
    add_provider_parser.add_argument("--name", help="Agent name to write into the config.")
    add_provider_parser.add_argument("--base-url", help="Override provider base URL.")
    add_provider_parser.add_argument("--api-key-env", help="Environment variable containing the API key.")
    add_provider_parser.add_argument("--route", default="cloud-agent", help="Route to prepend this agent to.")
    add_provider_parser.add_argument("--enabled", action="store_true", help="Enable the agent immediately.")
    add_provider_parser.add_argument("--paid", action="store_true", help="Mark provider free=false.")

    add_presets_parser = subparsers.add_parser(
        "add-free-presets",
        help="Merge editable free cloud provider presets into the config.",
    )
    add_presets_parser.add_argument("--enable", action="store_true", help="Enable added presets immediately.")
    add_presets_parser.add_argument("--route", default="cloud-agent", help="Route to append presets to.")

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
    _add_agent_runtime_flags(agent_parser)
    agent_parser.add_argument(
        "--allow-shell-tools",
        action="store_true",
        help="Allow the agent to run local shell commands.",
    )
    agent_parser.add_argument(
        "--confirm-shell-tools",
        action="store_true",
        help="Ask before each shell command is executed.",
    )
    agent_parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="Respect config free_only=false. By default this command forces free_only=true.",
    )

    group_agent_parser = subparsers.add_parser("group-agent", help="Run the collaborative team coding agent.")
    group_agent_parser.add_argument("task", nargs="+", help="Task for the agent team.")
    group_agent_parser.add_argument("--route", default="cloud-agent", help="Route to use for team model calls.")
    group_agent_parser.add_argument("--plan-candidates", type=int, default=1, help="Number of planner candidates.")
    group_agent_parser.add_argument("--max-steps", type=int, default=20, help="Maximum coder tool steps.")
    _add_agent_runtime_flags(group_agent_parser)
    group_agent_parser.add_argument(
        "--allow-shell-tools",
        action="store_true",
        help="Allow the agent team to run local shell commands.",
    )
    group_agent_parser.add_argument(
        "--confirm-shell-tools",
        action="store_true",
        help="Ask before each shell command is executed.",
    )
    group_agent_parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="Respect config free_only=false. By default this command forces free_only=true.",
    )

    benchmark_parser = subparsers.add_parser("benchmark", help="Run a small route latency benchmark.")
    benchmark_parser.add_argument("--route", default="cloud-agent")
    benchmark_parser.add_argument("--prompt", default="Reply with one short sentence.")
    benchmark_parser.add_argument("--json", action="store_true")

    eval_parser = subparsers.add_parser("eval", help="Evaluate configured providers and store provider scores.")
    eval_parser.add_argument("--route", default="cloud-agent")
    eval_parser.add_argument("--json", action="store_true")
    eval_parser.add_argument("--limit", type=int, default=6, help="Maximum benchmark tasks to run.")

    route_test_parser = subparsers.add_parser("route-test", help="Route a prompt and show selected provider.")
    route_test_parser.add_argument("prompt", nargs="*", default=["hello"])
    route_test_parser.add_argument("--route", default="cloud-agent")
    route_test_parser.add_argument("--json", action="store_true")

    export_logs_parser = subparsers.add_parser("export-logs", help="Export recent diagnostic logs.")
    export_logs_parser.add_argument("--format", choices=["json", "markdown", "zip"], default="json")
    export_logs_parser.add_argument("--output", help="Output path. Defaults to stdout for json/markdown.")

    chat_parser = subparsers.add_parser("chat", help="Open an interactive Codex-style workspace chat.")
    chat_parser.add_argument("--route", default="cloud-agent", help="Route to use for chat turns.")
    chat_parser.add_argument("--session-id", help="Reuse an existing chat session id.")
    chat_parser.add_argument("--max-steps", type=int, default=20, help="Maximum agent tool steps per turn.")
    _add_agent_runtime_flags(chat_parser)
    chat_parser.add_argument(
        "--allow-shell-tools",
        action="store_true",
        help="Allow the chat agent to run local shell commands.",
    )
    chat_parser.add_argument(
        "--confirm-shell-tools",
        action="store_true",
        help="Ask before each shell command is executed.",
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
        choices=["native", "openai-chat", "openai-responses", "anthropic-messages"],
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
    if command == "add-provider":
        return _add_provider(
            args.config,
            provider_type=args.provider,
            model=args.model,
            name=args.name,
            route=args.route,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
            enabled=args.enabled,
            paid=args.paid,
        )
    if command == "add-free-presets":
        return _add_free_presets(
            args.config,
            route=args.route,
            enabled=args.enable,
        )
    if command == "migrate-config":
        return _migrate_config(
            args.config,
            write=args.write,
            output=args.output,
            as_json=args.json,
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
        if args.providers:
            report["provider_types"] = provider_metadata_rows()
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _print_doctor(report)
        return 0
    if command == "health":
        report = _health_report(config, route=args.route, include_history=False)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _print_health(report)
        return 0
    if command == "metrics":
        report = _health_report(config, route=args.route, include_history=True)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _print_metrics(report)
        return 0
    if command == "providers":
        rows = provider_metadata_rows()
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            _print_table(rows, ["provider_type", "display_name", "base_url", "api_key_env", "free"])
        return 0
    if command == "presets":
        if args.action == "apply":
            return _apply_routing_preset(args.config, args.preset_name, as_json=args.json)
        provider_rows = preset_rows()
        routing_rows = _routing_preset_rows()
        if args.json:
            print(
                json.dumps(
                    {
                        "provider_presets": provider_rows,
                        "routing_presets": routing_rows,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print("Provider presets:")
            _print_table(provider_rows, ["name", "provider_type", "model", "free", "enabled", "context_window"])
            print()
            print("Routing presets:")
            _print_table(routing_rows, ["name", "label", "free_only", "approval_mode", "description"])
        return 0
    if command == "export-logs":
        return _export_logs(config, output_format=args.format, output_path=args.output)
    if command == "local-models":
        report = _local_models_report(config)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _print_local_models(report)
        return 0
    if command == "inspect-request":
        return _inspect_request(
            args.path,
            api_shape=args.api_shape,
            as_json=args.json,
        )
    if command == "recommend":
        return _recommend(
            config,
            route=args.route,
            prompt=" ".join(args.prompt),
            limit=args.limit,
            prefer=args.prefer,
            needs_tools=args.needs_tools,
            include_unavailable=args.include_unavailable,
            as_json=args.json,
        )
    if command == "serve":
        if getattr(args, "watch_inbox", False):
            processor = InboxProcessor(config)
            thread = threading.Thread(target=processor.watch, daemon=True)
            thread.start()
        serve = getattr(__import__("agent_hub.server", fromlist=["serve"]), "serve")
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
        if args.allow_shell_tools or args.confirm_shell_tools:
            payload["allow_shell_tools"] = True
        if args.confirm_shell_tools:
            payload["shell_command_policy"] = "ask"
        _apply_agent_runtime_flags(payload, args)
        request = request_from_payload(payload)
        try:
            response = AgentRunner(config, AgentRouter(config)).run(
                request,
                shell_permission_callback=_shell_permission_prompt
                if args.confirm_shell_tools
                else None,
            )
        except RouterError as exc:
            _print_route_error(exc)
            return 1
        print(json.dumps(response.to_native_dict(), indent=2, ensure_ascii=False))
        return 0
    if command == "group-agent":
        if not args.allow_cloud:
            config.free_only = True
        payload = {
            "session_id": f"cli-team-{uuid.uuid4().hex}",
            "mode": "group-agent",
            "route": args.route,
            "task": " ".join(args.task),
            "agent_max_steps": args.max_steps,
            "coder_max_steps": args.max_steps,
            "group_agent": {"plan_candidates": args.plan_candidates},
        }
        if args.allow_shell_tools or args.confirm_shell_tools:
            payload["allow_shell_tools"] = True
        if args.confirm_shell_tools:
            payload["shell_command_policy"] = "ask"
        _apply_agent_runtime_flags(payload, args)
        request = request_from_payload(payload)
        try:
            response = TeamAgentRunner(config, AgentRouter(config)).run(
                request,
                shell_permission_callback=_shell_permission_prompt
                if args.confirm_shell_tools
                else None,
            )
        except RouterError as exc:
            _print_route_error(exc)
            return 1
        print(json.dumps(response.to_native_dict(include_routing_details=True), indent=2, ensure_ascii=False))
        return 0
    if command == "benchmark":
        return _benchmark(config, route=args.route, prompt=args.prompt, as_json=args.json)
    if command == "eval":
        return _eval_providers(config, route=args.route, limit=args.limit, as_json=args.json)
    if command == "route-test":
        return _route_test(config, route=args.route, prompt=" ".join(args.prompt), as_json=args.json)
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


def _add_agent_runtime_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fast-write-finalize",
        action="store_true",
        help="Finish immediately after the first successful file edit.",
    )
    patch_group = parser.add_mutually_exclusive_group()
    patch_group.add_argument(
        "--prefer-multi-file-patches",
        dest="prefer_multi_file_patches",
        action="store_true",
        default=None,
        help="Prefer grouped apply_patch edits for implementation, tests, docs, and config.",
    )
    patch_group.add_argument(
        "--no-prefer-multi-file-patches",
        dest="prefer_multi_file_patches",
        action="store_false",
        help="Allow single-file edit tools when otherwise permitted.",
    )
    parser.add_argument(
        "--context-change-bar",
        choices=["off", "light", "strict"],
        help="Control how aggressively the agent refreshes repository context before edits.",
    )
    parser.add_argument(
        "--context-change-threshold",
        type=int,
        help="Changed-file count that triggers a context refresh before more edits.",
    )
    parser.add_argument(
        "--validation-mode",
        choices=["off", "basic", "strict"],
        help="Validation mode after agent edits.",
    )
    parser.add_argument(
        "--no-auto-validate",
        action="store_true",
        help="Disable automatic validation after file edits.",
    )
    parser.add_argument(
        "--validation-command",
        action="append",
        default=[],
        help="Additional validation command to run after edits. Can be repeated.",
    )


def _apply_agent_runtime_flags(payload: dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "fast_write_finalize", False):
        payload["fast_write_finalize"] = True
    prefer_multi_file_patches = getattr(args, "prefer_multi_file_patches", None)
    if prefer_multi_file_patches is not None:
        payload["prefer_multi_file_patches"] = bool(prefer_multi_file_patches)
    context_change_bar = getattr(args, "context_change_bar", None)
    if context_change_bar:
        payload["context_change_bar_mode"] = context_change_bar
        payload["context_change_bar_enabled"] = context_change_bar != "off"
    threshold = getattr(args, "context_change_threshold", None)
    if threshold is not None:
        payload["context_change_bar_threshold"] = max(0, int(threshold))
    if getattr(args, "validation_mode", None):
        payload["validation_mode"] = args.validation_mode
    if getattr(args, "no_auto_validate", False):
        payload["auto_validate_after_edits"] = False
    validation_commands = [
        str(command)
        for command in getattr(args, "validation_command", []) or []
        if str(command).strip()
    ]
    if validation_commands:
        payload["validation_commands"] = validation_commands


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
            print(f"shell_command_policy: {'ask' if args.confirm_shell_tools else config.shell_command_policy}")
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
        if args.allow_shell_tools or args.confirm_shell_tools:
            payload["allow_shell_tools"] = True
        if args.confirm_shell_tools:
            payload["shell_command_policy"] = "ask"
        _apply_agent_runtime_flags(payload, args)
        request = request_from_payload(payload)
        try:
            response = (
                router.route(request)
                if args.no_agent
                else runner.run(
                    request,
                    shell_permission_callback=_shell_permission_prompt
                    if args.confirm_shell_tools
                    else None,
                )
            )
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
    if route in {"cloud-agent", "hybrid-agent"}:
        data["cloud_control_selection"] = {
            "route_mode": "api-key",
            "api_key_models_enabled": True,
        }
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Enabled {agent_name} on route {route} in {config_path}.")
    print(f"Set {agent['api_key_env']} before starting Agent-Hub.")
    if not paid:
        print("Provider is marked free=true, so it remains eligible while free_only is enabled.")
    print("Restart the Agent-Hub server if it is already running.")
    return 0


def _add_provider(
    path: str,
    *,
    provider_type: str,
    model: str,
    name: str | None,
    route: str,
    base_url: str | None,
    api_key_env: str | None,
    enabled: bool,
    paid: bool,
) -> int:
    config_path = Path(path)
    data = _load_or_default_config_dict(config_path)
    metadata = provider_metadata(provider_type)
    normalized_provider_type = provider_type.lower()
    agent_name = name or _agent_name_from_provider_model(normalized_provider_type, model)
    provider_name = metadata.provider if metadata else "openai-compatible"
    agent = {
        "name": agent_name,
        "provider": provider_name,
        "provider_type": normalized_provider_type,
        "model": model,
        "enabled": enabled,
        "free": not paid,
        "api_key_env": api_key_env or (metadata.api_key_env if metadata else None),
        "base_url": base_url or (metadata.base_url if metadata else None),
        "headers": dict(metadata.default_headers) if metadata else {},
        "chat_completions_path": metadata.chat_completions_path if metadata else None,
        "timeout_seconds": 120,
        "cooldown_seconds": 120,
        "supports_tools": metadata.supports_tools if metadata else None,
        "supports_json": metadata.supports_json if metadata else None,
        "supports_streaming": metadata.supports_streaming if metadata else None,
        "supports_vision": metadata.supports_vision if metadata else None,
        "supports_function_calling": metadata.supports_function_calling if metadata else None,
    }
    agent = _drop_empty(agent)
    _upsert_agent(data, agent)
    _ensure_cloud_routes(data)
    _move_agent_to_front(data, route, agent_name)
    if paid:
        data["free_only"] = False
    _write_config_dict(config_path, data)
    print(f"Added {agent_name} ({provider_type}) to {config_path}.")
    if agent.get("api_key_env"):
        print(f"Set {agent['api_key_env']} before enabling or routing to it.")
    if not agent.get("base_url"):
        print("No base_url is known for this provider type; edit the config before enabling it.")
    return 0


def _add_free_presets(path: str, *, route: str, enabled: bool) -> int:
    config_path = Path(path)
    data = _load_or_default_config_dict(config_path)
    _ensure_cloud_routes(data)
    added: list[str] = []
    for preset in FREE_PROVIDER_PRESETS:
        agent = agent_dict_from_preset(preset, enabled=enabled)
        if _upsert_agent(data, agent, replace_existing=False):
            added.append(agent["name"])
        _append_agent_to_route(data, route, agent["name"])
    _write_config_dict(config_path, data)
    print(f"Merged {len(added)} free provider preset(s) into {config_path}.")
    if added:
        print("Added: " + ", ".join(added))
    print("Preset model IDs are editable; if a free model disappears, change or disable that agent.")
    return 0


def _routing_preset_rows() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "label": preset["label"],
            "free_only": preset["free_only"],
            "approval_mode": preset["approval_mode"],
            "description": preset["description"],
        }
        for name, preset in ROUTING_PRESETS.items()
    ]


def _apply_routing_preset(path: str, preset_name: str | None, *, as_json: bool) -> int:
    preset = _routing_preset_from_name(preset_name)
    if preset is None:
        known = ", ".join(ROUTING_PRESETS)
        if preset_name:
            print(f"Unknown routing preset {preset_name!r}. Known presets: {known}.")
        else:
            print(f"Choose a routing preset: {known}.")
        return 2

    config_path = Path(path)
    data = _load_or_default_config_dict(config_path)
    agent_names = _select_routing_preset_agents(data, preset)
    if not agent_names:
        print("No configured agents are available for that preset.")
        return 1

    data["default_route"] = agent_names
    data["free_only"] = bool(preset["free_only"])
    data["approval_mode"] = str(preset["approval_mode"])
    routing = data.setdefault("routing", {})
    if isinstance(routing, dict):
        routing["auto_failover"] = True
        routing["free_first"] = bool(preset["free_first"])
        if preset["name"] == "fallback-safe":
            routing["max_provider_attempts"] = max(3, int(routing.get("max_provider_attempts") or 3))
    if preset["name"] == "private":
        data["auto_enable_available_providers"] = False

    for route_name in ("cloud-agent", "coding", "hybrid-agent"):
        _replace_route_agents(data, route_name, agent_names)
    if preset["name"] in {"cheap-local", "private"}:
        _replace_route_agents(data, "local-agent", agent_names)

    _write_config_dict(config_path, data)
    result = {
        "preset": preset["name"],
        "config": str(config_path),
        "default_route": agent_names,
        "free_only": data["free_only"],
        "approval_mode": data["approval_mode"],
    }
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Applied {preset['label']} to {config_path}.")
        print("default_route: " + ", ".join(agent_names))
        print(f"free_only: {data['free_only']}")
        print(f"approval_mode: {data['approval_mode']}")
    return 0


def _routing_preset_from_name(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    key = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if key.endswith("-mode"):
        key = key[: -len("-mode")]
    return ROUTING_PRESETS.get(key)


def _select_routing_preset_agents(data: dict[str, Any], preset: dict[str, Any]) -> list[str]:
    raw_agents = data.get("agents", [])
    if not isinstance(raw_agents, list):
        return []
    agents = [agent for agent in raw_agents if isinstance(agent, dict) and isinstance(agent.get("name"), str)]
    enabled = [agent for agent in agents if _agent_enabled(agent)]
    candidates = enabled or agents
    selector = str(preset["selector"])

    if selector == "private":
        selected = [agent for agent in candidates if _agent_is_private(agent)]
    elif selector == "cheap-local":
        selected = [agent for agent in candidates if _agent_is_free(agent) and _agent_is_private(agent)]
    elif selector == "best-coding":
        selected = sorted(candidates, key=_coding_agent_rank, reverse=True)
    elif selector == "fastest":
        selected = sorted(candidates, key=_speed_agent_rank, reverse=True)
    elif selector == "fallback-safe":
        selected = sorted(candidates, key=_fallback_safe_agent_rank, reverse=True)
    else:
        selected = candidates

    if not selected:
        selected = sorted(candidates, key=_fallback_safe_agent_rank, reverse=True)
    names: list[str] = []
    for agent in selected:
        name = str(agent.get("name"))
        if name not in names:
            names.append(name)
    return names


def _replace_route_agents(data: dict[str, Any], route_name: str, agent_names: list[str]) -> None:
    routes = data.setdefault("routes", [])
    if not isinstance(routes, list):
        data["routes"] = routes = []
    route = next(
        (item for item in routes if isinstance(item, dict) and item.get("name") == route_name),
        None,
    )
    if route is None:
        route = {"name": route_name, "keywords": _default_route_keywords(route_name), "agents": []}
        routes.append(route)
    route["agents"] = list(agent_names)


def _default_route_keywords(route_name: str) -> list[str]:
    if route_name == "coding":
        return ["code", "bug", "fix", "refactor", "test", "repo"]
    if route_name == "local-agent":
        return ["agent", "workspace", "edit", "implement"]
    return []


def _agent_enabled(agent: dict[str, Any]) -> bool:
    return agent.get("enabled", True) is not False


def _agent_is_free(agent: dict[str, Any]) -> bool:
    return agent.get("free", True) is not False


def _agent_is_private(agent: dict[str, Any]) -> bool:
    provider_type = str(agent.get("provider_type") or "").lower()
    provider = str(agent.get("provider") or "").lower()
    name = str(agent.get("name") or "").lower()
    if provider_type == "ollama-cloud" or name.endswith("-cloud"):
        return False
    if provider_type in LOCAL_PROVIDER_TYPES or provider in LOCAL_PROVIDER_TYPES:
        return True
    base_url = str(agent.get("base_url") or "").lower()
    return base_url.startswith(LOCAL_URL_PREFIXES)


def _coding_agent_rank(agent: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        _safe_float(agent.get("coding_score")),
        1.0 if agent.get("supports_tools") or agent.get("supports_function_calling") else 0.0,
        _safe_float(agent.get("reasoning_score")),
        _safe_float(agent.get("priority")),
        _safe_float(agent.get("context_window")),
    )


def _speed_agent_rank(agent: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        _safe_float(agent.get("speed_score")),
        _safe_float(agent.get("priority")),
        1.0 if _agent_is_private(agent) else 0.0,
        _safe_float(agent.get("coding_score")),
    )


def _fallback_safe_agent_rank(agent: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        1.0 if _agent_is_free(agent) else 0.0,
        1.0 if _agent_is_private(agent) else 0.0,
        _safe_float(agent.get("priority")),
        _safe_float(agent.get("coding_score")),
        _safe_float(agent.get("speed_score")),
    )


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _export_logs(config: Any, *, output_format: str, output_path: str | None) -> int:
    bundle = _log_export_bundle(config)
    json_text = json.dumps(bundle, indent=2, ensure_ascii=False, default=str)
    markdown_text = _log_bundle_markdown(bundle)
    if output_format == "zip":
        path = Path(output_path or "agent-hub-debug-bundle.zip")
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("debug-bundle.json", json_text)
            archive.writestr("debug-bundle.md", markdown_text)
        print(f"Wrote {path}")
        return 0

    text = markdown_text if output_format == "markdown" else json_text
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path}")
    else:
        print(text)
    return 0


def _log_export_bundle(config: Any) -> dict[str, Any]:
    streams = {
        stream: [_redact_sensitive(event) for event in recent_events(config.state_dir, stream, limit=200)]
        for stream in STREAM_FILES
    }
    return {
        "object": "agent_hub.debug_bundle",
        "backend_version": backend_version(),
        "generated_at": time.time(),
        "state_dir": str(config.state_dir),
        "server": {"host": config.host, "port": config.port},
        "config": {
            "free_only": config.free_only,
            "approval_mode": config.approval_mode,
            "shell_command_policy": config.shell_command_policy,
            "cline_compatibility_mode": config.cline_compatibility_mode,
            "routes": [route.name for route in config.routes],
            "agents": sorted(config.agents),
        },
        "counts": {stream: len(events) for stream, events in streams.items()},
        "streams": streams,
    }


def _log_bundle_markdown(bundle: dict[str, Any]) -> str:
    lines = [
        "# Agent Hub Debug Bundle",
        "",
        f"- backend_version: {bundle.get('backend_version')}",
        f"- generated_at: {bundle.get('generated_at')}",
        f"- state_dir: {bundle.get('state_dir')}",
        "",
        "## Counts",
        "",
    ]
    counts = bundle.get("counts")
    if isinstance(counts, dict):
        for stream, count in sorted(counts.items()):
            lines.append(f"- {stream}: {count}")
    streams = bundle.get("streams")
    if isinstance(streams, dict):
        for stream, events in sorted(streams.items()):
            lines.extend(["", f"## {stream}", ""])
            if not isinstance(events, list) or not events:
                lines.append("No recent events.")
                continue
            for event in events[-10:]:
                lines.append("```json")
                lines.append(json.dumps(event, indent=2, ensure_ascii=False, default=str))
                lines.append("```")
    return "\n".join(lines) + "\n"


def _redact_sensitive(value: Any, key: str = "") -> Any:
    if _sensitive_key(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(item_key): _redact_sensitive(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive(item, key) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        lowered = stripped.lower()
        if lowered.startswith("bearer ") or lowered.startswith("sk-") or lowered.startswith("xox"):
            return "[redacted]"
    return value


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    collapsed = re.sub(r"[^a-z0-9]+", "", lowered)
    return any(fragment in lowered or fragment in collapsed for fragment in SENSITIVE_KEY_FRAGMENTS)


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


def _print_route_error(error: RouterError) -> None:
    print(f"Agent-Hub route failed: {error}")
    if getattr(error, "suggested_fix", None):
        print(f"Suggested fix: {error.suggested_fix}")
    if error.failover:
        print("Failover:")
        for event in error.failover:
            print(f"- {event.agent}: {event.reason}")


def _shell_permission_prompt(details: dict[str, Any]) -> bool:
    command = str(details.get("command") or "")
    cwd = str(details.get("cwd") or ".")
    timeout = details.get("timeout_seconds")
    print()
    print("Agent-Hub wants to run a shell command:")
    print(f"cwd: {cwd}")
    print(f"command: {command}")
    if timeout:
        print(f"timeout: {timeout}s")
    try:
        answer = input("Allow this command? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in {"y", "yes"}


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
                "provider_type": agent.provider_type,
                "model": agent.model,
                "enabled": agent.enabled,
                "free": free,
                "allowed": allowed,
                "tokens": agent.context_window or "?",
                "status": status,
                "base_url": agent.base_url,
                "api_key_env": agent.api_key_env,
                "priority": agent.priority,
                "coding_score": agent.coding_score,
                "reasoning_score": agent.reasoning_score,
                "speed_score": agent.speed_score,
            }
        )
    return rows


def _agent_status(agent: Any, *, free: bool, allowed: bool, normalized: str) -> str:
    if not agent.enabled:
        return "disabled"
    if not allowed:
        return "skipped by free_only"
    if agent.api_key_env and not agent.resolved_api_key and normalized in {"openai", "anthropic", "gemini", "openai-compatible"}:
        return f"missing {agent.api_key_env or 'api key'}"
    if normalized == "openai-compatible":
        if not agent.base_url:
            return "missing base_url"
        return "configured"
    return "ready"


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


def _doctor_report(config: Any, config_path: str) -> dict[str, Any]:
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

    local_servers = _local_endpoint_status()
    install_checks = _doctor_install_checks(config, config_path, rows)
    backend_status = _backend_reachability(config)
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
        "local_servers": local_servers,
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
    rows: list[dict[str, Any]] = []
    for name, url in endpoints:
        ok = False
        detail = ""
        try:
            with urllib.request.urlopen(url, timeout=0.6) as response:
                ok = 200 <= int(response.status) < 300
                detail = f"HTTP {response.status}"
        except Exception as exc:
            detail = str(exc)
        rows.append({"name": name, "url": url, "running": ok, "detail": detail})
    return rows


def _doctor_install_checks(config: Any, config_path: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        {
            "id": "providers_available",
            "category": "provider",
            "ok": any(row["allowed"] and row["status"] in {"ready", "configured"} for row in rows),
            "detail": ", ".join(row["name"] for row in rows if row["enabled"]) or "no enabled providers",
        },
    ]
    checks.extend(_dependency_checks(root))
    extension_manifest = root / "vscode-extension" / "package.json"
    checks.append(
        {
            "id": "vscode_extension_manifest",
            "category": "extension",
            "ok": extension_manifest.exists(),
            "detail": extension_manifest.as_posix(),
        }
    )
    snapshot = root / "vscode-extension" / "backend" / "SNAPSHOT.json"
    checks.append(
        {
            "id": "backend_snapshot",
            "category": "extension",
            "ok": snapshot.exists(),
            "detail": snapshot.as_posix() if snapshot.exists() else "run npm run prepare-backend before packaging",
        }
    )
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
    pyproject = root / "pyproject.toml"
    dependencies: list[str] = []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project") if isinstance(data, dict) else {}
        raw = project.get("dependencies") if isinstance(project, dict) else []
        dependencies = [str(item) for item in raw if isinstance(item, str)] if isinstance(raw, list) else []
    except (OSError, tomllib.TOMLDecodeError):
        return [
            {
                "id": "runtime_dependencies",
                "category": "dependency",
                "ok": False,
                "detail": "Could not read pyproject.toml",
            }
        ]
    if not dependencies:
        return [
            {
                "id": "runtime_dependencies",
                "category": "dependency",
                "ok": True,
                "detail": "No third-party runtime dependencies declared.",
            }
        ]
    rows: list[dict[str, Any]] = []
    for dependency in dependencies:
        module = _dependency_import_name(dependency)
        rows.append(
            {
                "id": f"dependency:{module}",
                "category": "dependency",
                "ok": importlib.util.find_spec(module) is not None,
                "detail": dependency,
            }
        )
    return rows


def _dependency_import_name(dependency: str) -> str:
    name = re.split(r"[<>=!~;\[]", dependency, maxsplit=1)[0].strip()
    return name.replace("-", "_")


def _backend_reachability(config: Any) -> dict[str, Any]:
    url = f"http://{config.host}:{config.port}/health"
    try:
        with urllib.request.urlopen(url, timeout=0.8) as response:
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
    if config.approval_mode in {"auto", "deny"}:
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


def _health_rows(provider_health: Any) -> list[dict[str, Any]]:
    if not isinstance(provider_health, dict):
        return []
    rows: list[dict[str, Any]] = []
    for name, health in provider_health.items():
        if not isinstance(health, dict):
            continue
        status = "ready"
        if health.get("cooldown_until", 0) and float(health.get("cooldown_until") or 0) > time.time():
            status = "cooldown"
        elif health.get("requests_remaining") == 0:
            status = "quota"
        elif health.get("quota_remaining") == 0:
            status = "quota"
        elif health.get("degraded"):
            status = "degraded"
        rows.append(
            {
                "name": name,
                "available": health.get("available"),
                "degraded": health.get("degraded"),
                "reliability": health.get("reliability_score"),
                "avg_ms": health.get("average_latency_ms"),
                "cooldown": _future_seconds(health.get("cooldown_until")),
                "quota": _unknown_if_none(health.get("quota_remaining")),
                "requests": _unknown_if_none(health.get("requests_remaining")),
                "status": status,
            }
        )
    return rows


def _metrics_rows(provider_health: Any) -> list[dict[str, Any]]:
    if not isinstance(provider_health, dict):
        return []
    rows: list[dict[str, Any]] = []
    for name, health in provider_health.items():
        if not isinstance(health, dict):
            continue
        rows.append(
            {
                "name": name,
                "success": health.get("success_count", 0),
                "failure": health.get("failure_count", 0),
                "timeouts": health.get("timeout_count", 0),
                "tool_ok": health.get("tool_call_success_count", 0),
                "tool_fail": health.get("tool_call_failure_count", 0),
                "avg_ms": health.get("average_latency_ms", 0),
                "stream_tps": health.get("streaming_tokens_per_second", 0),
                "tokens": f"{health.get('tokens_in', 0)}/{health.get('tokens_out', 0)}",
            }
        )
    return rows


def _recent_failover_events(provider_health: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for health in provider_health.values():
        if not isinstance(health, dict):
            continue
        for event in health.get("failover_events", []):
            if isinstance(event, dict):
                events.append(
                    {
                        "time": event.get("time", 0),
                        "age": _age_seconds(event.get("time")),
                        "agent": event.get("agent", ""),
                        "error_type": event.get("error_type", ""),
                        "status_code": event.get("status_code", ""),
                        "reason": str(event.get("reason", ""))[:100],
                    }
                )
    return sorted(events, key=lambda item: float(item.get("time") or 0), reverse=True)


def _future_seconds(timestamp: Any) -> str:
    try:
        value = float(timestamp or 0)
    except (TypeError, ValueError):
        return ""
    remaining = int(value - time.time())
    return f"{remaining}s" if remaining > 0 else ""


def _age_seconds(timestamp: Any) -> str:
    try:
        value = float(timestamp or 0)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return f"{max(0, int(time.time() - value))}s"


def _unknown_if_none(value: Any) -> Any:
    return "?" if value is None else value


def _health_report(config: Any, *, route: str, include_history: bool) -> dict[str, Any]:
    router = AgentRouter(config)
    request = request_from_payload(
        {
            "session_id": f"health-{uuid.uuid4().hex}",
            "route": route,
            "task": "Choose the best available model for an agent workflow.",
            "use_session_history": False,
            "record_session": False,
        }
    )
    recommendations = router.recommend(
        request,
        limit=8,
        needs_tools=True,
        include_unavailable=True,
    )
    health = router.health_snapshot(include_history=include_history)
    return {
        "status": "ok",
        "route": route,
        "provider_health": health,
        "recommendations": recommendations,
        "routing_decisions": [
            {
                "rank": row["rank"],
                "agent": row["agent"],
                "available": row["available"],
                "degraded": row["degraded"],
                "score": row["score"],
                "reason": row.get("unavailable_reason") or row.get("why"),
            }
            for row in recommendations
        ],
        "failover_history": _recent_failover_events(health),
    }


def _print_health(report: dict[str, Any]) -> None:
    print("Agent-Hub health")
    print(f"Route: {report['route']}")
    print()
    _print_table(
        _health_rows(report.get("provider_health", {})),
        ["name", "available", "degraded", "reliability", "avg_ms", "cooldown", "quota", "requests", "status"],
    )
    recommendations = report.get("recommendations")
    if isinstance(recommendations, list) and recommendations:
        print()
        print("Best candidates:")
        _print_table(
            recommendations[:5],
            ["rank", "agent", "provider", "model", "score", "available", "why"],
        )


def _print_metrics(report: dict[str, Any]) -> None:
    print("Agent-Hub metrics")
    print(f"Route: {report['route']}")
    print()
    _print_table(
        _metrics_rows(report.get("provider_health", {})),
        [
            "name",
            "success",
            "failure",
            "timeouts",
            "tool_ok",
            "tool_fail",
            "avg_ms",
            "stream_tps",
            "tokens",
        ],
    )
    history = report.get("failover_history")
    if isinstance(history, list) and history:
        print()
        print("Recent failover:")
        _print_table(history[:10], ["age", "agent", "error_type", "status_code", "reason"])


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


def _recommend(
    config: Any,
    *,
    route: str,
    prompt: str,
    limit: int,
    prefer: str,
    needs_tools: bool,
    include_unavailable: bool,
    as_json: bool,
) -> int:
    router = AgentRouter(config)
    request = request_from_payload(
        {
            "session_id": f"recommend-{uuid.uuid4().hex}",
            "route": route,
            "task": prompt or "Recommend a model.",
            "use_session_history": False,
            "record_session": False,
        }
    )
    rows = router.recommend(
        request,
        limit=max(1, limit),
        needs_tools=needs_tools or None,
        prefer=None if prefer == "balanced" else prefer,
        include_unavailable=include_unavailable,
    )
    if as_json:
        print(json.dumps({"route": route, "recommendations": rows}, indent=2, ensure_ascii=False))
    else:
        if not rows:
            print("No configured agents are available for that route.")
            return 1
        _print_table(rows, ["rank", "agent", "provider", "model", "score", "free", "available", "why"])
        unavailable = [row for row in rows if not row.get("available")]
        if unavailable:
            print()
            print("Unavailable:")
            for row in unavailable:
                print(f"- {row['agent']}: {row['unavailable_reason']}")
    return 0


def _benchmark(config: HubConfig, *, route: str, prompt: str, as_json: bool) -> int:
    router = AgentRouter(config)
    request = request_from_payload(
        {
            "session_id": f"benchmark-{uuid.uuid4().hex}",
            "route": route,
            "task": prompt,
            "max_tokens": 128,
            "use_session_history": False,
            "record_session": False,
        }
    )
    try:
        response = router.route(request)
    except RouterError as exc:
        _print_route_error(exc)
        return 1
    data = {
        "route": route,
        "agent": response.agent,
        "provider": response.provider,
        "model": response.model,
        "usage": response.usage,
        "health": router.health_snapshot(),
        "failover": [event.to_dict() for event in response.failover],
    }
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Route: {route}")
        print(f"Selected: {response.agent} ({response.provider}) model={response.model}")
        if response.failover:
            print("Failover:")
            for event in response.failover:
                print(f"- {event.agent}: {event.reason}")
        print("Health:")
        for name, health in data["health"].items():
            print(
                f"- {name}: success={health['success_count']} failure={health['failure_count']} "
                f"avg_latency={health['average_latency_seconds']}s"
            )
    return 0


def _eval_providers(config: HubConfig, *, route: str, limit: int, as_json: bool) -> int:
    router = AgentRouter(config)
    tasks = default_benchmark_tasks(route=route)[: max(1, min(limit, 20))]
    runner = BenchmarkRunner(router, store=ProviderScoreStore(config.state_dir))
    results = runner.run(tasks)
    scores = ProviderScoreStore(config.state_dir).load()
    data = {
        "object": "agent_hub.provider_evaluation",
        "route": route,
        "results": [result.to_dict() for result in results],
        "provider_scores": scores,
    }
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Provider evaluation for route {route}")
        _print_table(
            data["results"],
            ["agent", "provider", "model", "task_type", "score", "latency_ms", "ok", "error"],
        )
        print(f"Stored scores: {config.state_dir / 'provider_scores.json'}")
    return 0 if any(result.ok for result in results) else 1


def _route_test(config: HubConfig, *, route: str, prompt: str, as_json: bool) -> int:
    router = AgentRouter(config)
    request = request_from_payload(
        {
            "session_id": f"route-test-{uuid.uuid4().hex}",
            "route": route,
            "task": prompt,
            "max_tokens": 256,
            "use_session_history": False,
            "record_session": False,
        }
    )
    try:
        response = router.route(request)
    except RouterError as exc:
        _print_route_error(exc)
        return 1
    data = response.to_native_dict(include_routing_details=True)
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Selected {response.agent} ({response.provider}) model={response.model}")
        print(response.text)
        if response.failover:
            print("Failover:")
            for event in response.failover:
                print(f"- {event.agent}: {event.reason}")
    return 0


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
