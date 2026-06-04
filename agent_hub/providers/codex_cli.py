from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..config import AgentConfig
from ..models import HubRequest, ProviderResult
from .base import BaseProviderAdapter
from .errors import ProviderError
from .shared import _openai_messages


class CodexCliProvider(BaseProviderAdapter):
    """Adapter that calls a locally authenticated Codex CLI session."""

    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        output_path = _temporary_output_path()
        command = _codex_exec_command(self.agent, output_path)
        prompt = _codex_prompt(request)
        try:
            completed = subprocess.run(
                command,
                input=prompt.encode("utf-8"),
                capture_output=True,
                timeout=max(1.0, float(self.agent.timeout_seconds or 120.0)),
                cwd=os.getcwd(),
            )
            output_text = _read_output(output_path).strip()
            if completed.returncode != 0:
                raise ProviderError(
                    _failure_message(completed),
                    retryable=True,
                    error_type=_failure_type(completed),
                    metadata={
                        "provider": "codex-cli",
                        "returncode": completed.returncode,
                        "stdout": _short(completed.stdout),
                        "stderr": _short(completed.stderr),
                    },
                )
            text = output_text or completed.stdout.strip()
            return ProviderResult(
                text=text,
                model=self.agent.model,
                raw={
                    "provider": "codex-cli",
                    "returncode": completed.returncode,
                    "stdout": _short(completed.stdout),
                    "stderr": _short(completed.stderr),
                },
                finish_reason="stop",
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"Codex CLI timed out after {self.agent.timeout_seconds:g}s",
                retryable=True,
                error_type="timeout",
                metadata={"provider": "codex-cli", "stdout": _short(exc.stdout), "stderr": _short(exc.stderr)},
            ) from exc
        except OSError as exc:
            raise ProviderError(
                f"Could not run Codex CLI: {exc}",
                retryable=True,
                error_type="configuration",
                metadata={"provider": "codex-cli"},
            ) from exc
        finally:
            _remove_output(output_path)

    def supports_streaming(self) -> bool:
        return False


def _codex_exec_command(agent: AgentConfig, output_path: Path) -> list[str]:
    command = os.environ.get("AGENT_HUB_CODEX_CLI_COMMAND", "codex")
    args = [
        command,
        "--ask-for-approval",
        os.environ.get("AGENT_HUB_CODEX_CLI_APPROVAL", "never"),
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        os.environ.get("AGENT_HUB_CODEX_CLI_SANDBOX", "read-only"),
        "--color",
        "never",
        "--output-last-message",
        str(output_path),
    ]
    if agent.model and agent.model.lower() not in {"default", "codex-default"}:
        args.extend(["--model", agent.model])
    extra_profile = os.environ.get("AGENT_HUB_CODEX_CLI_PROFILE")
    if extra_profile:
        args.extend(["--profile", extra_profile])
    args.append("-")
    return args


def _codex_prompt(request: HubRequest) -> str:
    messages = _openai_messages(request.messages)
    if not messages and request.task:
        messages = [{"role": "user", "content": request.task}]

    lines = [
        "You are being invoked by Agent-Hub as a routed model provider.",
        "Answer the conversation below as the assistant.",
        "If the transcript asks for an Agent-Hub JSON action, output exactly one JSON object and no Markdown.",
        "Otherwise, output only the final assistant response text.",
        "Do not mention this Codex CLI wrapper.",
    ]
    if request.max_tokens:
        lines.append(f"Keep the response within about {request.max_tokens} tokens.")
    if request.context:
        lines.extend(["", "Context:", str(request.context)])
    lines.append("")
    lines.append("Conversation:")
    for message in messages:
        role = str(message.get("role") or "user").upper()
        content = _content_text(message.get("content"))
        metadata = {
            key: value
            for key, value in message.items()
            if key not in {"role", "content"} and value not in (None, "", [], {})
        }
        lines.append(f"<{role}>")
        lines.append(content)
        if metadata:
            lines.append("Metadata:")
            lines.append(json.dumps(metadata, ensure_ascii=False, default=str))
        lines.append(f"</{role}>")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
                else:
                    parts.append(json.dumps(item, ensure_ascii=False, default=str))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False, default=str)


def _temporary_output_path() -> Path:
    fd, path = tempfile.mkstemp(prefix="agent-hub-codex-", suffix=".txt")
    os.close(fd)
    return Path(path)


def _read_output(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _remove_output(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _failure_message(completed: subprocess.CompletedProcess[Any]) -> str:
    text = (_decode(completed.stderr) or _decode(completed.stdout)).strip()
    if not text:
        text = f"Codex CLI exited with status {completed.returncode}"
    return _short(text, maximum=1000)


def _failure_type(completed: subprocess.CompletedProcess[Any]) -> str:
    text = f"{_decode(completed.stdout)}\n{_decode(completed.stderr)}".lower()
    if any(marker in text for marker in ("login", "auth", "access token", "api key", "unauthorized")):
        return "configuration"
    if any(marker in text for marker in ("rate limit", "quota", "usage limit")):
        return "quota_exhausted"
    return "provider_error"


def _short(value: Any, *, maximum: int = 2000) -> str:
    text = _decode(value)
    if len(text) <= maximum:
        return text
    return text[: maximum - 3] + "..."


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


CodexCLIProvider = CodexCliProvider


__all__ = ["CodexCLIProvider", "CodexCliProvider"]
