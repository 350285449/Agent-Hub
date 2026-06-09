from __future__ import annotations

import hashlib
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
_TASK_KEYWORD_LIMIT = 24
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]{8,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----|"
    r"\bsk-[A-Za-z0-9_-]{20,}",
    re.DOTALL,
)
_CONTEXT_ANCHOR_RE = re.compile(
    r"(?i)^\s*(file|current file|current folder|language|diff --git|@@|[-+]{3}\s|current folder files)\b"
)
_CODE_SYMBOL_RE = re.compile(
    r"^\s*(async\s+)?(def|class|function|const|let|var|import|export|interface|type|enum)\b|"
    r"^\s*[A-Za-z_][\w$.-]{2,}\s*[:=]\s*"
)
_TASK_STOPWORDS = {
    "about",
    "after",
    "again",
    "agent",
    "because",
    "before",
    "codex",
    "could",
    "current",
    "from",
    "have",
    "into",
    "should",
    "that",
    "their",
    "there",
    "these",
    "this",
    "through",
    "want",
    "what",
    "when",
    "where",
    "while",
    "with",
    "would",
}


class CodexCliProvider(BaseProviderAdapter):
    """Adapter that calls a locally authenticated Codex CLI session."""

    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent

    def complete(self, request: HubRequest) -> ProviderResult:
        output_path = _temporary_output_path()
        command = _codex_exec_command(self.agent, output_path)
        prompt = _codex_prompt(request)
        optimized = _codex_prompt_optimized(request)
        budget_chars = _codex_prompt_budget_chars(request, optimized=optimized)
        options = _agent_hub_options(request)
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
                    "prompt_chars": len(prompt),
                    "prompt_budget_tokens": max(1, budget_chars // _CHARS_PER_TOKEN),
                    "prompt_optimized": optimized,
                    "token_safe_profile": options.get("token_safe_profile") or ("optimized" if optimized else "standard"),
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
    latest_task = _latest_task_text(selected_messages) or request.task or ""
    options = _agent_hub_options(request)
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
        profile = str(options.get("token_safe_profile") or "surgical")
        lines.append(
            f"Token-safe profile: {profile}. Use the compact context digest below; "
            "prefer concise answers, inspect files only when needed, and avoid restating unchanged code."
        )
    if request.max_tokens:
        lines.append(f"Keep the response within about {request.max_tokens} tokens.")
    if request.context:
        heading = "Context digest:" if optimized else "Context:"
        context_text = _context_digest(request.context, latest_task, context_budget) if optimized else _compact_text(request.context, context_budget)
        lines.extend(["", heading, context_text])
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


def _latest_task_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "").lower() == "user":
            return _content_text(message.get("content"))
    return ""


def _context_digest(context: Any, task_text: str, budget_chars: int) -> str:
    text = _redact_secrets(str(context or ""))
    if len(text) <= budget_chars:
        return text
    maximum = max(800, int(budget_chars))
    keywords = _task_keywords(task_text)
    lines = text.splitlines()
    selected: dict[int, int] = {}
    for index, line in enumerate(lines):
        score = _context_line_score(line, keywords)
        if score <= 0:
            continue
        selected[index] = max(score, selected.get(index, 0))
        if score >= 6:
            if index > 0:
                selected.setdefault(index - 1, 1)
            if index + 1 < len(lines):
                selected.setdefault(index + 1, 1)

    if not selected:
        return _compact_text(text, maximum)

    digest_lines = [
        "[Agent Hub token-safe context digest]",
        f"source_chars={len(text)} source_sha256={hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]} selected_lines={len(selected)}",
    ]
    for index in sorted(selected, key=lambda item: (-selected[item], item))[:160]:
        digest_lines.append(f"L{index + 1}: {lines[index]}")
    digest_lines = digest_lines[:2] + sorted(digest_lines[2:], key=_digest_line_number)
    digest = "\n".join(digest_lines)
    if len(digest) <= maximum:
        return digest
    marker = "\n...[context digest trimmed; ask Agent Hub tools for exact file contents if needed]...\n"
    keep = max(200, maximum - len(marker))
    return digest[:keep].rstrip() + marker


def _digest_line_number(line: str) -> int:
    match = re.match(r"L(\d+):", line)
    return int(match.group(1)) if match else 0


def _context_line_score(line: str, keywords: list[str]) -> int:
    stripped = line.strip()
    if not stripped:
        return 0
    score = 0
    lowered = stripped.lower()
    if _CONTEXT_ANCHOR_RE.search(stripped):
        score += 8
    if _CODE_SYMBOL_RE.search(stripped):
        score += 3
    if stripped.startswith(("+", "-")) and not stripped.startswith(("+++", "---")):
        score += 3
    if "[redacted secret]" in lowered:
        score += 4
    if any(keyword in lowered for keyword in keywords):
        score += 6
    if re.search(r"[\w./-]+\.(py|js|ts|tsx|jsx|json|md|toml|yaml|yml|css|html)\b", stripped, re.I):
        score += 2
    return score


def _task_keywords(text: str) -> list[str]:
    counts: dict[str, int] = {}
    for raw in re.findall(r"[A-Za-z0-9_./-]{4,}", text.lower()):
        word = raw.strip("./-_")
        if not word or word in _TASK_STOPWORDS or word.isdigit():
            continue
        counts[word] = counts.get(word, 0) + 1
    return [
        word
        for word, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:_TASK_KEYWORD_LIMIT]
    ]


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
