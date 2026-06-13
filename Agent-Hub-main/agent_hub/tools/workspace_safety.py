from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any, Callable

from ..models import HubRequest


SKIPPED_DIRS = {
    ".agent-hub",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "state",
    "sessions",
    "logs",
}
RUNTIME_DIR_OPTIONS = ("state_dir", "inbox_dir", "outbox_dir", "archive_dir")
MAX_FILE_CHARS = 80_000
MAX_TOOL_OUTPUT_CHARS = 20_000
MAX_REPLACE_CHARS = 200_000
MAX_PATCH_CHARS = 1_000_000
MAX_PATH_HINTS = 10
MAX_COMMAND_TIMEOUT_SECONDS = 600
MAX_CHECKPOINT_RETENTION = 100
MAX_REPO_MAP_FILES = 80
MAX_SYMBOLS_PER_FILE = 20


class ToolError(Exception):
    pass


ShellPermissionCallback = Callable[[dict[str, Any]], bool]


def _approval_intelligence(
    tool_name: str,
    affected_files: list[str],
    patch_preview: str,
    commands: list[str],
) -> dict[str, Any]:
    additions = sum(1 for line in patch_preview.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in patch_preview.splitlines() if line.startswith("-") and not line.startswith("---"))
    file_groups = _file_groups(affected_files)
    risk_level = _risk_level(tool_name, affected_files, additions, deletions, commands)
    impact_bits: list[str] = []
    if affected_files:
        impact_bits.append(f"{len(affected_files)} file(s)")
    if additions or deletions:
        impact_bits.append(f"+{additions}/-{deletions} line(s)")
    if commands:
        impact_bits.append(f"{len(commands)} planned command(s)")
    if file_groups:
        impact_bits.append("groups: " + ", ".join(group["group"] for group in file_groups[:4]))
    return {
        "risk_level": risk_level,
        "impact": ", ".join(impact_bits) if impact_bits else "No file changes detected.",
        "estimated_impact": {
            "files": len(affected_files),
            "additions": additions,
            "deletions": deletions,
            "commands": len(commands),
        },
        "file_groups": file_groups,
    }


def _file_groups(paths: list[str]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for path in paths:
        lowered = path.lower()
        if "/test" in lowered or lowered.startswith("test") or "\\test" in lowered:
            group = "tests"
        elif lowered.endswith((".md", ".txt", ".rst")):
            group = "docs"
        elif lowered.endswith((".json", ".toml", ".yaml", ".yml", ".ini", ".cfg")):
            group = "config"
        elif lowered.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs")):
            group = "implementation"
        else:
            group = "other"
        groups.setdefault(group, []).append(path)
    return [
        {"group": group, "files": files}
        for group, files in sorted(groups.items(), key=lambda item: item[0])
    ]


def _risk_level(
    tool_name: str,
    affected_files: list[str],
    additions: int,
    deletions: int,
    commands: list[str],
) -> str:
    total_lines = additions + deletions
    command_text = " ".join(commands).lower()
    if tool_name == "run_command" and any(token in command_text for token in (" rm ", "git reset", "delete", "del ")):
        return "high"
    if len(affected_files) >= 8 or total_lines > 600:
        return "high"
    if len(affected_files) >= 3 or total_lines > 120 or commands:
        return "medium"
    return "low"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _matches_repo_ignore(relative: str, patterns: list[str]) -> bool:
    normalized = relative.replace("\\", "/").strip("./")
    for pattern in patterns:
        clean = str(pattern).replace("\\", "/").strip()
        if not clean:
            continue
        if fnmatch.fnmatch(normalized, clean) or fnmatch.fnmatch(normalized, clean.rstrip("/**")):
            return True
        if clean.endswith("/**") and normalized.startswith(clean[:-3].rstrip("/") + "/"):
            return True
    return False


def _request_option(request: HubRequest, key: str, default: Any) -> Any:
    raw = request.raw or {}
    hub_options = raw.get("agent_hub")
    if isinstance(hub_options, dict) and key in hub_options:
        return hub_options[key]
    return raw.get(key, default)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "approved"}
    return bool(value)


def _shell_instruction(allow_shell: bool, policy: str) -> str:
    if not allow_shell:
        return "Shell tools are disabled; do not call run_command."
    if policy == "ask":
        return (
            "Use run_command only when it materially helps; the user will be asked "
            "for permission before each shell command runs."
        )
    if policy == "deny":
        return "Shell command execution is disabled by policy; do not call run_command."
    return "If shell tools are enabled, use run_command for fast inspection, builds, tests, and requested commands."


def _normalize_shell_policy(value: Any) -> str:
    text = str(value or "allow").strip().lower()
    if text in {"ask", "confirm", "prompt"}:
        return "ask"
    if text in {"deny", "disabled", "disable", "off", "false", "0"}:
        return "deny"
    return "allow"


def _is_bare_filename(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    if "/" in value or "\\" in value:
        return False
    path = Path(value)
    return not path.is_absolute() and len(path.parts) == 1


def _positive_int(value: Any, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, maximum))


def tool_result_message(tool_name: str, result: dict[str, Any]) -> dict[str, str]:
    content = json.dumps(result, indent=2, ensure_ascii=False)
    return {
        "role": "user",
        "content": (
            f"Tool result for {tool_name}:\n{content}\n\n"
            "Continue with exactly one JSON object: another tool call or a final answer. "
            "If the tool failed, correct the arguments before retrying."
        ),
    }




__all__ = [
    "SKIPPED_DIRS",
    "RUNTIME_DIR_OPTIONS",
    "MAX_FILE_CHARS",
    "MAX_TOOL_OUTPUT_CHARS",
    "MAX_REPLACE_CHARS",
    "MAX_PATCH_CHARS",
    "MAX_PATH_HINTS",
    "MAX_COMMAND_TIMEOUT_SECONDS",
    "MAX_CHECKPOINT_RETENTION",
    "MAX_REPO_MAP_FILES",
    "MAX_SYMBOLS_PER_FILE",
    "ToolError",
    "ShellPermissionCallback",
    "_approval_intelligence",
    "_file_groups",
    "_risk_level",
    "_dedupe",
    "_matches_repo_ignore",
    "_request_option",
    "_string_list",
    "_truthy",
    "_shell_instruction",
    "_normalize_shell_policy",
    "_is_bare_filename",
    "_positive_int",
    "tool_result_message",
]
