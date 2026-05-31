from __future__ import annotations

import unittest
from unittest.mock import patch

import agent_hub.providers as provider_facade
from agent_hub.config import AgentConfig
from agent_hub.models import HubRequest
from agent_hub.providers import (
    AnthropicMessagesProvider,
    OpenAIChatProvider,
    GeminiProvider,
    LocalResearchProvider,
    ProviderError,
    create_provider,
    provider_headers,
    _classify_provider_error,
    _join_url,
    _provider_error_from_http,
    _quota_metadata_from_headers,
)
from agent_hub.providers.errors import (
    ProviderError as ExtractedProviderError,
    provider_error_from_http,
)
from agent_hub.providers.quota import quota_metadata_from_headers
from agent_hub.providers.registry import ProviderRegistry, provider_registry_key
from agent_hub.providers.transport import post_stream_json


class ProviderTests(unittest.TestCase):
    def test_provider_facade_keeps_extracted_compatibility_shims(self) -> None:
        self.assertIs(ProviderError, ExtractedProviderError)
        self.assertIs(provider_facade.ProviderError, ExtractedProviderError)
        self.assertIs(provider_facade._provider_error_from_http, provider_error_from_http)
        self.assertIs(provider_facade._quota_metadata_from_headers, quota_metadata_from_headers)
        self.assertIs(provider_facade._post_stream_json, post_stream_json)

    def test_provider_registry_key_normalizes_provider_aliases(self) -> None:
        self.assertEqual(
            provider_registry_key(AgentConfig(name="openai", provider="chatgpt", model="m")),
            "openai-chat",
        )
        self.assertEqual(
            provider_registry_key(
                AgentConfig(
                    name="openrouter",
                    provider="openai-compatible",
                    provider_type="openrouter",
                    model="m",
                )
            ),
            "openrouter",
        )
        self.assertEqual(
            provider_registry_key(AgentConfig(name="local", provider="local-research", model="m")),
            "local-research",
        )
        self.assertEqual(
            provider_registry_key(AgentConfig(name="claude", provider="claude", model="m")),
            "anthropic",
        )
        self.assertEqual(
            provider_registry_key(AgentConfig(name="gemini", provider="gemini", model="m")),
            "gemini",
        )

    def test_provider_registry_dispatches_to_registered_factory(self) -> None:
        registry: ProviderRegistry[str] = ProviderRegistry()
        registry.register("openai-chat", lambda agent: f"chat:{agent.name}")

        provider = registry.create(AgentConfig(name="chatgpt", provider="chatgpt", model="m"))

        self.assertEqual(provider, "chat:chatgpt")

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

    def test_provider_errors_use_unlimited_routing_taxonomy(self) -> None:
        self.assertEqual(
            _classify_provider_error("rate limit exceeded", status_code=429),
            "temporary_rate_limit",
        )
        self.assertEqual(
            _classify_provider_error("context length exceeded"),
            "context_too_large",
        )
        self.assertEqual(
            _classify_provider_error("max_output_tokens is too high"),
            "output_too_large",
        )
        self.assertEqual(
            _classify_provider_error("model is temporarily overloaded", status_code=503),
            "provider_overloaded",
        )
        self.assertEqual(
            _classify_provider_error("tool use is not supported"),
            "unsupported_feature",
        )

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
        self.assertNotIn("max_tokens", payload)

    def test_output_token_limit_error_retries_with_agent_maximum(self) -> None:
        agent = AgentConfig(
            name="openai",
            provider="openai-compatible",
            model="model",
            base_url="http://127.0.0.1:9999",
            max_tokens=4096,
        )
        request = HubRequest(
            session_id="s",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=100000,
            raw={"agent_hub": {"auto_retry": True}},
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.side_effect = [
                ProviderError("max_tokens is too high", error_type="output_too_large"),
                {
                    "choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}],
                    "usage": {},
                },
            ]
            result = OpenAIChatProvider(agent).complete(request)

        self.assertEqual(result.text, "Done")
        self.assertEqual(post_json.call_args_list[0].kwargs["payload"]["max_tokens"], 100000)
        self.assertEqual(post_json.call_args_list[1].kwargs["payload"]["max_tokens"], 4096)

    def test_openai_provider_carries_protected_client_metadata_to_model(self) -> None:
        agent = AgentConfig(
            name="ollama",
            provider="openai-compatible",
            model="tool-test",
            base_url="http://127.0.0.1:11434",
        )
        request = HubRequest(
            session_id="s",
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Read the active file"}],
                    "task_progress": [{"title": "inspect"}],
                    "active_files": ["tests/test_providers.py"],
                }
            ],
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}],
                "usage": {},
            }
            OpenAIChatProvider(agent).complete(request)

        content = post_json.call_args.kwargs["payload"]["messages"][0]["content"]
        self.assertIn("Read the active file", content)
        self.assertIn("Protected client context", content)
        self.assertIn("task_progress", content)
        self.assertIn("tests/test_providers.py", content)

    def test_openai_provider_preserves_legacy_functions(self) -> None:
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
                "functions": [
                    {
                        "name": "read_file",
                        "description": "Read a workspace file.",
                        "parameters": {"type": "object"},
                    }
                ],
                "function_call": {"name": "read_file"},
            },
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}],
                "usage": {},
            }
            OpenAIChatProvider(agent).complete(request)

        payload = post_json.call_args.kwargs["payload"]
        self.assertEqual(payload["functions"][0]["name"], "read_file")
        self.assertEqual(payload["function_call"]["name"], "read_file")
        self.assertNotIn("tools", payload)

    def test_openai_provider_translates_anthropic_tools_and_results(self) -> None:
        agent = AgentConfig(
            name="ollama",
            provider="openai-compatible",
            model="tool-test",
            base_url="http://127.0.0.1:11434",
        )
        request = HubRequest(
            session_id="s",
            api_shape="anthropic-messages",
            messages=[
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "read_file",
                            "input": {"path": "README.md"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_1",
                            "content": "file text",
                        }
                    ],
                },
            ],
            raw={
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read a workspace file.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    }
                ],
                "tool_choice": {"type": "tool", "name": "read_file"},
            },
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}],
                "usage": {},
            }
            OpenAIChatProvider(agent).complete(request)

        payload = post_json.call_args.kwargs["payload"]
        self.assertEqual(payload["tools"][0]["function"]["parameters"]["properties"]["path"]["type"], "string")
        self.assertEqual(payload["tool_choice"]["function"]["name"], "read_file")
        self.assertEqual(payload["messages"][0]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(payload["messages"][1]["role"], "tool")
        self.assertEqual(payload["messages"][1]["tool_call_id"], "call_1")

    def test_anthropic_provider_translates_openai_tools_and_results(self) -> None:
        agent = AgentConfig(
            name="claude",
            provider="anthropic",
            model="claude-test",
            api_key="key",
        )
        request = HubRequest(
            session_id="s",
            api_shape="openai-chat",
            messages=[
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": "{\"path\":\"README.md\"}",
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": "file text",
                },
            ],
            raw={
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "parameters": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                            },
                        },
                    }
                ],
                "tool_choice": {"type": "function", "function": {"name": "read_file"}},
            },
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "content": [{"type": "text", "text": "Done"}],
                "usage": {},
                "stop_reason": "end_turn",
            }
            AnthropicMessagesProvider(agent).complete(request)

        payload = post_json.call_args.kwargs["payload"]
        self.assertEqual(payload["tools"][0]["input_schema"]["properties"]["path"]["type"], "string")
        self.assertEqual(payload["tool_choice"]["type"], "tool")
        self.assertEqual(payload["messages"][0]["content"][0]["type"], "tool_use")
        self.assertEqual(payload["messages"][1]["content"][0]["type"], "tool_result")

    def test_anthropic_provider_carries_protected_client_metadata_to_model(self) -> None:
        agent = AgentConfig(
            name="claude",
            provider="anthropic",
            model="claude-test",
            api_key="key",
        )
        request = HubRequest(
            session_id="s",
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Read the active file"}],
                    "task_progress": [{"title": "inspect"}],
                    "active_files": ["tests/test_providers.py"],
                }
            ],
        )

        with patch("agent_hub.providers._post_json") as post_json:
            post_json.return_value = {
                "content": [{"type": "text", "text": "Done"}],
                "usage": {},
                "stop_reason": "end_turn",
            }
            AnthropicMessagesProvider(agent).complete(request)

        content = post_json.call_args.kwargs["payload"]["messages"][0]["content"]
        self.assertEqual(content[0]["text"], "Read the active file")
        self.assertIn("Protected client context", content[1]["text"])
        self.assertIn("task_progress", content[1]["text"])

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
