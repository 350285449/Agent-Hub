from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..config import AgentConfig
from ..models import HubRequest, ProviderResult
from .base import BaseProviderAdapter
from .errors import ProviderError
from .shared import _openai_messages

_CHARS_PER_TOKEN = 4
_DEFAULT_PROMPT_BUDGET_TOKENS = 6_000
_OPTIMIZED_PROMPT_BUDGET_TOKENS = 2_400
_OPTIMIZED_RECENT_MESSAGES = 4
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]{8,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----|"
    r"\bsk-[A-Za-z0-9_-]{20,}",
    re.DOTALL,
)


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
            optimized = _codex_prompt_optimized(request)
            return ProviderResult(
                text=text,
                model=self.agent.model,
                raw={
                    "provider": "codex-cli",
                    "returncode": completed.returncode,
                    "prompt_chars": len(prompt),
                    "prompt_optimized": optimized,
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

    optimized = _codex_prompt_optimized(request)
    budget_chars = _codex_prompt_budget_chars(request, optimized=optimized)
    selected_messages = _selected_messages(messages, optimized=optimized)
    context_budget = max(800, int(budget_chars * (0.38 if optimized else 0.55)))
    message_budget = max(800, budget_chars - context_budget - 1200)

    lines = [
        "Agent-Hub routed this request to the local Codex CLI.",
        "Answer as the assistant.",
        "If the transcript asks for an Agent-Hub JSON action, output exactly one JSON object and no Markdown.",
        "Otherwise, output only the final response text.",
        "Do not mention this Codex CLI wrapper.",
    ]
    if optimized:
        lines.append("Use the compact context below; prefer concise answers and avoid restating unchanged code.")
    if request.max_tokens:
        lines.append(f"Keep the response within about {request.max_tokens} tokens.")
    if request.context:
        lines.extend(["", "Context:", _compact_text(request.context, context_budget)])
    lines.append("")
    lines.append("Conversation:")
    per_message_budget = max(600, int(message_budget / max(1, len(selected_messages))))
    for message in selected_messages:
        role = str(message.get("role") or "user").upper()
        content = _compact_text(_content_text(message.get("content")), per_message_budget)
        metadata = {
            key: value
            for key, value in message.items()
            if key not in {"role", "content"} and value not in (None, "", [], {})
        }
        lines.append(f"<{role}>")
        lines.append(content)
        if metadata and not optimized:
            lines.append("Metadata:")
            lines.append(_compact_text(json.dumps(metadata, ensure_ascii=False, default=str), per_message_budget))
        lines.append(f"</{role}>")
        lines.append("")
    return _compact_text("\n".join(lines).strip(), budget_chars) + "\n"


def _selected_messages(messages: list[dict[str, Any]], *, optimized: bool) -> list[dict[str, Any]]:
    if not optimized or len(messages) <= _OPTIMIZED_RECENT_MESSAGES + 1:
        return messages
    system_messages = [message for message in messages if str(message.get("role") or "").lower() == "system"]
    non_system = [message for message in messages if str(message.get("role") or "").lower() != "system"]
    selected: list[dict[str, Any]] = []
    if system_messages:
        selected.append(system_messages[-1])
    selected.extend(non_system[-_OPTIMIZED_RECENT_MESSAGES:])
    return selected


def _codex_prompt_optimized(request: HubRequest) -> bool:
    env = os.environ.get("AGENT_HUB_CODEX_CLI_TOKEN_OPTIMIZED")
    if env is not None:
        return env.strip().lower() not in {"0", "false", "off", "no"}
    options = _agent_hub_options(request)
    raw = request.raw if isinstance(request.raw, dict) else {}
    if any(
        bool(options.get(key))
        for key in (
            "codex_cli_token_optimized",
            "max_token_save_mode",
            "minimal_tool_schema",
            "reduced_repo_context",
        )
    ):
        return True
    context_mode = str(options.get("context_mode") or raw.get("context_mode") or "").lower()
    if context_mode == "minimal":
        return True
    budget = _positive_int(
        options.get("codex_cli_prompt_budget_tokens")
        or options.get("context_budget_tokens")
        or options.get("max_context_tokens")
        or raw.get("agent_context_budget_tokens")
    )
    return budget is not None and budget <= 4_000


def _codex_prompt_budget_chars(request: HubRequest, *, optimized: bool) -> int:
    env_budget = _positive_int(os.environ.get("AGENT_HUB_CODEX_CLI_PROMPT_TOKENS"))
    if env_budget is not None:
        return env_budget * _CHARS_PER_TOKEN
    options = _agent_hub_options(request)
    configured = _positive_int(
        options.get("codex_cli_prompt_budget_tokens")
        or options.get("context_budget_tokens")
        or options.get("max_context_tokens")
    )
    if configured is not None:
        return configured * _CHARS_PER_TOKEN
    default_budget = _OPTIMIZED_PROMPT_BUDGET_TOKENS if optimized else _DEFAULT_PROMPT_BUDGET_TOKENS
    return default_budget * _CHARS_PER_TOKEN


def _agent_hub_options(request: HubRequest) -> dict[str, Any]:
    raw = request.raw if isinstance(request.raw, dict) else {}
    options = raw.get("agent_hub")
    return options if isinstance(options, dict) else {}


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _compact_text(value: Any, maximum_chars: int) -> str:
    text = _redact_secrets(str(value or ""))
    maximum = max(200, int(maximum_chars))
    if len(text) <= maximum:
        return text
    marker = f"\n...[{len(text) - maximum} chars compacted for Codex token budget]...\n"
    keep = max(80, maximum - len(marker))
    head = max(40, int(keep * 0.42))
    tail = max(40, keep - head)
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def _redact_secrets(text: str) -> str:
    return _SECRET_RE.sub("[redacted secret]", text)


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
