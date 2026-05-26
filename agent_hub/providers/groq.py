from __future__ import annotations

from . import OpenAIChatProvider


class GroqProvider(OpenAIChatProvider):
    """Groq adapter backed by Groq's OpenAI-compatible API."""

    @property
    def display_name(self) -> str:
        return f"Groq / {self.agent.model}"


GroqAdapter = GroqProvider


__all__ = ["GroqAdapter", "GroqProvider"]
