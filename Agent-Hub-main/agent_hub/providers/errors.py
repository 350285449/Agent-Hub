from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..models import ErrorCategory, StructuredError
from .quota import metadata_cooldown_seconds, quota_metadata_from_headers


FAILOVER_STATUSES = {401, 402, 403, 404, 408, 409, 413, 429, 500, 502, 503, 504, 529}
QUOTA_TEXT_MARKERS = (
    "account limit",
    "billing",
    "credit",
    "credits exhausted",
    "daily limit",
    "exceeded your quota",
    "free quota",
    "free tier",
    "free-tier",
    "free usage",
    "insufficient balance",
    "insufficient_quota",
    "monthly limit",
    "payment required",
    "quota",
    "quota exceeded",
    "quotaexceeded",
    "resource exhausted",
    "resource_exhausted",
    "tokens exhausted",
    "usage limit",
)
RATE_LIMIT_TEXT_MARKERS = (
    "rate limit",
    "rate_limit",
    "rate-limit",
    "rate limited",
    "rate_limit_error",
    "rate_limit_exceeded",
    "requests per day",
    "requests per minute",
    "rpm",
    "too_many_requests",
    "tokens per minute",
    "tpm",
)
OUTPUT_LIMIT_TEXT_MARKERS = (
    "completion token",
    "completion tokens",
    "max completion",
    "max_completion_tokens",
    "max output",
    "max_output_tokens",
    "output token",
    "output tokens",
    "requested output",
)
CONTEXT_LIMIT_TEXT_MARKERS = (
    "context length",
    "context_length",
    "context window",
    "input is too long",
    "maximum context",
    "max tokens",
    "too many tokens",
    "token limit",
)
TEMPORARY_TEXT_MARKERS = (
    "capacity",
    "overloaded",
    "temporarily overloaded",
    "temporarily unavailable",
    "try again later",
    "server error",
    "service unavailable",
)
UNSUPPORTED_TEXT_MARKERS = (
    "does not support",
    "not supported",
    "unsupported",
    "unsupported_feature",
)
AUTH_TEXT_MARKERS = (
    "api key",
    "authentication",
    "authorization",
    "invalid api key",
    "permission denied",
    "unauthorized",
)
FAILOVER_TEXT_MARKERS = (
    *QUOTA_TEXT_MARKERS,
    *RATE_LIMIT_TEXT_MARKERS,
    *OUTPUT_LIMIT_TEXT_MARKERS,
    *CONTEXT_LIMIT_TEXT_MARKERS,
    *TEMPORARY_TEXT_MARKERS,
    *UNSUPPORTED_TEXT_MARKERS,
    *AUTH_TEXT_MARKERS,
)
RETRYABLE_ERROR_TYPES = {
    "quota_exhausted",
    "temporary_rate_limit",
    "context_too_large",
    "output_too_large",
    "provider_overloaded",
    "provider_unavailable",
    "authentication_error",
    "unsupported_feature",
    "rate_limited",
    "context_limit",
    "temporary_unavailable",
    "authentication",
    "model_unavailable",
    "network",
    "timeout",
}
ERROR_TYPE_ALIASES = {
    "rate_limited": "temporary_rate_limit",
    "context_limit": "context_too_large",
    "temporary_unavailable": "provider_overloaded",
    "authentication": "authentication_error",
    "model_unavailable": "provider_unavailable",
    "network": "provider_unavailable",
    "timeout": "provider_unavailable",
    "provider_error": "unknown_error",
}
PASS_THROUGH_ERROR_TYPES = {
    "configuration",
    "invalid_provider_response",
    "quota_exhausted",
    "temporary_rate_limit",
    "context_too_large",
    "output_too_large",
    "provider_overloaded",
    "provider_unavailable",
    "authentication_error",
    "unsupported_feature",
    "unknown_error",
}


@dataclass(slots=True)
class ProviderError(Exception):
    message: str
    status_code: int | None = None
    retryable: bool = True
    error_type: str = "provider_error"
    cooldown_seconds: float | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.error_type == "provider_error":
            self.error_type = classify_provider_error(self.message, status_code=self.status_code)
        elif self.error_type in ERROR_TYPE_ALIASES:
            self.error_type = ERROR_TYPE_ALIASES[self.error_type]
        elif self.error_type not in PASS_THROUGH_ERROR_TYPES:
            self.error_type = self.error_type or "unknown_error"

    def __str__(self) -> str:
        return self.message

    def to_structured_error(self) -> StructuredError:
        return StructuredError(
            category=provider_error_category(self.error_type),
            code=self.error_type or "provider_error",
            message=self.message,
            retryable=self.retryable,
            user_message=provider_user_message(self),
            status_code=self.status_code,
            details=dict(self.metadata or {}),
        )


def provider_error_from_http(
    status_code: int,
    text: str,
    headers: dict[str, str] | None = None,
) -> ProviderError:
    message = extract_error_message(text)
    error_type = classify_provider_error(message, status_code=status_code)
    retryable = (
        status_code in FAILOVER_STATUSES
        or status_code >= 500
        or error_type in RETRYABLE_ERROR_TYPES
    )
    metadata = quota_metadata_from_headers(headers or {})
    return ProviderError(
        message,
        status_code=status_code,
        retryable=retryable,
        error_type=error_type,
        cooldown_seconds=metadata_cooldown_seconds(metadata),
        metadata=metadata,
    )


def provider_error_from_payload(
    data: dict[str, Any],
    status_code: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProviderError:
    message = extract_error_message(json.dumps(data))
    error_type = classify_provider_error(message, status_code=status_code)
    retryable = (
        status_code in FAILOVER_STATUSES
        or (status_code is not None and status_code >= 500)
        or error_type in RETRYABLE_ERROR_TYPES
    )
    return ProviderError(
        message,
        status_code=status_code,
        retryable=retryable,
        error_type=error_type,
        cooldown_seconds=metadata_cooldown_seconds(metadata or {}),
        metadata=metadata or {},
    )


def classify_provider_error(message: str, status_code: int | None = None) -> str:
    marker_text = message.lower().replace("-", " ")
    if any(marker in marker_text for marker in QUOTA_TEXT_MARKERS):
        return "quota_exhausted"
    if (
        any(marker in marker_text for marker in OUTPUT_LIMIT_TEXT_MARKERS)
        or "max_tokens" in message.lower()
        or ("max tokens" in marker_text and "context" not in marker_text)
    ):
        return "output_too_large"
    if status_code == 429 or any(marker in marker_text for marker in RATE_LIMIT_TEXT_MARKERS):
        return "temporary_rate_limit"
    if any(marker in marker_text for marker in UNSUPPORTED_TEXT_MARKERS):
        return "unsupported_feature"
    if any(marker in marker_text for marker in CONTEXT_LIMIT_TEXT_MARKERS):
        return "context_too_large"
    if status_code in {401, 403} or any(marker in marker_text for marker in AUTH_TEXT_MARKERS):
        return "authentication_error"
    if status_code in {408, 409, 503, 504, 529} or any(
        marker in marker_text for marker in TEMPORARY_TEXT_MARKERS
    ):
        return "provider_overloaded"
    if status_code in {404, 500, 502}:
        return "provider_unavailable"
    if status_code == 413:
        return "context_too_large"
    return "unknown_error"


def provider_error_category(error_type: str) -> str:
    error_type = ERROR_TYPE_ALIASES.get(error_type, error_type)
    if error_type == "quota_exhausted":
        return ErrorCategory.QUOTA
    if error_type == "temporary_rate_limit":
        return ErrorCategory.RATE_LIMIT
    if error_type == "context_too_large":
        return ErrorCategory.CONTEXT_LIMIT
    if error_type in {"configuration", "authentication_error"}:
        return ErrorCategory.CONFIGURATION
    if error_type in {"provider_unavailable", "provider_overloaded"}:
        return ErrorCategory.NETWORK
    if error_type == "output_too_large":
        return ErrorCategory.CONTEXT_LIMIT
    if error_type == "invalid_provider_response":
        return ErrorCategory.VALIDATION
    return ErrorCategory.PROVIDER


def provider_user_message(error: ProviderError) -> str:
    if error.error_type == "quota_exhausted":
        return "The selected provider is out of quota or free-tier credits. Agent Hub will try a fallback model when one is available."
    if error.error_type == "temporary_rate_limit":
        return "The selected provider is rate-limited. Agent Hub will retry or fail over when possible."
    if error.error_type == "context_too_large":
        return "The prompt exceeded this provider's context limit. Agent Hub can reduce context or try a larger-context model."
    if error.error_type == "output_too_large":
        return "The requested output budget exceeded this provider's limit. Agent Hub will retry with a smaller supported value when possible."
    if error.error_type == "authentication_error":
        return "The provider rejected authentication. Check the configured API key or provider settings."
    if error.error_type == "configuration":
        return "The provider is not fully configured. Check Agent Hub settings and API key environment variables."
    if error.error_type == "unsupported_feature":
        return "The provider does not support a requested feature. Agent Hub will try a compatible model when one is available."
    if error.error_type in {"provider_overloaded", "provider_unavailable"}:
        return "The provider is unavailable or overloaded. Agent Hub will try a fallback model when one is available."
    if error.error_type == "invalid_provider_response":
        return "The provider returned a malformed response. Agent Hub will retry, fail over, or synthesize a safe response."
    return error.message


def extract_error_message(text: str) -> str:
    if not text:
        return "Provider request failed"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    error = data.get("error")
    if isinstance(error, dict):
        for key in ("message", "type", "code"):
            if error.get(key):
                return str(error[key])
    if isinstance(error, str):
        return error
    return text[:500]


_classify_provider_error = classify_provider_error
_extract_error_message = extract_error_message
_provider_error_category = provider_error_category
_provider_error_from_http = provider_error_from_http
_provider_error_from_payload = provider_error_from_payload
_provider_user_message = provider_user_message


__all__ = [
    "AUTH_TEXT_MARKERS",
    "CONTEXT_LIMIT_TEXT_MARKERS",
    "ERROR_TYPE_ALIASES",
    "FAILOVER_STATUSES",
    "FAILOVER_TEXT_MARKERS",
    "OUTPUT_LIMIT_TEXT_MARKERS",
    "PASS_THROUGH_ERROR_TYPES",
    "ProviderError",
    "QUOTA_TEXT_MARKERS",
    "RATE_LIMIT_TEXT_MARKERS",
    "RETRYABLE_ERROR_TYPES",
    "TEMPORARY_TEXT_MARKERS",
    "UNSUPPORTED_TEXT_MARKERS",
    "classify_provider_error",
    "extract_error_message",
    "provider_error_category",
    "provider_error_from_http",
    "provider_error_from_payload",
    "provider_user_message",
    "_classify_provider_error",
    "_extract_error_message",
    "_provider_error_category",
    "_provider_error_from_http",
    "_provider_error_from_payload",
    "_provider_user_message",
]
