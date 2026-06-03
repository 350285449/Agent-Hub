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


def diagnostics_auth_error(config: HubConfig, headers: Any) -> tuple[dict[str, Any], int] | None:
    if not diagnostics_auth_required(config):
        return None
    expected = diagnostics_token(config)
    if not expected:
        return (
            {
                "error": {
                    "type": "diagnostics_auth_not_configured",
                    "message": (
                        "Diagnostics endpoints require diagnostics_auth_token or "
                        "diagnostics_auth_token_env when Agent Hub is bound publicly."
                    ),
                }
            },
            403,
        )
    provided = diagnostics_token_from_headers(headers)
    if provided and hmac.compare_digest(provided, expected):
        return None
    return (
        {
            "error": {
                "type": "diagnostics_auth_required",
                "message": "Diagnostics authentication is required for this endpoint.",
            }
        },
        401,
    )


def diagnostics_auth_required(config: HubConfig) -> bool:
    return public_bind_host(str(getattr(config, "host", "127.0.0.1") or "127.0.0.1"))


def diagnostics_token(config: HubConfig) -> str:
    explicit = getattr(config, "diagnostics_auth_token", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    env_name = getattr(config, "diagnostics_auth_token_env", None)
    if isinstance(env_name, str) and env_name:
        return os.environ.get(env_name, "")
    return ""


def diagnostics_token_from_headers(headers: Any) -> str:
    direct = headers.get("X-Agent-Hub-Diagnostics-Token")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    auth = headers.get("Authorization")
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


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
