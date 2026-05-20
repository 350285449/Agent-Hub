from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_hub.config import AgentConfig
from agent_hub.models import HubRequest
from agent_hub.providers import (
    GeminiProvider,
    LocalResearchProvider,
    create_provider,
    _join_url,
    _provider_error_from_http,
)


class ProviderTests(unittest.TestCase):
    def test_model_not_found_can_fail_over_to_next_agent(self) -> None:
        error = _provider_error_from_http(
            404,
            '{"error":{"message":"model not found"}}',
        )

        self.assertTrue(error.retryable)

    def test_bad_request_still_stops_routing(self) -> None:
        error = _provider_error_from_http(
            400,
            '{"error":{"message":"invalid payload"}}',
        )

        self.assertFalse(error.retryable)

    def test_openai_compatible_base_url_may_include_v1(self) -> None:
        self.assertEqual(
            _join_url("http://127.0.0.1:11434/v1", "/v1/chat/completions"),
            "http://127.0.0.1:11434/v1/chat/completions",
        )

    def test_provider_aliases_are_accepted(self) -> None:
        self.assertEqual(
            create_provider(
                AgentConfig(name="chatgpt", provider="chatgpt", model="model")
            ).__class__.__name__,
            "OpenAIChatProvider",
        )
        self.assertEqual(
            create_provider(
                AgentConfig(name="claude", provider="claude", model="model")
            ).__class__.__name__,
            "AnthropicMessagesProvider",
        )
        self.assertEqual(
            create_provider(
                AgentConfig(name="gemma", provider="gemma", model="model", base_url="http://127.0.0.1:9999")
            ).__class__.__name__,
            "OpenAIChatProvider",
        )
        self.assertEqual(
            create_provider(
                AgentConfig(name="gemini", provider="gemini", model="model")
            ).__class__.__name__,
            "GeminiProvider",
        )
        self.assertEqual(
            create_provider(
                AgentConfig(
                    name="local-research",
                    provider="local-research",
                    model="local-extractive-research",
                )
            ).__class__.__name__,
            "LocalResearchProvider",
        )

    def test_gemini_provider_translates_request_and_response(self) -> None:
        agent = AgentConfig(
            name="gemini",
            provider="gemini",
            model="gemini-test",
            api_key="key",
            max_tokens=300,
        )
        request = HubRequest(
            session_id="s",
            messages=[
                {"role": "system", "content": "Be concise"},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "Summarize"},
            ],
            temperature=0.2,
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Done"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"totalTokenCount": 10},
            }
            result = GeminiProvider(agent).complete(request)

        self.assertEqual(result.text, "Done")
        self.assertEqual(result.usage["totalTokenCount"], 10)
        payload = post_json.call_args.kwargs["payload"]
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertEqual(payload["contents"][1]["role"], "model")
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Be concise")
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 300)
        self.assertEqual(payload["generationConfig"]["temperature"], 0.2)
        self.assertTrue(
            post_json.call_args.kwargs["url"].endswith(
                "/v1beta/models/gemini-test:generateContent"
            )
        )

    def test_local_research_provider_builds_cited_answer(self) -> None:
        agent = AgentConfig(
            name="local-research",
            provider="local-research",
            model="local-extractive-research",
        )
        request = HubRequest(
            session_id="s",
            messages=[{"role": "user", "content": "latest AI news"}],
            raw={"query": "AI news", "max_sources": 1},
        )

        with (
            patch("agent_hub.providers._search_with_duckduckgo") as search,
            patch("agent_hub.providers._get_url_text") as get_url_text,
        ):
            search.return_value = [
                {"title": "AI source", "url": "https://example.com/a", "snippet": ""}
            ]
            get_url_text.return_value = (
                "text/html",
                "<html><body><p>AI news today focuses on local models and open tooling.</p></body></html>",
            )
            result = LocalResearchProvider(agent).complete(request)

        self.assertIn("Local research for: AI news", result.text)
        self.assertIn("AI news today", result.text)
        self.assertEqual(result.citations, ["https://example.com/a"])
        self.assertEqual(result.search_results[0]["title"], "AI source")
        search.assert_called_once()
        get_url_text.assert_called_once()


if __name__ == "__main__":
    unittest.main()
