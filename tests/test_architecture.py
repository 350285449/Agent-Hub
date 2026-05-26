from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_hub.config import AgentConfig, HubConfig
from agent_hub.core.provider_manager import ProviderManager
from agent_hub.models import HubRequest, ProviderResult
from agent_hub.providers import OpenAIChatProvider, create_provider
from agent_hub.providers.base import ChatResponse
from agent_hub.router import AgentRouter


class ArchitectureTests(unittest.TestCase):
    def test_openai_compatible_adapter_exposes_strict_interface(self) -> None:
        agent = AgentConfig(
            name="local",
            provider="openai-compatible",
            model="test-model",
            base_url="http://127.0.0.1:11434",
            free=True,
            context_window=8192,
            supports_streaming=True,
            supports_tools=True,
        )
        provider = OpenAIChatProvider(agent)
        request = HubRequest(
            session_id="s",
            messages=[{"role": "user", "content": "hello"}],
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 4},
                "model": "test-model",
            }
            response = provider.chat(request)

        self.assertIsInstance(response, ChatResponse)
        self.assertEqual(provider.name, "local")
        self.assertEqual(provider.models, ["test-model"])
        self.assertTrue(provider.supports_streaming())
        self.assertTrue(provider.supports_tools())
        self.assertEqual(provider.context_limit("test-model"), 8192)
        self.assertEqual(provider.cost_estimate(10, 20, "test-model"), 0.0)
        self.assertEqual(response.text, "Done")

    def test_ollama_adapter_is_registered_as_openai_compatible(self) -> None:
        provider = create_provider(
            AgentConfig(
                name="ollama",
                provider="ollama",
                provider_type="ollama",
                model="qwen2.5-coder:7b",
                base_url="http://127.0.0.1:11434",
            )
        )

        self.assertEqual(provider.__class__.__name__, "OllamaProvider")
        self.assertIn("Ollama", provider.display_name)

    def test_provider_manager_bridges_legacy_complete_adapters(self) -> None:
        calls: list[str] = []

        class LegacyProvider:
            def __init__(self, agent: AgentConfig) -> None:
                self.agent = agent

            def complete(self, request: HubRequest) -> ProviderResult:
                calls.append(self.agent.name)
                return ProviderResult(text="ok", model=self.agent.model)

        config = HubConfig(
            agents={
                "legacy": AgentConfig(
                    name="legacy",
                    provider="openai-compatible",
                    model="legacy-model",
                    base_url="http://127.0.0.1:9999",
                )
            }
        )
        manager = ProviderManager(config, provider_factory=LegacyProvider)

        result = manager.chat(
            "legacy",
            HubRequest(session_id="s", messages=[{"role": "user", "content": "hi"}]),
        )

        self.assertEqual(calls, ["legacy"])
        self.assertEqual(result.text, "ok")

    def test_routing_modes_are_explainable_and_ranked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = AgentRouter(_routing_config(Path(tmp)))

            fastest = router.decide(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "hello"}],
                    raw={"routing_mode": "fastest"},
                )
            )
            cheapest = router.decide(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "hello"}],
                    raw={"routing_mode": "cheapest"},
                )
            )
            coding = router.decide(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "debug this error in the tests"}],
                )
            )
            long_context = router.decide(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "x" * 100_000}],
                    raw={"routing_mode": "long_context"},
                )
            )
            local = router.decide(
                HubRequest(
                    session_id="s",
                    messages=[{"role": "user", "content": "keep this private"}],
                    raw={"agent_hub": {"local_private": True}},
                )
            )

        self.assertEqual(fastest.selected_agent, "fast")
        self.assertEqual(fastest.routing_mode, "fastest")
        self.assertEqual(cheapest.selected_agent, "free")
        self.assertEqual(coding.selected_agent, "coder")
        self.assertEqual(coding.routing_mode, "coding")
        self.assertEqual(long_context.selected_agent, "long")
        self.assertEqual(local.selected_agent, "local")
        self.assertEqual(local.fallback_chain, ["local"])
        self.assertIn("Privacy/local", local.reason)


def _routing_config(path: Path) -> HubConfig:
    return HubConfig(
        state_dir=path,
        free_only=False,
        default_route=["slow", "fast", "free", "coder", "long", "local"],
        agents={
            "slow": AgentConfig(
                name="slow",
                provider="openai",
                model="slow-model",
                free=False,
                speed_score=0.1,
                context_window=8000,
            ),
            "fast": AgentConfig(
                name="fast",
                provider="openai",
                model="fast-model",
                free=False,
                speed_score=1.0,
                context_window=8000,
            ),
            "free": AgentConfig(
                name="free",
                provider="openai-compatible",
                model="free-model",
                base_url="https://example.invalid/v1",
                free=True,
                speed_score=0.2,
                context_window=8000,
            ),
            "coder": AgentConfig(
                name="coder",
                provider="openai-compatible",
                model="coder-model",
                base_url="https://example.invalid/v1",
                free=False,
                coding_score=1.0,
                supports_tools=True,
                context_window=8000,
            ),
            "long": AgentConfig(
                name="long",
                provider="openai-compatible",
                model="long-model",
                base_url="https://example.invalid/v1",
                free=False,
                context_window=128000,
            ),
            "local": AgentConfig(
                name="local",
                provider="ollama",
                provider_type="ollama",
                model="local-model",
                base_url="http://127.0.0.1:11434",
                free=False,
                context_window=16000,
            ),
        },
    )


if __name__ == "__main__":
    unittest.main()
