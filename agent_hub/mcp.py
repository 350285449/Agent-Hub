from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
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
    """Policy-gated stdio bridge for explicitly configured MCP servers."""

    def __init__(self, config: HubConfig) -> None:
        self.config = config
        self.servers = [server for server in config.mcp_servers if server.enabled]

    def discover_tools(self) -> list[MCPToolDefinition]:
        definitions: list[MCPToolDefinition] = []
        for server in self.servers:
            definitions.extend(normalize_mcp_tools(server))
        return definitions

    def agent_hub_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        for server in self.servers:
            tools.extend(
                definition_to_tool(definition, server=server, config=self.config)
                for definition in normalize_mcp_tools(server)
            )
        return tools

    def execute(self, call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        for tool in self.agent_hub_tools():
            if tool.name == call.name:
                return tool.executor(call, context)
        return ToolResult(call_id=call.id, name=call.name, ok=False, error="Unknown MCP tool.")


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


def definition_to_tool(
    definition: MCPToolDefinition,
    *,
    server: MCPServerConfig | None = None,
    config: HubConfig | None = None,
) -> Tool:
    execution_enabled = bool(config and config.mcp_execution_enabled and server and server.command)
    status = "ready" if execution_enabled else "execution_disabled"

    def _execute(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        if server is None or config is None or not config.mcp_execution_enabled:
            return _mcp_error(call, definition, "MCP stdio execution is disabled by mcp_execution_enabled=false.")
        if not server.command:
            return _mcp_error(call, definition, "MCP server command is not configured.")
        return _execute_stdio_tool(
            server=server,
            definition=definition,
            call=call,
            context=context,
            timeout_seconds=config.mcp_timeout_seconds,
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
                "status": status,
                "transport": "stdio",
                "execution_enabled": execution_enabled,
            },
            "raw": dict(definition.raw),
        },
    )


def _execute_stdio_tool(
    *,
    server: MCPServerConfig,
    definition: MCPToolDefinition,
    call: ToolCall,
    context: ToolExecutionContext,
    timeout_seconds: float,
) -> ToolResult:
    started = time.time()
    argv = [str(server.command), *[str(arg) for arg in server.args]]
    env = {**os.environ, **server.env}
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agent-hub", "version": "0.8"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": definition.name, "arguments": dict(call.arguments)},
        },
    ]
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(context.workspace_dir),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            bufsize=1,
        )
    except OSError as exc:
        return _mcp_error(call, definition, f"Could not start MCP server: {exc}")

    responses: queue.Queue[dict[str, Any]] = queue.Queue()

    def _read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                responses.put(value)

    reader = threading.Thread(target=_read_stdout, daemon=True)
    reader.start()
    try:
        assert process.stdin is not None
        for message in messages:
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + max(1.0, min(float(timeout_seconds), 120.0))
        response: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            try:
                candidate = responses.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if candidate.get("id") == 2:
                response = candidate
                break
        if response is None:
            stderr = _read_process_stderr(process)
            return _mcp_error(
                call,
                definition,
                "MCP tool call timed out or the server exited before returning a result."
                + (f" {stderr}" if stderr else ""),
            )
        if isinstance(response.get("error"), dict):
            error = response["error"]
            return _mcp_error(call, definition, str(error.get("message") or error))
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=response.get("result"),
            started_at=started,
            finished_at=time.time(),
            metadata={
                "mcp": {
                    "server": definition.server,
                    "tool": definition.name,
                    "status": "executed",
                    "transport": "stdio",
                }
            },
        )
    except (OSError, BrokenPipeError) as exc:
        return _mcp_error(call, definition, f"MCP stdio communication failed: {exc}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()


def _read_process_stderr(process: subprocess.Popen[str]) -> str:
    if process.stderr is None or process.poll() is None:
        return ""
    try:
        return process.stderr.read(2000).strip()
    except OSError:
        return ""


def _mcp_error(call: ToolCall, definition: MCPToolDefinition, error: str) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        ok=False,
        error=error,
        metadata={
            "mcp": {
                "server": definition.server,
                "tool": definition.name,
                "status": "error",
                "transport": "stdio",
            }
        },
    )
