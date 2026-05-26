from __future__ import annotations

from typing import Iterable

from .types import Tool


class ToolRegistry:
    """In-memory catalog of executable tools.

    Aliases let compatibility clients keep using older Cline-style function
    names while the built-in canonical names stay stable.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool name is required")
        self._tools[tool.name] = tool

    def register_alias(self, alias: str, target: str) -> None:
        if not alias or not target:
            raise ValueError("Tool alias and target are required")
        if target not in self._tools:
            raise KeyError(f"Unknown target tool {target!r}")
        self._aliases[alias] = target

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        for alias, target in list(self._aliases.items()):
            if alias == name or target == name:
                self._aliases.pop(alias, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(self.resolve_name(name))

    def require(self, name: str) -> Tool:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool {name!r}")
        return tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def list(self) -> list[Tool]:
        return [self._tools[name] for name in self.names()]

    def extend(self, tools: Iterable[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def resolve_name(self, name: str) -> str:
        return self._aliases.get(name, name)

    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)
