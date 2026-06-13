from __future__ import annotations

from ..health import ProviderHealth, ProviderHealthTracker
from .selection import (
    HEALTH_STATE_FILE,
    HEALTH_STATE_VERSION,
    HEALTH_STALE_SECONDS,
    MAX_FAILOVER_HISTORY,
    _apply_agent_capabilities,
    _apply_provider_metadata,
    _assign_float,
    _assign_int,
    _health_quota_state,
    _optional_float,
    _optional_int,
    _optional_timestamp,
    _provider_health_to_state,
    _provider_metadata_from_raw,
    _provider_stream_metadata,
    _remaining_quota_value,
    _temporary_health_path,
)

__all__ = [
    "HEALTH_STATE_FILE",
    "HEALTH_STATE_VERSION",
    "HEALTH_STALE_SECONDS",
    "MAX_FAILOVER_HISTORY",
    "ProviderHealth",
    "ProviderHealthTracker",
    "_apply_agent_capabilities",
    "_apply_provider_metadata",
    "_assign_float",
    "_assign_int",
    "_health_quota_state",
    "_optional_float",
    "_optional_int",
    "_optional_timestamp",
    "_provider_health_to_state",
    "_provider_metadata_from_raw",
    "_provider_stream_metadata",
    "_remaining_quota_value",
    "_temporary_health_path",
]

