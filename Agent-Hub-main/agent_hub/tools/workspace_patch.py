from __future__ import annotations

import difflib
import re
from typing import Any

from .workspace_safety import ToolError


def _parse_unified_diff(patch_text: str) -> list[dict[str, Any]]:
    lines = patch_text.splitlines(keepends=True)
    patches: list[dict[str, Any]] = []
    index = 0
    current: dict[str, Any] | None = None
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            if current is not None:
                patches.append(current)
            old_path = _diff_path(line[4:].strip())
            index += 1
            if index >= len(lines) or not lines[index].startswith("+++ "):
                raise ToolError("Unified diff missing +++ path after --- path")
            new_path = _diff_path(lines[index][4:].strip())
            current = {"old_path": old_path, "new_path": new_path, "hunks": []}
        elif line.startswith("@@ "):
            if current is None:
                raise ToolError("Unified diff hunk appeared before file header")
            hunk_lines = [line]
            index += 1
            while index < len(lines) and not lines[index].startswith(("--- ", "@@ ")):
                hunk_lines.append(lines[index])
                index += 1
            current["hunks"].append(hunk_lines)
            continue
        index += 1
    if current is not None:
        patches.append(current)
    return patches


def _diff_path(value: str) -> str:
    path = value.split("\t", 1)[0].split(" ", 1)[0]
    if path in {"/dev/null", "dev/null"}:
        return "/dev/null"
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _apply_unified_hunks(original: str, hunks: list[list[str]], relative: str) -> str:
    original_lines = original.splitlines(keepends=True)
    output: list[str] = []
    source_index = 0
    for hunk in hunks:
        if not hunk:
            continue
        match = re.match(r"@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@", hunk[0])
        if not match:
            raise ToolError(f"{relative}: invalid unified diff hunk header")
        old_start = int(match.group("old"))
        target_index = max(0, old_start - 1)
        if target_index < source_index:
            raise ToolError(f"{relative}: overlapping unified diff hunks")
        output.extend(original_lines[source_index:target_index])
        source_index = target_index
        for line in hunk[1:]:
            if line.startswith("\\"):
                continue
            marker = line[:1]
            content = line[1:]
            if marker == " ":
                if source_index >= len(original_lines) or original_lines[source_index] != content:
                    raise ToolError(f"{relative}: unified diff context does not match")
                output.append(original_lines[source_index])
                source_index += 1
            elif marker == "-":
                if source_index >= len(original_lines) or original_lines[source_index] != content:
                    raise ToolError(f"{relative}: unified diff removal does not match")
                source_index += 1
            elif marker == "+":
                output.append(content)
            else:
                raise ToolError(f"{relative}: invalid unified diff line {line[:20]!r}")
    output.extend(original_lines[source_index:])
    return "".join(output)


def _simple_unified_diff(before: str, after: str, path: str) -> list[str]:
    return list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )




__all__ = [
    "_parse_unified_diff",
    "_diff_path",
    "_apply_unified_hunks",
    "_simple_unified_diff",
]
