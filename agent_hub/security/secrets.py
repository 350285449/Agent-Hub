from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import AgentConfig


SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "x_api_key",
    "x-api-key",
)
SECRET_KEY_EXACT = {
    "access_token",
    "api_auth_token",
    "api-key",
    "api_key",
    "auth_token",
    "bearer_token",
    "diagnostics_auth_token",
    "id_token",
    "refresh_token",
    "token",
    "trusted_approval_token",
    "x-api-key",
}
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_\-]{12,})\b"),
    re.compile(r"(?i)\b(ghp_[A-Za-z0-9_]{12,})\b"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(
        r"(?i)\b(api[_-]?key|authorization|x-api-key|api-key|access[_-]?token|refresh[_-]?token|secret)\s*[:=]\s*['\"]?([A-Za-z0-9._~+/=-]{8,})"
    ),
    re.compile(
        r"\b(?=[A-Za-z0-9._~+/=-]{36,}\b)(?=[A-Za-z0-9._~+/=-]*[A-Za-z])(?=[A-Za-z0-9._~+/=-]*\d)(?=[A-Za-z0-9._~+/=-]*[._~+/=-])[A-Za-z0-9._~+/=-]{36,}\b"
    ),
)
LONG_SECRET_PATTERN_INDEX = len(SECRET_VALUE_PATTERNS) - 1
SAFE_OPERATIONAL_IDENTIFIER_PATTERNS = (
    re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    re.compile(r"(?i)^(?:hub|resp|chatcmpl|msg|toolu|call|thread|run|task|session|conversation|trace|request)[_-][A-Za-z0-9][A-Za-z0-9_.-]{16,}$"),
    re.compile(r"(?i)^(?:session|conversation|thread|request|trace|tool(?:_use)?|call|message|msg|run|task|workflow|checkpoint)_?id=[A-Za-z0-9][A-Za-z0-9_.:-]{16,}$"),
)
PROMPT_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_instructions", re.compile(r"(?i)\bignore (?:all )?(?:previous|prior|system|developer) instructions\b")),
    ("override_rules", re.compile(r"(?i)\b(?:override|bypass|disable) (?:the )?(?:system|developer|tool|safety|security) (?:rules|instructions|policy)\b")),
    ("exfiltrate_secrets", re.compile(r"(?i)\b(?:send|upload|exfiltrate|leak|print|dump).{0,80}\b(?:secret|token|api key|password|private key|\\.env)\b")),
    ("system_prompt_request", re.compile(r"(?i)\b(?:reveal|print|show|copy).{0,80}\b(?:system prompt|developer message|tool instructions)\b")),
    ("tool_rule_override", re.compile(r"(?i)\b(?:use|call|run).{0,80}\b(?:shell|terminal|powershell|bash).{0,80}\bwithout (?:approval|permission)\b")),
)
SENSITIVE_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(?:^|[\\/])\.env(?:\.|$)"),
    re.compile(r"(?i)(?:^|[\\/])\.npmrc$"),
    re.compile(r"(?i)(?:^|[\\/])\.pypirc$"),
    re.compile(r"(?i)(?:^|[\\/])id_rsa$"),
    re.compile(r"(?i)(?:^|[\\/])id_ed25519$"),
    re.compile(r"(?i)(?:^|[\\/]).*private.*key"),
)


@dataclass(slots=True)
class ContextSecurityScan:
    """Summary of repo/context safety findings before provider calls."""

    text: str
    secret_findings: list[dict[str, Any]]
    injection_findings: list[dict[str, Any]]
    sensitive_files: list[str]

    @property
    def has_findings(self) -> bool:
        return bool(self.secret_findings or self.injection_findings or self.sensitive_files)

    @property
    def has_secret_findings(self) -> bool:
        return bool(self.secret_findings)

    @property
    def has_sensitive_file_references(self) -> bool:
        return bool(self.sensitive_files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "secret_findings": self.secret_findings,
            "injection_findings": self.injection_findings,
            "sensitive_files": self.sensitive_files,
            "has_findings": self.has_findings,
            "has_secret_findings": self.has_secret_findings,
            "has_sensitive_file_references": self.has_sensitive_file_references,
        }


def mask_secret_value(value: Any) -> str:
    text = "" if value is None else str(value)
    if not text:
        return ""
    if len(text) <= 8:
        return "***"
    return f"{text[:2]}...{text[-4:]}"


def mask_mapping_secrets(data: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for key, value in data.items():
        if secret_key(str(key)):
            masked[key] = mask_secret_value(value)
        elif isinstance(value, dict):
            masked[key] = mask_mapping_secrets(value)
        elif isinstance(value, str):
            masked[key] = redact_secret_like_text(value)
        else:
            masked[key] = value
    return masked


def redact_secrets(value: Any) -> Any:
    """Recursively redact configured secrets and secret-like provider text."""

    return _redact(value)


def redact_secret_like_text(value: str) -> str:
    text = value
    for index, pattern in enumerate(SECRET_VALUE_PATTERNS):
        text = pattern.sub(lambda match, index=index: _redacted_match(match, index=index), text)
    return text


def scan_and_redact_context_text(value: str, *, source: str = "") -> ContextSecurityScan:
    """Detect and redact secrets and prompt-injection-like instructions in context text."""

    text = value or ""
    secret_findings = _secret_findings(text, source=source)
    injection_findings = _prompt_injection_findings(text, source=source)
    sensitive_files = _sensitive_paths(text)
    return ContextSecurityScan(
        text=redact_secret_like_text(text),
        secret_findings=secret_findings[:20],
        injection_findings=injection_findings[:20],
        sensitive_files=sensitive_files[:20],
    )


def provider_security_context_from_messages(
    messages: list[dict[str, Any]],
    *,
    context: str | None = None,
) -> dict[str, Any]:
    """Return provider-call security metadata from already-prepared messages."""

    combined = "\n".join(
        [
            context or "",
            *[
                str(message.get("content") or "")
                for message in messages
                if isinstance(message, dict)
            ],
        ]
    )
    return scan_and_redact_context_text(combined).to_dict()


def secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in {item.replace("-", "_") for item in SECRET_KEY_EXACT}:
        return True
    return any(marker.replace("-", "_") in normalized for marker in SECRET_KEY_MARKERS)


def masked_agent_config(agent: AgentConfig) -> dict[str, Any]:
    return {
        "name": agent.name,
        "provider": agent.provider,
        "provider_type": agent.provider_type,
        "model": agent.model,
        "enabled": agent.enabled,
        "api_key_env": agent.api_key_env,
        "api_key": mask_secret_value(agent.api_key) if agent.api_key else None,
        "base_url": agent.base_url,
        "headers": mask_mapping_secrets(dict(agent.headers)),
        "privacy_mode": agent.privacy_mode,
        "local_only": agent.local_only,
        "safe_for_code": agent.safe_for_code,
        "safe_for_secrets": agent.safe_for_secrets,
        "never_send_workspace_files": agent.never_send_workspace_files,
    }


def _redact(value: Any, key: str = "") -> Any:
    if secret_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return redact_secret_like_text(value)
    return value


def _redacted_match(match: re.Match[str], *, index: int) -> str:
    if index == LONG_SECRET_PATTERN_INDEX and _safe_long_secret_candidate(match.group(0)):
        return match.group(0)
    if match.lastindex and match.lastindex >= 2:
        return f"{match.group(1)}=[REDACTED]"
    if match.lastindex == 1:
        value = match.group(1)
        if value.lower().startswith("bearer"):
            return f"{value}[REDACTED]"
    return "[REDACTED]"


def _secret_findings(text: str, *, source: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not text:
        return findings
    line_starts = _line_starts(text)
    for index, pattern in enumerate(SECRET_VALUE_PATTERNS):
        for match in pattern.finditer(text):
            if index == LONG_SECRET_PATTERN_INDEX and _safe_long_secret_candidate(match.group(0)):
                continue
            findings.append(
                {
                    "kind": _secret_kind(index, match.group(0)),
                    "preview": redact_secret_like_text(match.group(0))[:160],
                    "line": _line_for_offset(line_starts, match.start()),
                    **({"source": source} if source else {}),
                }
            )
            if len(findings) >= 20:
                return findings
    return findings


def _safe_long_secret_candidate(value: str) -> bool:
    text = str(value or "").strip()
    if any(pattern.fullmatch(text) for pattern in SAFE_OPERATIONAL_IDENTIFIER_PATTERNS):
        return True
    return _looks_like_path_or_model_identifier(text)


def _looks_like_path_or_model_identifier(value: str) -> bool:
    if "/" not in value or any(marker in value for marker in ("+", "=")):
        return False
    segments = [segment for segment in value.split("/") if segment]
    if len(segments) < 2:
        return False
    return "." in value or "-" in value or "_" in value or len(segments) >= 3


def _prompt_injection_findings(text: str, *, source: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not text:
        return findings
    line_starts = _line_starts(text)
    for kind, pattern in PROMPT_INJECTION_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(
                {
                    "kind": kind,
                    "preview": match.group(0)[:160],
                    "line": _line_for_offset(line_starts, match.start()),
                    **({"source": source} if source else {}),
                }
            )
            if len(findings) >= 20:
                return findings
    return findings


def _sensitive_paths(text: str) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        candidate = line.strip().strip("`'\"")
        if ":" in candidate:
            candidate = candidate.split(":", 1)[1].strip()
        if _safe_sensitive_template_path(candidate):
            continue
        if any(pattern.search(candidate) for pattern in SENSITIVE_PATH_PATTERNS):
            if candidate not in paths:
                paths.append(candidate[:240])
        if len(paths) >= 20:
            break
    return paths


def _safe_sensitive_template_path(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name in {
        ".env.example",
        ".env.sample",
        ".env.template",
        ".env.dist",
        ".env.defaults",
    }


def _secret_kind(index: int, value: str) -> str:
    lowered = value.lower()
    if "bearer" in lowered:
        return "bearer_token"
    if lowered.startswith("sk-"):
        return "api_key"
    if lowered.startswith("ghp_"):
        return "github_token"
    if lowered.startswith("akia"):
        return "aws_access_key"
    if index == len(SECRET_VALUE_PATTERNS) - 1:
        return "long_secret"
    return "secret_assignment"


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for match in re.finditer(r"\n", text):
        starts.append(match.end())
    return starts


def _line_for_offset(starts: list[int], offset: int) -> int:
    line = 1
    for index, start in enumerate(starts, start=1):
        if start > offset:
            break
        line = index
    return line


__all__ = [
    "mask_mapping_secrets",
    "mask_secret_value",
    "masked_agent_config",
    "provider_security_context_from_messages",
    "scan_and_redact_context_text",
    "redact_secret_like_text",
    "redact_secrets",
    "secret_key",
]
