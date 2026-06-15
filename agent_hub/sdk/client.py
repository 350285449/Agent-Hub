from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .types import ChatMessage, SDKResponse


class AgentHubClientError(RuntimeError):
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error") or payload.get("message") or f"Agent-Hub HTTP {status_code}")
        self.status_code = status_code
        self.payload = payload


class AgentHubClient:
    """Dependency-free Python client for the stable local Agent-Hub API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8787",
        *,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def route(
        self,
        messages: list[ChatMessage],
        *,
        model: str = "agent-hub",
        route: str | None = None,
        session_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> SDKResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if route:
            payload["route"] = route
        if session_id:
            payload["session_id"] = session_id
        if extra:
            payload.update(extra)
        return SDKResponse(self.post("/v1/chat/completions", payload))

    def simulate_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("/v1/routing/simulate", payload)

    def readiness(self) -> dict[str, Any]:
        return self.get("/v1/readiness")

    def openapi(self) -> dict[str, Any]:
        return self.get("/openapi.json")

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers=self._headers(payload is not None),
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raw = error.read().decode("utf-8")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"error": raw}
            raise AgentHubClientError(error.code, payload) from error

    def _headers(self, has_body: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if has_body:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
