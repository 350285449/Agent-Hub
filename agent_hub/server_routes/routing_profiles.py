from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from ..application.routing_profile_service import RoutingProfileApplicationService, RoutingProfileError
from ..routing_strategies import routing_strategy_catalog


def handle_get(handler: object, path: str) -> bool:
    if path == "/v1/routing-strategies":
        handler._send_json(routing_strategy_catalog())
        return True
    if path == "/v1/routing-profiles":
        handler._send_json(RoutingProfileApplicationService(handler.server.config).list_profiles())
        return True
    profile_id = _profile_id_from_path(path)
    if profile_id is None:
        return False
    try:
        body = RoutingProfileApplicationService(handler.server.config).get_profile(profile_id)
    except RoutingProfileError as exc:
        handler._send_json(exc.to_response(), status=exc.status)
        return True
    handler._send_json(body)
    return True


def handle_post(handler: object, path: str, payload: dict[str, Any]) -> bool:
    service = RoutingProfileApplicationService(handler.server.config)
    try:
        if path == "/v1/routing-profiles":
            body = service.create_profile(payload)
            handler.server.invalidate_diagnostics_cache("POST /v1/routing-profiles")
            handler._send_json(body, status=201)
            return True
        profile_id = _profile_id_from_path(path)
        if profile_id is None:
            return False
        body = service.update_profile(profile_id, payload)
        handler.server.invalidate_diagnostics_cache(f"POST /v1/routing-profiles/{profile_id}")
        handler._send_json(body)
        return True
    except RoutingProfileError as exc:
        handler._send_json(exc.to_response(), status=exc.status)
        return True


def handle_delete(handler: object, path: str) -> bool:
    profile_id = _profile_id_from_path(path)
    if profile_id is None:
        return False
    try:
        body = RoutingProfileApplicationService(handler.server.config).delete_profile(profile_id)
    except RoutingProfileError as exc:
        handler._send_json(exc.to_response(), status=exc.status)
        return True
    handler.server.invalidate_diagnostics_cache(f"DELETE /v1/routing-profiles/{profile_id}")
    handler._send_json(body)
    return True


def _profile_id_from_path(path: str) -> str | None:
    prefix = "/v1/routing-profiles/"
    if not path.startswith(prefix):
        return None
    profile_id = unquote(path[len(prefix) :]).strip()
    if not profile_id or "/" in profile_id:
        return None
    return profile_id


__all__ = ["handle_delete", "handle_get", "handle_post"]
