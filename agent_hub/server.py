from __future__ import annotations

import json
import hmac
import os
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

from .agent_runner import AgentRunner
from .config import HubConfig, normalize_provider
from .context import request_context_diagnostics
from .enterprise import export_enterprise_audit
from .evaluation import ProviderScoreStore
from .models import HubRequest
from .observability import metrics_snapshot, permission_snapshot, recent_events, record_event, usage_snapshot
from .permissions import UNTRUSTED_EXTERNAL
from .security.secrets import redact_secrets
from .streaming import safe_stream_failure_chunk
from .plugins import discover_plugins
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
from .workflows import WorkflowEngine


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
    "provider_health_scoring": True,
    "native_provider_streaming": True,
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
    "context_engine_v2": True,
    "deterministic_workflows": True,
    "mcp_tool_compatibility_layer": True,
    "tool_execution_loop": True,
    "external_mcp_bridge": True,
    "repo_aware_coding": True,
    "provider_evaluation": True,
    "dashboard_status_endpoints": True,
    "raw_provider_response_debugging": True,
    "response_normalization_hardening": True,
    "streaming_recovery": True,
    "context_safety_cap": True,
    "repo_ignore_patterns": True,
    "plugin_sdk_foundation": True,
    "signed_plugin_manifests": True,
    "plugin_sandbox_foundation": True,
    "enterprise_foundation_models": True,
    "enterprise_audit_logs": True,
    "config_migration": True,
    "events_endpoint": True,
    "deployment_templates": True,
}
DIAGNOSTIC_ENDPOINTS = {
    "/v1/provider-health",
    "/v1/routing/status",
    "/v1/routing/last-decision",
    "/v1/routing/test-failover",
    "/v1/limits",
    "/v1/usage",
    "/v1/client-sources",
    "/v1/events",
    "/v1/tools",
    "/v1/workflows/status",
    "/v1/plugins",
    "/v1/enterprise/audit",
}


class AgentHubHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], config: HubConfig) -> None:
        super().__init__(server_address, AgentHubHandler)
        self.config = config
        self.router = AgentRouter(config)
        self.agent_runner = AgentRunner(config, self.router)
        self.team_agent_runner = TeamAgentRunner(config, self.router)
        self.workflow_engine = WorkflowEngine(config, self.router)
        self.debug_requests: list[dict[str, Any]] = []


class AgentHubHandler(BaseHTTPRequestHandler):
    server: AgentHubHTTPServer

    def do_GET(self) -> None:
        path = _request_path(self.path)
        if path in {"/", ""}:
            self._send_html(self._root_html())
            return
        if path == "/dashboard":
            self._send_html(self._root_html())
            return
        if path == "/v1/status":
            self._send_json(_status_body(self.server.config, self.server.router))
            return
        if path == "/v1/routing/status":
            self._send_diagnostics_json(_routing_status_body(self.server.config, self.server.router))
            return
        if path == "/v1/routing/last-decision":
            self._send_diagnostics_json(_routing_last_decision_body(self.server.config))
            return
        if path == "/v1/routing/test-failover":
            self._send_diagnostics_json(_routing_test_failover_body(self.server.config, self.server.router))
            return
        if path == "/v1/limits":
            self._send_diagnostics_json(_limits_body(self.server.config, self.server.router))
            return
        if path == "/v1/usage":
            self._send_diagnostics_json(
                usage_snapshot(
                    self.server.config.state_dir,
                    self.server.router.health_snapshot(include_history=True),
                )
            )
            return
        if path == "/v1/client-sources":
            self._send_diagnostics_json(_client_sources_body(self.server.config, self.server.router))
            return
        if path == "/v1/routing-history":
            self._send_json(_routing_history_body(self.server.config))
            return
        if path == "/v1/provider-scores":
            self._send_json(_provider_scores_body(self.server.config))
            return
        if path == "/v1/provider-health":
            self._send_diagnostics_json(_provider_health_body(self.server.config, self.server.router))
            return
        if path == "/v1/events":
            self._send_diagnostics_json(_events_body(self.server.config))
            return
        if path == "/v1/tools":
            self._send_diagnostics_json(_tools_body(self.server.router))
            return
        if path == "/v1/workflows/status":
            self._send_diagnostics_json(_workflow_status_body(self.server.config))
            return
        if path == "/v1/plugins":
            self._send_diagnostics_json(_plugins_body(self.server.config))
            return
        if path == "/v1/enterprise/audit":
            self._send_diagnostics_json(_enterprise_audit_body(self.server.config, _request_query(self.path)))
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
                        "max_context_tokens": self.server.config.max_context_tokens,
                        "compatibility_mode": self.server.config.compatibility_mode,
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
                    "streaming": {
                        "force_compatibility_streaming": self.server.config.force_compatibility_streaming,
                    },
                    "repo_ignore_patterns": self.server.config.repo_ignore_patterns,
                    "plugins": _plugins_body(self.server.config),
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
                    "providers": self.server.router.provider_status(),
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
                redact_secrets(
                    usage_snapshot(
                        self.server.config.state_dir,
                        self.server.router.health_snapshot(include_history=True),
                    )
                )
            )
            return
        if path == "/permissions":
            self._send_json(
                redact_secrets(
                    permission_snapshot(
                        self.server.config.state_dir,
                        approval_mode=self.server.config.approval_mode,
                        safe_mode=self.server.config.approval_mode == "safe",
                    )
                )
            )
            return
        if path == "/metrics":
            self._send_json(
                redact_secrets(
                    metrics_snapshot(
                        self.server.config.state_dir,
                        self.server.router.health_snapshot(include_history=True),
                    )
                )
            )
            return
        if path == "/debug/request":
            self._send_json(
                redact_secrets(
                    {
                        "object": "agent_hub.debug.request",
                        "recent": list(reversed(self.server.debug_requests[-20:])),
                    }
                )
            )
            return
        if path == "/debug/context":
            self._send_json(
                redact_secrets(
                    {
                        "object": "agent_hub.debug.context",
                        "summary": _debug_context_summary(self.server),
                        "recent": list(reversed(self.server.debug_requests[-20:])),
                    }
                )
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
        if path.startswith("/v1/workflows/"):
            workflow = path.rsplit("/", 1)[-1]
            self._handle_workflow(payload, workflow)
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

    def _handle_workflow(self, payload: dict[str, Any], workflow: str) -> None:
        payload = _payload_with_header_metadata(payload, self.headers)
        request = request_from_payload(payload, api_shape="native")
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
        request = _attach_internal_client_metadata(request, api_shape=api_shape)
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
        _apply_model_routing(self.server.config, request)
        model_error = _model_lookup_error(self.server.config, request)
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
        if response_shape == "native" and request.stream:
            self._send_native_stream(
                request,
                agent_mode=_wants_agent_mode(payload, default=agent_mode_default),
            )
            return
        mode = _payload_mode(payload, default_agent=agent_mode_default)
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
        status = _status_body(config, self.server.router)
        enabled_agents = [
            name
            for name, agent in config.agents.items()
            if agent.enabled
        ]
        agents = ", ".join(enabled_agents) or "none"
        active = ", ".join(status["active_providers"]) or "none"
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
    <table>
      <thead><tr><th>Provider</th><th>Model</th><th>Health</th><th>Score</th><th>Latency</th><th>Tools</th></tr></thead>
      <tbody>
        {''.join(_provider_row_html(row) for row in status["providers"][:12])}
      </tbody>
    </table>
    <p>
      <a href="/v1/status">Status JSON</a> |
      <a href="/v1/routing-history">Routing History</a> |
      <a href="/v1/provider-scores">Provider Scores</a>
    </p>
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
            if not _safe_write(self, f"data: {data}\n\n"):
                return
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
            if not _safe_write(self, f"event: {name}\n"):
                return
            if not _safe_write(self, f"data: {json.dumps(event, ensure_ascii=False)}\n\n"):
                return
        _safe_flush(self)

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
            if not _safe_write(self, f"data: {data}\n\n"):
                return
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


def _stream_response_headers(stream: Any, router: AgentRouter) -> dict[str, str]:
    health = router.health_snapshot().get(stream.agent.name, {})
    fallback_models = [
        event.model
        for event in stream.failover
        if event and event.model
    ]
    values = {
        "X-Agent-Hub-Agent": stream.agent.name,
        "X-Agent-Hub-Provider": stream.agent.provider,
        "X-Agent-Hub-Model": stream.model,
        "X-Agent-Hub-Active-Model": stream.model,
        "X-Agent-Hub-Provider-Score": health.get("score"),
        "X-Agent-Hub-Fallback-Models": ",".join(fallback_models),
        "X-AgentHub-Provider": stream.agent.provider,
        "X-AgentHub-Model": stream.model,
        "X-AgentHub-Fallback": ",".join(fallback_models),
    }
    return {
        name: _safe_header_value(value)
        for name, value in values.items()
        if _safe_header_value(value)
    }


def _recover_native_stream(
    server: AgentHubHTTPServer,
    stream: Any,
    *,
    replay_required: bool = True,
    emitted_text: str = "",
) -> Any | None:
    policy = str(getattr(server.config, "native_stream_failure_policy", "recover") or "recover")
    routing = getattr(server.config, "routing", {}) or {}
    if policy == "recover":
        policy = "fallback_provider"
    if policy == "terminate":
        return None
    if replay_required and not str(emitted_text or "").strip() and not _stream_replay_safe(getattr(stream, "request", None)):
        return None
    if policy == "retry_same_provider":
        request = _stream_recovery_request(
            stream.request,
            recovery="retry_same_provider",
            emitted_text=emitted_text,
        )
        return server.router.native_stream_for_agent(request, stream.agent.name)
    if policy == "fallback_provider":
        server.router.cooldown_agent(stream.agent.name, getattr(stream.agent, "cooldown_seconds", 1.0))
        request = _stream_recovery_request(
            stream.request,
            recovery="fallback_provider",
            emitted_text=emitted_text,
        )
        return server.router.native_stream(request)
    return None


def _stream_replay_safe(request: Any) -> bool:
    raw = request.raw if request is not None and isinstance(getattr(request, "raw", None), dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (
        hub.get("stream_replay_safe"),
        hub.get("replay_safe"),
        raw.get("stream_replay_safe"),
        raw.get("replay_safe"),
    ):
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _stream_recovery_request(request: Any, *, recovery: str, emitted_text: str = "") -> Any:
    raw = dict(request.raw or {})
    hub = dict(raw.get("agent_hub") or {})
    hub["stream_recovery_attempt"] = recovery
    raw["agent_hub"] = hub
    partial = str(emitted_text or "").strip()
    if not partial:
        return replace(request, raw=raw, record_session=False)
    messages = [
        *[dict(message) for message in request.messages],
        {
            "role": "assistant",
            "content": partial,
            "agent_hub_partial_response": True,
        },
        {
            "role": "user",
            "content": (
                "Continue from the exact point where the stream stopped. "
                "Do not repeat completed text. Preserve the requested format, JSON/schema "
                "requirements, tool state, and task context."
            ),
            "agent_hub_stream_recovery_instruction": True,
        },
    ]
    return replace(request, messages=messages, raw=raw, record_session=False)


def _trim_stream_overlap(prefix: str, suffix: str) -> str:
    if not prefix or not suffix:
        return suffix
    max_overlap = min(len(prefix), len(suffix), 4000)
    for size in range(max_overlap, 0, -1):
        if prefix[-size:] == suffix[:size]:
            return suffix[size:]
    return suffix


def _safe_header_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:1000]


def _safe_write(handler: AgentHubHandler, text: str) -> bool:
    try:
        handler.wfile.write(text.encode("utf-8"))
        return True
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return False


def _safe_flush(handler: AgentHubHandler) -> None:
    try:
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return


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


def _status_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    routing = recent_events(config.state_dir, "routing", limit=50)
    tools = recent_events(config.state_dir, "tools", limit=50)
    latest = routing[-1] if routing else {}
    return {
        "object": "agent_hub.status",
        "status": "running",
        "running": True,
        "version": BACKEND_VERSION,
        "features": BACKEND_FEATURES,
        "workspace_dir": str(config.workspace_dir),
        "active_providers": _active_provider_names(config, router),
        "providers": router.provider_status(),
        "provider_health": health,
        "provider_scores": ProviderScoreStore(config.state_dir).load(),
        "selected_model": latest.get("model") or latest.get("selected_model"),
        "stream_mode": latest.get("stream_mode") or ("native" if latest.get("type") == "streaming_decision" else "compatibility"),
        "token_usage": usage_snapshot(config.state_dir, health),
        "fallback_history": _routing_failures(routing),
        "workflow_stages": _recent_workflow_stages(routing),
        "tool_calls": tools[-25:],
        "routing_history_count": len(routing),
    }


def _routing_status_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    routing = recent_events(config.state_dir, "routing", limit=100)
    latest = _latest_routing_decision(routing)
    recommendations = router.recommend(
        HubRequest(
            session_id="routing-status",
            route="cloud-agent",
            messages=[{"role": "user", "content": "diagnose active routing"}],
            record_session=False,
        ),
        limit=12,
        needs_tools=True,
        include_unavailable=True,
    )
    return {
        "object": "agent_hub.routing.status",
        "status": "running",
        "running": True,
        "active_provider": latest.get("agent") or latest.get("selected_agent"),
        "active_model": latest.get("model") or latest.get("selected_model"),
        "routing_candidates": recommendations,
        "degraded_providers": [row for row in health.values() if row.get("degraded")],
        "cooldowns": {
            name: row.get("cooldown_until")
            for name, row in health.items()
            if row.get("cooldown_until")
        },
        "last_failover_reason": _last_failover_reason(routing),
        "last_decision": latest,
        "client_sources": _client_source_counts(config, health),
        "streaming_stats": {
            name: {
                "streaming_tokens_per_second": row.get("streaming_tokens_per_second"),
                "last_first_token_latency_seconds": row.get("last_first_token_latency_seconds"),
            }
            for name, row in health.items()
            if row.get("supports_streaming")
        },
        "provider_health": health,
    }


def _routing_last_decision_body(config: HubConfig) -> dict[str, Any]:
    routing = recent_events(config.state_dir, "routing", limit=100)
    latest = _latest_routing_decision(routing)
    return {
        "object": "agent_hub.routing.last_decision",
        "decision": latest,
        "failover": latest.get("failover", []) if isinstance(latest, dict) else [],
    }


def _routing_test_failover_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    request = HubRequest(
        session_id="routing-test-failover",
        route="cloud-agent",
        messages=[{"role": "user", "content": "simulate provider failover"}],
        record_session=False,
    )
    candidates = router.recommend(
        request,
        limit=20,
        needs_tools=True,
        include_unavailable=True,
    )
    available = [row for row in candidates if row.get("available")]
    simulated_failed = available[0] if available else (candidates[0] if candidates else None)
    simulated_next = next(
        (row for row in candidates if simulated_failed and row.get("agent") != simulated_failed.get("agent") and row.get("available")),
        None,
    )
    return {
        "object": "agent_hub.routing.test_failover",
        "dry_run": True,
        "source": "diagnostics",
        "selected": simulated_failed,
        "next_compatible_provider": simulated_next,
        "candidates": candidates,
        "message": "Dry run only; no provider request was sent and no cooldown was changed.",
    }


def _client_sources_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    return {
        "object": "agent_hub.client_sources",
        "sources": _client_source_counts(config, health),
        "recent_requests": recent_events(config.state_dir, "requests", limit=100),
    }


def _routing_history_body(config: HubConfig) -> dict[str, Any]:
    events = recent_events(config.state_dir, "routing", limit=100)
    return {
        "object": "agent_hub.routing_history",
        "data": events,
        "count": len(events),
    }


def _provider_scores_body(config: HubConfig) -> dict[str, Any]:
    scores = ProviderScoreStore(config.state_dir).load()
    return {
        "object": "agent_hub.provider_scores",
        "benchmark_types": [
            "coding",
            "reasoning",
            "summarization",
            "tool_calling",
            "long_context",
            "latency",
        ],
        "data": scores,
    }


def _provider_health_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    return {
        "object": "agent_hub.provider_health",
        "providers": router.provider_status(),
        "health": health,
        "recent_failures": metrics_snapshot(config.state_dir, health).get("recent_failures", []),
    }


def _events_body(config: HubConfig) -> dict[str, Any]:
    return {
        "object": "agent_hub.events",
        "events": recent_events(config.state_dir, "events", limit=100),
        "routing": recent_events(config.state_dir, "routing", limit=50),
        "workflows": recent_events(config.state_dir, "workflows", limit=50),
    }


def _tools_body(router: AgentRouter) -> dict[str, Any]:
    tools = [tool.to_agent_hub_spec() for tool in router.tool_registry.list()]
    return {
        "object": "agent_hub.tools",
        "count": len(tools),
        "tools": tools,
    }


def _workflow_status_body(config: HubConfig) -> dict[str, Any]:
    events = recent_events(config.state_dir, "workflows", limit=100)
    return {
        "object": "agent_hub.workflow_status",
        "recent": events,
        "active": [],
        "count": len(events),
    }


def _plugins_body(config: HubConfig) -> dict[str, Any]:
    return discover_plugins(config).to_dict()


def _enterprise_audit_body(config: HubConfig, query: dict[str, str] | None = None) -> dict[str, Any]:
    query = query or {}
    export = export_enterprise_audit(
        config.state_dir,
        limit=_positive_int(query.get("limit"), default=100, maximum=1000),
        user=query.get("user") or query.get("actor_id"),
        workspace=query.get("workspace") or query.get("workspace_id"),
        action=query.get("action"),
        allowed=_allowed_query(query),
        start_at=query.get("start_at") or query.get("from"),
        end_at=query.get("end_at") or query.get("to"),
        retention_days=getattr(config, "enterprise_audit_retention_days", None),
    )
    events = export["events"]
    return {
        "object": "agent_hub.enterprise_audit",
        "count": len(events),
        "recent": events,
        "export": export,
    }


def _provider_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(row.get('health'))}</td>"
        f"<td>{_html(row.get('score'))}</td>"
        f"<td>{_html(row.get('latency_ms'))} ms</td>"
        f"<td>{str(bool(row.get('supports_tools'))).lower()}</td>"
        "</tr>"
    )


def _routing_failures(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for event in events:
        failover = event.get("failover")
        if isinstance(failover, list) and failover:
            failures.extend(item for item in failover if isinstance(item, dict))
        elif event.get("type") == "routing_failure":
            failures.append(event)
    return failures[-25:]


def _latest_routing_decision(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("type") in {
            "routing_decision",
            "stream_request_started",
            "request_started",
            "native_stream_finished",
            "routing_failure",
        }:
            return dict(event)
    return dict(events[-1]) if events else {}


def _last_failover_reason(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        failover = event.get("failover")
        if isinstance(failover, list):
            for item in reversed(failover):
                if isinstance(item, dict) and item.get("reason"):
                    return str(item["reason"])
        if event.get("type") == "routing_failure" and event.get("message"):
            return str(event["message"])
    return ""


def _client_source_counts(config: HubConfig, health: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    requests = recent_events(config.state_dir, "requests", limit=100)
    routing = recent_events(config.state_dir, "routing", limit=100)
    for event in [*requests, *routing]:
        source = _event_source(event)
        counts[source] = counts.get(source, 0) + 1
    for row in health.values():
        source = row.get("last_request_source")
        if isinstance(source, str) and source:
            counts[source] = counts.get(source, 0) + 1
    return {
        "counts": counts,
        "known_sources": sorted(counts),
        "recent": [
            {
                "time": event.get("time"),
                "source": _event_source(event),
                "api_shape": event.get("api_shape"),
                "route": event.get("route"),
                "stream": event.get("stream"),
            }
            for event in requests[-25:]
        ],
    }


def _event_source(event: dict[str, Any]) -> str:
    for key in ("source", "client", "request_source", "last_request_source"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    api_shape = event.get("api_shape")
    if isinstance(api_shape, str) and api_shape.strip():
        return api_shape.strip()
    return "unknown"


def _recent_workflow_stages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events[-50:]
        if isinstance(event.get("workflow_stage"), str) or str(event.get("type", "")).startswith("workflow_")
    ][-25:]


def _html(value: Any) -> str:
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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
        "remaining": health.get("remaining", "unknown"),
        "quota_state": health.get("quota_state", "unknown"),
        "quota_source": health.get("quota_source", "unknown"),
        "quota_remaining": health.get("quota_remaining"),
        "requests_remaining": health.get("requests_remaining"),
        "tokens_remaining": health.get("tokens_remaining"),
        "credits_remaining": health.get("credits_remaining"),
        "rate_limit_reset_at": health.get("rate_limit_reset_at"),
        "cooldown_until": health.get("cooldown_until"),
        "unavailable_until": health.get("unavailable_until"),
        "last_error_type": health.get("last_error_type"),
        "last_error_message": health.get("last_error_message"),
        "average_latency_seconds": health.get("average_latency_seconds"),
        "tokens_per_second": health.get("average_tokens_per_second"),
        "context_limit": health.get("context_window"),
        "output_limit": health.get("max_output_tokens"),
        "last_request_source": health.get("last_request_source"),
        "last_failover_attempts": health.get("last_failover_attempts"),
        "stream_interruption_count": health.get("stream_interruption_count", 0),
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
        "remaining": row.get("remaining", "unknown"),
        "quota_state": row.get("quota_state", "unknown"),
        "requests_remaining": row.get("requests_remaining"),
        "tokens_remaining": row.get("tokens_remaining"),
        "credits_remaining": row.get("credits_remaining"),
        "rate_limit_reset_at": row.get("rate_limit_reset_at"),
        "cooldown_until": row.get("cooldown_until"),
        "average_latency_seconds": row.get("average_latency_seconds"),
        "tokens_per_second": row.get("tokens_per_second"),
        "context_limit": row.get("context_limit"),
        "output_limit": row.get("output_limit"),
        "source_client": row.get("last_request_source"),
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


def _model_lookup_error(config: HubConfig, request: HubRequest) -> dict[str, Any] | None:
    if request.api_shape not in {"openai-chat", "openai-responses", "anthropic-messages"}:
        return None
    raw = request.raw if isinstance(request.raw, dict) else {}
    model = raw.get("model")
    if not isinstance(model, str) or not model.strip():
        return None
    normalized = model.strip().lower()
    known_routes = {route.name.lower() for route in config.routes}
    known_agents = {agent.name.lower() for agent in config.agents.values()}
    known_models = {agent.model.lower() for agent in config.agents.values()}
    known_aliases = set(ROUTE_MODEL_ALIASES)
    if normalized in known_routes | known_agents | known_models | known_aliases:
        return None
    for prefix in ("agent:", "agent-hub-agent:"):
        if normalized.startswith(prefix):
            target = model.strip()[len(prefix) :].strip().lower()
            if target in known_agents:
                return None
    if normalized.startswith("agent:") or normalized.startswith("agent-hub"):
        return {
            "message": f"Model {model!r} was not found in Agent Hub routes or agents.",
            "type": "model_not_found",
            "suggested_fix": "Use /v1/models, agent-hub-coding, a configured route name, or agent:<agent-name>.",
        }
    return None


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


def _request_query(path: str) -> dict[str, str]:
    if "?" not in path:
        return {}
    parsed = parse_qs(path.split("?", 1)[1], keep_blank_values=False)
    return {
        key: values[-1]
        for key, values in parsed.items()
        if values
    }


def _allowed_query(query: dict[str, str]) -> bool | None:
    if "allowed" in query:
        return _query_bool(query["allowed"])
    if "allow" in query and _query_bool(query["allow"]) is True:
        return True
    for key in ("deny", "denied"):
        if key in query and _query_bool(query[key]) is True:
            return False
    return None


def _query_bool(value: str) -> bool | None:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "allow", "allowed"}:
        return True
    if text in {"0", "false", "no", "off", "deny", "denied"}:
        return False
    return None


def _diagnostics_auth_error(config: HubConfig, headers: Any) -> tuple[dict[str, Any], int] | None:
    if not _diagnostics_auth_required(config):
        return None
    expected = _diagnostics_token(config)
    if not expected:
        return (
            {
                "error": {
                    "type": "diagnostics_auth_not_configured",
                    "message": (
                        "Diagnostics endpoints require diagnostics_auth_token or "
                        "diagnostics_auth_token_env when Agent Hub is bound publicly."
                    ),
                }
            },
            403,
        )
    provided = _diagnostics_token_from_headers(headers)
    if provided and hmac.compare_digest(provided, expected):
        return None
    return (
        {
            "error": {
                "type": "diagnostics_auth_required",
                "message": "Diagnostics authentication is required for this endpoint.",
            }
        },
        401,
    )


def _diagnostics_auth_required(config: HubConfig) -> bool:
    return _public_bind_host(str(getattr(config, "host", "127.0.0.1") or "127.0.0.1"))


def _diagnostics_token(config: HubConfig) -> str:
    explicit = getattr(config, "diagnostics_auth_token", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    env_name = getattr(config, "diagnostics_auth_token_env", None)
    if isinstance(env_name, str) and env_name:
        return os.environ.get(env_name, "")
    return ""


def _diagnostics_token_from_headers(headers: Any) -> str:
    direct = headers.get("X-Agent-Hub-Diagnostics-Token")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    auth = headers.get("Authorization")
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _public_bind_host(host: str) -> bool:
    value = host.strip().lower()
    if value in {"", "localhost", "127.0.0.1", "::1"}:
        return False
    if value in {"0.0.0.0", "::", "[::]"}:
        return True
    try:
        import ipaddress

        address = ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return True
    return not address.is_loopback


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
    user_agent = headers.get("User-Agent")
    if isinstance(user_agent, str) and user_agent.strip():
        metadata.setdefault("user_agent", user_agent.strip()[:300])
        client = _known_client_from_user_agent(user_agent)
        if client:
            metadata.setdefault("client", client)
            metadata.setdefault("source", client)
    for header_name, key in (
        ("X-Agent-Hub-Client", "client"),
        ("X-Cline-Version", "cline_version"),
        ("X-Continue-Version", "continue_version"),
        ("Anthropic-Version", "anthropic_version"),
        ("OpenAI-Organization", "openai_compatible_header"),
    ):
        value = headers.get(header_name)
        if isinstance(value, str) and value.strip():
            metadata.setdefault(key, value.strip()[:200])
    if not metadata:
        return payload
    copied = dict(payload)
    copied["metadata"] = metadata
    return copied


def _attach_internal_client_metadata(request: HubRequest, *, api_shape: str) -> HubRequest:
    metadata = dict(request.metadata or {})
    raw = dict(request.raw or {})
    hub = dict(raw.get("agent_hub") or {})
    user_agent = str(metadata.get("user_agent") or "")
    detected_client = (
        str(metadata.get("source") or metadata.get("client") or "").strip()
        or _known_client_from_user_agent(user_agent)
    )
    if api_shape == "openai-chat" and detected_client == "cline":
        metadata.setdefault("source", "cline")
        metadata.setdefault("client", "cline")
        metadata.setdefault("client_compatibility", "openai")
        metadata["health_tracking_enabled"] = True
    elif api_shape in {"openai-chat", "openai-responses", "anthropic-messages"}:
        metadata.setdefault("source", detected_client or api_shape)
        metadata.setdefault("client_compatibility", _compatibility_label(api_shape))
        metadata["health_tracking_enabled"] = True
    else:
        metadata.setdefault("source", detected_client or "native")
        metadata.setdefault("client_compatibility", _compatibility_label(api_shape))
        metadata.setdefault("health_tracking_enabled", True)
    hub.setdefault("source", metadata.get("source"))
    hub.setdefault("client_compatibility", metadata.get("client_compatibility"))
    hub.setdefault("health_tracking_enabled", True)
    raw["agent_hub"] = hub
    return replace(request, metadata=metadata, raw=raw)


def _compatibility_label(api_shape: str) -> str:
    if api_shape in {"openai-chat", "openai-responses"}:
        return "openai"
    if api_shape == "anthropic-messages":
        return "anthropic"
    return "native"


def _known_client_from_user_agent(value: str) -> str:
    lowered = value.lower()
    for marker, client in (
        ("cline", "cline"),
        ("continue", "continue"),
        ("claude-code", "claude-code"),
        ("claude_code", "claude-code"),
        ("vscode", "vscode"),
        ("visual studio code", "vscode"),
    ):
        if marker in lowered:
            return client
    return ""


def _has_session_key(data: dict[str, Any]) -> bool:
    return any(
        isinstance(data.get(key), str) and str(data.get(key)).strip()
        for key in ("session_id", "conversation_id", "thread_id")
    )
