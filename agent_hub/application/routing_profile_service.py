from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..config import HubConfig
from ..models import HubRequest
from ..plugins.discovery import discover_plugins
from ..routing_strategies import builtin_routing_profiles, routing_strategy_catalog


BUILTIN_ROUTING_PROFILES: dict[str, dict[str, Any]] = builtin_routing_profiles()
_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_ROUTING_MODES = {"best_available", "coding", "long_context", "fastest", "cheapest", "local_private"}


class RoutingProfileApplicationService:
    """Universal router profiles backed by built-ins plus local JSON state."""

    def __init__(self, config: HubConfig) -> None:
        self.config = config

    def list_profiles(self) -> dict[str, Any]:
        profiles = self._profiles_by_id()
        rows = [profiles[key] for key in sorted(profiles)]
        return {
            "object": "agent_hub.routing_profiles",
            "data": rows,
            "count": len(rows),
            "source": "builtin_and_local_state",
            "storage": str(self._profile_path()),
            "strategies": routing_strategy_catalog()["data"],
        }

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self._profiles_by_id().get(profile_id)
        if profile is None:
            raise RoutingProfileError("routing_profile_not_found", f"Routing profile '{profile_id}' is not configured.", status=404)
        return {"object": "agent_hub.routing_profile", "data": profile}

    def create_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self._normalize_profile(payload, source="local")
        if profile["id"] in self._profiles_by_id():
            raise RoutingProfileError("routing_profile_exists", f"Routing profile '{profile['id']}' already exists.", status=409)
        local = self._load_local_profiles()
        local[profile["id"]] = profile
        self._save_local_profiles(local)
        return {"object": "agent_hub.routing_profile", "created": True, "data": profile}

    def update_profile(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self._profiles_by_id().get(profile_id)
        if existing is None:
            raise RoutingProfileError("routing_profile_not_found", f"Routing profile '{profile_id}' is not configured.", status=404)
        if existing.get("source") in {"builtin", "plugin"}:
            raise RoutingProfileError(
                "builtin_routing_profile_readonly",
                "Built-in and plugin routing profiles are read-only; create a local profile with a new id.",
                status=409,
            )
        merged = {**existing, **payload, "id": profile_id}
        profile = self._normalize_profile(merged, source="local")
        local = self._load_local_profiles()
        local[profile_id] = profile
        self._save_local_profiles(local)
        return {"object": "agent_hub.routing_profile", "updated": True, "data": profile}

    def delete_profile(self, profile_id: str) -> dict[str, Any]:
        existing = self._profiles_by_id().get(profile_id)
        if existing is None:
            raise RoutingProfileError("routing_profile_not_found", f"Routing profile '{profile_id}' is not configured.", status=404)
        if existing.get("source") in {"builtin", "plugin"}:
            raise RoutingProfileError(
                "builtin_routing_profile_readonly",
                "Built-in and plugin routing profiles are read-only.",
                status=409,
            )
        local = self._load_local_profiles()
        local.pop(profile_id, None)
        self._save_local_profiles(local)
        return {"object": "agent_hub.routing_profile", "deleted": True, "id": profile_id}

    def apply_to_request(self, request: HubRequest) -> HubRequest:
        profile_id = routing_profile_id(request)
        if not profile_id:
            return request
        profile = self._profiles_by_id().get(profile_id)
        if profile is None:
            return request
        raw = dict(request.raw) if isinstance(request.raw, dict) else {}
        hub = dict(raw.get("agent_hub")) if isinstance(raw.get("agent_hub"), dict) else {}
        raw.setdefault("routing_mode", profile["routing_mode"])
        hub["routing_profile"] = profile
        hub["routing_profile_id"] = profile["id"]
        hub.setdefault("fallback_policy", profile.get("fallback_policy", {}))
        raw["agent_hub"] = hub
        metadata = dict(request.metadata) if isinstance(request.metadata, dict) else {}
        metadata["routing_profile"] = profile
        return replace(request, raw=raw, metadata=metadata)

    def _profiles_by_id(self) -> dict[str, dict[str, Any]]:
        profiles = {key: {**value, "source": "builtin"} for key, value in BUILTIN_ROUTING_PROFILES.items()}
        profiles.update(self._plugin_profiles())
        profiles.update(self._load_local_profiles())
        return profiles

    def _plugin_profiles(self) -> dict[str, dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        for plugin in discover_plugins(self.config).plugins:
            if not plugin.registerable or plugin.manifest.type != "router_strategy":
                continue
            metadata = plugin.manifest.metadata if isinstance(plugin.manifest.metadata, dict) else {}
            try:
                profile = self._normalize_profile(
                    {
                        "id": metadata.get("profile_id") or plugin.manifest.id,
                        "label": metadata.get("label") or plugin.manifest.name,
                        "routing_mode": metadata.get("routing_mode", "best_available"),
                        "description": metadata.get("description") or plugin.manifest.description,
                        "fallback_policy": metadata.get("fallback_policy"),
                        "metadata": {"plugin_id": plugin.manifest.id, **(dict(metadata.get("metadata")) if isinstance(metadata.get("metadata"), dict) else {})},
                    },
                    source="plugin",
                )
            except RoutingProfileError:
                continue
            profile["plugin_id"] = plugin.manifest.id
            profiles[profile["id"]] = profile
        return profiles

    def _normalize_profile(self, payload: dict[str, Any], *, source: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RoutingProfileError("invalid_routing_profile", "Expected a routing profile object.", status=400)
        profile_id = str(payload.get("id") or "").strip()
        if not _PROFILE_ID_RE.match(profile_id):
            raise RoutingProfileError(
                "invalid_routing_profile_id",
                "Profile id must be 1-80 characters and use letters, numbers, dots, underscores, or hyphens.",
                status=400,
            )
        routing_mode = str(payload.get("routing_mode") or "best_available").strip().lower().replace("-", "_")
        if routing_mode not in _ROUTING_MODES:
            raise RoutingProfileError("invalid_routing_mode", f"Unknown routing mode '{routing_mode}'.", status=400)
        fallback_policy = _normalize_fallback_policy(payload.get("fallback_policy"))
        return {
            "id": profile_id,
            "label": str(payload.get("label") or profile_id).strip(),
            "routing_mode": routing_mode,
            "description": str(payload.get("description") or "").strip(),
            "fallback_policy": fallback_policy,
            "metadata": dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {},
            "source": source,
        }

    def _load_local_profiles(self) -> dict[str, dict[str, Any]]:
        path = self._profile_path()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        rows = raw.get("profiles") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return {}
        profiles: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                profile = self._normalize_profile(row, source="local")
            except RoutingProfileError:
                continue
            profiles[profile["id"]] = profile
        return profiles

    def _save_local_profiles(self, profiles: dict[str, dict[str, Any]]) -> None:
        path = self._profile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "object": "agent_hub.routing_profiles.local",
                    "profiles": [profiles[key] for key in sorted(profiles)],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _profile_path(self) -> Path:
        return Path(self.config.state_dir) / "routing_profiles.json"


class RoutingProfileError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_response(self) -> dict[str, Any]:
        return {"error": {"type": self.code, "message": self.message}}


def routing_profile_id(request: HubRequest) -> str:
    raw = request.raw if isinstance(request.raw, dict) else {}
    hub = raw.get("agent_hub") if isinstance(raw.get("agent_hub"), dict) else {}
    for value in (
        hub.get("routing_profile"),
        hub.get("routing_profile_id"),
        raw.get("routing_profile"),
        raw.get("routing_profile_id"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_fallback_policy(value: Any) -> dict[str, Any]:
    source = dict(value) if isinstance(value, dict) else {}
    attempts = _int_with_default(source.get("max_provider_attempts"), 5)
    order = str(source.get("order") or "ranked").strip().lower().replace("-", "_")
    if order not in {"ranked", "cost_first", "latency_first", "local_only", "policy_first"}:
        order = "ranked"
    return {
        "max_provider_attempts": max(1, min(attempts, 20)),
        "order": order,
        "failover_on_quota": _bool_with_default(source.get("failover_on_quota"), True),
        "failover_on_rate_limit": _bool_with_default(source.get("failover_on_rate_limit"), True),
        "failover_on_context_limit": _bool_with_default(source.get("failover_on_context_limit"), True),
    }


def _int_with_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_with_default(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


__all__ = [
    "BUILTIN_ROUTING_PROFILES",
    "RoutingProfileApplicationService",
    "RoutingProfileError",
    "routing_profile_id",
]
