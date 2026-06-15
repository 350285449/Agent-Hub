from __future__ import annotations

import ast
import importlib
import json
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent_hub.config import AgentConfig, HubConfig, RouteRule
from agent_hub.core.router import AgentRouter
from agent_hub.models import HubResponse
from agent_hub.payloads import (
    anthropic_message_response,
    anthropic_stream_events,
    openai_chat_response,
    openai_response_response,
    openai_response_stream_events,
    openai_stream_events,
)
from agent_hub.server import _openai_model_rows


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "agent_hub"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "phase0_api_compat.json"

KNOWN_DEPENDENCY_CYCLES = {
    frozenset({"agent_hub.config", "agent_hub.discovery"}),
    frozenset(
        {
            "agent_hub.providers.__init__",
            "agent_hub.providers.groq",
            "agent_hub.providers.ollama",
            "agent_hub.providers.openrouter",
        }
    ),
}

FAN_OUT_BASELINE = {
    "agent_hub.core.router": 23,
    "agent_hub.server": 19,
    "agent_hub.cli": 15,
    "agent_hub.providers.__init__": 10,
}

FAN_OUT_EXEMPT_EDGES = {
    "agent_hub.core.router": {
        "agent_hub.core.routing.selection",
    },
    "agent_hub.core.routing.selection": {
        "agent_hub.capabilities",
        "agent_hub.core.router_diagnostics",
        "agent_hub.core.routing_policy",
    },
    "agent_hub.server": {
        "agent_hub.server_routes.__init__",
        "agent_hub.server_routes.chat",
        "agent_hub.server_routes.diagnostics",
        "agent_hub.server_routes.middleware",
    },
    "agent_hub.providers.__init__": {
        "agent_hub.providers.errors",
        "agent_hub.providers.quota",
        "agent_hub.providers.registry",
        "agent_hub.providers.transport",
    },
}

DOMAIN_CANDIDATE_MODULES = {
    "agent_hub.capabilities",
    "agent_hub.models",
    "agent_hub.reasoning",
    "agent_hub.context",
    "agent_hub.core.context",
}

DOMAIN_FORBIDDEN_PREFIXES = (
    "agent_hub.agent_tools",
    "agent_hub.observability",
    "agent_hub.permissions",
    "agent_hub.providers",
    "agent_hub.security",
    "agent_hub.server",
    "agent_hub.tools",
)

PUBLIC_IMPORTS = {
    "agent_hub": [
        "AgentConfig",
        "AgentRunner",
        "AgentRouter",
        "HubConfig",
        "HubRequest",
        "HubResponse",
        "ProviderResult",
        "RouteRule",
        "TeamAgentRunner",
        "backend_version",
        "load_config",
    ],
    "agent_hub.router": [
        "AgentRouter",
        "RoutingDecision",
        "RouterError",
        "NO_TOOL_CAPABLE_MODEL",
        "estimate_input_tokens",
        "expected_output_tokens",
    ],
    "agent_hub.providers": [
        "CONFORMANCE_DIMENSIONS",
        "Provider",
        "ProviderError",
        "ProviderCapabilities",
        "ProviderDescriptor",
        "ProviderPricing",
        "OpenAIChatProvider",
        "LocalResearchProvider",
        "AnthropicMessagesProvider",
        "GeminiProvider",
        "SimpleOpenAICompatibleProvider",
        "builtin_provider_descriptors",
        "create_provider",
        "descriptor_from_metadata",
        "provider_conformance_report",
    ],
    "agent_hub.providers.sdk": [
        "CONFORMANCE_DIMENSIONS",
        "ProviderAdapter",
        "ProviderCapabilities",
        "ProviderDescriptor",
        "ProviderPricing",
        "SimpleOpenAICompatibleProvider",
        "builtin_provider_descriptors",
        "descriptor_from_metadata",
        "provider_conformance_report",
    ],
    "agent_hub.providers.base": [
        "ProviderAdapter",
        "BaseProviderAdapter",
        "ChatRequest",
        "ChatResponse",
        "StreamChunk",
    ],
    "agent_hub.tools": [
        "Tool",
        "ToolCall",
        "ToolExecutionContext",
        "ToolExecutionPipeline",
        "ToolLoopMetadata",
        "ToolLoopRunner",
        "ToolRegistry",
        "ToolResult",
        "create_builtin_registry",
        "extract_tool_calls",
        "openai_tool_specs",
    ],
    "agent_hub.workflows": [
        "WorkflowEngine",
        "WorkflowEventRecorder",
        "WorkflowEventSink",
        "WorkflowMemory",
        "WorkflowPlanner",
        "WorkflowResult",
        "WorkflowStage",
        "WorkflowStageResult",
        "WorkflowState",
        "WorkflowExtensionPoints",
    ],
    "agent_hub.api.openai_compat": [
        "openai_chat_response",
        "openai_response_response",
        "openai_response_stream_events",
        "openai_stream_events",
        "request_from_openai_chat",
        "request_from_openai_responses",
    ],
    "agent_hub.api.server": [
        "AgentHubHTTPServer",
        "AgentHubHandler",
        "serve",
    ],
    "agent_hub.api.compatibility": [
        "CompatibilityEndpoint",
        "apply_model_routing",
        "anthropic_sse_frames",
        "available_model_ids",
        "compatibility_endpoint",
        "debug_api_shape",
        "model_rows",
        "model_lookup_error",
        "openai_chat_sse_frames",
        "openai_model_rows",
        "openai_response_sse_frames",
        "request_from_compat_payload",
        "response_headers",
        "response_for_shape",
        "sse_data_frame",
        "sse_named_event_frame",
        "stream_response_headers",
    ],
    "agent_hub.capabilities": [
        "AgentCapabilities",
        "agent_capabilities",
        "agent_supports_tools",
    ],
    "agent_hub.core.routing_policy": [
        "RouterPreflightPolicy",
        "estimate_input_tokens",
        "expected_output_tokens",
    ],
    "agent_hub.core.router_diagnostics": [
        "build_capability_graph",
        "build_provider_status",
    ],
    "agent_hub.core.routing.selection": [
        "AgentRouter",
        "RoutingDecision",
        "RouterError",
    ],
    "agent_hub.core.routing.fallback": [
        "RouterError",
        "_no_fallback_reason",
        "_route_error_type",
    ],
    "agent_hub.core.routing.policies": [
        "RouterPreflightPolicy",
        "estimate_input_tokens",
        "expected_output_tokens",
    ],
    "agent_hub.core.routing.provider_status": [
        "ProviderHealth",
        "ProviderHealthTracker",
    ],
    "agent_hub.core.routing.scoring": [
        "RoutingDecision",
        "_recommendation_reason",
    ],
    "agent_hub.core.provider_attempts": [
        "ProviderAttemptExecutor",
        "ProviderAttemptHelpers",
    ],
    "agent_hub.events": [
        "RouterEventRecorder",
        "record_internal_event",
        "request_event_context",
        "request_source",
    ],
    "agent_hub.security.provider_permissions": [
        "ProviderPermissionPolicy",
    ],
    "agent_hub.workflows.events": [
        "WorkflowEventRecorder",
        "WorkflowEventSink",
    ],
    "agent_hub.workflows.planning": [
        "WorkflowPlanner",
        "WorkflowStage",
    ],
}

PROVIDER_ADAPTER_CONTRACT = {
    "chat",
    "stream",
    "health_check",
    "supports_streaming",
    "supports_tools",
    "supports_vision",
    "context_limit",
    "cost_estimate",
    "normalize_request",
    "normalize_response",
}


class ArchitectureGuardrailTests(unittest.TestCase):
    def test_public_imports_remain_available(self) -> None:
        for module_name, names in PUBLIC_IMPORTS.items():
            module = importlib.import_module(module_name)
            missing = [name for name in names if not hasattr(module, name)]
            self.assertEqual(missing, [], module_name)

    def test_provider_adapter_contract_surface_is_stable(self) -> None:
        from agent_hub.providers.base import BaseProviderAdapter, ProviderAdapter

        for name in sorted(PROVIDER_ADAPTER_CONTRACT):
            self.assertTrue(hasattr(ProviderAdapter, name), name)
            self.assertTrue(hasattr(BaseProviderAdapter, name), name)

    def test_compatibility_endpoints_remain_registered(self) -> None:
        fixture = _fixture()
        server_text = (PACKAGE_ROOT / "server.py").read_text(encoding="utf-8")
        expected = fixture["compatibility_endpoints"] + fixture["diagnostic_endpoints"]
        missing = [endpoint for endpoint in expected if endpoint not in server_text]

        self.assertEqual(missing, [])

    def test_dependency_cycles_do_not_grow_beyond_phase0_baseline(self) -> None:
        graph = _internal_import_graph()
        cycles = {
            frozenset(component)
            for component in _strongly_connected_components(graph)
            if len(component) > 1
        }
        unexpected = cycles - KNOWN_DEPENDENCY_CYCLES

        self.assertEqual(unexpected, set())

    def test_high_risk_module_fan_out_does_not_exceed_phase0_baseline(self) -> None:
        graph = _internal_import_graph()
        too_many = {
            module: len(_counted_fan_out(graph, module))
            for module, maximum in FAN_OUT_BASELINE.items()
            if len(_counted_fan_out(graph, module)) > maximum
        }

        self.assertEqual(too_many, {})

    def test_architecture_roadmap_tracks_current_large_modules_and_plugin_maturity(self) -> None:
        roadmap = (ROOT / "docs" / "platform-architecture-roadmap.md").read_text(encoding="utf-8")
        large_modules = _largest_python_modules(limit=5)
        missing = [
            path.replace("\\", "/")
            for path, _lines in large_modules
            if path.replace("\\", "/") not in roadmap
        ]

        self.assertEqual(missing, [])
        self.assertIn("policy-gated local-process execution foundation", roadmap)
        self.assertIn("capability-inventory", roadmap)
        self.assertNotIn("Plugins do not execute code", roadmap)

    def test_domain_candidate_modules_do_not_import_infrastructure(self) -> None:
        graph = _internal_import_graph()
        violations: dict[str, list[str]] = {}
        for module in sorted(DOMAIN_CANDIDATE_MODULES):
            deps = graph.get(module, set())
            forbidden = [
                dep
                for dep in sorted(deps)
                if dep.startswith(DOMAIN_FORBIDDEN_PREFIXES)
            ]
            if forbidden:
                violations[module] = forbidden

        self.assertEqual(violations, {})

    def test_router_provider_permissions_flow_through_security_boundary(self) -> None:
        graph = _internal_import_graph()
        router_deps = graph.get("agent_hub.core.routing.selection", set())
        forbidden = {
            "agent_hub.enterprise",
            "agent_hub.permissions",
            "agent_hub.security.audit",
        }

        self.assertIn("agent_hub.security.provider_permissions", router_deps)
        self.assertEqual(router_deps & forbidden, set())

    def test_router_observability_flows_through_event_recorder(self) -> None:
        graph = _internal_import_graph()
        router_deps = graph.get("agent_hub.core.routing.selection", set())

        self.assertIn("agent_hub.events", router_deps)
        self.assertNotIn("agent_hub.observability", router_deps)

    def test_workflow_execution_uses_planning_and_event_boundaries(self) -> None:
        graph = _internal_import_graph()
        workflow_deps = graph.get("agent_hub.workflows.engine", set())

        self.assertIn("agent_hub.workflows.planning", workflow_deps)
        self.assertIn("agent_hub.workflows.events", workflow_deps)
        self.assertNotIn("agent_hub.observability", workflow_deps)

    def test_server_api_compatibility_flows_through_compatibility_layer(self) -> None:
        graph = _internal_import_graph()
        server_deps = graph.get("agent_hub.server", set())
        server_text = (PACKAGE_ROOT / "server.py").read_text(encoding="utf-8")

        self.assertIn("agent_hub.api.compatibility", server_deps)
        self.assertNotIn("agent_hub.payloads", server_deps)
        self.assertIn("openai_chat_sse_frames", server_text)
        self.assertIn("anthropic_sse_frames", server_text)
        self.assertIn("openai_response_sse_frames", server_text)
        self.assertNotIn("openai_stream_events(", server_text)
        self.assertNotIn("anthropic_stream_events(", server_text)
        self.assertNotIn("openai_response_stream_events(", server_text)

    def test_api_compatibility_fixture_shapes_match_payload_helpers(self) -> None:
        fixture = _fixture()
        response = _fixture_response(text="hello")

        openai = openai_chat_response(response)
        openai_events = openai_stream_events(response)
        responses = openai_response_response(response)
        response_events = openai_response_stream_events(response)
        anthropic = anthropic_message_response(response)
        anthropic_events = anthropic_stream_events(response)
        models = {
            "object": "list",
            "data": _openai_model_rows(_fixture_config(), AgentRouter(_fixture_config())),
        }

        self.assertEqual(sorted(openai), fixture["openai_chat_success_keys"])
        self.assertEqual(sorted(openai["choices"][0]), fixture["openai_chat_choice_keys"])
        self.assertEqual(
            [openai_events[0]["object"], openai_events[-1]],
            fixture["openai_chat_stream_objects"],
        )
        self.assertEqual(sorted(responses), fixture["openai_responses_success_keys"])
        self.assertEqual(
            [
                item if isinstance(item, str) else item["type"]
                for item in response_events
            ],
            fixture["openai_responses_stream_events"],
        )
        self.assertEqual(sorted(anthropic), fixture["anthropic_message_success_keys"])
        self.assertEqual(
            [name for name, _ in anthropic_events],
            fixture["anthropic_stream_events"],
        )
        self.assertEqual(sorted(models), fixture["model_list_keys"])
        self.assertTrue(models["data"])
        for row in models["data"]:
            self.assertTrue(set(fixture["model_row_keys"]).issubset(row))

    def test_tool_call_fixture_shapes_remain_compatible(self) -> None:
        response = _fixture_response(
            text="",
            raw={
                "choices": [
                    {
                        "message": {
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
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            finish_reason="tool_calls",
        )

        openai = openai_chat_response(response)
        anthropic = anthropic_message_response(response)
        responses = openai_response_response(response)

        self.assertIsNone(openai["choices"][0]["message"]["content"])
        self.assertEqual(
            openai["choices"][0]["message"]["tool_calls"][0]["function"]["name"],
            "read_file",
        )
        self.assertEqual(anthropic["content"][0]["type"], "tool_use")
        self.assertEqual(anthropic["content"][0]["name"], "read_file")
        self.assertEqual(responses["output"][0]["type"], "function_call")
        self.assertEqual(responses["output"][0]["name"], "read_file")


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_response(
    *,
    text: str,
    raw: dict[str, Any] | None = None,
    finish_reason: str | None = "stop",
) -> HubResponse:
    return HubResponse(
        request_id="hub-phase0",
        session_id="phase0",
        agent="tooly",
        provider="openai-compatible",
        model="tool-model",
        public_model="agent-hub-coding",
        text=text,
        raw=raw or {},
        usage={"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        finish_reason=finish_reason,
    )


def _fixture_config() -> HubConfig:
    return HubConfig(
        default_route=["tooly"],
        routes=[
            RouteRule(name="coding", agents=["tooly"]),
            RouteRule(name="cloud-agent", agents=["tooly"]),
            RouteRule(name="local-agent", agents=["tooly"]),
        ],
        agents={
            "tooly": AgentConfig(
                name="tooly",
                provider="openai-compatible",
                model="tool-model",
                base_url="http://127.0.0.1:9999",
                free=True,
                enabled=True,
                supports_tools=True,
                supports_function_calling=True,
            )
        },
    )


def _internal_import_graph() -> dict[str, set[str]]:
    modules = _module_paths()
    packages = _package_modules(modules)
    graph: dict[str, set[str]] = {module: set() for module in modules}

    for module, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for raw_target in _import_targets(module, node):
                if not _is_internal(raw_target):
                    continue
                target = _resolve_known_module(raw_target, modules, packages)
                if target is not None and target != module:
                    graph[module].add(target)
    return graph


def _counted_fan_out(graph: dict[str, set[str]], module: str) -> set[str]:
    return graph.get(module, set()) - FAN_OUT_EXEMPT_EDGES.get(module, set())


def _module_paths() -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for path in PACKAGE_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT).with_suffix("")
        paths[".".join(relative.parts)] = path
    return paths


def _largest_python_modules(*, limit: int) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = str(path.relative_to(ROOT))
        lines = len(path.read_text(encoding="utf-8").splitlines())
        rows.append((relative, lines))
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows[:limit]


def _package_modules(modules: dict[str, Path]) -> set[str]:
    return {
        module.removesuffix(".__init__")
        for module in modules
        if module.endswith(".__init__")
    }


def _import_targets(module: str, node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [_resolve_import_from(module, node.level, node.module)]
    return []


def _resolve_import_from(module: str, level: int, imported: str | None) -> str:
    if level == 0:
        return imported or ""
    package_parts = module.split(".")[:-1]
    base = package_parts[: len(package_parts) - level + 1]
    if imported:
        return ".".join(base + imported.split("."))
    return ".".join(base)


def _is_internal(target: str) -> bool:
    return target == "agent_hub" or target.startswith("agent_hub.")


def _resolve_known_module(
    target: str,
    modules: dict[str, Path],
    packages: set[str],
) -> str | None:
    if target in modules:
        return target
    if target in packages:
        return f"{target}.__init__"
    parts = target.split(".")
    while len(parts) > 1:
        parts.pop()
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        if candidate in packages:
            return f"{candidate}.__init__"
    return None


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target in graph.get(node, set()):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                target = stack.pop()
                on_stack.remove(target)
                component.append(target)
                if target == node:
                    break
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return components


if __name__ == "__main__":
    unittest.main()
