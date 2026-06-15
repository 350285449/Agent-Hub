from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict


class ChatMessage(TypedDict, total=False):
    role: str
    content: Any


@dataclass(slots=True)
class SDKResponse:
    raw: dict[str, Any]

    @property
    def text(self) -> str:
        message = self.raw.get("message")
        if isinstance(message, dict):
            return str(message.get("content") or "")
        choices = self.raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                choice_message = first.get("message")
                if isinstance(choice_message, dict):
                    return str(choice_message.get("content") or "")
        return ""
