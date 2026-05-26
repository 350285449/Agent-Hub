from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .agent_runner import AgentRunner
from .config import HubConfig, normalize_provider
from .context import request_context_diagnostics
from .models import HubRequest
from .observability import metrics_snapshot, permission_snapshot, record_event, usage_snapshot
from .payloads import (
    anthropic_message_response,
    anthropic_stream_events,
    openai_chat_response,
    openai_response_response,
    openai_response_stream_events,
    openai_stream_events,
    request_from_payload,
)
from .core.router import NO_TOOL_CAPABLE_MODEL, AgentRouter, RouterError
from .team_agent_runner import TeamAgentRunner
from .version import backend_version, build_metadata, config_runtime_hash


BACKEND_VERSION = backend_version()
BACKEND_FEATURES = {
    "native_agent_streaming": True,
    "native_agent_tool_schemas": True,
    "agent_progress_v2": True,
    "workspace_edit_events": True,
    "active_file_context_resolution": True,
    "current_folder_context": True,
    "workspace_shell_commands": True,
    "file_write_tools": True,
    "fast_write_finalize": True,
    "multi_file_apply_patch": True,
    "post_edit_validation": True,
    "team_agent_mode": True,
    "transparent_openai_responses": True,
    "openrouter_style_api_path": True,
    "provider_presets": True,
    "automatic_config_initialization": True,
    "model_recommendations": True,
    "quota_aware_failover": True,
    "persistent_provider_health": True,
    "adaptive_latency_routing": True,
    "provider_health_metrics": True,
    "shell_command_permission_policy": True,
    "agent_hub_model_aliases": True,
    "openai_tool_call_passthrough": True,
    "anthropic_messages_compatibility": True,
    "anthropic_tool_use_passthrough": True,
    "local_dummy_auth_compatibility": True,
    "workspace_checkpoints": True,
    "validation_repair_loops": True,
    "validation_rollback": True,
    "context_change_bar": True,
    "agent_context_compaction": True,
    "context_usage_bar": True,
    "strict_repository_context": True,
    "grouped_patch_enforcement": True,
    "repository_context_scoring": True,
    "repository_graph_propagation": True,
    "semantic_related_file_detection": True,
    "anti_hallucination_edit_blocking": True,
    "limits_endpoint": True,
    "response_limit_headers": True,
    "central_permission_manager": True,
    "provider_permission_gate": True,
    "debug_echo_gate": True,
    "cline_tool_model_gate": True,
    "central_token_budget_manager": True,
    "tool_security_classifier": True,
    "secret_detection": True,
    "structured_observability": True,
    "capability_graph": True,
    "safe_mode": True,
    "cline_compatibility_mode": True,
    "protected_context_categories": True,
    "context_debug_endpoints": True,
}


class AgentHubHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], config: HubConfig) -> None:
        super().__init__(server_address, AgentHubHandler)
        self.config = config
        self.router = AgentRouter(config)
        self.agent_runner = AgentRunner(config, self.router)
        self.team_agent_runner = TeamAgentRunner(config, self.router)
        self.debug_requests: list[dict[str, Any]] = []


class AgentHubHandler(BaseHTTPRequestHandler):
    server: AgentHubHTTPServer

    def do_GET(self) -> None:
        path = _request_path(self.path)
        if path in {"/", ""}:
            self._send_html(self._root_html())
            return
        if path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "running": True,
                    "server_status": "running",
                    "version": BACKEND_VERSION,
                    "build": build_metadata(),
                    "runtime": {"config_hash": config_runtime_hash(self.server.config)},
                    "features": BACKEND_FEATURES,
                    "agents": [
                        name
                        for name, agent in self.server.config.agents.items()
                        if agent.enabled
                    ],
                    "configured_agents": list(self.server.config.agents),
                    "free_only": self.server.config.free_only,
                    "allow_shell_tools": self.server.config.allow_shell_tools,
                    "shell_command_policy": self.server.config.shell_command_policy,
                    "approval_mode": self.server.config.approval_mode,
                    "debug_echo_enabled": self.server.config.debug_echo_enabled,
                    "permission_policy": {
                        "approval_mode": self.server.config.approval_mode,
                        "safe_mode": self.server.config.approval_mode == "safe",
                        "readonly_mode": self.server.config.approval_mode == "readonly",
                        "shell_command_policy": self.server.config.shell_command_policy,
                        "external_provider_approval": True,
                        "file_write_approval": self.server.config.approval_mode in {"ask", "safe", "readonly", "deny"},
                        "dangerous_command_blocking": True,
                        "secret_detection": True,
                    },
                    "prefer_multi_file_patches": self.server.config.prefer_multi_file_patches,
                    "grouped_patch_enforcement": {
                        "enabled": self.server.config.prefer_multi_file_patches,
                    },
                    "context_change_bar": {
                        "enabled": self.server.config.context_change_bar_enabled,
                        "mode": self.server.config.context_change_bar_mode,
                        "threshold": self.server.config.context_change_bar_threshold,
                    },
                    "agent_context_compaction": {
                        "enabled": self.server.config.agent_context_compaction_enabled,
                        "budget_tokens": self.server.config.agent_context_budget_tokens,
                        "mode": self.server.config.context_mode,
                    },
                    "token_budget": {
                        "mode": self.server.config.context_mode,
                        "budget_tokens": self.server.config.agent_context_budget_tokens,
                        "adaptive_modes": ["minimal", "balanced", "deep"],
                        "cline_compatibility_mode": self.server.config.cline_compatibility_mode,
                        "protected_categories": [
                            "recent_tool_calls",
                            "task_progress",
                            "todos",
                            "active_editor",
                            "workspace_state",
                            "mcp_state",
                            "latest_reasoning",
                        ],
                    },
                    "context_diagnostics": _debug_context_summary(self.server),
                    "repository_context_scoring": {
                        "enabled": self.server.config.context_change_bar_enabled,
                        "light_minimum": 3,
                        "strict_minimum": 6,
                        "changed_file_threshold": self.server.config.context_change_bar_threshold,
                    },
                    "repository_graph": {
                        "enabled": True,
                        "node_count": 0,
                        "related_file_detection_enabled": True,
                        "strict_anti_hallucination_enforcement_enabled": (
                            self.server.config.context_change_bar_enabled
                            and self.server.config.context_change_bar_mode == "strict"
                        ),
                    },
                    "workspace_dir": str(self.server.config.workspace_dir),
                    "initialization": self.server.config.initialization_report,
                    "provider_health": self.server.router.health_snapshot(),
                    "providers": self.server.router.provider_manager.available_models(),
                    "capability_graph": self.server.router.capability_graph(),
                    "active_providers": _active_provider_names(
                        self.server.config,
                        self.server.router,
                    ),
                    "limits": _limits_body(self.server.config, self.server.router),
                    "recommendations": self.server.router.recommend(
                        HubRequest(
                            session_id="health",
                            route="cloud-agent",
                            messages=[{"role": "user", "content": "select an agent model"}],
                            record_session=False,
                        ),
                        limit=5,
                        needs_tools=True,
                        include_unavailable=True,
                    ),
                    "models": _model_rows(self.server.config, self.server.router),
                    "available_models": _available_model_ids(
                        self.server.config,
                        self.server.router,
                    ),
                }
            )
            return
        if path == "/limits":
            self._send_json(_limits_body(self.server.config, self.server.router))
            return
        if path == "/usage":
            self._send_json(
                usage_snapshot(
                    self.server.config.state_dir,
                    self.server.router.health_snapshot(include_history=True),
                )
            )
            return
        if path == "/permissions":
            self._send_json(
                permission_snapshot(
                    self.server.config.state_dir,
                    approval_mode=self.server.config.approval_mode,
                    safe_mode=self.server.config.approval_mode == "safe",
                )
            )
            return
        if path == "/metrics":
            self._send_json(
                metrics_snapshot(
                    self.server.config.state_dir,
                    self.server.router.health_snapshot(include_history=True),
                )
            )
            return
        if path == "/debug/request":
            self._send_json(
                {
                    "object": "agent_hub.debug.request",
                    "recent": list(reversed(self.server.debug_requests[-20:])),
                }
            )
            return
        if path == "/debug/context":
            self._send_json(
                {
                    "object": "agent_hub.debug.context",
                    "summary": _debug_context_summary(self.server),
                    "recent": list(reversed(self.server.debug_requests[-20:])),
                }
            )
            return
        if path in {"/models", "/v1/models", "/api/v1/models"}:
            self._send_json(
                {
                    "object": "list",
                    "data": _openai_model_rows(
                        self.server.config,
                        self.server.router,
                        include_routing_details=self.server.config.expose_routing_details,
                    ),
                }
            )
            return
        self._send_json({"error": "not found"}, status=404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_common_headers()
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS",
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            (
                "Authorization, Content-Type, X-API-Key, API-Key, "
                "Anthropic-Version, Anthropic-Beta, X-Agent-Hub-Session-ID, "
                "X-Session-ID, X-Conversation-ID, X-Thread-ID"
            ),
        )
        self.end_headers()

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        path = _request_path(self.path)
        if path == "/debug/request":
            api_shape = _debug_api_shape(payload)
            debug_payload = _payload_with_header_metadata(payload, self.headers)
            request = request_from_payload(debug_payload, api_shape=api_shape)
            diagnostics = request_context_diagnostics(request)
            _record_debug_request(
                self.server,
                {
                    "path": path,
                    "api_shape": api_shape,
                    "response_shape": "debug",
                    "session_id": request.session_id,
                    "route": request.route,
                    "preferred_agent": request.preferred_agent,
                    "message_count": len(request.messages),
                    "diagnostics": diagnostics,
                },
            )
            self._send_json(
                {
                    "object": "agent_hub.debug.request",
                    "api_shape": api_shape,
                    "session_id": request.session_id,
                    "route": request.route,
                    "preferred_agent": request.preferred_agent,
                    "message_count": len(request.messages),
                    "metadata": request.metadata,
                    "diagnostics": diagnostics,
                }
            )
            return
        if path in {"/agent", "/v1/agent"}:
            self._handle_payload(
                payload,
                api_shape="native",
                response_shape="native",
                agent_mode_default=True,
            )
            return
        if path in {"/v1/recommend-model", "/api/v1/recommend-model"}:
            self._handle_recommendation(payload)
            return
        if path in {"/api/v1/chat/completions", "/openrouter/v1/chat/completions"}:
            self._handle_payload(
                payload,
                api_shape="openai-chat",
                response_shape="openai-chat",
            )
            return
        if path == "/v1/route":
            self._handle_payload(payload, api_shape="native", response_shape="native")
            return
        if path == "/v1/chat/completions":
            self._handle_payload(
                payload,
                api_shape="openai-chat",
                response_shape="openai-chat",
            )
            return
        if path == "/v1/responses":
            self._handle_payload(
                payload,
                api_shape="openai-responses",
                response_shape="openai-responses",
            )
            return
        if path == "/v1/messages":
            self._handle_payload(
                payload,
                api_shape="anthropic-messages",
                response_shape="anthropic-messages",
            )
            return
        self._send_json({"error": "not found"}, status=404)

    def _handle_recommendation(self, payload: dict[str, Any]) -> None:
        payload = _payload_with_header_metadata(payload, self.headers)
        request = request_from_payload(payload, api_shape="native")
        limit = _positive_int(payload.get("limit"), default=5, maximum=25)
        prefer = payload.get("prefer")
        if not isinstance(prefer, str) or prefer == "balanced":
            prefer = None
        needs_tools = payload.get("needs_tools")
        recommendations = self.server.router.recommend(
            request,
            limit=limit,
            needs_tools=bool(needs_tools) if needs_tools is not None else None,
            prefer=prefer,
            include_unavailable=bool(payload.get("include_unavailable", False)),
        )
        self._send_json(
            {
                "object": "agent_hub.model_recommendations",
                "route": request.route,
                "recommendations": recommendations,
            }
        )

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.config.include_raw_responses:
            super().log_message(format, *args)

    def _handle_payload(
        self,
        payload: dict[str, Any],
        api_shape: str,
        response_shape: str,
        agent_mode_default: bool = False,
    ) -> None:
        payload = _payload_with_header_metadata(payload, self.headers)
        request = request_from_payload(payload, api_shape=api_shape)
        record_event(
            self.server.config.state_dir,
            "requests",
            {
                "type": "http_request",
                "path": _request_path(self.path),
                "api_shape": api_shape,
                "response_shape": response_shape,
                "session_id": request.session_id,
                "route": request.route,
                "stream": request.stream,
            },
        )
        _apply_model_routing(self.server.config, request)
        diagnostics = request_context_diagnostics(request)
        _record_debug_request(
            self.server,
            {
                "path": _request_path(self.path),
                "api_shape": api_shape,
                "response_shape": response_shape,
                "session_id": request.session_id,
                "route": request.route,
                "preferred_agent": request.preferred_agent,
                "message_count": len(request.messages),
                "diagnostics": diagnostics,
            },
        )
        if response_shape == "native" and request.stream:
            self._send_native_stream(
                request,
                agent_mode=_wants_agent_mode(payload, default=agent_mode_default),
            )
            return
        try:
            mode = _payload_mode(payload, default_agent=agent_mode_default)
            if mode == "group-agent":
                response = self.server.team_agent_runner.run(request)
            elif mode == "agent":
                response = self.server.agent_runner.run(request)
            else:
                response = self.server.router.route(request)
        except RouterError as exc:
            permission_required = any(
                event.error_type in {"permission_required", "permission_denied"}
                for event in exc.failover
            )
            route_error_type = getattr(exc, "error_type", None)
            error_type = (
                "agent_hub_permission_required"
                if permission_required
                else route_error_type or "agent_hub_route_error"
            )
            error_body: dict[str, Any] = {
                "error": {
                    "message": str(exc),
                    "type": error_type,
                },
            }
            suggested_fix = getattr(exc, "suggested_fix", None)
            if suggested_fix:
                error_body["error"]["suggested_fix"] = suggested_fix
            if permission_required:
                permission_event = next(
                    (
                        event
                        for event in reversed(exc.failover)
                        if event.error_type in {"permission_required", "permission_denied"}
                    ),
                    None,
                )
                error_body["agent_hub"] = {
                    "permission_required": True,
                    "approval_mode": self.server.config.approval_mode,
                    "message": str(exc),
                }
                if permission_event and permission_event.metadata.get("permission"):
                    error_body["agent_hub"]["permission"] = permission_event.metadata["permission"]
            elif route_error_type == NO_TOOL_CAPABLE_MODEL:
                error_body["agent_hub"] = {
                    "error_type": NO_TOOL_CAPABLE_MODEL,
                    "message": str(exc),
                    "suggested_fix": suggested_fix,
                }
            if self.server.config.expose_routing_details or permission_required:
                error_body["failover"] = [event.to_dict() for event in exc.failover]
            status = getattr(exc, "status_code", None)
            if status is None:
                status = 403 if permission_required else 503
            self._send_json(error_body, status=status)
            return

        if request.stream and response_shape == "openai-chat":
            self._send_openai_stream(response)
            return
        if request.stream and response_shape == "anthropic-messages":
            self._send_anthropic_stream(response)
            return
        if request.stream and response_shape == "openai-responses":
            self._send_openai_response_stream(response)
            return
        response_headers = _response_headers(response, self.server.router)
        if response_shape == "openai-chat":
            self._send_json(
                openai_chat_response(
                    response,
                    include_routing_details=self.server.config.expose_routing_details,
                ),
                headers=response_headers,
            )
            return
        if response_shape == "anthropic-messages":
            self._send_json(
                anthropic_message_response(
                    response,
                    include_routing_details=self.server.config.expose_routing_details,
                ),
                headers=response_headers,
            )
            return
        if response_shape == "openai-responses":
            self._send_json(
                openai_response_response(
                    response,
                    include_routing_details=self.server.config.expose_routing_details,
                ),
                headers=response_headers,
            )
            return
        self._send_json(
            response.to_native_dict(
                include_raw=self.server.config.include_raw_responses,
                include_routing_details=self.server.config.expose_routing_details,
            ),
            headers=response_headers,
        )

    def _send_native_stream(self, request: Any, agent_mode: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Agent-Hub-Stream-Mode", "compatibility")
        self._send_common_headers()
        self.end_headers()

        client_connected = True

        def send_event(name: str, data: dict[str, Any]) -> None:
            nonlocal client_connected
            if not client_connected:
                return
            try:
                self.wfile.write(f"event: {name}\n".encode("utf-8"))
                self.wfile.write(
                    f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
                )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                client_connected = False

        def send_progress(event: dict[str, Any]) -> None:
            event_type = str(event.get("type") or "progress")
            send_event(event_type, event)

        try:
            send_event(
                "stream_open",
                {
                    "type": "stream_open",
                    "message": "Opened live Agent Hub stream.",
                },
            )
            mode = _payload_mode(request.raw, default_agent=agent_mode)
            if mode == "group-agent":
                response = self.server.team_agent_runner.run(request, event_sink=send_progress)
            elif mode == "agent":
                response = self.server.agent_runner.run(request, event_sink=send_progress)
            else:
                send_event("route_started", {"type": "route_started", "message": "Routing request."})
                response = self.server.router.route(request)
                send_event(
                    "route_finished",
                    {
                        "type": "route_finished",
                        "message": f"Response received from {response.agent}.",
                        "agent": response.agent,
                        "provider": response.provider,
                        "model": response.model,
                        "failover": [event.to_dict() for event in response.failover],
                    },
                )
            send_event(
                "final",
                {
                    "type": "final",
                    "response": response.to_native_dict(
                        include_raw=self.server.config.include_raw_responses,
                        include_routing_details=self.server.config.expose_routing_details,
                    ),
                },
            )
            send_event("done", {"type": "done"})
        except RouterError as exc:
            send_event(
                "error",
                {
                    "type": "error",
                    "message": str(exc),
                    "failover": [event.to_dict() for event in exc.failover],
                },
            )
        except Exception as exc:
            send_event("error", {"type": "error", "message": str(exc)})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0:
            raise ValueError("Expected a JSON request body")
        body = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        return payload

    def _send_json(
        self,
        data: dict[str, Any],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_common_headers()
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_common_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header(
            "Access-Control-Expose-Headers",
            (
                "X-Agent-Hub-Agent, X-Agent-Hub-Provider, X-Agent-Hub-Model, "
                "X-AgentHub-Provider, X-AgentHub-Model, X-AgentHub-Fallback, "
                "X-AgentHub-Tokens-Saved, X-AgentHub-Requests-Remaining, "
                "X-AgentHub-Permission-Status, X-AgentHub-Safe-Mode, "
                "X-AgentHub-Context-Warning, "
                "X-Agent-Hub-Active-Model, X-Agent-Hub-Requests-Remaining, "
                "X-Agent-Hub-Tokens-Remaining, X-Agent-Hub-Credits-Remaining, "
                "X-Agent-Hub-Quota-Remaining, X-Agent-Hub-Reset-At, "
                "X-Agent-Hub-Cooldown-Until, X-Agent-Hub-Fallback-Models"
            ),
        )

    def _root_html(self) -> str:
        config = self.server.config
        enabled_agents = [
            name
            for name, agent in config.agents.items()
            if agent.enabled
        ]
        agents = ", ".join(enabled_agents) or "none"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Hub</title>
  <style>
    body {{
      margin: 0;
      padding: 32px;
      color: #e8e8e8;
      background: #151515;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    main {{
      max-width: 760px;
      margin: 0 auto;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
    }}
    .status {{
      display: inline-block;
      margin: 8px 0 20px;
      padding: 4px 9px;
      border-radius: 999px;
      color: #122313;
      background: #8ee99a;
      font-weight: 600;
    }}
    dl {{
      display: grid;
      grid-template-columns: 150px 1fr;
      gap: 8px 14px;
      margin: 20px 0;
    }}
    dt {{
      color: #aaa;
    }}
    dd {{
      margin: 0;
    }}
    a {{
      color: #8ab4ff;
    }}
    code {{
      padding: 2px 5px;
      border-radius: 4px;
      background: #252525;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Agent Hub</h1>
    <div class="status">Running</div>
    <p>This is the local Agent Hub backend. Use the VS Code extension chat for the UI, or call the HTTP endpoints directly.</p>
    <dl>
      <dt>Version</dt><dd>{BACKEND_VERSION}</dd>
      <dt>Config hash</dt><dd><code>{config_runtime_hash(config)}</code></dd>
      <dt>Workspace</dt><dd><code>{config.workspace_dir}</code></dd>
      <dt>Shell tools</dt><dd>{str(config.allow_shell_tools).lower()}</dd>
      <dt>Free only</dt><dd>{str(config.free_only).lower()}</dd>
      <dt>Patch preference</dt><dd>{str(config.prefer_multi_file_patches).lower()}</dd>
      <dt>Context bar</dt><dd>{config.context_change_bar_mode} / threshold {config.context_change_bar_threshold} / enabled {str(config.context_change_bar_enabled).lower()}</dd>
      <dt>Agents</dt><dd>{agents}</dd>
    </dl>
    <p>
      <a href="/health">Health JSON</a> ·
      <a href="/v1/models">Models JSON</a>
    </p>
  </main>
</body>
</html>"""

    def _send_openai_stream(self, response: Any) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Agent-Hub-Stream-Mode", "compatibility")
        self._send_common_headers()
        for name, value in _response_headers(response, self.server.router).items():
            self.send_header(name, value)
        self.end_headers()
        for event in openai_stream_events(
            response,
            include_routing_details=self.server.config.expose_routing_details,
        ):
            data = event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_anthropic_stream(self, response: Any) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self._send_common_headers()
        for name, value in _response_headers(response, self.server.router).items():
            self.send_header(name, value)
        self.end_headers()
        for name, event in anthropic_stream_events(
            response,
            include_routing_details=self.server.config.expose_routing_details,
        ):
            self.wfile.write(f"event: {name}\n".encode("utf-8"))
            self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_openai_response_stream(self, response: Any) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Agent-Hub-Stream-Mode", "compatibility")
        self._send_common_headers()
        for name, value in _response_headers(response, self.server.router).items():
            self.send_header(name, value)
        self.end_headers()
        for event in openai_response_stream_events(
            response,
            include_routing_details=self.server.config.expose_routing_details,
        ):
            data = event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()


def serve(config: HubConfig) -> None:
    config.ensure_dirs()
    try:
        server = AgentHubHTTPServer((config.host, config.port), config)
    except OSError as exc:
        raise SystemExit(
            f"Agent Hub could not bind http://{config.host}:{config.port}. "
            "Another process may already be using the port. Stop the old server, "
            "change the agentHub.serverUrl/port setting, or run agent-hub serve --port <free-port>."
        ) from exc
    build = build_metadata()
    print(
        "Agent Hub "
        f"{BACKEND_VERSION} ({build.get('commit', 'unknown')}"
        f"{', dirty' if build.get('dirty') else ''}) "
        f"listening on http://{config.host}:{config.port}"
    )
    print(f"Runtime config hash: {config_runtime_hash(config)}")
    print(f"JSON inbox: {config.inbox_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Agent Hub")
    finally:
        server.server_close()


def _record_debug_request(server: AgentHubHTTPServer, entry: dict[str, Any]) -> None:
    entry = {"time": time.time(), **entry}
    server.debug_requests.append(entry)
    if len(server.debug_requests) > 100:
        del server.debug_requests[:-100]


def _debug_context_summary(server: AgentHubHTTPServer) -> dict[str, Any]:
    recent = server.debug_requests[-20:]
    if not recent:
        return {
            "request_count": 0,
            "incoming_token_count": 0,
            "compacted_token_count": 0,
            "protected_token_count": 0,
            "warning": "",
        }
    latest = recent[-1].get("diagnostics") if isinstance(recent[-1], dict) else {}
    diagnostics = latest if isinstance(latest, dict) else {}
    suspicious = [
        item
        for item in recent
        if isinstance(item.get("diagnostics"), dict)
        and item["diagnostics"].get("suspiciously_empty")
    ]
    return {
        "request_count": len(recent),
        "incoming_context_size": diagnostics.get("incoming_token_count", 0),
        "preserved_context_size": diagnostics.get("compacted_token_count", 0),
        "compacted_amount": diagnostics.get("dropped_token_count", 0),
        "incoming_token_count": diagnostics.get("incoming_token_count", 0),
        "compacted_token_count": diagnostics.get("compacted_token_count", 0),
        "protected_token_count": diagnostics.get("protected_token_count", 0),
        "preserved_tool_calls": diagnostics.get("preserved_tool_calls", 0),
        "preserved_tool_results": diagnostics.get("preserved_tool_results", 0),
        "preserved_todo_count": diagnostics.get("preserved_todo_count", 0),
        "active_files_detected": diagnostics.get("active_files_detected", []),
        "task_progress_present": diagnostics.get("task_progress_present", False),
        "suspiciously_empty": diagnostics.get("suspiciously_empty", False),
        "warning": (
            "Incoming context looks suspiciously empty; check Cline/Claude Code setup and active workspace state."
            if suspicious
            else ""
        ),
    }


def _debug_api_shape(payload: dict[str, Any]) -> str:
    shape = payload.get("api_shape") or payload.get("response_shape")
    if isinstance(shape, str) and shape in {"native", "openai-chat", "openai-responses", "anthropic-messages"}:
        return shape
    if "messages" in payload and ("anthropic_version" in payload or "system" in payload and "model" in payload):
        return "anthropic-messages"
    if "input" in payload:
        return "openai-responses"
    if "messages" in payload:
        return "openai-chat"
    return "native"


ROUTE_MODEL_ALIASES = {
    "agent-hub": "cloud-agent",
    "agent-hub-cloud": "cloud-agent",
    "agent-hub-coding": "coding",
    "agent-hub-tools": "coding",
    "agent-hub-agent": "coding",
    "agent-hub-local": "local-agent",
    "agent-hub-research": "research",
}


def _response_headers(response: Any, router: AgentRouter) -> dict[str, str]:
    health = router.health_snapshot().get(response.agent, {})
    fallback_models = [
        event.model
        for event in response.failover
        if event and event.model
    ]
    fallback_chain = ",".join(fallback_models)
    token_metadata = _response_token_metadata(response)
    permission_status = _response_permission_status(response)
    safe_mode = "on" if router.config.approval_mode == "safe" else "off"
    context_warning = (
        "suspiciously_empty"
        if token_metadata.get("suspiciously_empty")
        else ""
    )
    values = {
        "X-Agent-Hub-Agent": response.agent,
        "X-Agent-Hub-Provider": response.provider,
        "X-Agent-Hub-Model": response.model,
        "X-Agent-Hub-Active-Model": response.model,
        "X-Agent-Hub-Requests-Remaining": health.get("requests_remaining"),
        "X-Agent-Hub-Tokens-Remaining": health.get("tokens_remaining"),
        "X-Agent-Hub-Credits-Remaining": health.get("credits_remaining"),
        "X-Agent-Hub-Quota-Remaining": health.get("quota_remaining"),
        "X-Agent-Hub-Reset-At": health.get("rate_limit_reset_at"),
        "X-Agent-Hub-Cooldown-Until": health.get("cooldown_until"),
        "X-Agent-Hub-Fallback-Models": fallback_chain,
        "X-AgentHub-Provider": response.provider,
        "X-AgentHub-Model": response.model,
        "X-AgentHub-Fallback": fallback_chain,
        "X-AgentHub-Tokens-Saved": token_metadata.get("estimated_tokens_saved"),
        "X-AgentHub-Requests-Remaining": health.get("requests_remaining"),
        "X-AgentHub-Permission-Status": permission_status,
        "X-AgentHub-Safe-Mode": safe_mode,
        "X-AgentHub-Context-Warning": context_warning,
    }
    return {
        name: _safe_header_value(value)
        for name, value in values.items()
        if _safe_header_value(value)
    }


def _safe_header_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:1000]


def _response_token_metadata(response: Any) -> dict[str, Any]:
    raw = response.raw if isinstance(getattr(response, "raw", None), dict) else {}
    metadata = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    context_usage = metadata.get("context_usage") if isinstance(metadata, dict) else None
    if isinstance(context_usage, dict):
        return context_usage
    token_budget = metadata.get("token_budget") if isinstance(metadata, dict) else None
    return token_budget if isinstance(token_budget, dict) else {}


def _response_permission_status(response: Any) -> str:
    if any(event.error_type == "permission_denied" for event in getattr(response, "failover", [])):
        return "denied"
    if any(event.error_type == "permission_required" for event in getattr(response, "failover", [])):
        return "required"
    raw = response.raw if isinstance(getattr(response, "raw", None), dict) else {}
    metadata = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    steps = metadata.get("steps") if isinstance(metadata, dict) else []
    if isinstance(steps, list):
        for step in steps:
            result = step.get("result") if isinstance(step, dict) and isinstance(step.get("result"), dict) else {}
            if result.get("approval_required"):
                return "required"
            if result.get("permission_denied"):
                return "denied"
    return "allowed"


def _limits_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    recommendations = router.recommend(
        HubRequest(
            session_id="limits",
            route="cloud-agent",
            messages=[{"role": "user", "content": "select an agent model"}],
            record_session=False,
        ),
        limit=8,
        needs_tools=True,
        include_unavailable=True,
    )
    active = next((row for row in recommendations if row.get("available")), None)
    if active is None and recommendations:
        active = recommendations[0]
    providers = [
        _provider_limit_row(name, agent, health.get(name, {}))
        for name, agent in sorted(config.agents.items())
        if agent.enabled
    ]
    failed_models: list[dict[str, Any]] = []
    for row in providers:
        if row.get("last_error_message"):
            failed_models.append(
                {
                    "agent": row["agent"],
                    "provider": row["provider"],
                    "model": row["model"],
                    "reason": row["last_error_message"],
                    "cooldown_until": row["cooldown_until"],
                }
            )
    return {
        "object": "agent_hub.limits",
        "status": "running",
        "running": True,
        "active_model": _active_model_row(active),
        "active_providers": [
            row["agent"]
            for row in providers
            if row.get("available")
        ],
        "providers": providers,
        "limits": providers,
        "provider_health": health,
        "cooldowns": {
            row["agent"]: row["cooldown_until"]
            for row in providers
            if row.get("cooldown_until")
        },
        "available_models": _available_model_ids(config, router),
        "failed_models": failed_models,
        "fallback_models": failed_models,
        "recommendations": recommendations,
    }


def _provider_limit_row(
    name: str,
    agent: Any,
    health: dict[str, Any],
) -> dict[str, Any]:
    return {
        "agent": name,
        "provider": agent.provider,
        "provider_name": agent.provider,
        "provider_type": agent.provider_type,
        "model": agent.model,
        "available": bool(health.get("available")),
        "degraded": bool(health.get("degraded")),
        "quota_remaining": health.get("quota_remaining"),
        "requests_remaining": health.get("requests_remaining"),
        "tokens_remaining": health.get("tokens_remaining"),
        "credits_remaining": health.get("credits_remaining"),
        "rate_limit_reset_at": health.get("rate_limit_reset_at"),
        "cooldown_until": health.get("cooldown_until"),
        "unavailable_until": health.get("unavailable_until"),
        "last_error_type": health.get("last_error_type"),
        "last_error_message": health.get("last_error_message"),
        "success_count": health.get("success_count", 0),
        "failure_count": health.get("failure_count", 0),
    }


def _active_model_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "agent": row.get("agent"),
        "provider": row.get("provider"),
        "provider_name": row.get("provider"),
        "provider_type": row.get("provider_type"),
        "model": row.get("model"),
        "available": row.get("available"),
        "requests_remaining": row.get("requests_remaining"),
        "tokens_remaining": row.get("tokens_remaining"),
        "credits_remaining": row.get("credits_remaining"),
        "rate_limit_reset_at": row.get("rate_limit_reset_at"),
        "cooldown_until": row.get("cooldown_until"),
    }


def _active_provider_names(config: HubConfig, router: AgentRouter) -> list[str]:
    health = router.health_snapshot()
    return [
        name
        for name, agent in sorted(config.agents.items())
        if agent.enabled and health.get(name, {}).get("available")
    ]


def _available_model_ids(config: HubConfig, router: AgentRouter) -> list[str]:
    ids: list[str] = []
    for row in _model_rows(config, router):
        metadata = row.get("agent_hub") if isinstance(row, dict) else None
        if isinstance(metadata, dict) and metadata.get("available") is False:
            continue
        model_id = row.get("id") if isinstance(row, dict) else None
        if isinstance(model_id, str) and model_id not in ids:
            ids.append(model_id)
    return ids


def _openai_model_rows(
    config: HubConfig,
    router: AgentRouter,
    *,
    include_routing_details: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _model_rows(config, router):
        metadata = row.get("agent_hub") if isinstance(row, dict) else None
        if isinstance(metadata, dict) and metadata.get("available") is False:
            continue
        public_row = {
            "id": row["id"],
            "object": "model",
            "created": row.get("created", 0),
            "owned_by": row.get("owned_by", "agent-hub"),
        }
        if include_routing_details and isinstance(metadata, dict):
            public_row["agent_hub"] = metadata
        rows.append(public_row)
    return rows


def _model_rows(config: HubConfig, router: AgentRouter) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    health = router.health_snapshot()
    for model_id, route_name in ROUTE_MODEL_ALIASES.items():
        if route_name not in {route.name for route in config.routes}:
            continue
        recommendation = router.recommend(
            HubRequest(
                session_id="models",
                route=route_name,
                messages=[{"role": "user", "content": "select an agent model"}],
                record_session=False,
            ),
            limit=1,
            needs_tools=route_name in {"coding", "local-agent"},
        )
        row = {
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "agent-hub",
            "agent_hub": {
                "type": "route",
                "route": route_name,
                "recommended_agent": recommendation[0]["agent"] if recommendation else None,
                "recommended_model": recommendation[0]["model"] if recommendation else None,
                "available": bool(recommendation)
                and _route_has_visible_agent(config, route_name),
                "recommended_health": (
                    health.get(recommendation[0]["agent"], {}) if recommendation else {}
                ),
            },
        }
        rows.append(row)
        seen.add(model_id)

    for route in config.routes:
        if route.name in seen:
            continue
        rows.append(
            {
                "id": route.name,
                "object": "model",
                "created": 0,
                "owned_by": "agent-hub",
                "agent_hub": {
                    "type": "route",
                    "route": route.name,
                    "available": _route_has_visible_agent(config, route.name),
                },
            }
        )
        seen.add(route.name)

    for agent in config.agents.values():
        if not _agent_visible_in_models(config, agent):
            continue
        for model_id in (f"agent:{agent.name}", agent.name, agent.model):
            if model_id in seen:
                continue
            rows.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "agent-hub" if model_id.startswith("agent:") else agent.provider,
                    "agent_hub": {
                        "type": "agent_alias" if model_id.startswith("agent:") else "agent",
                        "agent": agent.name,
                        "provider_type": agent.provider_type,
                        "free": agent.free,
                        "context_window": agent.context_window,
                        "coding_score": agent.coding_score,
                        "reasoning_score": agent.reasoning_score,
                        "speed_score": agent.speed_score,
                        "supports_tools": bool(agent.supports_tools or agent.supports_function_calling),
                        "health": health.get(agent.name, {}),
                    },
                }
            )
            seen.add(model_id)
    return rows


def _route_has_visible_agent(config: HubConfig, route_name: str) -> bool:
    route = next((item for item in config.routes if item.name == route_name), None)
    if route is None:
        return False
    return any(
        _agent_visible_in_models(config, config.agents[name])
        for name in route.agents
        if name in config.agents
    )


def _agent_visible_in_models(config: HubConfig, agent: Any) -> bool:
    if not getattr(agent, "enabled", False):
        return False
    if normalize_provider(getattr(agent, "provider", "")) == "echo":
        return bool(config.debug_echo_enabled)
    return True


def _apply_model_routing(config: HubConfig, request: HubRequest) -> None:
    if not isinstance(request.raw, dict):
        return
    model = request.raw.get("model")
    if not isinstance(model, str) or not model.strip():
        return
    normalized = model.strip().lower()
    if request.route is None and normalized in ROUTE_MODEL_ALIASES:
        request.route = ROUTE_MODEL_ALIASES[normalized]
        return
    for prefix in ("agent:", "agent-hub-agent:"):
        if request.preferred_agent is None and normalized.startswith(prefix):
            agent_name = model.strip()[len(prefix) :].strip()
            if agent_name:
                request.preferred_agent = agent_name
                return
    if request.route is None and normalized.startswith("agent-hub/"):
        route_name = normalized.split("/", 1)[1].strip()
        if route_name:
            request.route = route_name
            return
    route_names = {route.name.lower(): route.name for route in config.routes}
    if request.route is None and normalized in route_names:
        request.route = route_names[normalized]
        return
    agent_names = {agent.name.lower(): agent.name for agent in config.agents.values()}
    if request.preferred_agent is None and normalized in agent_names:
        request.preferred_agent = agent_names[normalized]
        return
    if request.preferred_agent is None:
        for agent in config.agents.values():
            if agent.model.lower() == normalized:
                request.preferred_agent = agent.name
                return


def _wants_agent_mode(payload: dict[str, Any], default: bool = False) -> bool:
    hub_options = payload.get("agent_hub")
    if isinstance(hub_options, dict) and "agent_mode" in hub_options:
        return bool(hub_options["agent_mode"])
    if "agent_mode" in payload:
        return bool(payload["agent_mode"])
    mode = payload.get("mode")
    if isinstance(mode, str) and mode.lower() == "agent":
        return True
    return default


def _payload_mode(payload: dict[str, Any], default_agent: bool = False) -> str:
    hub_options = payload.get("agent_hub")
    if isinstance(hub_options, dict):
        mode = hub_options.get("mode")
        if isinstance(mode, str) and mode.lower() in {"agent", "group-agent", "team-agent"}:
            return "group-agent" if mode.lower() == "team-agent" else mode.lower()
        if bool(hub_options.get("agent_mode")):
            return "agent"
    mode = payload.get("mode")
    if isinstance(mode, str) and mode.lower() in {"agent", "group-agent", "team-agent"}:
        return "group-agent" if mode.lower() == "team-agent" else mode.lower()
    if bool(payload.get("agent_mode")):
        return "agent"
    return "agent" if default_agent else "route"


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, maximum))


def _request_path(path: str) -> str:
    return path.split("?", 1)[0]


def _payload_with_header_metadata(payload: dict[str, Any], headers: Any) -> dict[str, Any]:
    metadata = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    for header_name, key in (
        ("X-Agent-Hub-Session-ID", "session_id"),
        ("X-Session-ID", "session_id"),
        ("X-Conversation-ID", "conversation_id"),
        ("X-Thread-ID", "thread_id"),
    ):
        value = headers.get(header_name)
        if isinstance(value, str) and value.strip() and not _has_session_key(metadata):
            metadata[key] = value.strip()
            break
    if not metadata:
        return payload
    copied = dict(payload)
    copied["metadata"] = metadata
    return copied


def _has_session_key(data: dict[str, Any]) -> bool:
    return any(
        isinstance(data.get(key), str) and str(data.get(key)).strip()
        for key in ("session_id", "conversation_id", "thread_id")
    )
