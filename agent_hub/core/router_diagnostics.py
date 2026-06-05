from __future__ import annotations

from typing import Any

from ..capabilities import agent_capabilities
from ..config import HubConfig, normalize_provider
from ..tool_compatibility import tool_compatibility_mode


def build_provider_status(
    config: HubConfig,
    snapshot: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, agent in sorted(config.agents.items()):
        row = snapshot.get(name, {})
        capabilities = agent_capabilities(agent)
        rows.append(
            {
                "name": name,
                "agent": name,
                "provider": agent.provider,
                "provider_type": agent.provider_type or normalize_provider(agent.provider),
                "model": agent.model,
                "available": bool(row.get("available")),
                "health": row.get("health", "unknown"),
                "latency_ms": row.get("latency_ms", 0.0),
                "score": row.get("score", 0.0),
                "streaming": capabilities.supports_streaming,
                "supports_tools": capabilities.tool_capable,
                "effective_supports_tools": (
                    capabilities.tool_capable or tool_compatibility_mode(config, agent) == "emulated"
                ),
                "tool_compatibility": tool_compatibility_mode(config, agent),
                "cooldown_until": row.get("cooldown_until"),
                "unavailable_until": row.get("unavailable_until"),
                "recent_failures": row.get("failure_count", 0),
                "average_latency_seconds": row.get("average_latency_seconds", 0.0),
                "tokens_per_second": row.get("average_tokens_per_second", 0.0),
                "quota_state": row.get("quota_state", "unknown"),
                "remaining": row.get("remaining", "unknown"),
                "context_limit": row.get("context_window"),
                "output_limit": row.get("max_output_tokens"),
                "last_request_source": row.get("last_request_source"),
                "last_failover_attempts": row.get("last_failover_attempts", 0),
                "stream_interruption_count": row.get("stream_interruption_count", 0),
            }
        )
    return rows


def build_capability_graph(
    config: HubConfig,
    health: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for route in config.routes:
        for index, agent_name in enumerate(route.agents):
            agent = config.agents.get(agent_name)
            if not agent:
                continue
            edges.append(
                {
                    "route": route.name,
                    "agent": agent.name,
                    "order": index,
                    "available": bool(health.get(agent.name, {}).get("available")),
                }
            )
    for agent in config.agents.values():
        row = health.get(agent.name, {})
        compatibility_mode = tool_compatibility_mode(config, agent)
        nodes.append(
            {
                "agent": agent.name,
                "provider": agent.provider,
                "provider_type": agent.provider_type or normalize_provider(agent.provider),
                "model": agent.model,
                "enabled": agent.enabled,
                "available": bool(row.get("available")),
                "capabilities": agent_capabilities(agent).to_graph_dict(),
                "compatibility": {
                    "request_shapes": ["native", "openai-chat", "openai-responses", "anthropic-messages"],
                    "response_shapes": ["native", "openai-chat", "openai-responses", "anthropic-messages"],
                    "tool_mode": compatibility_mode,
                    "effective_tools": compatibility_mode in {"native", "emulated"},
                    "buffered_stream_fallback": True,
                },
                "benchmark_memory": {
                    "reliability_score": row.get("reliability_score"),
                    "average_latency_ms": row.get("average_latency_ms"),
                    "streaming_tokens_per_second": row.get("streaming_tokens_per_second"),
                    "success_count": row.get("success_count"),
                    "failure_count": row.get("failure_count"),
                },
            }
        )
    return {"object": "agent_hub.capability_graph", "nodes": nodes, "edges": edges}


__all__ = ["build_capability_graph", "build_provider_status"]
