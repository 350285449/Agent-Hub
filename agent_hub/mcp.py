from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import HubConfig, MCPServerConfig
from .tools import Tool, ToolCall, ToolExecutionContext, ToolResult


@dataclass(slots=True)
class MCPToolDefinition:
    """Normalized MCP-like tool metadata before Agent Hub registration."""

    server: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    output_schema: dict[str, Any] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        return f"mcp.{self.server}.{self.name}"


class MCPServerRegistry:
    """Future-ready bridge for external MCP servers.

    Full stdio/SSE MCP protocol execution is intentionally not faked here. The
    registry can discover tools declared in config and normalize them into Agent
    Hub Tool objects so routing, permissions, and docs can build on one shape.
    """

    def __init__(self, config: HubConfig) -> None:
        self.config = config
        self.servers = [server for server in config.mcp_servers if server.enabled]

    def discover_tools(self) -> list[MCPToolDefinition]:
        definitions: list[MCPToolDefinition] = []
        for server in self.servers:
            definitions.extend(normalize_mcp_tools(server))
        return definitions

    def agent_hub_tools(self) -> list[Tool]:
        return [definition_to_tool(definition) for definition in self.discover_tools()]

    def execute(self, call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=False,
            error=(
                "External MCP protocol execution is future-ready but not yet "
                "implemented in this build."
            ),
            metadata={
                "mcp": {
                    "status": "future_ready",
                    "tool": call.name,
                    "workspace_dir": str(context.workspace_dir),
                }
            },
        )


def normalize_mcp_tools(server: MCPServerConfig) -> list[MCPToolDefinition]:
    definitions: list[MCPToolDefinition] = []
    for raw_tool in server.tools:
        if not isinstance(raw_tool, dict):
            continue
        name = raw_tool.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        input_schema = (
            raw_tool.get("input_schema")
            or raw_tool.get("parameters")
            or {"type": "object", "properties": {}}
        )
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}
        output_schema = raw_tool.get("output") or raw_tool.get("output_schema") or {}
        if not isinstance(output_schema, dict):
            output_schema = {}
        permissions = raw_tool.get("permissions")
        if not isinstance(permissions, list):
            permissions = list(server.permissions)
        definitions.append(
            MCPToolDefinition(
                server=server.name,
                name=name.strip(),
                description=str(raw_tool.get("description") or server.description or ""),
                input_schema=input_schema,
                output_schema=output_schema,
                permissions=[str(item) for item in permissions if isinstance(item, str)],
                raw=dict(raw_tool),
            )
        )
    return definitions


def definition_to_tool(definition: MCPToolDefinition) -> Tool:
    def _execute(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=False,
            error=(
                "External MCP protocol execution is future-ready but not yet "
                "implemented in this build."
            ),
            metadata={"mcp": {"server": definition.server, "tool": definition.name, "status": "future_ready"}},
        )

    return Tool(
        name=definition.qualified_name,
        description=definition.description,
        input_schema=definition.input_schema,
        output_schema=definition.output_schema,
        executor=_execute,
        read_only="write" not in {permission.lower() for permission in definition.permissions},
        permission="mcp_tool",
        permissions=list(definition.permissions),
        metadata={
            "mcp": {
                "server": definition.server,
                "tool": definition.name,
                "status": "future_ready",
            },
            "raw": dict(definition.raw),
        },
    )
