from __future__ import annotations

import unittest

from agent_hub.sdk import AgentHubClient, SDKResponse


class SDKClientTests(unittest.TestCase):
    def test_client_exposes_stable_public_methods(self) -> None:
        client = AgentHubClient("http://127.0.0.1:8787", token="secret")

        self.assertTrue(callable(client.route))
        self.assertTrue(callable(client.simulate_route))
        self.assertTrue(callable(client.list_agents))
        self.assertTrue(callable(client.create_agent))
        self.assertTrue(callable(client.update_agent))
        self.assertTrue(callable(client.delete_agent))
        self.assertTrue(callable(client.list_workflow_templates))
        self.assertTrue(callable(client.create_workflow_template))
        self.assertTrue(callable(client.update_workflow_template))
        self.assertTrue(callable(client.delete_workflow_template))
        self.assertTrue(callable(client.list_routing_profiles))
        self.assertTrue(callable(client.list_routing_strategies))
        self.assertTrue(callable(client.create_routing_profile))
        self.assertTrue(callable(client.update_routing_profile))
        self.assertTrue(callable(client.delete_routing_profile))
        self.assertTrue(callable(client.compact_analytics))
        self.assertTrue(callable(client.observability_export))
        self.assertTrue(callable(client.otlp_export))
        self.assertTrue(callable(client.prometheus_export))
        self.assertTrue(callable(client.simulate_swarm))
        self.assertTrue(callable(client.simulate_token_pooling))
        self.assertTrue(callable(client.readiness))
        self.assertTrue(callable(client.openapi))

    def test_sdk_response_extracts_native_and_openai_text(self) -> None:
        self.assertEqual(SDKResponse({"message": {"content": "native"}}).text, "native")
        self.assertEqual(
            SDKResponse({"choices": [{"message": {"content": "openai"}}]}).text,
            "openai",
        )


if __name__ == "__main__":
    unittest.main()
