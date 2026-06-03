from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.capabilities import agent_capabilities, agent_supports_tools
from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.core.provider_manager import ProviderManager
from agent_hub.core.router import AgentRouter
from agent_hub.providers.base import BaseProviderAdapter


class CapabilityModelTests(unittest.TestCase):
    def test_defaults_match_agent_config_truthiness(self) -> None:
        agent = AgentConfig(name="plain", provider="openai-compatible", model="m")

        capabilities = agent_capabilities(agent)

        self.assertFalse(capabilities.supports_tools)
        self.assertFalse(capabilities.supports_json)
        self.assertFalse(capabilities.supports_streaming)
        self.assertFalse(capabilities.supports_vision)
        self.assertFalse(capabilities.supports_function_calling)
        self.assertFalse(capabilities.tool_capable)
        self.assertIsNone(capabilities.context_window)
        self.assertIsNone(capabilities.max_output_tokens)

    def test_function_calling_counts_as_tool_capable_for_legacy_surfaces(self) -> None:
        agent = AgentConfig(
            name="tooly",
            provider="openai-compatible",
            model="m",
            supports_function_calling=True,
            context_window=8192,
            max_tokens=512,
        )

        capabilities = agent_capabilities(agent)

        self.assertTrue(agent_supports_tools(agent))
        self.assertTrue(capabilities.tool_capable)
        self.assertEqual(capabilities.to_graph_dict()["tools"], True)
        self.assertEqual(capabilities.to_model_info_dict()["supports_tools"], True)
        self.assertEqual(capabilities.to_health_fields()["max_output_tokens"], 512)

    def test_base_provider_adapter_reads_capabilities_from_shared_model(self) -> None:
        agent = AgentConfig(
            name="adapter",
            provider="openai-compatible",
            model="m",
            supports_function_calling=True,
            supports_streaming=True,
            context_window=4096,
        )

        provider = _DummyProvider(agent)

        self.assertTrue(provider.supports_tools())
        self.assertTrue(provider.supports_streaming())
        self.assertFalse(provider.supports_vision())
        self.assertEqual(provider.context_limit("m"), 4096)

    def test_provider_manager_model_rows_use_capability_model(self) -> None:
        config = HubConfig(
            agents={
                "tooly": AgentConfig(
                    name="tooly",
                    provider="openai-compatible",
                    model="m",
                    supports_function_calling=True,
                )
            }
        )

        rows = ProviderManager(config).models()

        self.assertTrue(rows[0].supports_tools)

    def test_router_capability_graph_uses_capability_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = HubConfig(
                state_dir=Path(tmp),
                routes=[RouteRule(name="coding", agents=["tooly"])],
                agents={
                    "tooly": AgentConfig(
                        name="tooly",
                        provider="openai-compatible",
                        model="m",
                        supports_function_calling=True,
                        supports_json=True,
                    )
                },
            )

            graph = AgentRouter(config).capability_graph()

        node = graph["nodes"][0]
        self.assertTrue(node["capabilities"]["tools"])
        self.assertTrue(node["capabilities"]["json"])


class _DummyProvider(BaseProviderAdapter):
    def __init__(self, agent: AgentConfig) -> None:
        self.agent = agent


if __name__ == "__main__":
    unittest.main()
