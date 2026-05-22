"""Local agent routing hub.

This package provides the core components for the Agent Hub system:
- Agent configurations and utilities
- Request/response models
- Routing logic
- Runner implementations for individual and team agents
"""

from .agent_runner import AgentRunner
from .config import (
    AgentConfig,          # Configuration for a single agent
    HubConfig,            # Global hub configuration
    RouteRule,            # Defines how requests are routed to agents
    config_to_dict,       # Utility to convert config objects to dictionaries
    free_local_config,    # Pre-configured free/local agent settings
    is_free_agent,        # Check if an agent is free/local
    load_config,          # Load configuration from file/sources
    normalize_provider,   # Normalize provider names
)
from .models import HubRequest, HubResponse, ProviderResult  # Data models for hub communication
from .reasoning import ExecutionNode, ExecutionPlan, WorkspaceReasoningState
from .router import AgentRouter  # Routes requests to appropriate agents
from .team_agent_runner import TeamAgentRunner  # Runs a team of agents collaboratively
from .version import backend_version

__all__ = [
    "AgentConfig",
    "AgentRunner",
    "AgentRouter",
    "TeamAgentRunner",
    "HubConfig",
    "HubRequest",
    "HubResponse",
    "ProviderResult",
    "RouteRule",
    "ExecutionNode",
    "ExecutionPlan",
    "WorkspaceReasoningState",
    "config_to_dict",
    "free_local_config",
    "is_free_agent",
    "load_config",
    "normalize_provider",
    "backend_version",
]
