from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Iterator

from ..debug import log_provider_debug_event
from .errors import ProviderError, provider_error_from_http, provider_error_from_payload
from .quota import quota_metadata_from_headers


def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    log_provider_debug_event(
        debug,
        {
            "type": "provider_request",
            "url": url,
            "payload": payload,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_headers = dict(response.headers.items())
            provider_request_id = provider_request_id_from_headers(response_headers)
            text = response.read().decode("utf-8")
            log_provider_debug_event(
                debug,
                {
                    "type": "raw_provider_response",
                    "provider_request_id": provider_request_id,
                    "status": response.status,
                    "headers": response_headers,
                    "raw_json": text,
                    "empty_response": not bool(text.strip()),
                },
            )
            data = json.loads(text) if text else {}
            metadata = quota_metadata_from_headers(dict(response.headers.items()))
            if isinstance(data, dict) and data.get("error"):
                raise provider_error_from_payload(
                    data,
                    status_code=response.status,
                    metadata=metadata,
                )
            if isinstance(data, dict) and metadata:
                provider_metadata = data.setdefault("agent_hub_provider", {})
                if isinstance(provider_metadata, dict):
                    provider_metadata["quota"] = metadata
            return data
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        log_provider_debug_event(
            debug,
            {
                "type": "provider_http_error",
                "status": exc.code,
                "headers": dict(exc.headers.items()) if exc.headers else {},
                "raw_json": text,
            },
        )
        raise provider_error_from_http(
            exc.code,
            text,
            headers=dict(exc.headers.items()) if exc.headers else None,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderError(
            f"Provider request timed out: {exc}",
            retryable=True,
            error_type="provider_unavailable",
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        error_type = "provider_unavailable"
        prefix = "Provider request timed out" if looks_like_timeout(reason) else "Network error"
        raise ProviderError(f"{prefix}: {reason}", retryable=True, error_type=error_type) from exc
    except json.JSONDecodeError as exc:
        log_provider_debug_event(
            debug,
            {
                "type": "malformed_provider_json",
                "message": str(exc),
            },
        )
        raise ProviderError(
            f"Provider returned invalid JSON: {exc}",
            retryable=True,
            error_type="invalid_provider_response",
        ) from exc


def post_stream_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    debug: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    log_provider_debug_event(
        debug,
        {
            "type": "provider_stream_request",
            "url": url,
            "payload": payload,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_headers = dict(response.headers.items())
            provider_request_id = provider_request_id_from_headers(response_headers)
            metadata = quota_metadata_from_headers(response_headers)
            saw_done = False
            yielded = 0
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                log_provider_debug_event(
                    debug,
                    {
                        "type": "raw_stream_chunk",
                        "provider_request_id": provider_request_id,
                        "chunk": line,
                        "empty_chunk": not bool(line),
                    },
                )
                if not line or line.startswith(":") or line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    saw_done = True
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    log_provider_debug_event(
                        debug,
                        {
                            "type": "malformed_stream_chunk",
                            "provider_request_id": provider_request_id,
                            "message": str(exc),
                            "chunk": line,
                        },
                    )
                    continue
                if not isinstance(data, dict):
                    log_provider_debug_event(
                        debug,
                        {
                            "type": "malformed_stream_chunk",
                            "provider_request_id": provider_request_id,
                            "message": "Provider returned a non-object stream chunk",
                            "chunk": data,
                        },
                    )
                    continue
                if isinstance(data, dict) and data.get("error"):
                    raise provider_error_from_payload(
                        data,
                        status_code=response.status,
                        metadata=metadata,
                    )
                if metadata:
                    provider_metadata = data.setdefault("agent_hub_provider", {})
                    if isinstance(provider_metadata, dict):
                        provider_metadata["quota"] = metadata
                yielded += 1
                yield data
            if not saw_done:
                log_provider_debug_event(
                    debug,
                    {
                        "type": "stream_missing_done",
                        "provider_request_id": provider_request_id,
                        "yielded_chunks": yielded,
                    },
                )
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        log_provider_debug_event(
            debug,
            {
                "type": "provider_stream_http_error",
                "status": exc.code,
                "headers": dict(exc.headers.items()) if exc.headers else {},
                "raw_json": text,
            },
        )
        raise provider_error_from_http(
            exc.code,
            text,
            headers=dict(exc.headers.items()) if exc.headers else None,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderError(
            f"Provider stream timed out: {exc}",
            retryable=True,
            error_type="provider_unavailable",
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        error_type = "provider_unavailable"
        prefix = "Provider stream timed out" if looks_like_timeout(reason) else "Network error"
        raise ProviderError(f"{prefix}: {reason}", retryable=True, error_type=error_type) from exc


def provider_request_id_from_headers(headers: dict[str, str]) -> str | None:
    lower = {str(key).lower(): str(value) for key, value in headers.items() if value is not None}
    for name in (
        "x-request-id",
        "request-id",
        "x-amzn-requestid",
        "x-goog-request-id",
        "cf-ray",
    ):
        value = lower.get(name)
        if value:
            return value
    return None


def looks_like_timeout(reason: object) -> bool:
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    return "timed out" in str(reason).lower() or "timeout" in str(reason).lower()


_looks_like_timeout = looks_like_timeout
_post_json = post_json
_post_stream_json = post_stream_json
_provider_request_id = provider_request_id_from_headers


__all__ = [
    "looks_like_timeout",
    "post_json",
    "post_stream_json",
    "provider_request_id_from_headers",
    "_looks_like_timeout",
    "_post_json",
    "_post_stream_json",
    "_provider_request_id",
]
