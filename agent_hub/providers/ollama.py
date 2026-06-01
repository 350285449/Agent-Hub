from __future__ import annotations

from .openai_chat import OpenAIChatProvider


class OllamaProvider(OpenAIChatProvider):
    """Ollama adapter using Ollama's OpenAI-compatible chat endpoint."""

    @property
    def display_name(self) -> str:
        return f"Ollama / {self.agent.model}"


OllamaAdapter = OllamaProvider


__all__ = ["OllamaAdapter", "OllamaProvider"]
