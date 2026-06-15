from __future__ import annotations

from typing import Any

from .version import backend_version


def openapi_spec() -> dict[str, Any]:
    """Minimal OpenAPI surface for stable public Agent-Hub endpoints."""

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Agent-Hub Local API",
            "version": backend_version(),
            "description": "Local AI routing, compatibility, diagnostics, proof, and workspace control APIs.",
        },
        "servers": [{"url": "http://127.0.0.1:8787"}],
        "paths": {
            "/v1/chat/completions": _post_path("OpenAI-compatible routed chat completions."),
            "/v1/responses": _post_path("OpenAI Responses-compatible routed requests."),
            "/v1/messages": _post_path("Anthropic Messages-compatible routed requests."),
            "/api/v1/chat/completions": _post_path("OpenRouter-style chat completions compatibility path."),
            "/v1/agent": _post_path("Native workspace-agent request."),
            "/v1/auto": _post_path("Auto workflow selection and execution."),
            "/v1/route": _post_path("Single routed provider call."),
            "/v1/agents": {
                "get": _get_path("List configured runtime agents.")["get"],
                "post": _post_path("Create a runtime-local custom agent.")["post"],
            },
            "/v1/agents/{name}": {
                "get": _get_path("Get one configured runtime agent.")["get"],
                "post": _post_path("Update one runtime-local custom agent.")["post"],
                "delete": _delete_path("Delete one runtime-local custom agent."),
                "parameters": [
                    {
                        "name": "name",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
            "/v1/routing/simulate": _post_path("Dry-run workflow and route simulation without provider calls."),
            "/v1/routing-strategies": _get_path("List built-in routing strategy descriptors and explanations."),
            "/v1/routing-profiles": {
                "get": _get_path("List universal routing profiles.")["get"],
                "post": _post_path("Create a local routing profile.")["post"],
            },
            "/v1/routing-profiles/{id}": {
                "get": _get_path("Get one routing profile.")["get"],
                "post": _post_path("Update one local routing profile.")["post"],
                "delete": _delete_path("Delete one local routing profile."),
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
            "/v1/feedback": _post_path("Submit structured route/workflow feedback."),
            "/v1/token-pools/simulate": _post_path("Dry-run user-owned quota token-pool selection without provider calls."),
            "/v1/swarms/simulate": _post_path("Build and validate a bounded dry-run swarm plan."),
            "/v1/workflow-presets": _get_path("List built-in and local workflow templates."),
            "/v1/workflow-templates": {
                "get": _get_path("List built-in and local workflow templates.")["get"],
                "post": _post_path("Create a local workflow template.")["post"],
            },
            "/v1/workflow-templates/{id}": {
                "get": _get_path("Get one workflow template.")["get"],
                "post": _post_path("Update one local workflow template.")["post"],
                "delete": _delete_path("Delete one local workflow template."),
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
            "/v1/models": _get_path("OpenAI-compatible model and route alias catalog."),
            "/v1/readiness": _get_path("Setup, contract, and runtime readiness scorecard."),
            "/v1/feature-scorecard": _get_path("Local implementation feature scorecard."),
            "/v1/production-check": _get_path("Strict production-readiness checks."),
            "/v1/status": _get_path("Backend status and routing summary."),
            "/v1/routing-intelligence": _get_path("Latest routing explanation and candidate diagnostics."),
            "/v1/provider-health": _get_path("Provider health, cooldown, quota, and capability status."),
            "/v1/model-leaderboard": _get_path("Model leaderboard from measured and baseline evidence."),
            "/v1/cost-dashboard": _get_path("Cost and usage dashboard data."),
            "/v1/observability/export": _get_path("Combined observability export catalog, OTLP spans, and Prometheus lines."),
            "/v1/observability/otlp": _get_path("OTLP-style JSON spans for recent Agent-Hub events."),
            "/v1/observability/prometheus": _get_path("Prometheus text format returned as JSON lines/text fields."),
            "/v1/analytics/compact": _post_path("Run analytics retention and compaction immediately."),
            "/v1/benchmarks": _get_path("Benchmark report inventory and proof dashboard data."),
            "/v1/plugins": _get_path("Plugin discovery, capability inventory, and execution policy."),
            "/v1/mcp/status": _get_path("MCP server/tool inventory and execution policy."),
            "/v1/extension-contract": _get_path("Backend feature contract consumed by the VS Code extension."),
            "/openapi.json": _get_path("OpenAPI 3.1 document for the Agent-Hub local API."),
        },
        "x-agent-hub-sdk": {
            "python": "agent_hub.sdk.AgentHubClient",
            "typescript": "sdk/typescript/src/index.ts",
            "library_mode": "from agent_hub import AgentHub",
        },
        "components": {
            "securitySchemes": {
                "AgentHubToken": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Required on public binds and local authenticated servers.",
                }
            },
            "schemas": {
                "GenericObject": {"type": "object", "additionalProperties": True},
                "Error": {
                    "type": "object",
                    "properties": {
                        "error": {"oneOf": [{"type": "string"}, {"type": "object"}]},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "security": [{"AgentHubToken": []}],
    }


def _get_path(summary: str) -> dict[str, Any]:
    return {
        "get": {
            "summary": summary,
            "responses": {
                "200": {
                    "description": "Successful response.",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/GenericObject"}}},
                }
            },
        }
    }


def _post_path(summary: str) -> dict[str, Any]:
    return {
        "post": {
            "summary": summary,
            "requestBody": {
                "required": False,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/GenericObject"}}},
            },
            "responses": {
                "200": {
                    "description": "Successful response.",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/GenericObject"}}},
                },
                "400": {
                    "description": "Invalid request.",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                },
            },
        }
    }


def _delete_path(summary: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "responses": {
            "200": {
                "description": "Successful response.",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/GenericObject"}}},
            },
            "404": {
                "description": "Not found.",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
            },
        },
    }


__all__ = ["openapi_spec"]
