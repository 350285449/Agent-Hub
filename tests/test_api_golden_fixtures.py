from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.server import AgentHubHTTPServer


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_FIXTURE = ROOT / "tests" / "fixtures" / "phase05_api_golden.json"


class ApiGoldenFixtureTests(unittest.TestCase):
    def test_phase05_compatibility_endpoints_match_golden_fixtures(self) -> None:
        expected = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        actual = _collect_golden_responses()

        for name in sorted(expected):
            with self.subTest(name=name):
                self.assertEqual(actual[name], expected[name])


class GoldenProvider:
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        raw = request.raw if isinstance(request.raw, dict) else {}
        scenario = raw.get("scenario")
        metadata = raw.get("metadata")
        if scenario is None and isinstance(metadata, dict):
            scenario = metadata.get("scenario")
        if scenario == "tool":
            return ProviderResult(
                text="",
                model=self.agent.model,
                raw={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": "{\"path\":\"README.md\"}",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
                usage={"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
                finish_reason="tool_calls",
            )
        return ProviderResult(
            text="golden hello",
            model=self.agent.model,
            usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            finish_reason="stop",
        )


def _collect_golden_responses() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        server = AgentHubHTTPServer(("127.0.0.1", 0), _golden_config(Path(tmp)))
        server.router.provider_factory = GoldenProvider
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            anthropic_headers = {
                "x-api-key": "local-agent-hub-token",
                "anthropic-version": "2023-06-01",
            }
            chat_stream, chat_headers = _post_text(
                f"{base}/v1/chat/completions",
                {
                    "model": "agent-hub-coding",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )
            responses_stream, responses_headers = _post_text(
                f"{base}/v1/responses",
                {
                    "model": "agent-hub-coding",
                    "input": "hello",
                    "stream": True,
                },
            )
            messages_stream, messages_headers = _post_text(
                f"{base}/v1/messages",
                {
                    "model": "agent-hub-coding",
                    "max_tokens": 128,
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
                headers=anthropic_headers,
            )
            return {
                "chat_success": _try_post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                ),
                "chat_tool": _try_post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent-hub-coding",
                        "scenario": "tool",
                        "messages": [{"role": "user", "content": "read"}],
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "parameters": {"type": "object"},
                                },
                            }
                        ],
                    },
                ),
                "chat_stream": {
                    "headers": {
                        "X-Agent-Hub-Stream-Mode": chat_headers.get("X-Agent-Hub-Stream-Mode")
                    },
                    "events": _parse_sse_events(chat_stream),
                },
                "chat_failure": _try_post_json(
                    f"{base}/v1/chat/completions",
                    {
                        "model": "agent:missing",
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                ),
                "responses_success": _try_post_json(
                    f"{base}/v1/responses",
                    {
                        "model": "agent-hub-coding",
                        "input": "hello",
                    },
                ),
                "responses_tool": _try_post_json(
                    f"{base}/v1/responses",
                    {
                        "model": "agent-hub-coding",
                        "scenario": "tool",
                        "input": "read",
                        "tools": [
                            {
                                "type": "function",
                                "name": "read_file",
                                "parameters": {"type": "object"},
                            }
                        ],
                    },
                ),
                "responses_stream": {
                    "headers": {
                        "X-Agent-Hub-Stream-Mode": responses_headers.get("X-Agent-Hub-Stream-Mode")
                    },
                    "events": _parse_sse_events(responses_stream),
                },
                "responses_failure": _try_post_json(
                    f"{base}/v1/responses",
                    {
                        "model": "agent:missing",
                        "input": "hello",
                    },
                ),
                "messages_success": _try_post_json(
                    f"{base}/v1/messages",
                    {
                        "model": "agent-hub-coding",
                        "max_tokens": 128,
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                    headers=anthropic_headers,
                ),
                "messages_tool": _try_post_json(
                    f"{base}/v1/messages",
                    {
                        "model": "agent-hub-coding",
                        "scenario": "tool",
                        "max_tokens": 128,
                        "messages": [{"role": "user", "content": "read"}],
                        "tools": [
                            {
                                "name": "read_file",
                                "input_schema": {"type": "object"},
                            }
                        ],
                    },
                    headers=anthropic_headers,
                ),
                "messages_stream": {
                    "headers": {
                        "X-Agent-Hub-Stream-Mode": messages_headers.get("X-Agent-Hub-Stream-Mode")
                    },
                    "events": _parse_sse_events(messages_stream),
                },
                "messages_failure": _try_post_json(
                    f"{base}/v1/messages",
                    {
                        "model": "agent:missing",
                        "max_tokens": 128,
                        "messages": [{"role": "user", "content": "hello"}],
                    },
                    headers=anthropic_headers,
                ),
                "models_success": _get_json(f"{base}/v1/models"),
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def _golden_config(path: Path) -> HubConfig:
    return HubConfig(
        state_dir=path / "state",
        default_route=["tooly"],
        routes=[
            RouteRule(name="coding", agents=["tooly"]),
            RouteRule(name="cloud-agent", agents=["tooly"]),
            RouteRule(name="local-agent", agents=["tooly"]),
        ],
        agents={
            "tooly": AgentConfig(
                name="tooly",
                provider="openai-compatible",
                model="tool-model",
                base_url="http://127.0.0.1:9999",
                free=True,
                enabled=True,
                supports_tools=True,
                supports_function_calling=True,
                supports_streaming=True,
            )
        },
    )


def _try_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        return _post_json(url, payload, headers=headers)[0]
    except HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        status = exc.code
        exc.close()
        return {"status": status, "body": _normalize_dynamic_values(body)}


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        data = json.loads(response.read().decode("utf-8"))
        return _normalize_dynamic_values(data), dict(response.headers.items())


def _post_text(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8"), dict(response.headers.items())


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=5) as response:
        data = json.loads(response.read().decode("utf-8"))
    return _normalize_dynamic_values(data)


def _parse_sse_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        data_text = "\n".join(data_lines)
        if data_text == "[DONE]":
            data: Any = "[DONE]"
        else:
            data = json.loads(data_text)
        events.append({"event": event, "data": _normalize_dynamic_values(data)})
    return events


def _normalize_dynamic_values(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key == "id" and isinstance(item, str):
                normalized[key] = _normalize_id(item)
            elif key in {"created", "created_at"}:
                normalized[key] = 0
            else:
                normalized[key] = _normalize_dynamic_values(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_dynamic_values(item) for item in value]
    if isinstance(value, str):
        return _normalize_id(value)
    return value


def _normalize_id(value: str) -> str:
    if value.startswith("chatcmpl-hub-"):
        return "chatcmpl-<request-id>"
    if value.startswith("resp_hub-"):
        return "resp_<request-id>"
    if value.startswith("msg_hub-"):
        return "msg_<request-id>"
    if value.startswith("hub-"):
        return "<request-id>"
    return value


if __name__ == "__main__":
    unittest.main()
