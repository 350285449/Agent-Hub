from __future__ import annotations

import argparse
import json
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .agent_runner import AgentRunner
from .core.router import AgentRouter, RouterError
from .observability import STREAM_FILES, recent_events
from .payloads import request_from_payload
from .version import backend_version
from .output import _print_route_error, _shell_permission_prompt


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


def _export_logs(config: Any, *, output_format: str, output_path: str | None) -> int:
    bundle = _log_export_bundle(config)
    json_text = json.dumps(bundle, indent=2, ensure_ascii=False, default=str)
    markdown_text = _log_bundle_markdown(bundle)
    if output_format == "zip":
        path = Path(output_path or "agent-hub-debug-bundle.zip")
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "object": "agent_hub.debug_bundle_manifest",
            "backend_version": bundle.get("backend_version"),
            "generated_at": bundle.get("generated_at"),
            "files": ["debug-bundle.json", "debug-bundle.md"],
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
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
