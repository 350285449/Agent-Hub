from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .agent_runner import AgentRunner
from .config import HubConfig
from .payloads import (
    anthropic_message_response,
    openai_chat_response,
    request_from_payload,
)
from .router import AgentRouter, RouterError


class InboxProcessor:
    def __init__(self, config: HubConfig, router: AgentRouter | None = None) -> None:
        self.config = config
        self.router = router or AgentRouter(config)
        self.agent_runner = AgentRunner(config, self.router)
        self.config.ensure_dirs()

    def watch(self, interval_seconds: float = 1.0) -> None:
        print(f"Watching {self.config.inbox_dir} for JSON tasks")
        try:
            while True:
                self.process_once()
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\nStopping inbox watcher")

    def process_once(self) -> list[Path]:
        outputs: list[Path] = []
        for path in sorted(self.config.inbox_dir.glob("*.json")):
            if path.name.endswith(".processing.json"):
                continue
            outputs.append(self.process_file(path))
        return outputs

    def process_file(self, path: Path) -> Path:
        work_path = path.with_name(f"{path.stem}.processing.json")
        path.rename(work_path)
        try:
            payload = json.loads(work_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            api_shape = payload.get("api_shape") or payload.get("target_api") or "native"
            response_shape = payload.get("response_shape") or api_shape
            request = request_from_payload(payload, api_shape=_normalized_shape(api_shape))
            if _wants_agent_mode(payload):
                response = self.agent_runner.run(request)
            else:
                response = self.router.route(request)
            body = _shape_response(
                response_shape,
                response,
                self.config.include_raw_responses,
                self.config.expose_routing_details,
            )
            output_path = self.config.outbox_dir / f"{path.stem}.response.json"
            output_path.write_text(
                json.dumps(body, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (RouterError, ValueError, json.JSONDecodeError) as exc:
            body = {"error": str(exc)}
            if isinstance(exc, RouterError) and self.config.expose_routing_details:
                body["failover"] = [event.to_dict() for event in exc.failover]
            output_path = self.config.outbox_dir / f"{path.stem}.error.json"
            output_path.write_text(
                json.dumps(body, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        archive_path = self.config.archive_dir / f"{int(time.time())}-{path.name}"
        work_path.rename(archive_path)
        return output_path


def _normalized_shape(value: Any) -> str:
    if value in {"openai", "openai-chat", "chat.completions"}:
        return "openai-chat"
    if value in {"anthropic", "anthropic-messages", "claude"}:
        return "anthropic-messages"
    return "native"


def _shape_response(
    response_shape: Any,
    response: Any,
    include_raw: bool,
    include_routing_details: bool,
) -> dict[str, Any]:
    shape = _normalized_shape(response_shape)
    if shape == "openai-chat":
        return openai_chat_response(response, include_routing_details=include_routing_details)
    if shape == "anthropic-messages":
        return anthropic_message_response(response, include_routing_details=include_routing_details)
    return response.to_native_dict(
        include_raw=include_raw,
        include_routing_details=include_routing_details,
    )


def _wants_agent_mode(payload: dict[str, Any]) -> bool:
    hub_options = payload.get("agent_hub")
    if isinstance(hub_options, dict) and "agent_mode" in hub_options:
        return bool(hub_options["agent_mode"])
    if "agent_mode" in payload:
        return bool(payload["agent_mode"])
    mode = payload.get("mode")
    return isinstance(mode, str) and mode.lower() == "agent"
