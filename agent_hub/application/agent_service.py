from __future__ import annotations

import re
from typing import Any

from ..config import AgentConfig, HubConfig, config_from_dict, config_to_dict


_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class AgentApplicationService:
    """Runtime-local CRUD surface for custom agent definitions."""

    def __init__(self, config: HubConfig) -> None:
        self.config = config

    def list_agents(self) -> dict[str, Any]:
        return {
            "object": "agent_hub.agents",
            "data": [self._agent_row(agent) for agent in self.config.agents.values()],
            "count": len(self.config.agents),
            "source": "runtime_config",
        }

    def get_agent(self, name: str) -> dict[str, Any]:
        agent = self.config.agents.get(name)
        if agent is None:
            raise AgentServiceError("agent_not_found", f"Agent '{name}' is not configured.", status=404)
        return {
            "object": "agent_hub.agent",
            "data": self._agent_row(agent),
            "source": "runtime_config",
        }

    def create_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self._agent_from_payload(payload)
        if agent.name in self.config.agents:
            raise AgentServiceError("agent_exists", f"Agent '{agent.name}' already exists.", status=409)
        self.config.agents[agent.name] = agent
        self._ensure_default_route_has_agent(agent.name, payload)
        return {
            "object": "agent_hub.agent",
            "created": True,
            "data": self._agent_row(agent),
            "source": "runtime_config",
        }

    def update_agent(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if name not in self.config.agents:
            raise AgentServiceError("agent_not_found", f"Agent '{name}' is not configured.", status=404)
        current = config_to_dict(HubConfig(agents={name: self.config.agents[name]}))["agents"][0]
        merged = {**current, **payload, "name": name}
        agent = self._agent_from_payload(merged)
        self.config.agents[name] = agent
        self._ensure_default_route_has_agent(agent.name, payload)
        return {
            "object": "agent_hub.agent",
            "updated": True,
            "data": self._agent_row(agent),
            "source": "runtime_config",
        }

    def delete_agent(self, name: str) -> dict[str, Any]:
        if name not in self.config.agents:
            raise AgentServiceError("agent_not_found", f"Agent '{name}' is not configured.", status=404)
        self.config.agents.pop(name)
        self.config.default_route = [agent for agent in self.config.default_route if agent != name]
        for route in self.config.routes:
            route.agents = [agent for agent in route.agents if agent != name]
        return {
            "object": "agent_hub.agent",
            "deleted": True,
            "name": name,
            "source": "runtime_config",
        }

    def _agent_from_payload(self, payload: dict[str, Any]) -> AgentConfig:
        if not isinstance(payload, dict):
            raise AgentServiceError("invalid_agent", "Expected an agent JSON object.", status=400)
        name = str(payload.get("name") or "").strip()
        if not _AGENT_NAME_RE.match(name):
            raise AgentServiceError(
                "invalid_agent_name",
                "Agent name must be 1-80 characters and use letters, numbers, dots, underscores, or hyphens.",
                status=400,
            )
        provider = str(payload.get("provider") or "").strip()
        if not provider:
            raise AgentServiceError("invalid_provider", "Agent provider is required.", status=400)
        parsed = config_from_dict({"agents": [payload]})
        agent = parsed.agents.get(name)
        if agent is None:
            raise AgentServiceError("invalid_agent", "Agent payload could not be normalized.", status=400)
        return agent

    def _agent_row(self, agent: AgentConfig) -> dict[str, Any]:
        data = config_to_dict(HubConfig(agents={agent.name: agent}))["agents"][0]
        data.pop("api_key", None)
        data["has_api_key"] = bool(agent.api_key)
        return data

    def _ensure_default_route_has_agent(self, name: str, payload: dict[str, Any]) -> None:
        if not bool(payload.get("add_to_default_route")):
            return
        if name not in self.config.default_route:
            self.config.default_route.append(name)


class AgentServiceError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_response(self) -> dict[str, Any]:
        return {"error": {"type": self.code, "message": self.message}}


__all__ = ["AgentApplicationService", "AgentServiceError"]
