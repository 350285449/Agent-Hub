from __future__ import annotations

from typing import Any

from .core.router import RouterError


def _print_route_error(error: RouterError) -> None:
    print(f"Agent-Hub route failed: {error}")
    if getattr(error, "suggested_fix", None):
        print(f"Suggested fix: {error.suggested_fix}")
    if error.failover:
        print("Failover:")
        for event in error.failover:
            print(f"- {event.agent}: {event.reason}")


def _shell_permission_prompt(details: dict[str, Any]) -> bool:
    command = str(details.get("command") or "")
    cwd = str(details.get("cwd") or ".")
    timeout = details.get("timeout_seconds")
    print()
    print("Agent-Hub wants to run a shell command:")
    print(f"cwd: {cwd}")
    print(f"command: {command}")
    if timeout:
        print(f"timeout: {timeout}s")
    try:
        answer = input("Allow this command? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in {"y", "yes"}


def _print_table(rows: list[dict[str, Any]], columns: list[str]) -> None:
    if not rows:
        print("No agents configured.")
        return
    widths = {
        column: max(len(column), *(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }
    print("  ".join(column.ljust(widths[column]) for column in columns))
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print("  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))
