from __future__ import annotations

import json
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .agent_runner import AgentRunner
from .application import (
    AdaptiveApplicationService,
    BACKEND_FEATURES,
    BACKEND_VERSION,
    DiagnosticsApplicationService,
)
from .api.compatibility import (
    apply_model_routing,
    anthropic_sse_frames,
    compatibility_endpoint,
    debug_api_shape,
    model_lookup_error,
    openai_chat_sse_frames,
    openai_model_rows,
    openai_response_sse_frames,
    payload_with_header_metadata,
    request_from_compat_payload,
    request_from_header_payload,
    response_headers,
    response_permission_status,
    response_token_metadata,
    response_for_shape,
    safe_header_value,
    stream_response_headers,
)
from .config import HubConfig
from .context import request_context_diagnostics
from .models import HubRequest
from .observability import permission_snapshot, recent_events, record_event, usage_snapshot
from .permissions import UNTRUSTED_EXTERNAL
from .security.secrets import redact_secrets
from .streaming import safe_stream_failure_chunk
from .core.router import NO_TOOL_CAPABLE_MODEL, AgentRouter, RouterError
from .team_agent_runner import TeamAgentRunner
from .version import build_metadata, config_runtime_hash
from .workflows import WorkflowEngine
from .server_routes.middleware import (
    diagnostics_auth_error as _diagnostics_auth_error,
    diagnostics_auth_required as _diagnostics_auth_required,
    diagnostics_token as _diagnostics_token,
    diagnostics_token_from_headers as _diagnostics_token_from_headers,
    public_bind_host as _public_bind_host,
    request_path as _request_path,
    request_query as _request_query,
)
from .server_routes import handle_get as handle_route_get, handle_post as handle_route_post
from .server_routes.chat import (
    _response_headers,
    _stream_response_headers,
    _recover_native_stream,
    _stream_replay_safe,
    _stream_recovery_request,
    _trim_stream_overlap,
    _safe_header_value,
    _safe_write,
    _safe_flush,
    _response_token_metadata,
    _response_permission_status,
    _wants_agent_mode,
    _payload_mode,
    _positive_int,
)
from .server_routes.diagnostics import (
    _record_debug_request,
    _debug_context_summary,
    _routing_diagnostics_module,
    _routing_failures,
    _recent_workflow_stages,
    _routing_status_body,
    _routing_last_decision_body,
    _routing_test_failover_body,
    _client_sources_body,
    _routing_history_body,
    _provider_health_body,
    _status_body,
    _events_body,
    _tools_body,
    _workflow_status_body,
    _plugins_body,
    _enterprise_audit_body,
    _provider_row_html,
    _optimization_dashboard_html,
    _task_winners_table_html,
    _role_winners_table_html,
    _model_win_rates_table_html,
    _provider_effectiveness_table_html,
    _workflow_analytics_table_html,
    _workflow_patterns_table_html,
    _recent_adaptive_table_html,
    _recommendation_list_html,
    _table_or_empty,
    _percent_label,
    _money_label,
    _ms_label,
    _role_label,
    _html,
    _limits_body,
    _active_provider_names,
    _available_model_ids,
    _openai_model_rows,
    _model_rows,
    _apply_model_routing,
    _model_lookup_error,
)


DIAGNOSTIC_ENDPOINTS = {
    "/v1/provider-health",
    "/v1/routing/status",
    "/v1/routing/last-decision",
    "/v1/routing/test-failover",
    "/v1/limits",
    "/v1/usage",
    "/v1/client-sources",
    "/v1/events",
    "/v1/optimization",
    "/v1/tools",
    "/v1/workflows/status",
    "/v1/plugins",
    "/v1/enterprise/audit",
    "/debug/context",
    "/debug/request",
    "/metrics",
    "/permissions",
}
COMPATIBILITY_ENDPOINT_REGISTRATION_MARKERS = (
    "/agent",
    "/api/v1/chat/completions",
    "/openrouter/v1/chat/completions",
    "/v1/agent",
    "/v1/auto",
    "/v1/feedback",
    "/v1/chat/completions",
    "/v1/messages",
    "/api/v1/models",
    "/v1/responses",
    "/v1/route",
)


class AgentHubHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], config: HubConfig) -> None:
        super().__init__(server_address, AgentHubHandler)
        self.config = config
        self.router = AgentRouter(config)
        self.agent_runner = AgentRunner(config, self.router)
        self.team_agent_runner = TeamAgentRunner(config, self.router)
        self.workflow_engine = WorkflowEngine(config, self.router)
        self.diagnostics_service = DiagnosticsApplicationService(config)
        self.adaptive_service = AdaptiveApplicationService(
            config,
            router=self.router,
            agent_runner=self.agent_runner,
            team_agent_runner=self.team_agent_runner,
            workflow_engine=self.workflow_engine,
        )
        self.debug_requests: list[dict[str, Any]] = []


class AgentHubHandler(BaseHTTPRequestHandler):
    server: AgentHubHTTPServer

    def do_GET(self) -> None:
        path = _request_path(self.path)
        if handle_route_get(self, path):
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
                "X-Session-ID, X-Conversation-ID, X-Thread-ID, "
                "X-Agent-Hub-Diagnostics-Token"
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
        if handle_route_post(self, path, payload):
            return
        self._send_json({"error": "not found"}, status=404)

    def _handle_recommendation(self, payload: dict[str, Any]) -> None:
        request = request_from_header_payload(payload, self.headers, api_shape="native")
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

    def _handle_workflow(self, payload: dict[str, Any], workflow: str) -> None:
        request = request_from_header_payload(payload, self.headers, api_shape="native")
        try:
            result = self.server.workflow_engine.execute(workflow, request)
        except ValueError as exc:
            self._send_json({"error": {"message": str(exc), "type": "unknown_workflow"}}, status=404)
            return
        except RouterError as exc:
            self._send_json(
                {
                    "error": {"message": str(exc), "type": getattr(exc, "error_type", None) or "workflow_route_error"},
                    "failover": [event.to_dict() for event in exc.failover],
                },
                status=getattr(exc, "status_code", None) or 503,
            )
            return
        self._send_json(
            result.to_dict(include_routing_details=self.server.config.expose_routing_details),
            headers=_response_headers(result.response, self.server.router),
        )

    def _handle_auto_payload(self, payload: dict[str, Any]) -> None:
        request = request_from_header_payload(payload, self.headers, api_shape="native")
        apply_model_routing(self.server.config, request)
        try:
            response = self.server.adaptive_service.execute_auto(request)
        except RouterError as exc:
            self._send_json(
                {
                    "error": {"message": str(exc), "type": getattr(exc, "error_type", None) or "auto_workflow_route_error"},
                    "failover": [event.to_dict() for event in exc.failover],
                },
                status=getattr(exc, "status_code", None) or 503,
            )
            return
        self._send_response_for_shape(response, "native", request.stream, include_routing_details=True)

    def _handle_feedback(self, payload: dict[str, Any]) -> None:
        body, status = self.server.adaptive_service.record_feedback_payload(payload)
        self._send_json(body, status=status)

    def _handle_routing_simulation(self, payload: dict[str, Any]) -> None:
        request = request_from_header_payload(payload, self.headers, api_shape="native")
        apply_model_routing(self.server.config, request)
        self._send_json(redact_secrets(self.server.adaptive_service.simulate_request(request)))

    def _send_response_for_shape(
        self,
        response: Any,
        response_shape: str,
        stream: bool = False,
        *,
        include_routing_details: bool | None = None,
    ) -> None:
        routing_details = (
            self.server.config.expose_routing_details
            if include_routing_details is None
            else include_routing_details
        )
        if stream and response_shape == "openai-chat":
            self._send_openai_stream(response)
            return
        if stream and response_shape == "anthropic-messages":
            self._send_anthropic_stream(response)
            return
        if stream and response_shape == "openai-responses":
            self._send_openai_response_stream(response)
            return
        self._send_json(
            response_for_shape(
                response,
                response_shape,
                include_raw=self.server.config.include_raw_responses,
                include_routing_details=routing_details,
            ),
            headers=_response_headers(response, self.server.router),
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
        request = request_from_compat_payload(payload, self.headers, api_shape=api_shape)
        payload = request.raw if isinstance(request.raw, dict) else payload
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
                "source": request.metadata.get("source"),
                "client_compatibility": request.metadata.get("client_compatibility"),
                "health_tracking_enabled": request.metadata.get("health_tracking_enabled"),
            },
        )
        apply_model_routing(self.server.config, request)
        model_error = model_lookup_error(self.server.config, request)
        if model_error is not None:
            self._send_json({"error": model_error}, status=404)
            return
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
        mode = _payload_mode(request.raw if isinstance(request.raw, dict) else payload, default_agent=agent_mode_default)
        if mode == "auto":
            response = self.server.adaptive_service.execute_auto(request)
            self._send_response_for_shape(
                response,
                response_shape,
                request.stream,
                include_routing_details=(
                    self.server.config.expose_routing_details or response_shape == "native"
                ),
            )
            return
        if response_shape == "native" and request.stream:
            self._send_native_stream(
                request,
                agent_mode=_wants_agent_mode(payload, default=agent_mode_default),
            )
            return
        if request.stream and response_shape == "openai-chat" and mode == "route":
            native_stream = self.server.router.native_stream(request)
            if native_stream is not None:
                self._send_openai_native_stream(native_stream)
                return
        try:
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
                if permission_event:
                    permission = (
                        permission_event.metadata.get("permission")
                        if isinstance(permission_event.metadata, dict)
                        else None
                    )
                    permission_details = (
                        permission.get("details")
                        if isinstance(permission, dict) and isinstance(permission.get("details"), dict)
                        else {}
                    )
                    security = (
                        permission_details.get("security")
                        if isinstance(permission_details.get("security"), dict)
                        else {}
                    )
                    trust_level = (
                        permission_event.metadata.get("trust_level")
                        if isinstance(permission_event.metadata, dict)
                        else None
                    )
                    explicit_security_approval = bool(
                        security.get("blocked") or security.get("explicit_approval_required")
                    )
                    unknown_external = (
                        trust_level == UNTRUSTED_EXTERNAL
                        or "unknown external" in permission_event.reason.lower()
                    )
                    error_body["error"]["provider"] = permission_event.agent
                    if explicit_security_approval:
                        error_body["error"]["message"] = (
                            "Provider request requires explicit approval because "
                            "the request content triggered a security rule."
                        )
                        error_body["error"]["suggested_fix"] = {
                            "remove_sensitive_content": True,
                            "provider_approval_granted": True,
                        }
                    elif unknown_external:
                        error_body["error"]["message"] = (
                            "Unknown external provider endpoint requires explicit approval. "
                            "Use a local endpoint, configure a known trusted provider type, "
                            "or approve this provider explicitly."
                        )
                        error_body["error"]["suggested_fix"] = {
                            "provider_approval_granted": True,
                            "trusted_provider_types": [
                                "openai",
                                "anthropic",
                                "gemini",
                                "groq",
                                "openrouter",
                                "ollama-cloud",
                            ],
                        }
                    else:
                        error_body["error"]["message"] = (
                            "Provider requires approval. Set approval_mode=auto or "
                            "enable cline_compatibility_mode."
                        )
                        error_body["error"]["suggested_fix"] = {
                            "approval_mode": "auto",
                            "cline_compatibility_mode": True,
                        }
                    error_body["agent_hub"]["provider"] = permission_event.agent
                    if isinstance(permission_event.metadata, dict) and permission_event.metadata.get("permission"):
                        error_body["agent_hub"]["permission"] = permission_event.metadata["permission"]
                    if trust_level:
                        error_body["agent_hub"]["trust_level"] = trust_level
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
        self._send_json(
            response_for_shape(
                response,
                response_shape,
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

    def _send_diagnostics_json(self, data: dict[str, Any]) -> None:
        auth_error = _diagnostics_auth_error(self.server.config, self.headers)
        if auth_error is not None:
            body, status = auth_error
            self._send_json(body, status=status)
            return
        self._send_json(redact_secrets(data))

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
                "X-Agent-Hub-Cooldown-Until, X-Agent-Hub-Fallback-Models, "
                "X-Agent-Hub-Stream-Mode, X-Agent-Hub-Provider-Score"
            ),
        )

    def _root_html(self) -> str:
        config = self.server.config
        status = _status_body(
            config,
            self.server.router,
            provider_scores=self.server.diagnostics_service.provider_scores(),
        )
        enabled_agents = [
            name
            for name, agent in config.agents.items()
            if agent.enabled
        ]
        agents = ", ".join(enabled_agents) or "none"
        active = ", ".join(status["active_providers"]) or "none"
        optimization = self.server.adaptive_service.optimization_summary()
        workflow_rate = optimization.get("workflow_success_rate", {})
        workflow_label = (
            f"{float(workflow_rate.get('rate', 0.0)) * 100:.0f}%"
            if workflow_rate.get("attempts")
            else "no samples"
        )
        best_models = optimization.get("model_win_rates") if isinstance(optimization.get("model_win_rates"), list) else []
        best_model = best_models[0] if best_models else {}
        best_model_label = " / ".join(
            str(best_model.get(key) or "")
            for key in ("provider", "model")
            if best_model.get(key)
        ) or "learning pending"
        avg_cost = optimization.get("average_known_cost_usd")
        avg_cost_label = f"${float(avg_cost):.4f}" if avg_cost is not None else "unknown"
        avg_latency_label = f"{float(optimization.get('average_latency_ms') or 0):.0f} ms"
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
      max-width: 980px;
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
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 18px 0;
    }}
    th, td {{
      padding: 8px 6px;
      border-bottom: 1px solid #303030;
      text-align: left;
      font-size: 14px;
    }}
    a {{
      color: #8ab4ff;
    }}
    code {{
      padding: 2px 5px;
      border-radius: 4px;
      background: #252525;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin: 18px 0;
    }}
    .card {{
      border: 1px solid #303030;
      border-radius: 8px;
      padding: 12px;
      background: #1d1d1d;
    }}
    .card strong {{
      display: block;
      font-size: 22px;
    }}
    .card span {{
      color: #aaa;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Agent Hub</h1>
    <div class="status">Running</div>
    <dl>
      <dt>Version</dt><dd>{BACKEND_VERSION}</dd>
      <dt>Config hash</dt><dd><code>{config_runtime_hash(config)}</code></dd>
      <dt>Workspace</dt><dd><code>{config.workspace_dir}</code></dd>
      <dt>Shell tools</dt><dd>{str(config.allow_shell_tools).lower()}</dd>
      <dt>Tool loop</dt><dd>{str(config.tool_loop_enabled).lower()} / max {config.max_tool_iterations}</dd>
      <dt>Repo context</dt><dd>{str(config.repo_context_enabled).lower()} / {config.repo_context_max_files} files</dd>
      <dt>Free only</dt><dd>{str(config.free_only).lower()}</dd>
      <dt>Patch preference</dt><dd>{str(config.prefer_multi_file_patches).lower()}</dd>
      <dt>Context bar</dt><dd>{config.context_change_bar_mode} / threshold {config.context_change_bar_threshold} / enabled {str(config.context_change_bar_enabled).lower()}</dd>
      <dt>Agents</dt><dd>{agents}</dd>
      <dt>Active</dt><dd>{active}</dd>
    </dl>
    <section>
      <h2>Optimization</h2>
      <div class="cards">
        <div class="card"><strong>{_html(workflow_label)}</strong><span>workflow success</span></div>
        <div class="card"><strong>{_html(best_model_label)}</strong><span>best learned model</span></div>
        <div class="card"><strong>{_html(avg_latency_label)}</strong><span>average latency</span></div>
        <div class="card"><strong>{_html(avg_cost_label)}</strong><span>average known cost</span></div>
      </div>
    </section>
    <table>
      <thead><tr><th>Provider</th><th>Model</th><th>Health</th><th>Score</th><th>Latency</th><th>Tools</th></tr></thead>
      <tbody>
        {''.join(_provider_row_html(row) for row in status["providers"][:12])}
      </tbody>
    </table>
    <p>
      <a href="/v1/status">Status JSON</a> |
      <a href="/v1/routing-history">Routing History</a> |
      <a href="/v1/provider-scores">Provider Scores</a> |
      <a href="/dashboard/optimization">Optimization Dashboard</a> |
      <a href="/v1/optimization">Optimization JSON</a>
    </p>
    <p>
      <a href="/health">Health JSON</a> ·
      <a href="/v1/models">Models JSON</a>
    </p>
  </main>
</body>
</html>"""

    def _send_openai_stream(self, response: Any) -> None:
        frames = openai_chat_sse_frames(
            response,
            include_routing_details=self.server.config.expose_routing_details,
        )
        body = "".join(frames).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Agent-Hub-Stream-Mode", "compatibility")
        self._send_common_headers()
        for name, value in _response_headers(response, self.server.router).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
        _safe_flush(self)

    def _send_openai_native_stream(self, stream: Any) -> None:
        created = int(time.time())
        chunk_id = f"chatcmpl-{stream.request_id}"
        model = stream.public_model or stream.model
        saw_finish = False
        emitted_content = False
        client_connected = True
        emitted_text_parts: list[str] = []

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Agent-Hub-Stream-Mode", "native")
        self._send_common_headers()
        for name, value in _stream_response_headers(stream, self.server.router).items():
            self.send_header(name, value)
        self.end_headers()

        def write_data(data: dict[str, Any] | str) -> None:
            nonlocal client_connected
            if not client_connected:
                return
            try:
                payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                client_connected = False

        write_data(
            {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
        )

        def write_chunk(source_chunk: Any, *, dedupe_against_emitted: bool = False) -> None:
            nonlocal saw_finish, emitted_content
            delta = dict(source_chunk.delta or {})
            if source_chunk.text and "content" not in delta:
                delta["content"] = source_chunk.text
            finish_reason = source_chunk.finish_reason
            if finish_reason:
                saw_finish = True
            if dedupe_against_emitted and isinstance(delta.get("content"), str):
                delta["content"] = _trim_stream_overlap("".join(emitted_text_parts), delta["content"])
            if not delta and not finish_reason:
                return
            if delta.get("content"):
                emitted_content = True
                emitted_text_parts.append(str(delta["content"]))
            write_data(
                {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": source_chunk.model or model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": finish_reason,
                        }
                    ],
                }
            )

        try:
            for chunk in stream.chunks:
                if not client_connected:
                    break
                write_chunk(chunk)
            if client_connected and not saw_finish:
                write_data(
                    {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                )
        except Exception as exc:
            recovered = _recover_native_stream(
                self.server,
                stream,
                replay_required=emitted_content,
                emitted_text="".join(emitted_text_parts),
            )
            if recovered is not None:
                try:
                    for chunk in recovered.chunks:
                        if not client_connected:
                            break
                        write_chunk(chunk, dedupe_against_emitted=emitted_content)
                    if client_connected and not saw_finish:
                        write_data(
                            {
                                "id": chunk_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model,
                                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            }
                        )
                    return
                except Exception:
                    pass
            write_chunk(
                safe_stream_failure_chunk(
                    model=model,
                    message="[Provider stream interrupted; switched to safe termination]",
                )
            )
            write_data(
                {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
        finally:
            write_data("[DONE]")

    def _send_anthropic_stream(self, response: Any) -> None:
        frames = anthropic_sse_frames(
            response,
            include_routing_details=self.server.config.expose_routing_details,
        )
        body = "".join(frames).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._send_common_headers()
        for name, value in _response_headers(response, self.server.router).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
        _safe_flush(self)

    def _send_openai_response_stream(self, response: Any) -> None:
        frames = openai_response_sse_frames(
            response,
            include_routing_details=self.server.config.expose_routing_details,
        )
        body = "".join(frames).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Agent-Hub-Stream-Mode", "compatibility")
        self._send_common_headers()
        for name, value in _response_headers(response, self.server.router).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
        _safe_flush(self)


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












































































































