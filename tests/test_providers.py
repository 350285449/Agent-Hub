from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_hub.config import AgentConfig
from agent_hub.models import HubRequest
from agent_hub.providers import (
    OpenAIChatProvider,
    GeminiProvider,
    LocalResearchProvider,
    create_provider,
    provider_headers,
    _join_url,
    _provider_error_from_http,
    _quota_metadata_from_headers,
)


class ProviderTests(unittest.TestCase):
    def test_model_not_found_can_fail_over_to_next_agent(self) -> None:
        error = _provider_error_from_http(
            404,
            '{"error":{"message":"model not found"}}',
        )

        self.assertTrue(error.retryable)

    def test_free_tier_quota_errors_are_classified_for_cooldown(self) -> None:
        error = _provider_error_from_http(
            429,
            '{"error":{"message":"Free tier usage limit reached"}}',
            headers={"Retry-After": "42", "X-RateLimit-Remaining-Requests": "0"},
        )

        self.assertTrue(error.retryable)
        self.assertEqual(error.error_type, "quota_exhausted")
        self.assertEqual(error.cooldown_seconds, 42)
        self.assertEqual(error.metadata["requests_remaining"], 0)

    def test_quota_metadata_is_normalized_from_headers(self) -> None:
        metadata = _quota_metadata_from_headers(
            {
                "X-RateLimit-Remaining-Requests": "12",
                "X-RateLimit-Remaining-Tokens": "3456",
                "X-Credits-Remaining": "7.5",
                "Retry-After": "3",
            }
        )

        self.assertEqual(metadata["requests_remaining"], 12)
        self.assertEqual(metadata["tokens_remaining"], 3456)
        self.assertEqual(metadata["credits_remaining"], 7.5)
        self.assertEqual(metadata["cooldown_seconds"], 3)

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

    def test_openai_compatible_cloud_provider_headers_are_created(self) -> None:
        agent = AgentConfig(
            name="openrouter-free",
            provider="openai-compatible",
            provider_type="openrouter",
            model="deepseek/deepseek-r1:free",
            api_key="key",
            headers={"X-Title": "Custom Hub"},
        )

        headers = provider_headers(agent, agent.resolved_api_key)

        self.assertEqual(headers["Authorization"], "Bearer key")
        self.assertEqual(headers["X-Title"], "Custom Hub")
        self.assertIn("HTTP-Referer", headers)

    def test_github_models_uses_provider_specific_chat_path(self) -> None:
        agent = AgentConfig(
            name="github-model",
            provider="openai-compatible",
            provider_type="github-models",
            model="qwen/qwen3-coder",
            api_key="ghp_key",
            base_url="https://models.github.ai/inference",
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
            OpenAIChatProvider(agent).complete(request)

        self.assertEqual(
            post_json.call_args.kwargs["url"],
            "https://models.github.ai/inference/chat/completions",
        )
        headers = post_json.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer ghp_key")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")

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

    def test_openai_provider_translates_agent_hub_tools(self) -> None:
        agent = AgentConfig(
            name="ollama",
            provider="openai-compatible",
            model="tool-test",
            base_url="http://127.0.0.1:11434",
        )
        request = HubRequest(
            session_id="s",
            messages=[{"role": "user", "content": "Read a file"}],
            raw={
                "agent_hub_tools": [
                    {
                        "name": "read_file",
                        "description": "Read a workspace file.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    }
                ]
            },
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}],
                "usage": {},
            }
            OpenAIChatProvider(agent).complete(request)

        payload = post_json.call_args.kwargs["payload"]
        self.assertEqual(payload["tools"][0]["type"], "function")
        self.assertEqual(payload["tools"][0]["function"]["name"], "read_file")
        self.assertEqual(payload["tool_choice"], "auto")

    def test_gemini_provider_translates_agent_hub_tools(self) -> None:
        agent = AgentConfig(
            name="gemini",
            provider="gemini",
            model="gemini-test",
            api_key="key",
        )
        request = HubRequest(
            session_id="s",
            messages=[{"role": "user", "content": "Read a file"}],
            raw={
                "agent_hub_tools": [
                    {
                        "name": "read_file",
                        "description": "Read a workspace file.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    }
                ]
            },
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "candidates": [{"content": {"parts": [{"text": "Done"}]}}],
                "usageMetadata": {},
            }
            GeminiProvider(agent).complete(request)

        declaration = post_json.call_args.kwargs["payload"]["tools"][0]["functionDeclarations"][0]
        self.assertEqual(declaration["name"], "read_file")
        self.assertEqual(declaration["parameters"]["type"], "OBJECT")
        self.assertEqual(declaration["parameters"]["properties"]["path"]["type"], "STRING")

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
