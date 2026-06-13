from __future__ import annotations

from .openai_chat import OpenAIChatProvider


class OpenAICompatibleAdapter(OpenAIChatProvider):
    """Adapter for OpenAI-compatible chat completions APIs."""


OpenAICompatibleProvider = OpenAICompatibleAdapter


__all__ = ["OpenAICompatibleAdapter", "OpenAICompatibleProvider"]
