from __future__ import annotations

from typing import Any

from ..config import AgentConfig


SECRET_KEYS = ("api_key", "authorization", "token", "secret", "password", "credential")


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
        if _secret_key(str(key)):
            masked[key] = mask_secret_value(value)
        elif isinstance(value, dict):
            masked[key] = mask_mapping_secrets(value)
        else:
            masked[key] = value
    return masked


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


def _secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_KEYS)


__all__ = ["mask_mapping_secrets", "mask_secret_value", "masked_agent_config"]
