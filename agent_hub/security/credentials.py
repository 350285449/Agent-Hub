from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from ..config import HubConfig


TOKEN_ENV_NAME = "AGENT_HUB_TOKEN"
CREDENTIALS_FILE = "credentials.json"


def ensure_local_credentials(config: HubConfig) -> dict[str, Any]:
    """Load or create local server credentials outside the editable config."""

    explicit = getattr(config, "api_auth_token", None)
    if isinstance(explicit, str) and explicit:
        return {"created": False, "source": "config", "token": explicit}
    env_name = getattr(config, "api_auth_token_env", None)
    if isinstance(env_name, str) and env_name and os.environ.get(env_name):
        return {"created": False, "source": "env", "token": os.environ[env_name]}
    if os.environ.get(TOKEN_ENV_NAME):
        config.api_auth_token = os.environ[TOKEN_ENV_NAME]
        return {"created": False, "source": "env", "token": config.api_auth_token}

    path = credentials_path(config)
    data = _read_credentials(path)
    token = str(data.get(TOKEN_ENV_NAME) or "")
    created = False
    if not token:
        token = secrets.token_urlsafe(48)
        data[TOKEN_ENV_NAME] = token
        data["created_at"] = time.time()
        data["remember_device_days"] = getattr(config, "session_remember_device_days", 30)
        _write_credentials(path, data)
        created = True
    config.api_auth_token = token
    return {"created": created, "source": "generated", "path": str(path), "token": token}


def credentials_path(config: HubConfig) -> Path:
    return Path(config.state_dir).expanduser().resolve() / CREDENTIALS_FILE


def _read_credentials(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        return {}
    return {}


def _write_credentials(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

