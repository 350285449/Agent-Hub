from __future__ import annotations

import re
import time
from email.utils import parsedate_to_datetime
from typing import Any


def quota_metadata_from_headers(headers: dict[str, str]) -> dict[str, Any]:
    """Normalize common provider quota/rate-limit headers into router metadata."""

    if not headers:
        return {}
    lower = {str(key).lower(): str(value) for key, value in headers.items() if value is not None}
    metadata: dict[str, Any] = {}

    requests_remaining = _first_number(
        lower,
        (
            "x-ratelimit-remaining-requests",
            "x-rate-limit-remaining-requests",
            "anthropic-ratelimit-requests-remaining",
            "x-request-limit-remaining",
            "ratelimit-remaining",
            "x-ratelimit-remaining",
        ),
        integer=True,
    )
    if requests_remaining is not None:
        metadata["requests_remaining"] = int(requests_remaining)
        metadata["quota_remaining"] = int(requests_remaining)

    tokens_remaining = _first_number(
        lower,
        (
            "x-ratelimit-remaining-tokens",
            "x-rate-limit-remaining-tokens",
            "anthropic-ratelimit-tokens-remaining",
            "x-token-limit-remaining",
        ),
        integer=True,
    )
    if tokens_remaining is not None:
        metadata["tokens_remaining"] = int(tokens_remaining)

    credits_remaining = _first_number(
        lower,
        (
            "x-ratelimit-remaining-credits",
            "x-credits-remaining",
            "x-credit-balance",
            "x-openrouter-credits-remaining",
        ),
    )
    if credits_remaining is not None:
        metadata["credits_remaining"] = credits_remaining
        metadata["quota_remaining"] = credits_remaining

    reset_at = _first_reset_timestamp(
        lower,
        (
            "x-ratelimit-reset",
            "x-ratelimit-reset-requests",
            "x-rate-limit-reset",
            "anthropic-ratelimit-requests-reset",
            "ratelimit-reset",
        ),
    )
    if reset_at is not None:
        metadata["rate_limit_reset_at"] = reset_at

    retry_after = _parse_retry_after(lower.get("retry-after"))
    if retry_after is not None:
        metadata["cooldown_seconds"] = retry_after
        metadata["cooldown_until"] = time.time() + retry_after

    return metadata


def metadata_cooldown_seconds(metadata: dict[str, Any]) -> float | None:
    value = metadata.get("cooldown_seconds")
    if value is not None:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None
    cooldown_until = metadata.get("cooldown_until")
    if cooldown_until is not None:
        try:
            return max(0.0, float(cooldown_until) - time.time())
        except (TypeError, ValueError):
            return None
    return None


def _first_number(
    headers: dict[str, str],
    names: tuple[str, ...],
    *,
    integer: bool = False,
) -> float | int | None:
    for name in names:
        if name not in headers:
            continue
        match = re.search(r"-?\d+(?:\.\d+)?", headers[name])
        if not match:
            continue
        try:
            value = float(match.group(0))
        except ValueError:
            continue
        return int(value) if integer else value
    return None


def _first_reset_timestamp(headers: dict[str, str], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = headers.get(name)
        parsed = _parse_reset_timestamp(value)
        if parsed is not None:
            return parsed
    return None


def _parse_reset_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    number_match = re.fullmatch(r"\d+(?:\.\d+)?", stripped)
    if number_match:
        try:
            number = float(number_match.group(0))
        except ValueError:
            number = 0.0
        if number > 1_000_000_000:
            return number / 1000.0 if number > 10_000_000_000 else number
        if number >= 0:
            return time.time() + number
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError, OverflowError):
        loose_match = re.search(r"\d+(?:\.\d+)?", stripped)
        if not loose_match:
            return None
        try:
            return time.time() + max(0.0, float(loose_match.group(0)))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.timestamp()
    return parsed.timestamp()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    try:
        return max(0.0, float(stripped))
    except ValueError:
        timestamp = _parse_reset_timestamp(stripped)
        if timestamp is None:
            return None
        return max(0.0, timestamp - time.time())


_quota_metadata_from_headers = quota_metadata_from_headers
_metadata_cooldown_seconds = metadata_cooldown_seconds


__all__ = [
    "metadata_cooldown_seconds",
    "quota_metadata_from_headers",
    "_metadata_cooldown_seconds",
    "_quota_metadata_from_headers",
]
