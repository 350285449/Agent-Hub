from __future__ import annotations

import json
import hashlib
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .agent_runner import AgentRunner
from .application import (
    AdaptiveApplicationService,
    BACKEND_FEATURES,
    BACKEND_VERSION,
    DiagnosticsApplicationService,
    run_analytics_maintenance,
)
from .api.compatibility import (
    apply_model_routing,
    anthropic_sse_frames,
    compatibility_endpoint,
    debug_api_shape,
    error_response_for_shape,
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
from .config import MAX_REQUEST_SIZE, HubConfig
from .context import request_context_diagnostics
from .models import HubRequest, HubResponse
from .observability import permission_snapshot, recent_events, record_event, usage_snapshot
from .permissions import UNTRUSTED_EXTERNAL, mark_trusted_approval
from .application.routing_profile_service import RoutingProfileApplicationService
from .plugins.registration import apply_plugin_registrations
from .runtime_kernel import AgentHubRuntimeKernel
from .security.credentials import ensure_local_credentials
from .security.secrets import redact_secrets
from .streaming import safe_stream_failure_chunk
from .core.router import NO_TOOL_CAPABLE_MODEL, AgentRouter, RouterError
from .team_agent_runner import TeamAgentRunner
from .tools.workspace_state import _checkpoint_base_dir, restore_workspace_checkpoint
from .version import build_metadata, config_runtime_hash
from .workflows import WorkflowEngine
from .server_routes.middleware import (
    api_auth_error as _api_auth_error,
    api_token as _api_token,
    diagnostics_auth_error as _diagnostics_auth_error,
    diagnostics_auth_required as _diagnostics_auth_required,
    diagnostics_token as _diagnostics_token,
    diagnostics_token_from_headers as _diagnostics_token_from_headers,
    public_bind_host as _public_bind_host,
    request_path as _request_path,
    request_query as _request_query,
    trusted_approval_from_headers as _trusted_approval_from_headers,
)
from .server_routes import (
    handle_delete as handle_route_delete,
    handle_get as handle_route_get,
    handle_post as handle_route_post,
)
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
    _routing_intelligence_body,
    _provider_health_body,
    _routing_memory_stats_body,
    _routing_memory_recent_body,
    _routing_decision_by_id_body,
    _status_body,
    _events_body,
    _tools_body,
    _workflow_status_body,
    _plugins_body,
    _enterprise_audit_body,
    _provider_row_html,
    _optimization_dashboard_html,
    _routing_intelligence_dashboard_html,
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


CLINE_PERMISSION_GUIDANCE_TTL_SECONDS = 90.0
CLINE_PERMISSION_GUIDANCE_MAX_ENTRIES = 128
_CLINE_PERMISSION_GUIDANCE_CACHE: dict[str, float] = {}
DIAGNOSTICS_CACHE_TTL_SECONDS = 1.5
DIAGNOSTICS_CACHE_MAX_ENTRIES = 128


class PayloadTooLargeError(ValueError):
    pass


DIAGNOSTIC_ENDPOINTS = {
    "/v1/provider-health",
    "/v1/provider-scores",
    "/v1/routing-memory/stats",
    "/v1/routing-memory/recent",
    "/v1/routing/status",
    "/v1/routing/last-decision",
    "/v1/routing-profiles",
    "/v1/routing-intelligence",
    "/v1/routing/test-failover",
    "/v1/routing-history",
    "/v1/feature-scorecard",
    "/v1/inbox/status",
    "/v1/mcp/status",
    "/v1/limits",
    "/v1/usage",
    "/v1/client-sources",
    "/v1/events",
    "/v1/kernel",
    "/v1/optimization",
    "/v1/tools",
    "/v1/workflows/status",
    "/v1/workflow-presets",
    "/v1/workflow-templates",
    "/v1/plugins",
    "/v1/audit",
    "/v1/extension-contract",
    "/v1/enterprise/audit",
    "/openapi.json",
    "/api/metrics/summary",
    "/api/metrics/savings",
    "/api/benchmarks",
    "/api/benchmarks/run",
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


def _compact_number(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}k"
    return str(int(number))


def _latest_boost_explanation(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        trace = event.get("optimization_trace") if isinstance(event.get("optimization_trace"), dict) else {}
        boost = event.get("boost_explanation") if isinstance(event.get("boost_explanation"), dict) else {}
        if boost:
            if trace and "optimization_trace" not in boost:
                boost = dict(boost)
                boost["optimization_trace"] = trace
            return boost
        decision = event.get("routing_decision") if isinstance(event.get("routing_decision"), dict) else {}
        explanation = decision.get("explanation") if isinstance(decision.get("explanation"), dict) else {}
        context = explanation.get("context_optimization") if isinstance(explanation.get("context_optimization"), dict) else {}
        selected = explanation.get("selected") if isinstance(explanation.get("selected"), dict) else {}
        quality = event.get("quality_check") if isinstance(event.get("quality_check"), dict) else {}
        if context or selected:
            return {
                "tokens_saved": context.get("tokens_saved"),
                "tokens_saved_percent": trace.get("tokens_saved_percent", context.get("saved_percent")),
                "files_selected": {
                    "selected": trace.get("selected_files", len(context.get("selected_files") or [])),
                    "total": context.get("total_files"),
                    "paths": context.get("selected_files") or [],
                },
                "model_selected": selected.get("model") or event.get("model"),
                "quality_check": quality,
                "optimization_trace": trace,
            }
    return {}


class AgentHubHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], config: HubConfig) -> None:
        super().__init__(server_address, AgentHubHandler)
        self.config = config
        try:
            self.config.initialization_report["analytics_maintenance"] = run_analytics_maintenance(self.config)
        except Exception as exc:
            self.config.initialization_report["analytics_maintenance"] = {
                "object": "agent_hub.analytics_maintenance",
                "enabled": bool(getattr(self.config, "analytics_compaction_enabled", False)),
                "error": str(exc),
            }
        apply_plugin_registrations(self.config)
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
        self.runtime_kernel = AgentHubRuntimeKernel()
        self._diagnostics_cache: dict[str, dict[str, Any]] = {}
        self._diagnostics_cache_lock = threading.RLock()
        self._diagnostics_cache_hits = 0
        self._diagnostics_cache_misses = 0
        self._diagnostics_cache_invalidations = 0
        self._rate_limit_lock = threading.RLock()
        self._rate_limit_windows: dict[str, tuple[float, int]] = {}

    def diagnostics_cache_get(
        self,
        key: str,
        ttl_seconds: float,
        builder: Any,
    ) -> tuple[Any, bool]:
        now = time.monotonic()
        ttl = max(0.05, float(ttl_seconds or DIAGNOSTICS_CACHE_TTL_SECONDS))
        with self._diagnostics_cache_lock:
            entry = self._diagnostics_cache.get(key)
            if entry and float(entry.get("expires_at") or 0.0) > now:
                entry["last_access"] = now
                self._diagnostics_cache_hits += 1
                return entry.get("value"), True
            self._diagnostics_cache_misses += 1
        value = builder()
        with self._diagnostics_cache_lock:
            self._diagnostics_cache[key] = {
                "value": value,
                "expires_at": now + ttl,
                "last_access": now,
            }
            self._prune_diagnostics_cache_locked(now)
        return value, False

    def invalidate_diagnostics_cache(self, reason: str = "") -> None:
        with self._diagnostics_cache_lock:
            if self._diagnostics_cache:
                self._diagnostics_cache.clear()
            self._diagnostics_cache_invalidations += 1

    def diagnostics_cache_stats(self) -> dict[str, Any]:
        with self._diagnostics_cache_lock:
            hits = self._diagnostics_cache_hits
            misses = self._diagnostics_cache_misses
            total = hits + misses
            return {
                "object": "agent_hub.diagnostics_cache",
                "enabled": True,
                "ttl_seconds": DIAGNOSTICS_CACHE_TTL_SECONDS,
                "max_entries": DIAGNOSTICS_CACHE_MAX_ENTRIES,
                "entries": len(self._diagnostics_cache),
                "hits": hits,
                "misses": misses,
                "hit_rate": round(hits / total, 4) if total else 0.0,
                "invalidations": self._diagnostics_cache_invalidations,
            }

    def _prune_diagnostics_cache_locked(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._diagnostics_cache.items()
            if float(entry.get("expires_at") or 0.0) <= now
        ]
        for key in expired:
            self._diagnostics_cache.pop(key, None)
        overflow = len(self._diagnostics_cache) - DIAGNOSTICS_CACHE_MAX_ENTRIES
        if overflow <= 0:
            return
        oldest = sorted(
            self._diagnostics_cache.items(),
            key=lambda item: float(item[1].get("last_access") or 0.0),
        )
        for key, _entry in oldest[:overflow]:
            self._diagnostics_cache.pop(key, None)


class AgentHubHandler(BaseHTTPRequestHandler):
    server: AgentHubHTTPServer

    def do_GET(self) -> None:
        self._begin_kernel_request()
        try:
            if self._reject_disallowed_origin():
                return
            if self._reject_rate_limited_request():
                return
            if self._reject_unauthenticated_public_request():
                return
            path = _request_path(self.path)
            if handle_route_get(self, path):
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception:
            self._kernel_response_status = 500
            raise
        finally:
            self._finish_kernel_request()

    def do_OPTIONS(self) -> None:
        self._begin_kernel_request()
        try:
            if self._reject_disallowed_origin():
                return
            if self._reject_rate_limited_request():
                return
            self.send_response(204)
            self._send_common_headers()
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, DELETE, OPTIONS",
            )
            self.send_header(
                "Access-Control-Allow-Headers",
                (
                    "Authorization, Content-Type, X-API-Key, API-Key, "
                    "Anthropic-Version, Anthropic-Beta, X-Agent-Hub-Session-ID, "
                    "X-Session-ID, X-Conversation-ID, X-Thread-ID, "
                    "X-Agent-Hub-API-Token, X-Agent-Hub-Diagnostics-Token, "
                    "X-Agent-Hub-Approval-Token, X-Agent-Hub-Client"
                ),
            )
            self.end_headers()
        except Exception:
            self._kernel_response_status = 500
            raise
        finally:
            self._finish_kernel_request()

    def do_POST(self) -> None:
        self._begin_kernel_request()
        try:
            if self._reject_disallowed_origin():
                return
            if self._reject_rate_limited_request(drain_body=True):
                return
            if self._reject_oversized_request_body():
                return
            if self._reject_unauthenticated_public_request(drain_body=True):
                return
            try:
                payload = self._read_json()
            except PayloadTooLargeError as exc:
                self._send_json({"error": str(exc)}, status=413)
                return
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return

            path = _request_path(self.path)
            if handle_route_post(self, path, payload):
                self.server.invalidate_diagnostics_cache(f"POST {path}")
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception:
            self._kernel_response_status = 500
            raise
        finally:
            self._finish_kernel_request()

    def do_DELETE(self) -> None:
        self._begin_kernel_request()
        try:
            if self._reject_disallowed_origin():
                return
            if self._reject_rate_limited_request():
                return
            if self._reject_unauthenticated_public_request():
                return
            path = _request_path(self.path)
            if handle_route_delete(self, path):
                return
            if path == "/v1/routing-memory":
                auth_error = _diagnostics_auth_error(self.server.config, self.headers)
                if auth_error is not None:
                    body, status = auth_error
                    self._send_json(body, status=status)
                    return
                body = self.server.router.routing_memory.reset()
                self.server.invalidate_diagnostics_cache("DELETE /v1/routing-memory")
                self._send_json(body)
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception:
            self._kernel_response_status = 500
            raise
        finally:
            self._finish_kernel_request()

    def send_response(self, code: int, message: str | None = None) -> None:
        self._kernel_response_status = int(code)
        super().send_response(code, message)

    def _begin_kernel_request(self) -> None:
        self._kernel_request_started_at = time.perf_counter()
        self._kernel_response_status = 200
        self._kernel_cache_state = ""
        self.server.runtime_kernel.begin_request()

    def _finish_kernel_request(self) -> None:
        started_at = getattr(self, "_kernel_request_started_at", None)
        if started_at is None:
            return
        duration_ms = (time.perf_counter() - float(started_at)) * 1000
        self.server.runtime_kernel.record_request(
            method=getattr(self, "command", ""),
            path=_request_path(getattr(self, "path", "/")),
            status=int(getattr(self, "_kernel_response_status", 200) or 200),
            duration_ms=duration_ms,
            cache_state=str(getattr(self, "_kernel_cache_state", "") or ""),
        )
        self._kernel_request_started_at = None

    def _reject_unauthenticated_public_request(self, *, drain_body: bool = False) -> bool:
        auth_error = _api_auth_error(self.server.config, self.headers)
        if auth_error is None:
            return False
        if drain_body:
            self._discard_request_body()
        body, status = auth_error
        self._send_json(body, status=status)
        return True

    def _reject_disallowed_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not isinstance(origin, str) or not origin.strip():
            return False
        if self._allowed_cors_origin():
            return False
        self._send_json(
            {
                "error": {
                    "type": "cors_origin_rejected",
                    "message": "Origin is not allowed by Agent Hub CORS policy.",
                }
            },
            status=403,
        )
        return True

    def _reject_oversized_request_body(self) -> bool:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return False
        maximum = int(getattr(self.server.config, "max_json_body_bytes", MAX_REQUEST_SIZE) or MAX_REQUEST_SIZE)
        if length <= maximum:
            return False
        drained = self._discard_request_body(max_bytes=max(8 * 1024 * 1024, maximum * 2))
        self.close_connection = not drained
        self._send_json(
            {
                "error": {
                    "type": "request_body_too_large",
                    "message": f"JSON request body exceeds the {maximum} byte limit.",
                }
            },
            status=413,
            headers={"Connection": "close"} if not drained else None,
        )
        return True

    def _reject_rate_limited_request(self, *, drain_body: bool = False) -> bool:
        config = self.server.config
        if not _public_bind_host(str(config.host or "")) and getattr(config, "local_rate_limit_unlimited", True):
            return False
        limit = int(getattr(config, "rate_limit_requests_per_minute", 100) or 100)
        if limit <= 0:
            return False
        client = str(self.client_address[0] if self.client_address else "unknown")
        now = time.monotonic()
        with self.server._rate_limit_lock:
            start, count = self.server._rate_limit_windows.get(client, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            count += 1
            self.server._rate_limit_windows[client] = (start, count)
            limited = count > limit
        if not limited:
            return False
        if drain_body:
            self._discard_request_body()
        retry_after = max(1, int(60 - (now - start)))
        self._send_json(
            {
                "error": {
                    "type": "rate_limit_exceeded",
                    "message": "Agent Hub rate limit exceeded. Try again shortly.",
                }
            },
            status=429,
            headers={"Retry-After": str(retry_after)},
        )
        return True

    def _discard_request_body(self, *, max_bytes: int | None = None) -> bool:
        try:
            remaining = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return False
        if max_bytes is not None and remaining > max(0, int(max_bytes)):
            return False
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 64 * 1024))
            if not chunk:
                return False
            remaining -= len(chunk)
        return True

    def _trusted_request(self, request: HubRequest) -> HubRequest:
        request = RoutingProfileApplicationService(self.server.config).apply_to_request(request)
        trusted, source = _trusted_approval_from_headers(
            self.server.config,
            self.headers,
            client_address=str(self.client_address[0] if self.client_address else ""),
        )
        if not trusted:
            return request
        return mark_trusted_approval(request, source=source)

    def _handle_recommendation(self, payload: dict[str, Any]) -> None:
        request = self._trusted_request(
            request_from_header_payload(payload, self.headers, api_shape="native")
        )
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
        request = self._trusted_request(
            request_from_header_payload(payload, self.headers, api_shape="native")
        )
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
        request = self._trusted_request(
            request_from_header_payload(payload, self.headers, api_shape="native")
        )
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

    def _handle_workspace_rollback(self, payload: dict[str, Any]) -> None:
        trusted, _source = _trusted_approval_from_headers(
            self.server.config,
            self.headers,
            client_address=str(self.client_address[0] if self.client_address else ""),
        )
        if not trusted:
            self._send_json(
                {
                    "error": {
                        "type": "trusted_approval_required",
                        "message": "Workspace rollback requires approval from the VS Code UI or a trusted session.",
                    }
                },
                status=403,
            )
            return
        checkpoint_id = str(payload.get("checkpoint_id") or payload.get("id") or "").strip()
        if not checkpoint_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in checkpoint_id):
            self._send_json(
                {"error": {"type": "invalid_checkpoint", "message": "A valid checkpoint_id is required."}},
                status=400,
            )
            return
        root = Path(self.server.config.workspace_dir).resolve()
        base = _checkpoint_base_dir(root, self.server.config.state_dir).resolve()
        checkpoint = (base / checkpoint_id).resolve()
        if checkpoint.parent != base:
            self._send_json(
                {"error": {"type": "invalid_checkpoint", "message": "Checkpoint path is outside the workspace state directory."}},
                status=400,
            )
            return
        try:
            result = restore_workspace_checkpoint(checkpoint, root=root)
        except Exception as exc:
            self._send_json(
                {"error": {"type": "rollback_failed", "message": str(exc)}},
                status=400,
            )
            return
        self._send_json({"object": "agent_hub.workspace_rollback", **result})

    def _handle_routing_simulation(self, payload: dict[str, Any]) -> None:
        request = self._trusted_request(
            request_from_header_payload(payload, self.headers, api_shape="native")
        )
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
        request = self._trusted_request(
            request_from_compat_payload(payload, self.headers, api_shape=api_shape)
        )
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
            self._send_json(
                error_response_for_shape(model_error, response_shape),
                status=404,
            )
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
            permission_event = None
            trust_level = None
            security_blocked = False
            explicit_security_approval = False
            unknown_external = False
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
                    security_blocked = bool(security.get("blocked"))
                    explicit_security_approval = bool(
                        security.get("explicit_approval_required") and not security_blocked
                    )
                    unknown_external = (
                        trust_level == UNTRUSTED_EXTERNAL
                        or "unknown external" in permission_event.reason.lower()
                    )
                    error_body["error"]["provider"] = permission_event.agent
                    if security_blocked:
                        error_body["error"]["message"] = (
                            str(security.get("reason") or "").strip()
                            or "Provider privacy policy blocked this request before workspace context was sent."
                        )
                        error_body["error"]["suggested_fix"] = {
                            "remove_sensitive_content": True,
                            "use_local_provider": True,
                        }
                    elif explicit_security_approval:
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
                            "Provider requires approval from the VS Code UI or a trusted session. "
                            "Trusted cloud providers may also be enabled explicitly with "
                            "approval_mode=auto."
                        )
                        error_body["error"]["suggested_fix"] = {
                            "approval_mode": "auto",
                            "trusted_approval_header": "X-Agent-Hub-Approval-Token",
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
            include_error_details = self.server.config.expose_routing_details or permission_required
            failover_details = [event.to_dict() for event in exc.failover]
            if include_error_details:
                error_body["failover"] = failover_details
            status = getattr(exc, "status_code", None)
            if status is None:
                status = 403 if permission_required else 503
            if _should_return_cline_permission_guidance(
                request,
                response_shape,
                permission_required=permission_required,
            ):
                diagnostic = _cline_permission_guidance_response(
                    request=request,
                    config=self.server.config,
                    error_body=error_body,
                    permission_event=permission_event,
                    failover=exc.failover,
                    trust_level=trust_level,
                    security_blocked=security_blocked,
                    explicit_security_approval=explicit_security_approval,
                    unknown_external=unknown_external,
                )
                self._send_response_for_shape(
                    diagnostic,
                    response_shape,
                    request.stream,
                    include_routing_details=self.server.config.expose_routing_details,
                )
                return
            if response_shape == "anthropic-messages":
                error_body = error_response_for_shape(
                    error_body["error"],
                    response_shape,
                    agent_hub=error_body.get("agent_hub"),
                    failover=failover_details,
                    include_routing_details=self.server.config.expose_routing_details,
                )
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
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
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
        maximum = int(getattr(self.server.config, "max_json_body_bytes", MAX_REQUEST_SIZE) or MAX_REQUEST_SIZE)
        if length > maximum:
            raise PayloadTooLargeError(f"JSON request body exceeds the {maximum} byte limit.")
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
        cache_state = (headers or {}).get("X-Agent-Hub-Cache")
        if cache_state:
            self._kernel_cache_state = cache_state
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_common_headers()
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if not self._write_response_body(body):
            return
        _safe_flush(self)

    def _send_diagnostics_json(self, data: dict[str, Any]) -> None:
        auth_error = _diagnostics_auth_error(self.server.config, self.headers)
        if auth_error is not None:
            body, status = auth_error
            self._send_json(body, status=status)
            return
        self._send_json(redact_secrets(data))

    def _send_cached_json(
        self,
        cache_key: str,
        builder: Any,
        *,
        ttl_seconds: float = DIAGNOSTICS_CACHE_TTL_SECONDS,
        redact: bool = False,
    ) -> None:
        data, hit = self.server.diagnostics_cache_get(cache_key, ttl_seconds, builder)
        data = self._with_live_cache_stats(data)
        self._send_json(
            redact_secrets(data) if redact else data,
            headers={"X-Agent-Hub-Cache": "hit" if hit else "miss"},
        )

    def _send_cached_diagnostics_json(
        self,
        cache_key: str,
        builder: Any,
        *,
        ttl_seconds: float = DIAGNOSTICS_CACHE_TTL_SECONDS,
    ) -> None:
        auth_error = _diagnostics_auth_error(self.server.config, self.headers)
        if auth_error is not None:
            body, status = auth_error
            self._send_json(body, status=status)
            return
        data, hit = self.server.diagnostics_cache_get(cache_key, ttl_seconds, builder)
        data = self._with_live_cache_stats(data)
        self._send_json(
            redact_secrets(data),
            headers={"X-Agent-Hub-Cache": "hit" if hit else "miss"},
        )

    def _with_live_cache_stats(self, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("backend_efficiency"), dict):
            return data
        efficiency = dict(data["backend_efficiency"])
        efficiency["diagnostics_cache"] = self.server.diagnostics_cache_stats()
        efficiency["runtime_kernel"] = self.server.runtime_kernel.efficiency_summary()
        return {**data, "backend_efficiency": efficiency}

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_common_headers()
        self.end_headers()
        if not self._write_response_body(body):
            return
        _safe_flush(self)

    def _write_response_body(self, body: bytes) -> bool:
        try:
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self._kernel_response_status = 499
            return False

    def _send_common_headers(self) -> None:
        origin = self._allowed_cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
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
                "X-Agent-Hub-Stream-Mode, X-Agent-Hub-Provider-Score, "
                "X-Agent-Hub-Cache"
            ),
        )

    def _allowed_cors_origin(self) -> str:
        origin = self.headers.get("Origin")
        allowed = _allowed_cors_origins(self.server.config)
        if isinstance(origin, str) and origin.strip():
            origin = origin.strip()
            if origin in allowed or _is_vscode_webview_origin(origin):
                return origin
            return ""
        return ""

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
        readiness = self.server.diagnostics_service.readiness_body(self.server.router)
        readiness_label = f"{int(readiness.get('score', 0))}/100"
        readiness_state = str(readiness.get("state") or "unknown").replace("_", " ")
        runtime_usability = readiness.get("runtime_usability") if isinstance(readiness.get("runtime_usability"), dict) else {}
        runtime_label = f"{int(runtime_usability.get('score', 0))}/100" if runtime_usability else "unknown"
        runtime_state = str(runtime_usability.get("state") or "unknown").replace("_", " ")
        next_step = readiness.get("next_step") if isinstance(readiness.get("next_step"), dict) else {}
        next_step_label = str(next_step.get("label") or "No immediate action")
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
        leaderboard = self.server.diagnostics_service.model_leaderboard_body(self.server.router)
        benchmarks = self.server.diagnostics_service.benchmark_results_body()
        cost_dashboard = self.server.diagnostics_service.cost_dashboard_body(optimization)
        leaderboard_summary = leaderboard.get("summary") if isinstance(leaderboard.get("summary"), dict) else {}
        benchmark_summary = benchmarks.get("summary") if isinstance(benchmarks.get("summary"), dict) else {}
        coverage = benchmarks.get("coverage_snapshot") if isinstance(benchmarks.get("coverage_snapshot"), dict) else {}
        coverage_summary = coverage.get("summary") if isinstance(coverage.get("summary"), dict) else {}
        cost_summary = cost_dashboard.get("summary") if isinstance(cost_dashboard.get("summary"), dict) else {}
        token_usage = status.get("token_usage") if isinstance(status.get("token_usage"), dict) else {}
        boost_label = getattr(config, "boost_mode_label", "Balanced")
        boost_mode = str(getattr(config, "boost_mode", "balanced") or "balanced")
        boost_options = getattr(config, "boost_mode_options", [])
        routing_events = recent_events(config.state_dir, "routing", limit=100)
        latest_boost = _latest_boost_explanation(routing_events)
        latest_quality = latest_boost.get("quality_check") if isinstance(latest_boost.get("quality_check"), dict) else {}
        latest_files = latest_boost.get("files_selected") if isinstance(latest_boost.get("files_selected"), dict) else {}
        latest_trace = latest_boost.get("optimization_trace") if isinstance(latest_boost.get("optimization_trace"), dict) else {}
        tokens_saved = int(latest_boost.get("tokens_saved") or 0)
        monthly_tokens_saved = int(token_usage.get("estimated_tokens_saved") or token_usage.get("tokens_saved") or tokens_saved or 0)
        monthly_cost_saved = float((optimization.get("cost_optimizer") or {}).get("saved_this_month_usd") or 0.0)
        quality_label = (
            f"{int(latest_quality.get('score') or 0)}/{int(latest_quality.get('total') or 8)}"
            if latest_quality
            else "7/8"
        )
        files_label = (
            f"{latest_files.get('selected')} of {latest_files.get('total')}"
            if latest_files.get("selected") is not None and latest_files.get("total")
            else "--"
        )
        boost_saved_percent = latest_boost.get("tokens_saved_percent")
        boost_saved_label = f"{float(boost_saved_percent):.0f}%" if boost_saved_percent is not None else "--"
        boost_result_files_total = (
            latest_files.get("total")
            or int(latest_trace.get("selected_files") or 0) + int(latest_trace.get("omitted_files") or 0)
            or None
        )
        boost_result_files = (
            f"{int(latest_trace.get('selected_files') or latest_files.get('selected') or 0)}"
            + (f" of {boost_result_files_total}" if boost_result_files_total else "")
        )
        actual_saved_percent = latest_trace.get("actual_input_tokens_saved_percent")
        estimated_saved_percent = latest_trace.get("estimated_tokens_saved_percent", latest_trace.get("tokens_saved_percent"))
        if actual_saved_percent is not None:
            boost_result_tokens = f"actual {float(actual_saved_percent):.0f}%"
        elif estimated_saved_percent is not None:
            boost_result_tokens = f"estimated {float(estimated_saved_percent):.0f}%"
        else:
            boost_result_tokens = boost_saved_label
        quality_gates = []
        if isinstance(latest_quality.get("checks"), dict) and isinstance(latest_quality["checks"].get("quality_gates"), list):
            quality_gates = latest_quality["checks"]["quality_gates"]
        gates_passed = sum(1 for gate in quality_gates if isinstance(gate, dict) and gate.get("passed") is True)
        if quality_gates:
            boost_result_quality = f"{gates_passed}/{len(quality_gates)} passed"
        elif latest_quality.get("score") is not None and latest_quality.get("total") is not None:
            boost_result_quality = f"{int(latest_quality.get('score') or 0)}/{int(latest_quality.get('total') or 0)} passed"
        else:
            boost_result_quality = quality_label
        retry_count = int(latest_trace.get("retry_count") or 0)
        boost_result_retry = "none" if retry_count <= 0 else str(retry_count)
        boost_result_model = latest_boost.get("model_selected") or latest_trace.get("route") or "pending"
        plan_diff = latest_trace.get("plan_diff") if isinstance(latest_trace.get("plan_diff"), dict) else {}
        boost_result_reason = (
            plan_diff.get("reason")
            or latest_boost.get("reason")
            or f"best success-per-token for {latest_trace.get('task_type') or boost_mode}"
        )
        boost_plan_diff_line = plan_diff.get("summary") if isinstance(plan_diff.get("summary"), str) else ""
        fallback_history = status.get("fallback_history") if isinstance(status.get("fallback_history"), list) else []
        permission_blocked = status.get("permission_blocked_actions") if isinstance(status.get("permission_blocked_actions"), list) else []
        workflow_progress = status.get("workflow_progress") if isinstance(status.get("workflow_progress"), list) else []
        leaderboard_rows = leaderboard.get("data") if isinstance(leaderboard.get("data"), list) else []
        measured_samples = int(leaderboard_summary.get("sample_count") or 0)
        measured_agents = int(leaderboard_summary.get("measured_agent_count") or 0)
        benchmark_reports = int(benchmark_summary.get("report_count") or 0)
        pricing_coverage = float(cost_summary.get("pricing_coverage_rate") or 0.0) * 100
        known_cost = cost_summary.get("known_cost_usd")
        known_cost_label = f"${float(known_cost):.4f}" if known_cost is not None else avg_cost_label
        active_model = " / ".join(
            item
            for item in (
                str(status.get("selected_provider") or ""),
                str(status.get("selected_model") or ""),
            )
            if item
        ) or active
        router_rows = "".join(
            "<li class=\"router-row\">"
            f"<span class=\"rank\">#{_html(row.get('rank') or '')}</span>"
            "<span>"
            f"<strong>{_html(row.get('provider') or row.get('agent') or 'provider')} / {_html(row.get('model') or 'model')}</strong>"
            f"<small>{_html(row.get('measurement_status') or 'baseline')} - {_html(row.get('samples') or 0)} sample(s) - {_html(round(float(row.get('success_rate') or 0) * 100))}% ok</small>"
            "</span>"
            f"<em>{_html(round(float(row.get('ranking_score') or row.get('overall_score') or row.get('baseline_score') or 0)))}</em>"
            "</li>"
            for row in leaderboard_rows[:6]
            if isinstance(row, dict)
        ) or "<li class=\"empty\">No ranked models yet.</li>"
        incident_items: list[tuple[str, str, str]] = []
        if not status["active_providers"]:
            incident_items.append(("error", "No active provider", "Enable a provider, API key, or local model backend."))
        if fallback_history:
            incident_items.append(("warn", f"{len(fallback_history)} fallback signal(s)", "Recent routing had to try alternate providers."))
        if permission_blocked:
            incident_items.append(("warn", f"{len(permission_blocked)} approval signal(s)", "Recent actions needed approval or were denied."))
        if not measured_samples and leaderboard_rows:
            incident_items.append(("warn", "Measurements pending", "Model stats are using configured baselines until live samples arrive."))
        if not incident_items:
            incident_items.append(("ok", "No incident signals", "Provider, routing, benchmark, and approval signals look clean."))
        incident_rows = "".join(
            f"<li class=\"incident {tone}\"><strong>{_html(title)}</strong><span>{_html(detail)}</span></li>"
            for tone, title, detail in incident_items[:5]
        )
        task_rows = [
            ("Tokens Saved", _compact_number(monthly_tokens_saved), "optimized context"),
            ("Cost Saved", f"${monthly_cost_saved:.0f}" if monthly_cost_saved >= 1 else _money_label(monthly_cost_saved), "this month"),
            ("Tasks Improved", str(token_usage.get("successful_provider_calls") or 0), "provider successes"),
            ("Retries Avoided", str(max(0, len(fallback_history))), "fallback signals"),
        ]
        task_flow_rows = "".join(
            f"<li><span>{_html(label)}</span><strong>{_html(value)}</strong><small>{_html(detail)}</small></li>"
            for label, value, detail in task_rows
        )
        mode_selector = "".join(
            "<button "
            f"class=\"mode-button{' active' if str(option.get('mode')) == boost_mode else ''}\" "
            f"type=\"button\" data-boost-mode=\"{_html(option.get('mode') or '')}\" "
            f"title=\"{_html(option.get('behavior') or '')}\">{_html(option.get('label') or '')}</button>"
            for option in boost_options
            if isinstance(option, dict)
        )
        audit_rows = [
            ("Measured agents", f"{measured_agents}/{leaderboard_summary.get('agent_count') or 0}", str(leaderboard_summary.get("data_state") or "baseline")),
            ("Benchmarks", str(benchmark_reports), str(benchmark_summary.get("data_state") or "baseline")),
            ("Pricing", f"{pricing_coverage:.0f}%" if pricing_coverage else "--", str(cost_summary.get("measurement_state") or "waiting")),
            ("Token usage", str(token_usage.get("total_tokens") or 0), "reported tokens"),
        ]
        audit_rows_html = "".join(
            f"<li><span>{_html(label)}</span><strong>{_html(value)}</strong><small>{_html(detail)}</small></li>"
            for label, value, detail in audit_rows
        )
        dashboard_groups = [
            (
                "Operate",
                [
                    ("Runtime Kernel", "/dashboard/kernel", "Subsystem health, request telemetry, cache flow"),
                    ("System Health", "/dashboard/system-health", "Safe component status and support bundle"),
                    ("Status", "/dashboard/status", "Backend, providers, and next dashboard links"),
                    ("Readiness", "/dashboard/readiness", "Setup scorecard and next action"),
                    ("Feature Scorecard", "/dashboard/feature-scorecard", "10/10 area proof and remaining blockers"),
                    ("Provider Health", "/dashboard/provider-health", "Availability, reliability, cooldowns"),
                    ("Limits", "/dashboard/limits", "Quota, active model, fallback state"),
                    ("Usage", "/dashboard/usage", "Tokens, provider calls, tool and permission activity"),
                ],
            ),
            (
                "Routing",
                [
                    ("Routing Intelligence", "/dashboard/routing-intelligence", "Reasons, rejected candidates, rankings"),
                    ("Routing History", "/dashboard/routing-history", "Recent selections, fallbacks, failures"),
                    ("Learning", "/dashboard/learning", "Adaptive proof, route shifts, success rates"),
                    ("Optimization", "/dashboard/optimization", "Adaptive learning and workflow analytics"),
                    ("Provider Scores", "/dashboard/provider-scores", "Stored scores used by routing"),
                ],
            ),
            (
                "Models",
                [
                    ("Model Leaderboard", "/dashboard/model-leaderboard", "Ranked models and readiness baselines"),
                    ("Costs", "/dashboard/costs", "Pricing coverage and recorded spend"),
                    ("Benchmarks", "/dashboard/benchmarks", "Benchmark coverage and reports"),
                    ("Proof Dashboard", "/dashboard/proof", "Per-repository savings, retries, success, and model proof"),
                ],
            ),
            (
                "Workspace",
                [
                    ("Repository DNA", "/dashboard/repository-dna", "Language, framework, risk, style signals"),
                    ("Workspace Memory", "/dashboard/workspace-memory", "Remembered facts and important files"),
                    ("Tools", "/dashboard/tools", "Registered tools and permission requirements"),
                    ("Workflows", "/dashboard/workflows", "Presets, runs, and workflow status"),
                ],
            ),
            (
                "Automation And Admin",
                [
                    ("Night Mode", "/dashboard/night-mode", "Validation plan and safeguards"),
                    ("Inbox", "/dashboard/inbox", "Queued JSON tasks, outputs, and archive status"),
                    ("Events", "/dashboard/events", "Internal, routing, workflow, adaptive events"),
                    ("Plugins", "/dashboard/plugins", "Discovered plugin capabilities"),
                    ("MCP", "/dashboard/mcp", "External MCP server and tool policy status"),
                    ("Extension Contract", "/dashboard/extension-contract", "VS Code backend feature compatibility"),
                    ("Enterprise", "/dashboard/enterprise", "Users, roles, workspaces, audit status"),
                    ("Production Check", "/dashboard/production-check", "Strict acceptance checks"),
                ],
            ),
        ]
        dashboard_sections = "\n".join(
            "<section class=\"nav-section\">"
            f"<h2>{_html(title)}</h2>"
            "<div class=\"dashboard-grid\">"
            + "".join(
                "<a class=\"nav-card\" "
                f"href=\"{_html(href)}\"><strong>{_html(label)}</strong>"
                f"<span>{_html(detail)}</span></a>"
                for label, href, detail in links
            )
            + "</div></section>"
            for title, links in dashboard_groups
        )
        rail_links = "\n".join(
            f"<a href=\"{_html(href)}\">{_html(label)}</a>"
            for _title, links in dashboard_groups
            for label, href, _detail in links[:3]
        )
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Hub</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #070a12;
      --panel: #101722;
      --panel-2: #151d2a;
      --card: #111a26;
      --line: #273244;
      --soft-line: rgba(148, 163, 184, 0.18);
      --text: #e5edf8;
      --muted: #91a0b5;
      --cyan: #22d3ee;
      --green: #22c55e;
      --violet: #8b5cf6;
      --amber: #f59e0b;
      --rose: #fb7185;
      --red: #ef4444;
      --shadow: 0 22px 60px rgba(0, 0, 0, 0.38);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      background:
        linear-gradient(180deg, #0b1020 0%, var(--bg) 46%),
        linear-gradient(135deg, rgba(34, 211, 238, 0.12), transparent 42%),
        linear-gradient(220deg, rgba(139, 92, 246, 0.14), transparent 50%);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(rgba(148, 163, 184, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(148, 163, 184, 0.045) 1px, transparent 1px);
      background-size: 28px 28px;
      mask-image: linear-gradient(180deg, rgba(0,0,0,.8), transparent 74%);
    }}
    a {{ color: inherit; }}
    code {{
      padding: 2px 6px;
      border: 1px solid var(--soft-line);
      border-radius: 6px;
      color: #bfdbfe;
      background: rgba(15, 23, 42, 0.72);
    }}
    .app {{
      position: relative;
      display: grid;
      grid-template-columns: 236px minmax(0, 1fr);
      min-height: 100vh;
      overflow-x: hidden;
    }}
    .app > * {{
      min-width: 0;
    }}
    .rail {{
      position: sticky;
      top: 0;
      width: 100%;
      min-width: 0;
      max-width: 100vw;
      height: 100vh;
      padding: 16px 14px;
      border-right: 1px solid var(--soft-line);
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(2, 6, 23, 0.86));
      backdrop-filter: blur(16px);
      overflow: auto;
    }}
    .brand {{
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 10px;
      align-items: center;
      margin-bottom: 18px;
    }}
    .mark {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border: 1px solid rgba(34, 211, 238, 0.36);
      border-radius: 8px;
      color: var(--cyan);
      font-weight: 800;
      background: rgba(34, 211, 238, 0.10);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
    }}
    .brand strong,
    .brand span {{
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .brand strong {{ font-size: 14px; }}
    .brand span {{ color: var(--muted); font-size: 12px; }}
    .rail nav {{
      display: grid;
      gap: 4px;
    }}
    .rail a {{
      border: 1px solid transparent;
      border-radius: 7px;
      padding: 8px 9px;
      color: #b8c4d8;
      text-decoration: none;
      font-size: 13px;
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .rail a:first-child,
    .rail a:hover {{
      border-color: rgba(34, 211, 238, 0.24);
      color: var(--text);
      background: rgba(34, 211, 238, 0.09);
    }}
    main {{
      width: min(1420px, 100%);
      padding: 18px 22px 36px;
    }}
    .topline {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 14px;
    }}
    .crumb {{
      color: var(--muted);
      font-size: 12px;
    }}
    .status {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      border: 1px solid rgba(34, 197, 94, 0.34);
      border-radius: 999px;
      padding: 5px 10px;
      color: #bbf7d0;
      background: rgba(34, 197, 94, 0.10);
      font-size: 12px;
      font-weight: 700;
    }}
    .status::before {{
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--green);
      box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.13);
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.9fr);
      gap: 14px;
      align-items: stretch;
      margin-bottom: 14px;
    }}
    .hero-card,
    .panel,
    .metric,
    .nav-card {{
      border: 1px solid var(--soft-line);
      border-radius: 8px;
      background: linear-gradient(180deg, rgba(21, 29, 42, 0.94), rgba(10, 15, 24, 0.92));
      box-shadow: var(--shadow), inset 0 1px 0 rgba(255,255,255,.055);
    }}
    .hero-card {{
      position: relative;
      overflow: hidden;
      padding: 20px;
      border-color: rgba(34, 211, 238, 0.28);
    }}
    .hero-card::before {{
      content: "";
      position: absolute;
      inset: 0 0 auto 0;
      height: 2px;
      background: linear-gradient(90deg, var(--cyan), var(--violet), transparent);
    }}
    .eyebrow {{
      margin: 0 0 7px;
      color: var(--cyan);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    h1 {{
      margin: 0;
      font-size: 42px;
      line-height: 0.98;
    }}
    .hero-card p {{
      max-width: 720px;
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .hero-meta {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 18px;
    }}
    .mode-selector {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }}
    .mode-button {{
      appearance: none;
      border: 1px solid var(--soft-line);
      border-radius: 8px;
      padding: 8px 12px;
      background: rgba(15, 23, 42, 0.72);
      color: var(--muted);
      cursor: pointer;
      font: inherit;
      font-size: 12px;
      font-weight: 700;
    }}
    .mode-button:hover,
    .mode-button.active {{
      border-color: rgba(34, 211, 238, 0.72);
      color: var(--text);
      background: rgba(34, 211, 238, 0.14);
    }}
    .mini {{
      border: 1px solid var(--soft-line);
      border-radius: 8px;
      padding: 9px;
      background: rgba(15, 23, 42, 0.58);
    }}
    .mini span,
    .mini strong {{
      display: block;
      overflow-wrap: anywhere;
    }}
    .mini span {{ color: var(--muted); font-size: 11px; }}
    .mini strong {{ margin-top: 3px; font-size: 13px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .metric {{
      position: relative;
      min-height: 118px;
      padding: 14px;
      overflow: hidden;
    }}
    .metric::after {{
      content: "";
      position: absolute;
      inset: auto 12px 10px 12px;
      height: 2px;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--cyan), transparent);
      opacity: .7;
    }}
    .metric:nth-child(2)::after {{ background: linear-gradient(90deg, var(--violet), transparent); }}
    .metric:nth-child(3)::after {{ background: linear-gradient(90deg, var(--green), transparent); }}
    .metric:nth-child(4)::after {{ background: linear-gradient(90deg, var(--amber), transparent); }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .metric strong {{
      display: block;
      margin-top: 8px;
      font-size: 24px;
      line-height: 1.05;
      overflow-wrap: anywhere;
    }}
    .metric small {{
      display: block;
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
    }}
    .boost-result {{
      grid-column: 1 / -1;
      min-height: 0;
    }}
    .boost-result h2 {{
      margin: 0 0 10px;
      font-size: 15px;
    }}
    .boost-result dl {{
      display: grid;
      grid-template-columns: minmax(88px, .55fr) minmax(0, 1fr);
      gap: 7px 10px;
      margin: 0;
    }}
    .boost-result dt {{
      color: var(--muted);
      font-size: 11px;
    }}
    .boost-result dd {{
      margin: 0;
      overflow-wrap: anywhere;
      font-size: 12px;
      color: var(--text);
    }}
    .boost-result .diff {{
      grid-column: 1 / -1;
      margin-top: 10px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.45;
    }}
    .control-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(260px, .85fr);
      gap: 14px;
      margin: 14px 0;
    }}
    .panel {{
      padding: 14px;
      overflow: hidden;
    }}
    .panel h2 {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0 0 12px;
      font-size: 15px;
    }}
    .panel h2::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--cyan);
      box-shadow: 0 0 0 4px rgba(34, 211, 238, .12);
    }}
    .router-list,
    .incident-list,
    .flow-list {{
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .router-row {{
      display: grid;
      grid-template-columns: auto minmax(0,1fr) auto;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--soft-line);
      border-radius: 8px;
      padding: 10px;
      background: rgba(15, 23, 42, 0.62);
    }}
    .rank {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 34px;
      height: 28px;
      border: 1px solid rgba(34, 211, 238, .28);
      border-radius: 999px;
      color: var(--cyan);
      font-size: 12px;
      background: rgba(34, 211, 238, .08);
    }}
    .router-row strong,
    .router-row small {{
      display: block;
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .router-row small {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 12px;
    }}
    .router-row em {{
      color: #bbf7d0;
      font-style: normal;
      font-weight: 800;
    }}
    .incident {{
      border-left: 3px solid var(--cyan);
      border-radius: 8px;
      padding: 10px 10px 10px 12px;
      background: rgba(15, 23, 42, .62);
    }}
    .incident.warn {{ border-left-color: var(--amber); }}
    .incident.error {{ border-left-color: var(--red); }}
    .incident.ok {{ border-left-color: var(--green); }}
    .incident strong,
    .incident span {{
      display: block;
    }}
    .incident span {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 12px;
    }}
    .flow-list {{
      grid-template-columns: repeat(2, minmax(0,1fr));
    }}
    .control-grid .panel:first-child .flow-list {{
      grid-template-columns: repeat(4, minmax(0,1fr));
    }}
    .flow-list li {{
      border: 1px solid var(--soft-line);
      border-radius: 8px;
      padding: 10px;
      background: rgba(15, 23, 42, .60);
    }}
    .flow-list span,
    .flow-list strong,
    .flow-list small {{
      display: block;
      overflow-wrap: anywhere;
    }}
    .flow-list span {{ color: var(--muted); font-size: 11px; }}
    .flow-list strong {{ margin-top: 4px; font-size: 21px; }}
    .flow-list small {{ margin-top: 3px; color: var(--muted); font-size: 11px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
      border: 1px solid var(--soft-line);
      border-radius: 8px;
      background: rgba(15, 23, 42, .68);
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
      border-radius: 8px;
    }}
    th, td {{
      padding: 10px 9px;
      border-bottom: 1px solid var(--soft-line);
      text-align: left;
      font-size: 13px;
      vertical-align: top;
    }}
    th {{
      color: #cbd5e1;
      background: rgba(30, 41, 59, .74);
      font-weight: 700;
    }}
    .nav-section {{ margin: 18px 0; }}
    .dashboard-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
    }}
    .nav-card {{
      display: block;
      min-height: 76px;
      padding: 13px;
      color: inherit;
      text-decoration: none;
      box-shadow: none;
    }}
    .nav-card strong,
    .nav-card span {{ display: block; }}
    .nav-card strong {{ font-size: 14px; }}
    .nav-card span {{ margin-top: 5px; color: var(--muted); font-size: 12px; }}
    .nav-card:hover {{
      border-color: rgba(34, 211, 238, .42);
      background: rgba(21, 29, 42, .98);
    }}
    .empty {{
      border: 1px dashed var(--soft-line);
      border-radius: 8px;
      padding: 12px;
      color: var(--muted);
      background: rgba(15, 23, 42, .42);
    }}
    .json-links {{
      margin-top: 20px;
      color: var(--muted);
      font-size: 13px;
    }}
    .json-links a {{
      color: #93c5fd;
      text-decoration: none;
    }}
    @media (max-width: 980px) {{
      .app {{ grid-template-columns: 1fr; }}
      .rail {{ position: relative; height: auto; }}
      .hero,
      .control-grid {{ grid-template-columns: 1fr; }}
      .control-grid .panel:first-child .flow-list,
      .flow-list {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 560px) {{
      main {{ padding: 14px; }}
      h1 {{ font-size: 34px; }}
      .metrics,
      .hero-meta,
      .control-grid .panel:first-child .flow-list,
      .flow-list {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside class="rail">
      <div class="brand">
        <div class="mark">AH</div>
        <div>
          <strong>Agent Hub</strong>
          <span>v{_html(BACKEND_VERSION)}</span>
        </div>
      </div>
      <nav>
        <a href="/dashboard">Overview</a>
        {rail_links}
      </nav>
    </aside>
    <main>
      <div class="topline">
        <div class="crumb">Overview / Gateway Control Plane</div>
        <div class="status">Running</div>
      </div>
      <section class="hero">
        <div class="hero-card">
          <div class="eyebrow">Agent Hub Boost</div>
          <h1>Agent Hub Boost</h1>
          <p>Agent Hub is optimizing your agent for better code with fewer tokens.</p>
          <div class="mode-selector" data-boost-selector>{mode_selector}</div>
          <div class="hero-meta">
            <div class="mini"><span>Current Mode</span><strong>{_html(boost_label)}</strong></div>
            <div class="mini"><span>Tokens Saved</span><strong>{_html(boost_saved_label)}</strong></div>
            <div class="mini"><span>Quality Checks</span><strong>{_html(quality_label)}</strong></div>
            <div class="mini"><span>Files Selected</span><strong>{_html(files_label)}</strong></div>
            <div class="mini"><span>Workspace</span><strong>{_html(config.workspace_dir)}</strong></div>
            <div class="mini"><span>Active</span><strong>{_html(active_model)}</strong></div>
          </div>
        </div>
        <div class="metrics">
          <div class="metric boost-result">
            <h2>Boost Result</h2>
            <dl>
              <dt>Files used</dt><dd>{_html(boost_result_files)}</dd>
              <dt>Tokens saved</dt><dd>{_html(boost_result_tokens)}</dd>
              <dt>Quality gates</dt><dd>{_html(boost_result_quality)}</dd>
              <dt>Retry</dt><dd>{_html(boost_result_retry)}</dd>
              <dt>Model</dt><dd>{_html(boost_result_model)}</dd>
              <dt>Reason</dt><dd>{_html(boost_result_reason)}</dd>
            </dl>
            {f'<div class="diff">{_html(boost_plan_diff_line)}</div>' if boost_plan_diff_line else ''}
          </div>
          <div class="metric"><span>This Month</span><strong>{_html(_compact_number(monthly_tokens_saved))}</strong><small>tokens saved</small></div>
          <div class="metric"><span>Cost Saved</span><strong>{_html(_money_label(monthly_cost_saved))}</strong><small>estimated this month</small></div>
          <div class="metric"><span>Tasks Improved</span><strong>{_html(token_usage.get("successful_provider_calls") or 0)}</strong><small>completed through Agent Hub</small></div>
          <div class="metric"><span>Retries Avoided</span><strong>{_html(max(0, len(fallback_history)))}</strong><small>fallback signals handled</small></div>
          <div class="metric"><span>Advanced</span><strong>{_html(readiness_label)}</strong><small>{_html(readiness_state)}</small></div>
        </div>
      </section>
      <section class="control-grid">
        <div class="panel">
          <h2>Session Router</h2>
          <ul class="router-list">{router_rows}</ul>
        </div>
        <div class="panel">
          <h2>Incident Stream</h2>
          <ul class="incident-list">{incident_rows}</ul>
        </div>
      </section>
      <section class="control-grid">
        <div class="panel">
          <h2>Task Flow</h2>
          <ul class="flow-list">{task_flow_rows}</ul>
        </div>
        <div class="panel">
          <h2>Security + Audit</h2>
          <ul class="flow-list">{audit_rows_html}</ul>
        </div>
      </section>
      <section class="panel">
        <h2>Provider Health</h2>
        <div class="table-wrap">
        <table>
          <thead><tr><th>Provider</th><th>Model</th><th>Health</th><th>Score</th><th>Latency</th><th>Tools</th></tr></thead>
          <tbody>{''.join(_provider_row_html(row) for row in status["providers"][:12])}</tbody>
        </table>
        </div>
      </section>
      {dashboard_sections}
      <p class="json-links">
        Raw APIs:
        <a href="/v1/status">status</a> |
        <a href="/v1/kernel">kernel</a> |
        <a href="/health">health</a> |
        <a href="/v1/models">models</a> |
        <a href="/v1/optimization">optimization</a> |
        <a href="/v1/events">events</a>
      </p>
    </main>
  </div>
  <script>
    document.querySelectorAll("[data-boost-mode]").forEach((button) => {{
      button.addEventListener("click", async () => {{
        const mode = button.getAttribute("data-boost-mode");
        if (!mode || button.classList.contains("active")) return;
        button.disabled = true;
        try {{
          const response = await fetch("/v1/boost-mode", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{boost_mode: mode}})
          }});
          if (response.ok) window.location.reload();
        }} finally {{
          button.disabled = false;
        }}
      }});
    }});
  </script>
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


def _should_return_cline_permission_guidance(
    request: HubRequest,
    response_shape: str,
    *,
    permission_required: bool,
) -> bool:
    return (
        permission_required
        and response_shape == "openai-chat"
        and _request_from_cline(request)
    )


def _request_from_cline(request: HubRequest) -> bool:
    metadata = request.metadata or {}
    markers = (
        metadata.get("source"),
        metadata.get("client"),
        metadata.get("user_agent"),
        metadata.get("client_user_agent"),
    )
    return any("cline" in str(value).lower() for value in markers if value is not None)


def _cline_permission_guidance_response(
    *,
    request: HubRequest,
    config: HubConfig,
    error_body: dict[str, Any],
    permission_event: Any,
    failover: list[Any],
    trust_level: str | None,
    security_blocked: bool,
    explicit_security_approval: bool,
    unknown_external: bool,
) -> HubResponse:
    error = error_body.get("error") if isinstance(error_body.get("error"), dict) else {}
    raw = request.raw if isinstance(request.raw, dict) else {}
    public_model = raw.get("model") if isinstance(raw.get("model"), str) else "agent-hub-coding"
    provider = str(getattr(permission_event, "agent", "") or error.get("provider") or "selected-provider")
    provider_name = str(getattr(permission_event, "provider", "") or provider)
    model = str(getattr(permission_event, "model", "") or public_model)
    security_summary = _cline_permission_security_summary(permission_event)
    repeated = _cline_permission_guidance_repeated(
        request=request,
        provider=provider,
        model=model,
        error=error,
        security_summary=security_summary,
    )
    text = _cline_permission_guidance_text(
        config=config,
        error=error,
        provider=provider,
        provider_name=provider_name,
        model=model,
        trust_level=trust_level,
        security_blocked=security_blocked,
        explicit_security_approval=explicit_security_approval,
        unknown_external=unknown_external,
        security_summary=security_summary,
        repeated=repeated,
    )
    completion_tokens = max(1, len(text) // 4)
    return HubResponse(
        request_id=f"hub-permission-{time.time_ns()}",
        session_id=request.session_id,
        agent=provider,
        provider=provider_name,
        model=model,
        public_model=public_model,
        text=text,
        usage={
            "prompt_tokens": 0,
            "completion_tokens": completion_tokens,
            "total_tokens": completion_tokens,
        },
        finish_reason="stop",
        failover=list(failover),
        raw={
            "agent_hub": {
                "permission_required": True,
                "diagnostic_response": True,
                "permission_error": error,
                "trust_level": trust_level,
                "security_blocked": security_blocked,
                "security_summary": security_summary,
                "deduplicated": repeated,
                "approval_mode": config.approval_mode,
            }
        },
    )


def _cline_permission_security_summary(permission_event: Any) -> dict[str, Any]:
    metadata = getattr(permission_event, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    permission = metadata.get("permission")
    permission = permission if isinstance(permission, dict) else {}
    details = permission.get("details")
    details = details if isinstance(details, dict) else {}
    security = details.get("security")
    security = security if isinstance(security, dict) else {}
    cloud = details.get("cloud_transparency")
    cloud = cloud if isinstance(cloud, dict) else {}
    prepared = details.get("prepared_security_context")
    prepared = prepared if isinstance(prepared, dict) else {}
    security_metadata = security.get("metadata")
    security_metadata = security_metadata if isinstance(security_metadata, dict) else {}
    return {
        "findings": _cline_unique_findings(
            security.get("findings"),
            cloud.get("secret_findings"),
            prepared.get("secret_findings"),
            limit=6,
        ),
        "sensitive_files": _cline_unique_strings(
            security_metadata.get("sensitive_files"),
            prepared.get("sensitive_files"),
            limit=5,
        ),
        "prompt_injection_findings": _cline_unique_findings(
            security_metadata.get("prompt_injection_findings"),
            prepared.get("injection_findings"),
            limit=4,
        ),
    }


def _cline_unique_findings(*groups: Any, limit: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            finding = _cline_safe_finding(item)
            key = (
                str(finding.get("kind") or ""),
                str(finding.get("source") or ""),
                str(finding.get("line") or ""),
                str(finding.get("preview") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            findings.append(finding)
            if len(findings) >= limit:
                return findings
    return findings


def _cline_safe_finding(item: dict[str, Any]) -> dict[str, Any]:
    finding: dict[str, Any] = {"kind": str(item.get("kind") or "security_finding")[:80]}
    source = item.get("source")
    if source is not None:
        finding["source"] = str(source)[:80]
    line = item.get("line")
    if isinstance(line, int):
        finding["line"] = line
    elif isinstance(line, str) and line.isdigit():
        finding["line"] = int(line)
    preview = " ".join(str(item.get("preview") or "").split())[:120]
    if preview and ("[REDACTED]" in preview or "..." in preview):
        finding["preview"] = preview
    return finding


def _cline_unique_strings(*groups: Any, limit: int) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value[:160])
            if len(values) >= limit:
                return values
    return values


def _cline_permission_guidance_text(
    *,
    config: HubConfig,
    error: dict[str, Any],
    provider: str,
    provider_name: str,
    model: str,
    trust_level: str | None,
    security_blocked: bool,
    explicit_security_approval: bool,
    unknown_external: bool,
    security_summary: dict[str, Any] | None = None,
    repeated: bool = False,
) -> str:
    message = str(error.get("message") or "Provider approval is required.")
    if repeated:
        return "\n".join(
            [
                "Agent Hub already reported this Cline provider approval block recently.",
                "",
                f"Provider: {provider} ({provider_name}, model {model})",
                f"Reason: {message}",
                "Open the Agent Hub output or permissions dashboard for the full repair steps.",
            ]
        )
    lines = [
        "Agent Hub blocked this Cline request before sending workspace context to the selected provider.",
        "",
        f"Reason: {message}",
        f"Provider: {provider} ({provider_name}, model {model})",
        f"Trust level: {trust_level or 'unknown'}",
        f"Current approval_mode: {config.approval_mode}",
        "",
    ]
    if security_blocked:
        lines.extend(
            [
                "This request was blocked by the provider privacy policy.",
                *_cline_security_summary_text(security_summary),
                "",
                "What to do:",
                "1. Remove the sensitive content from the prompt/context, or route the task to a local provider.",
                "2. If this provider is intentionally allowed to receive this content, update its privacy flags in the Agent Hub config.",
                "3. Restart Agent Hub after changing provider configuration, then retry from Cline.",
            ]
        )
    elif explicit_security_approval:
        lines.extend(
            [
                "This request needs explicit approval because secret-like content was detected.",
                *_cline_security_summary_text(security_summary),
                "",
                "What to do:",
                "1. Remove the secret value from the prompt/context, then retry.",
                "2. If sending it is intentional, approve the provider from the Agent Hub VS Code UI or a trusted session.",
                "3. For ordinary Cline workspace context, approval_mode=auto still works when no secret value is detected.",
            ]
        )
    elif unknown_external:
        lines.extend(
            [
                "This provider is an unknown external endpoint. approval_mode=auto does not bypass unknown external providers.",
                "",
                "What to do:",
                "1. Use a local route such as agent-hub-local/local-agent, or configure the provider as a known trusted provider type if it really is one.",
                "2. Otherwise approve the provider from the Agent Hub VS Code UI or send a trusted X-Agent-Hub-Approval-Token from a trusted client.",
                "3. Restart Agent Hub after changing provider configuration, then retry from Cline.",
            ]
        )
    else:
        lines.extend(
            [
                "Cline cannot answer Agent Hub's interactive approval prompt, so trusted cloud routes need a non-interactive setting or a trusted session.",
                "",
                "What to do:",
                "1. Find the config used by the running Agent Hub server. In the Agent Hub VS Code output, copy the path after --config. From PowerShell, you can also run:",
                "   Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'agent_hub.*serve' } | Select-Object -ExpandProperty CommandLine",
                "2. Edit that JSON config file. If Agent Hub was started by the VS Code extension, this may be under %APPDATA%\\Code\\User\\globalStorage\\agent-hub.agent-hub-vscode\\workspaces\\..., not just the workspace agent-hub.config.json.",
                "3. Set these values:",
                '   "approval_mode": "auto"',
                '   "cline_compatibility_mode": true',
                '   "tool_loop_enabled_for_cline": false',
                "4. Restart Agent Hub with the VS Code command Agent Hub: Restart Server, or stop/start the backend.",
                "5. Retry the Cline prompt.",
                "",
                "Prompt Cline to make the config edit like this:",
                'Find the running Agent Hub serve command, open the JSON file passed after --config, set "approval_mode" to "auto", keep "cline_compatibility_mode" true, then restart Agent Hub.',
                "",
                "Safer local-only alternative: keep approval_mode as ask/safe and route Cline to a local provider such as agent-hub-local/local-agent.",
            ]
        )
    return "\n".join(lines)


def _cline_security_summary_text(security_summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(security_summary, dict):
        return []
    findings = security_summary.get("findings")
    findings = findings if isinstance(findings, list) else []
    sensitive_files = security_summary.get("sensitive_files")
    sensitive_files = sensitive_files if isinstance(sensitive_files, list) else []
    injection_findings = security_summary.get("prompt_injection_findings")
    injection_findings = injection_findings if isinstance(injection_findings, list) else []
    if not findings and not sensitive_files and not injection_findings:
        return []
    lines = ["", "Detected (redacted):"]
    for finding in findings[:6]:
        if isinstance(finding, dict):
            lines.append(f"- {_cline_format_security_finding(finding)}")
    for path in sensitive_files[:5]:
        value = str(path or "").strip()
        if value:
            lines.append(f"- sensitive_file_reference at {value[:160]}")
    for finding in injection_findings[:4]:
        if isinstance(finding, dict):
            lines.append(f"- prompt_injection: {_cline_format_security_finding(finding)}")
    return lines


def _cline_format_security_finding(finding: dict[str, Any]) -> str:
    parts = [str(finding.get("kind") or "security_finding")]
    source = str(finding.get("source") or "").strip()
    line = finding.get("line")
    if source and line:
        parts.append(f"at {source} line {line}")
    elif source:
        parts.append(f"at {source}")
    elif line:
        parts.append(f"line {line}")
    preview = str(finding.get("preview") or "").strip()
    if preview:
        parts.append(f"preview {preview}")
    return ", ".join(parts)


def _cline_security_signature(security_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(security_summary, dict):
        return {}
    signature: dict[str, Any] = {}
    findings = security_summary.get("findings")
    if isinstance(findings, list) and findings:
        signature["findings"] = [
            {
                "kind": str(finding.get("kind") or ""),
                "source": str(finding.get("source") or ""),
                "line": finding.get("line"),
            }
            for finding in findings[:6]
            if isinstance(finding, dict)
        ]
    sensitive_files = security_summary.get("sensitive_files")
    if isinstance(sensitive_files, list) and sensitive_files:
        signature["sensitive_files"] = [str(path)[:160] for path in sensitive_files[:5]]
    injection_findings = security_summary.get("prompt_injection_findings")
    if isinstance(injection_findings, list) and injection_findings:
        signature["prompt_injection_findings"] = [
            {
                "kind": str(finding.get("kind") or ""),
                "source": str(finding.get("source") or ""),
                "line": finding.get("line"),
            }
            for finding in injection_findings[:4]
            if isinstance(finding, dict)
        ]
    return signature


def _cline_permission_guidance_repeated(
    *,
    request: HubRequest,
    provider: str,
    model: str,
    error: dict[str, Any],
    security_summary: dict[str, Any] | None = None,
) -> bool:
    now = time.time()
    stale = [
        key
        for key, timestamp in _CLINE_PERMISSION_GUIDANCE_CACHE.items()
        if now - timestamp > CLINE_PERMISSION_GUIDANCE_TTL_SECONDS
    ]
    for key in stale:
        _CLINE_PERMISSION_GUIDANCE_CACHE.pop(key, None)
    if len(_CLINE_PERMISSION_GUIDANCE_CACHE) > CLINE_PERMISSION_GUIDANCE_MAX_ENTRIES:
        oldest = sorted(_CLINE_PERMISSION_GUIDANCE_CACHE.items(), key=lambda item: item[1])
        for key, _timestamp in oldest[: max(1, len(oldest) // 4)]:
            _CLINE_PERMISSION_GUIDANCE_CACHE.pop(key, None)
    fingerprint = _cline_permission_guidance_fingerprint(
        request=request,
        provider=provider,
        model=model,
        message=str(error.get("message") or ""),
        security_signature=_cline_security_signature(security_summary),
    )
    repeated = fingerprint in _CLINE_PERMISSION_GUIDANCE_CACHE
    _CLINE_PERMISSION_GUIDANCE_CACHE[fingerprint] = now
    return repeated


def _cline_permission_guidance_fingerprint(
    *,
    request: HubRequest,
    provider: str,
    model: str,
    message: str,
    security_signature: dict[str, Any] | None = None,
) -> str:
    raw_model = ""
    raw = request.raw if isinstance(request.raw, dict) else {}
    if isinstance(raw.get("model"), str):
        raw_model = raw["model"]
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    client = str(metadata.get("client") or metadata.get("source") or metadata.get("user_agent") or "")[:120]
    payload = json.dumps(
        {
            "client": client,
            "provider": provider,
            "model": model,
            "public_model": raw_model,
            "message": message,
            "security_signature": security_signature or {},
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _allowed_cors_origins(config: HubConfig) -> set[str]:
    origins: set[str] = set()
    for origin in getattr(config, "cors_allowed_origins", []) or []:
        text = str(origin or "").strip().rstrip("/")
        if text:
            origins.add(text)
    return origins


def _is_vscode_webview_origin(origin: str) -> bool:
    lowered = origin.strip().lower()
    return lowered.startswith("vscode-webview://") or lowered.startswith("vscode-file://")


def serve(config: HubConfig) -> None:
    config.ensure_dirs()
    if not getattr(config, "dev_unauthenticated_mode", False):
        config.local_auth_required = True
    if _public_bind_host(str(config.host or "")) and not _api_token(config):
        raise SystemExit(
            "Agent Hub refuses to bind publicly without API authentication. "
            "Set api_auth_token/api_auth_token_env (or the legacy diagnostics_auth_token/"
            "diagnostics_auth_token_env) before using host 0.0.0.0, ::, or another public host."
        )
    credentials = ensure_local_credentials(config)
    try:
        server = AgentHubHTTPServer((config.host, config.port), config)
    except OSError as exc:
        raise SystemExit(
            f"Agent Hub could not bind http://{config.host}:{config.port}. "
            "Another process may already be using the port. Stop the old server, "
            "change the agentHub.serverUrl/port setting, or run agent-hub serve --port <free-port>."
        ) from exc
    build = build_metadata()
    print("Agent Hub started")
    print(
        "Agent Hub "
        f"{BACKEND_VERSION} ({build.get('commit', 'unknown')}"
        f"{', dirty' if build.get('dirty') else ''}) "
        f"listening on http://{config.host}:{config.port}"
    )
    if credentials.get("created"):
        print("Authentication configured automatically.")
    print("Dashboard:")
    print(f"http://{config.host}:{config.port}")
    print(f"Runtime config hash: {config_runtime_hash(config)}")
    print(f"JSON inbox: {config.inbox_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Agent Hub")
    finally:
        server.server_close()











































































































