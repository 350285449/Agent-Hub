from __future__ import annotations

import re
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
    "api-key",
    "api_key",
    "auth_token",
    "bearer_token",
    "id_token",
    "refresh_token",
    "token",
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
)


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
    for pattern in SECRET_VALUE_PATTERNS:
        text = pattern.sub(_redacted_match, text)
    return text


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


def _redacted_match(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 2:
        return f"{match.group(1)}=[REDACTED]"
    if match.lastindex == 1:
        value = match.group(1)
        if value.lower().startswith("bearer"):
            return f"{value}[REDACTED]"
    return "[REDACTED]"


__all__ = [
    "mask_mapping_secrets",
    "mask_secret_value",
    "masked_agent_config",
    "redact_secret_like_text",
    "redact_secrets",
    "secret_key",
]
