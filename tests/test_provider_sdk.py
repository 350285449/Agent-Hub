from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_hub.config import AgentConfig
from agent_hub.models import HubRequest
from agent_hub.provider_presets import (
    FREE_PROVIDER_PRESETS,
    OPENAI_COMPATIBLE_PROVIDER_TYPES,
    provider_metadata,
    provider_preset,
)
from agent_hub.providers import ProviderDescriptor, SimpleOpenAICompatibleProvider
from agent_hub.providers.sdk import (
    ProviderCapabilities,
    ProviderPricing,
    builtin_provider_descriptors,
    provider_conformance_report,
)


class ProviderSDKTests(unittest.TestCase):
    def test_descriptor_creates_agent_config_dict(self) -> None:
        descriptor = ProviderDescriptor(
            provider_type="demo-ai",
            display_name="Demo AI",
            base_url="https://api.demo.invalid/v1",
            api_key_env="DEMO_API_KEY",
            headers={"X-Demo": "Agent-Hub"},
            capabilities=ProviderCapabilities(
                context_window=128_000,
                supports_tools=True,
                supports_streaming=True,
            ),
            pricing=ProviderPricing(
                cost_per_million_input=0.25,
                cost_per_million_output=1.0,
            ),
            default_free=False,
        )

        data = descriptor.to_agent_dict(
            name="demo-coder",
            model="demo/coder",
            enabled=True,
            coding_score=0.9,
        )
        agent = descriptor.create_agent(
            name="demo-coder",
            model="demo/coder",
            enabled=True,
        )

        self.assertEqual(data["provider"], "openai-compatible")
        self.assertEqual(data["provider_type"], "demo-ai")
        self.assertEqual(data["headers"], {"X-Demo": "Agent-Hub"})
        self.assertEqual(data["context_window"], 128_000)
        self.assertEqual(data["cost_per_million_output"], 1.0)
        self.assertEqual(data["coding_score"], 0.9)
        self.assertEqual(agent.base_url, "https://api.demo.invalid/v1")

    def test_simple_openai_compatible_provider_applies_descriptor_defaults(self) -> None:
        class DemoProvider(SimpleOpenAICompatibleProvider):
            descriptor = ProviderDescriptor(
                provider_type="demo-ai",
                display_name="Demo AI",
                base_url="https://api.demo.invalid/v1",
                api_key_env="DEMO_API_KEY",
                headers={"X-Demo": "Agent-Hub"},
                capabilities=ProviderCapabilities(supports_tools=True),
                pricing=ProviderPricing(
                    cost_per_million_input=0.5,
                    cost_per_million_output=1.5,
                ),
                default_free=False,
            )

        agent = AgentConfig(
            name="demo",
            provider="openai-compatible",
            model="demo-model",
            api_key="key",
        )
        request = HubRequest(
            session_id="s",
            messages=[{"role": "user", "content": "hello"}],
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}],
                "usage": {},
            }
            provider = DemoProvider(agent)
            result = provider.complete(request)

        self.assertEqual(result.text, "Done")
        self.assertEqual(provider.agent.provider_type, "demo-ai")
        self.assertTrue(provider.supports_tools())
        self.assertEqual(provider.cost_estimate(1_000_000, 2_000_000), 3.5)
        self.assertEqual(
            post_json.call_args.kwargs["url"],
            "https://api.demo.invalid/v1/chat/completions",
        )
        self.assertEqual(post_json.call_args.kwargs["headers"]["X-Demo"], "Agent-Hub")
        self.assertEqual(
            post_json.call_args.kwargs["headers"]["Authorization"],
            "Bearer key",
        )

    def test_provider_conformance_report_validates_sdk_contract_without_network(self) -> None:
        class DemoProvider(SimpleOpenAICompatibleProvider):
            descriptor = ProviderDescriptor(
                provider_type="demo-ai",
                display_name="Demo AI",
                base_url="https://api.demo.invalid/v1",
                capabilities=ProviderCapabilities(
                    context_window=128_000,
                    supports_streaming=True,
                    supports_tools=True,
                ),
                pricing=ProviderPricing(
                    cost_per_million_input=0.25,
                    cost_per_million_output=1.0,
                ),
                default_free=False,
            )

        report = provider_conformance_report(DemoProvider)

        self.assertEqual(report["object"], "agent_hub.provider_conformance")
        self.assertTrue(report["ok"], report["checks"])
        self.assertEqual(report["rating"], 10.0)
        self.assertIn("ChatRequest", report["contract"]["request"])
        self.assertIn("chat", report["contract"]["required_methods"])

    def test_builtin_descriptors_cover_local_openai_compatible_servers(self) -> None:
        descriptors = builtin_provider_descriptors()

        for provider_type in ("lm-studio", "vllm", "localai", "llama-cpp"):
            with self.subTest(provider_type=provider_type):
                descriptor = descriptors[provider_type]
                metadata = provider_metadata(provider_type)

                self.assertIsNotNone(metadata)
                self.assertEqual(descriptor.provider, "openai-compatible")
                self.assertTrue(descriptor.base_url)
                self.assertTrue(descriptor.default_free)

    def test_provider_preset_catalog_has_unique_known_entries(self) -> None:
        names = [preset.name for preset in FREE_PROVIDER_PRESETS]
        provider_types = {preset.provider_type for preset in FREE_PROVIDER_PRESETS}

        self.assertEqual(len(names), len(set(names)))
        self.assertLessEqual(provider_types, OPENAI_COMPATIBLE_PROVIDER_TYPES)
        for preset in FREE_PROVIDER_PRESETS:
            self.assertIs(provider_preset(preset.name), preset)


if __name__ == "__main__":
    unittest.main()
