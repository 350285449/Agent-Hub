from __future__ import annotations

from typing import Any


AGENT_TOOL_METHODS = {
    "list_files": "_list_files",
    "read_file": "_read_file",
    "search_files": "_search_files",
    "repo_map": "_repo_map",
    "write_file": "_write_file",
    "replace_in_file": "_replace_in_file",
    "apply_patch": "_apply_patch",
    "run_command": "_run_command",
}
MUTATING_AGENT_TOOLS = frozenset({"write_file", "replace_in_file", "apply_patch"})


def dispatch_agent_tool(toolbox: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    method_name = AGENT_TOOL_METHODS.get(name)
    if method_name is None:
        raise ValueError(f"Unknown tool {name!r}")
    method = getattr(toolbox, method_name, None)
    if method is None:
        raise ValueError(f"Tool {name!r} is not implemented")
    return method(args)
