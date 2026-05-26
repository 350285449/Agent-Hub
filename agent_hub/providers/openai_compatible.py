from __future__ import annotations

from . import OpenAIChatProvider


class OpenAICompatibleAdapter(OpenAIChatProvider):
    """Adapter for OpenAI-compatible chat completions APIs."""


OpenAICompatibleProvider = OpenAICompatibleAdapter


__all__ = ["OpenAICompatibleAdapter", "OpenAICompatibleProvider"]
