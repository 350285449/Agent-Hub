from __future__ import annotations

from typing import Any


AGENT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List files or directories inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path."},
                "pattern": {"type": "string", "description": "Glob pattern to match."},
                "recursive": {"type": "boolean", "description": "Search subdirectories."},
                "limit": {"type": "integer", "description": "Maximum number of entries."},
            },
        },
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "start_line": {"type": "integer", "description": "First 1-based line to read."},
                "line_count": {"type": "integer", "description": "Maximum lines to read."},
                "max_chars": {"type": "integer", "description": "Maximum characters to return."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search workspace text files for a literal query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Literal text to search for."},
                "path": {"type": "string", "description": "Workspace-relative file or folder."},
                "pattern": {"type": "string", "description": "Glob pattern to search."},
                "case_sensitive": {"type": "boolean", "description": "Use case-sensitive matching."},
                "limit": {"type": "integer", "description": "Maximum number of matches."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "repo_map",
        "description": "Build a lightweight repository map with related files, tests, configs, and symbols before editing.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative focus path."},
                "target": {"type": "string", "description": "File, module, or symbol to prioritize."},
                "limit": {"type": "integer", "description": "Maximum files to return."},
            },
        },
    },
    {
        "name": "write_file",
        "description": "Create, overwrite, or append to one workspace text file. Prefer apply_patch for coordinated or repair edits.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "content": {"type": "string", "description": "Content to write."},
                "append": {"type": "boolean", "description": "Append instead of overwriting."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "replace_in_file",
        "description": "Replace exact text in one workspace text file. Prefer apply_patch for multi-file or validation-repair edits.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "old": {"type": "string", "description": "Exact text to replace."},
                "new": {"type": "string", "description": "Replacement text."},
                "expected_replacements": {
                    "type": "integer",
                    "description": "Expected number of replacements, usually 1.",
                },
            },
            "required": ["path", "old", "new"],
        },
    },
    {
        "name": "apply_patch",
        "description": "Apply a validated grouped patch across one or more files, with checkpoint rollback support.",
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "Unified diff patch. Supports multiple files.",
                },
                "changes": {
                    "type": "array",
                    "description": "Structured changes as path/content or path/old/new objects.",
                },
                "summary": {"type": "string", "description": "Short summary of planned changes."},
                "validation_plan": {
                    "type": "string",
                    "description": "Validation plan to run after applying the patch.",
                },
                "commands": {
                    "type": "array",
                    "description": "Commands the agent plans to run after applying the patch.",
                },
            },
        },
    },
]

RUN_COMMAND_TOOL_DEFINITION: dict[str, Any] = {
    "name": "run_command",
    "description": "Run a shell command inside the workspace.",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
            "cwd": {"type": "string", "description": "Workspace-relative working directory."},
            "timeout_seconds": {"type": "integer", "description": "Timeout in seconds."},
        },
        "required": ["command"],
    },
}


def agent_tool_definitions(allow_shell: bool) -> list[dict[str, Any]]:
    """Common workspace tool definitions converted by each provider."""

    tools = [*AGENT_TOOL_DEFINITIONS]
    if allow_shell:
        tools.append(RUN_COMMAND_TOOL_DEFINITION)
    return tools




__all__ = [
    "AGENT_TOOL_DEFINITIONS",
    "RUN_COMMAND_TOOL_DEFINITION",
    "agent_tool_definitions",
]
