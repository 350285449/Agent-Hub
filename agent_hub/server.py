from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .agent_runner import AgentRunner
from .config import HubConfig
from .payloads import (
    anthropic_message_response,
    anthropic_stream_events,
    openai_chat_response,
    openai_stream_events,
    request_from_payload,
)
from .router import AgentRouter, RouterError


BACKEND_VERSION = "0.2.1"
BACKEND_FEATURES = {
    "native_agent_streaming": True,
    "agent_progress_v2": True,
    "active_file_context_resolution": True,
    "current_folder_context": True,
    "workspace_shell_commands": True,
}


class AgentHubHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], config: HubConfig) -> None:
        super().__init__(server_address, AgentHubHandler)
        self.config = config
        self.router = AgentRouter(config)
        self.agent_runner = AgentRunner(config, self.router)


class AgentHubHandler(BaseHTTPRequestHandler):
    server: AgentHubHTTPServer

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "version": BACKEND_VERSION,
                    "features": BACKEND_FEATURES,
                    "agents": [
                        name
                        for name, agent in self.server.config.agents.items()
                        if agent.enabled
                    ],
                    "configured_agents": list(self.server.config.agents),
                    "free_only": self.server.config.free_only,
                    "allow_shell_tools": self.server.config.allow_shell_tools,
                    "workspace_dir": str(self.server.config.workspace_dir),
                }
            )
            return
        if self.path == "/v1/models":
            self._send_json(
                {
                    "object": "list",
                    "data": [
                        {
                            "id": agent.model,
                            "object": "model",
                            "owned_by": agent.provider,
                            "agent_hub": {"agent": agent.name},
                        }
                        for agent in self.server.config.agents.values()
                        if agent.enabled
                    ],
                }
            )
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        if self.path in {"/agent", "/v1/agent"}:
            self._handle_payload(
                payload,
                api_shape="native",
                response_shape="native",
                agent_mode_default=True,
            )
            return
        if self.path == "/v1/route":
            self._handle_payload(payload, api_shape="native", response_shape="native")
            return
        if self.path == "/v1/chat/completions":
            self._handle_payload(
                payload,
                api_shape="openai-chat",
                response_shape="openai-chat",
            )
            return
        if self.path == "/v1/messages":
            self._handle_payload(
                payload,
                api_shape="anthropic-messages",
                response_shape="anthropic-messages",
            )
            return
        self._send_json({"error": "not found"}, status=404)

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
        request = request_from_payload(payload, api_shape=api_shape)
        if response_shape == "native" and request.stream:
            self._send_native_stream(
                request,
                agent_mode=_wants_agent_mode(payload, default=agent_mode_default),
            )
            return
        try:
            if _wants_agent_mode(payload, default=agent_mode_default):
                response = self.server.agent_runner.run(request)
            else:
                response = self.server.router.route(request)
        except RouterError as exc:
            error_body: dict[str, Any] = {
                "error": {
                    "message": str(exc),
                    "type": "agent_hub_route_error",
                },
            }
            if self.server.config.expose_routing_details:
                error_body["failover"] = [event.to_dict() for event in exc.failover]
            self._send_json(error_body, status=503)
            return

        if request.stream and response_shape == "openai-chat":
            self._send_openai_stream(response)
            return
        if request.stream and response_shape == "anthropic-messages":
            self._send_anthropic_stream(response)
            return
        if response_shape == "openai-chat":
            self._send_json(
                openai_chat_response(
                    response,
                    include_routing_details=self.server.config.expose_routing_details,
                )
            )
            return
        if response_shape == "anthropic-messages":
            self._send_json(
                anthropic_message_response(
                    response,
                    include_routing_details=self.server.config.expose_routing_details,
                )
            )
            return
        self._send_json(
            response.to_native_dict(
                include_raw=self.server.config.include_raw_responses,
                include_routing_details=self.server.config.expose_routing_details,
            )
        )

    def _send_native_stream(self, request: Any, agent_mode: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
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
            if agent_mode:
                response = self.server.agent_runner.run(request, event_sink=send_progress)
            else:
                send_event("route_started", {"type": "route_started", "message": "Routing request."})
                response = self.server.router.route(request)
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

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_openai_stream(self, response: Any) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
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
        self.end_headers()
        for name, event in anthropic_stream_events(
            response,
            include_routing_details=self.server.config.expose_routing_details,
        ):
            self.wfile.write(f"event: {name}\n".encode("utf-8"))
            self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()


def serve(config: HubConfig) -> None:
    config.ensure_dirs()
    server = AgentHubHTTPServer((config.host, config.port), config)
    print(f"Agent Hub listening on http://{config.host}:{config.port}")
    print(f"JSON inbox: {config.inbox_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Agent Hub")
    finally:
        server.server_close()


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
