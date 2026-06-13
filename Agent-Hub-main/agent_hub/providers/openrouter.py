from __future__ import annotations

from .openai_chat import OpenAIChatProvider


class OpenRouterProvider(OpenAIChatProvider):
    """OpenRouter adapter backed by OpenRouter's OpenAI-compatible API."""

    @property
    def display_name(self) -> str:
        return f"OpenRouter / {self.agent.model}"


OpenRouterAdapter = OpenRouterProvider


__all__ = ["OpenRouterAdapter", "OpenRouterProvider"]
