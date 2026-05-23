from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from .models import HubRequest, HubResponse, Message


class SessionStore:
    def __init__(self, state_dir: Path) -> None:
        self.sessions_dir = state_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def load(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.exists():
            return {"session_id": session_id, "messages": [], "events": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def record_turn(self, request: HubRequest, response: HubResponse) -> None:
        data = self.load(request.session_id)
        existing = data.setdefault("messages", [])
        if _is_prefix(existing, request.messages):
            data["messages"] = list(request.messages)
        elif not _is_prefix(request.messages, existing):
            for message in request.messages:
                if not _same_message_at_tail(existing, message):
                    existing.append(message)

        if not _same_message_at_tail(data["messages"], {"role": "assistant", "content": response.text}):
            data["messages"].append({"role": "assistant", "content": response.text})
        # Ensure agent_hub dict exists in raw
        if isinstance(response.raw, dict):
            agent_hub = response.raw.setdefault("agent_hub", {})
            # Initialize session_models list if not present
            session_models = agent_hub.setdefault("session_models", [])
            # Helper to add a model record
            def add_model_record(agent, provider, model, failed=False):
                record = {"agent": agent, "provider": provider, "model": model, "failed": failed}
                if record not in session_models:
                    session_models.append(record)
            # Add failover events
            for event in response.failover:
                add_model_record(event.agent, event.provider, event.model, failed=True)
            # Add the successful response
            add_model_record(response.agent, response.provider, response.model, failed=False)

        data.setdefault("events", []).append(
            {
                "time": int(time.time()),
                "agent": response.agent,
                "provider": response.provider,
                "model": response.model,
                "failover": [event.to_dict() for event in response.failover],
            }
        )
        agent_metadata = response.raw.get("agent_hub") if isinstance(response.raw, dict) else None
        if isinstance(agent_metadata, dict) and isinstance(agent_metadata.get("reasoning_state"), dict):
            data["reasoning_state"] = agent_metadata["reasoning_state"]
        data["updated_at"] = int(time.time())
        _atomic_write_text(self._path(request.session_id), json.dumps(data, indent=2, ensure_ascii=False))

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:140] or "default"
        return self.sessions_dir / f"{safe}.json"


def _same_message_at_tail(messages: list[Message], message: Message) -> bool:
    return bool(messages) and messages[-1].get("role") == message.get("role") and messages[
        -1
    ].get("content") == message.get("content")


def _is_prefix(prefix: list[Message], messages: list[Message]) -> bool:
    if len(prefix) > len(messages):
        return False
    return all(
        left.get("role") == right.get("role") and left.get("content") == right.get("content")
        for left, right in zip(prefix, messages, strict=False)
    )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
