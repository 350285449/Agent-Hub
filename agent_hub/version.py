from __future__ import annotations

import hashlib
import json
import os
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


BASE_VERSION = "0.4.0"


def backend_version() -> str:
    return os.environ.get("AGENT_HUB_VERSION", BASE_VERSION)


def build_metadata() -> dict[str, Any]:
    commit = os.environ.get("AGENT_HUB_BUILD_COMMIT") or _git_value(["rev-parse", "--short", "HEAD"])
    dirty = _git_value(["status", "--short"])
    return {
        "version": backend_version(),
        "package_version": _package_version(),
        "commit": commit or "unknown",
        "dirty": bool(dirty),
    }


def config_runtime_hash(config: Any) -> str:
    from .config import config_to_dict

    payload = json.dumps(config_to_dict(config), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _git_value(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _package_version() -> str:
    try:
        return version("agent-hub")
    except PackageNotFoundError:
        return ""
