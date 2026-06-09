from __future__ import annotations

import argparse
import importlib
import json
import threading
import uuid
from pathlib import Path
from typing import Any
from typing import Sequence

from .agent_runner import AgentRunner
from .config import load_config
from .inbox import InboxProcessor
from .payloads import request_from_payload
from .provider_presets import preset_rows, provider_metadata_rows
from .core.router import AgentRouter, RouterError
from .team_agent_runner import TeamAgentRunner
from .commands_config import (
    _init_config,
    _inspect_request,
    _migrate_config,
)
from .commands_doctor import (
    _backend_reachability,
    _doctor_fix_safe,
    _print_doctor,
)
from .commands_provider import (
    _add_free_presets,
    _add_provider,
    _agent_rows,
    _apply_routing_preset,
    _benchmark,
    _benchmark_run,
    _benchmark_suite,
    _enable_cloud_provider,
    _estimate,
    _explain_route,
    _eval_providers,
    _feature_scorecard_report,
    _health_report,
    _local_models_report,
    _print_feature_scorecard,
    _print_health,
    _print_local_models,
    _print_metrics,
    _print_production_check,
    _production_check_report,
    _recommend,
    _benchmark_card,
    _benchmark_evolution,
    _calibrate_models,
    _generate_case_study,
    _replay_route,
    _route_test,
    _route_diagnose,
    _route_history,
    _routing_preset_rows,
)
from .commands_server import (
    _add_agent_runtime_flags,
    _apply_agent_runtime_flags,
    _chat,
    _export_logs,
    _wants_agent_mode,
)
from .output import _print_route_error, _print_table, _shell_permission_prompt


def _doctor_report(config: Any, config_path: str) -> dict[str, Any]:
    doctor_commands = importlib.import_module("agent_hub.commands_doctor")
    doctor_commands._backend_reachability = _backend_reachability
    return doctor_commands._doctor_report(config, config_path)


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
    doctor_parser.add_argument(
        "--fix-safe",
        action="store_true",
        help="Apply conservative config repairs such as removing unknown route agents.",
    )

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

    production_parser = subparsers.add_parser(
        "production-check",
        help="Run a strict local acceptance check for production readiness.",
    )
    production_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    feature_scorecard_parser = subparsers.add_parser(
        "feature-scorecard",
        help="Show 10/10 feature-area proof and remaining blockers.",
    )
    feature_scorecard_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

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

    estimate_parser = subparsers.add_parser(
        "estimate",
        help="Estimate routing, latency, and known provider cost without calling a provider.",
    )
    estimate_parser.add_argument("prompt", nargs="*", default=[""], help="Task or prompt to estimate.")
    estimate_parser.add_argument("--route", default="cloud-agent", help="Route to score.")
    estimate_parser.add_argument("--limit", type=int, default=5, help="Number of candidates.")
    estimate_parser.add_argument(
        "--prefer",
        choices=["balanced", "coding", "reasoning", "speed"],
        default="balanced",
        help="Recommendation bias.",
    )
    estimate_parser.add_argument(
        "--needs-tools",
        action="store_true",
        help="Prefer models with tool/function-call support.",
    )
    estimate_parser.add_argument(
        "--output-tokens",
        type=int,
        default=1024,
        help="Estimated output tokens used for known cost calculation.",
    )
    estimate_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

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

    benchmark_parser = subparsers.add_parser("benchmark", help="Run route benchmarks and proof reports.")
    benchmark_parser.add_argument("action", nargs="?", default="", help="Use 'run' for proof benchmarks.")
    benchmark_parser.add_argument("--route", default="cloud-agent")
    benchmark_parser.add_argument("--prompt", default="Reply with one short sentence.")
    benchmark_parser.add_argument("--baseline", default="", help="Baseline agent/model. Defaults to user default.")
    benchmark_parser.add_argument("--limit", type=int, default=50, help="Maximum proof benchmark tasks.")
    benchmark_parser.add_argument("--corpus", default="", help="Benchmark corpus directory.")
    benchmark_parser.add_argument("--output-dir", default="", help="Directory for benchmark-report files.")
    benchmark_parser.add_argument("--json", action="store_true")

    benchmark_suite_parser = subparsers.add_parser(
        "benchmark-suite",
        help="Compare static routing with adaptive routing and write a benchmark report.",
    )
    benchmark_suite_parser.add_argument("--route", default="cloud-agent")
    benchmark_suite_parser.add_argument("--limit", type=int, default=20)
    benchmark_suite_parser.add_argument("--output", default="")
    benchmark_suite_parser.add_argument("--json", action="store_true")

    eval_parser = subparsers.add_parser("eval", help="Evaluate configured providers and store provider scores.")
    eval_parser.add_argument("--route", default="cloud-agent")
    eval_parser.add_argument("--json", action="store_true")
    eval_parser.add_argument("--limit", type=int, default=6, help="Maximum benchmark tasks to run.")

    calibrate_parser = subparsers.add_parser(
        "calibrate-models",
        help="Run bounded calibration prompts against routed agents and store model score evidence.",
    )
    calibrate_parser.add_argument("--route", default="cloud-agent")
    calibrate_parser.add_argument("--limit", type=int, default=4, help="Tasks per agent.")
    calibrate_parser.add_argument("--max-agents", type=int, default=5, help="Maximum agents to calibrate.")
    calibrate_parser.add_argument("--agents", default="", help="Comma-separated agent names. Defaults to route agents.")
    calibrate_parser.add_argument("--json", action="store_true")

    route_test_parser = subparsers.add_parser("route-test", help="Route a prompt and show selected provider.")
    route_test_parser.add_argument("prompt", nargs="*", default=["hello"])
    route_test_parser.add_argument("--route", default="cloud-agent")
    route_test_parser.add_argument("--json", action="store_true")

    route_diagnose_parser = subparsers.add_parser(
        "route-diagnose",
        help="Explain provider/model selection, skipped providers, fallback reason, latency, and cost.",
    )
    route_diagnose_parser.add_argument("prompt", nargs="*", default=["Diagnose routing."])
    route_diagnose_parser.add_argument("--route", default="cloud-agent")
    route_diagnose_parser.add_argument(
        "--prefer",
        choices=["balanced", "coding", "reasoning", "speed"],
        default="balanced",
        help="Recommendation bias.",
    )
    route_diagnose_parser.add_argument(
        "--needs-tools",
        action="store_true",
        help="Prefer models with tool/function-call support.",
    )
    route_diagnose_parser.add_argument(
        "--output-tokens",
        type=int,
        default=1024,
        help="Estimated output tokens used for known cost calculation.",
    )
    route_diagnose_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    explain_route_parser = subparsers.add_parser(
        "explain-route",
        help="Explain provider/model ranking without calling a provider.",
    )
    explain_route_parser.add_argument("prompt", nargs="*", default=["Explain routing."])
    explain_route_parser.add_argument("--route", default="cloud-agent")
    explain_route_parser.add_argument(
        "--prefer",
        choices=["balanced", "coding", "reasoning", "speed"],
        default="balanced",
        help="Recommendation bias.",
    )
    explain_route_parser.add_argument("--needs-tools", action="store_true")
    explain_route_parser.add_argument("--output-tokens", type=int, default=1024)
    explain_route_parser.add_argument("--json", action="store_true")

    route_history_parser = subparsers.add_parser(
        "route-history",
        help="Show how routing distribution changed over recent weeks.",
    )
    route_history_parser.add_argument("--weeks", type=int, default=4)
    route_history_parser.add_argument("--json", action="store_true")

    replay_route_parser = subparsers.add_parser(
        "replay-route",
        help="Replay a recorded routing decision and show selected plus rejected alternatives.",
    )
    replay_route_parser.add_argument("request_id", help="Agent-Hub request id to replay.")
    replay_route_parser.add_argument("--json", action="store_true")

    benchmark_card_parser = subparsers.add_parser(
        "benchmark-card",
        help="Generate shareable benchmark card text from the latest proof report.",
    )
    benchmark_card_parser.add_argument("--report", default="", help="Optional benchmark-report.json path.")
    benchmark_card_parser.add_argument(
        "--variant",
        choices=["markdown", "reddit", "x", "github_discussion"],
        default="markdown",
    )
    benchmark_card_parser.add_argument("--json", action="store_true")

    case_study_parser = subparsers.add_parser(
        "generate-case-study",
        help="Generate a local Markdown case study from benchmark and routing history.",
    )
    case_study_parser.add_argument("--output", default="", help="Optional Markdown output path.")
    case_study_parser.add_argument("--json", action="store_true")

    benchmark_evolution_parser = subparsers.add_parser(
        "benchmark-evolution",
        help="Show month-by-month routing distribution changes.",
    )
    benchmark_evolution_parser.add_argument("--months", type=int, default=3)
    benchmark_evolution_parser.add_argument("--json", action="store_true")

    export_logs_parser = subparsers.add_parser("export-logs", help="Export recent diagnostic logs.")
    export_logs_parser.add_argument("--format", choices=["json", "markdown", "zip"], default="json")
    export_logs_parser.add_argument("--output", help="Output path. Defaults to stdout for json/markdown.")

    debug_bundle_parser = subparsers.add_parser("debug-bundle", help="Export a zipped debug bundle.")
    debug_bundle_parser.add_argument("--output", help="Output zip path.")

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
        fix_report = None
        if args.fix_safe:
            fix_report = _doctor_fix_safe(args.config)
            config = load_config(args.config)
            config.ensure_dirs()
        report = _doctor_report(config, args.config)
        if fix_report is not None:
            report["fix_safe"] = fix_report
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
    if command == "production-check":
        report = _production_check_report(config)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _print_production_check(report)
        return 0 if report.get("ok") else 1
    if command == "feature-scorecard":
        report = _feature_scorecard_report(config)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _print_feature_scorecard(report)
        return 0 if report.get("all_local_areas_10") else 1
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
        return _export_logs(config, output_format=args.format, output_path=args.output, config_path=args.config)
    if command == "debug-bundle":
        return _export_logs(config, output_format="zip", output_path=args.output, config_path=args.config)
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
    if command == "estimate":
        return _estimate(
            config,
            route=args.route,
            prompt=" ".join(args.prompt),
            limit=args.limit,
            prefer=args.prefer,
            needs_tools=args.needs_tools,
            output_tokens=args.output_tokens,
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
        if args.action == "run":
            return _benchmark_run(
                config,
                route=args.route,
                baseline=args.baseline,
                limit=args.limit,
                corpus=args.corpus,
                output_dir=args.output_dir,
                as_json=args.json,
            )
        if args.action:
            parser.error(f"Unknown benchmark action {args.action!r}")
        return _benchmark(config, route=args.route, prompt=args.prompt, as_json=args.json)
    if command == "benchmark-suite":
        return _benchmark_suite(
            config,
            route=args.route,
            limit=args.limit,
            output=args.output or None,
            as_json=args.json,
        )
    if command == "eval":
        return _eval_providers(config, route=args.route, limit=args.limit, as_json=args.json)
    if command == "calibrate-models":
        return _calibrate_models(
            config,
            route=args.route,
            limit=args.limit,
            max_agents=args.max_agents,
            agents=args.agents,
            as_json=args.json,
        )
    if command == "route-test":
        return _route_test(config, route=args.route, prompt=" ".join(args.prompt), as_json=args.json)
    if command == "route-diagnose":
        return _route_diagnose(
            config,
            route=args.route,
            prompt=" ".join(args.prompt),
            output_tokens=args.output_tokens,
            prefer=args.prefer,
            needs_tools=args.needs_tools,
            as_json=args.json,
        )
    if command == "explain-route":
        return _explain_route(
            config,
            route=args.route,
            prompt=" ".join(args.prompt),
            output_tokens=args.output_tokens,
            prefer=args.prefer,
            needs_tools=args.needs_tools,
            as_json=args.json,
        )
    if command == "route-history":
        return _route_history(config, weeks=args.weeks, as_json=args.json)
    if command == "replay-route":
        return _replay_route(config, request_id=args.request_id, as_json=args.json)
    if command == "benchmark-card":
        return _benchmark_card(
            config,
            report_path=args.report,
            variant=args.variant,
            as_json=args.json,
        )
    if command == "generate-case-study":
        return _generate_case_study(config, output=args.output, as_json=args.json)
    if command == "benchmark-evolution":
        return _benchmark_evolution(config, months=args.months, as_json=args.json)
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


if __name__ == "__main__":
    raise SystemExit(main())
