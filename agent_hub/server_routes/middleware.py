from __future__ import annotations

import hmac
import os
from typing import Any
from urllib.parse import parse_qs

from ..config import HubConfig


def request_path(path: str) -> str:
    return path.split("?", 1)[0]


def request_query(path: str) -> dict[str, str]:
    if "?" not in path:
        return {}
    parsed = parse_qs(path.split("?", 1)[1], keep_blank_values=False)
    return {
        key: values[-1]
        for key, values in parsed.items()
        if values
    }


def api_auth_error(config: HubConfig, headers: Any) -> tuple[dict[str, Any], int] | None:
    if not api_auth_required(config):
        return None
    expected = api_token(config)
    if not expected:
        return (
            {
                "error": {
                    "type": "api_auth_not_configured",
                    "message": (
                        "All Agent Hub endpoints require api_auth_token/api_auth_token_env "
                        "or diagnostics_auth_token/diagnostics_auth_token_env unless "
                        "dev_unauthenticated_mode is explicitly enabled."
                    ),
                }
            },
            403,
        )
    provided = api_token_from_headers(headers)
    if provided and hmac.compare_digest(provided, expected):
        return None
    return (
        {
            "error": {
                "type": "api_auth_required",
                "message": "Agent Hub API authentication is required for this endpoint.",
            }
        },
        401,
    )


def diagnostics_auth_error(config: HubConfig, headers: Any) -> tuple[dict[str, Any], int] | None:
    return api_auth_error(config, headers)


def api_auth_required(config: HubConfig) -> bool:
    if bool(getattr(config, "dev_unauthenticated_mode", False)):
        return False
    return bool(getattr(config, "local_auth_required", False)) or public_bind_host(
        str(getattr(config, "host", "127.0.0.1") or "127.0.0.1")
    )


def diagnostics_auth_required(config: HubConfig) -> bool:
    return api_auth_required(config)


def api_token(config: HubConfig) -> str:
    explicit = getattr(config, "api_auth_token", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    env_name = getattr(config, "api_auth_token_env", None)
    if isinstance(env_name, str) and env_name:
        value = os.environ.get(env_name, "")
        if value:
            return value
    fallback = os.environ.get("AGENT_HUB_API_TOKEN", "")
    if fallback:
        return fallback
    return diagnostics_token(config)


def diagnostics_token(config: HubConfig) -> str:
    explicit = getattr(config, "diagnostics_auth_token", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    env_name = getattr(config, "diagnostics_auth_token_env", None)
    if isinstance(env_name, str) and env_name:
        return os.environ.get(env_name, "")
    return ""


def api_token_from_headers(headers: Any) -> str:
    direct = headers.get("X-Agent-Hub-API-Token")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    diagnostics = diagnostics_token_from_headers(headers)
    if diagnostics:
        return diagnostics
    auth = headers.get("Authorization")
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def diagnostics_token_from_headers(headers: Any) -> str:
    direct = headers.get("X-Agent-Hub-Diagnostics-Token")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    auth = headers.get("Authorization")
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def trusted_approval_token(config: HubConfig) -> str:
    explicit = getattr(config, "trusted_approval_token", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    env_name = getattr(config, "trusted_approval_token_env", None)
    if isinstance(env_name, str) and env_name:
        value = os.environ.get(env_name, "")
        if value:
            return value
    fallback = os.environ.get("AGENT_HUB_TRUSTED_APPROVAL_TOKEN", "")
    if fallback:
        return fallback
    return ""


def trusted_approval_from_headers(
    config: HubConfig,
    headers: Any,
    *,
    client_address: str = "",
) -> tuple[bool, str]:
    expected = trusted_approval_token(config)
    provided = headers.get("X-Agent-Hub-Approval-Token")
    if isinstance(provided, str) and provided.strip() and expected:
        if hmac.compare_digest(provided.strip(), expected):
            return True, "approval-token"
    return False, ""


def public_bind_host(host: str) -> bool:
    value = host.strip().lower()
    if value in {"", "localhost", "127.0.0.1", "::1"}:
        return False
    if value in {"0.0.0.0", "::", "[::]"}:
        return True
    try:
        import ipaddress

        address = ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return True
    return not address.is_loopback
