from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import HubConfig
from .payloads import (
    anthropic_message_response,
    anthropic_stream_events,
    openai_chat_response,
    openai_stream_events,
    request_from_payload,
)
from .router import AgentRouter, RouterError


class AgentHubHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], config: HubConfig) -> None:
        super().__init__(server_address, AgentHubHandler)
        self.config = config
        self.router = AgentRouter(config)


class AgentHubHandler(BaseHTTPRequestHandler):
    server: AgentHubHTTPServer

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"status": "ok", "agents": list(self.server.config.agents)})
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

        if self.path in {"/agent", "/v1/agent", "/v1/route"}:
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
    ) -> None:
        request = request_from_payload(payload, api_shape=api_shape)
        try:
            response = self.server.router.route(request)
        except RouterError as exc:
            self._send_json(
                {
                    "error": {
                        "message": str(exc),
                        "type": "agent_hub_route_error",
                    },
                    "failover": [event.to_dict() for event in exc.failover],
                },
                status=503,
            )
            return

        if request.stream and response_shape == "openai-chat":
            self._send_openai_stream(response)
            return
        if request.stream and response_shape == "anthropic-messages":
            self._send_anthropic_stream(response)
            return
        if response_shape == "openai-chat":
            self._send_json(openai_chat_response(response))
            return
        if response_shape == "anthropic-messages":
            self._send_json(anthropic_message_response(response))
            return
        self._send_json(
            response.to_native_dict(include_raw=self.server.config.include_raw_responses)
        )

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
        for event in openai_stream_events(response):
            data = event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_anthropic_stream(self, response: Any) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for name, event in anthropic_stream_events(response):
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
