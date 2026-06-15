from __future__ import annotations

from typing import Any

from ..adaptive import compact_adaptive_state
from ..config import HubConfig
from ..observability import compact_observability_state
from ..session_store import compact_session_store


class AnalyticsMaintenanceService:
    """Runs bounded local state compaction for observability, adaptive, and sessions."""

    def __init__(self, config: HubConfig) -> None:
        self.config = config

    def compact(self, *, now: float | None = None) -> dict[str, Any]:
        if not self.config.analytics_compaction_enabled:
            return {
                "object": "agent_hub.analytics_maintenance",
                "enabled": False,
                "state_dir": str(self.config.state_dir),
                "removed_count": 0,
            }
        observability = compact_observability_state(
            self.config.state_dir,
            retention_days=self.config.analytics_retention_days,
            max_events_per_stream=self.config.analytics_max_events_per_stream,
            now=now,
        )
        adaptive = compact_adaptive_state(
            self.config.state_dir,
            retention_days=self.config.adaptive_retention_days,
            now=now,
        )
        sessions = compact_session_store(
            self.config.state_dir,
            retention_days=self.config.session_retention_days,
            max_sessions=self.config.session_max_records,
            now=now,
        )
        return {
            "object": "agent_hub.analytics_maintenance",
            "enabled": True,
            "state_dir": str(self.config.state_dir),
            "observability": observability,
            "adaptive": adaptive,
            "sessions": sessions,
            "removed_count": int(observability.get("removed_count") or 0)
            + int(adaptive.get("removed_count") or 0)
            + int(sessions.get("removed_count") or 0),
        }


def run_analytics_maintenance(config: HubConfig, *, now: float | None = None) -> dict[str, Any]:
    return AnalyticsMaintenanceService(config).compact(now=now)


__all__ = ["AnalyticsMaintenanceService", "run_analytics_maintenance"]
