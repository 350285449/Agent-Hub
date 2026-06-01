from __future__ import annotations

from typing import Any

from ..config import HubConfig
from ..evaluation import ProviderScoreStore


class DiagnosticsApplicationService:
    """Application boundary for diagnostics summaries that read local state."""

    def __init__(self, config: HubConfig) -> None:
        self.config = config

    def provider_scores(self) -> dict[str, Any]:
        return ProviderScoreStore(self.config.state_dir).load()

    def provider_scores_body(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.provider_scores",
            "benchmark_types": [
                "coding",
                "reasoning",
                "summarization",
                "tool_calling",
                "long_context",
                "latency",
            ],
            "data": self.provider_scores(),
        }


__all__ = ["DiagnosticsApplicationService"]
