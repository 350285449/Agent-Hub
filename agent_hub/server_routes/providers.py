from __future__ import annotations


def handle_get(handler: object, path: str) -> bool:
    from .. import server as server_module

    if path == "/v1/status":
        handler._send_json(
            server_module._status_body(
                handler.server.config,
                handler.server.router,
                provider_scores=handler.server.diagnostics_service.provider_scores(),
            )
        )
        return True
    if path == "/v1/routing/status":
        handler._send_diagnostics_json(server_module._routing_status_body(handler.server.config, handler.server.router))
        return True
    if path == "/v1/routing/last-decision":
        handler._send_diagnostics_json(server_module._routing_last_decision_body(handler.server.config))
        return True
    if path == "/v1/routing/test-failover":
        handler._send_diagnostics_json(server_module._routing_test_failover_body(handler.server.config, handler.server.router))
        return True
    if path == "/v1/client-sources":
        handler._send_diagnostics_json(server_module._client_sources_body(handler.server.config, handler.server.router))
        return True
    if path == "/v1/routing-history":
        handler._send_json(server_module._routing_history_body(handler.server.config))
        return True
    if path == "/v1/provider-scores":
        handler._send_json(handler.server.diagnostics_service.provider_scores_body())
        return True
    if path == "/v1/provider-health":
        handler._send_diagnostics_json(server_module._provider_health_body(handler.server.config, handler.server.router))
        return True
    if path == "/v1/routing-memory/stats":
        handler._send_diagnostics_json(server_module._routing_memory_stats_body(handler.server.config, handler.server.router))
        return True
    if path == "/v1/routing-memory/recent":
        limit = 50
        try:
            from .middleware import request_query

            query = request_query(handler.path)
            if query.get("limit"):
                limit = max(1, min(500, int(query["limit"])))
        except (TypeError, ValueError):
            limit = 50
        handler._send_diagnostics_json(
            server_module._routing_memory_recent_body(
                handler.server.config,
                handler.server.router,
                limit=limit,
            )
        )
        return True
    if path.startswith("/v1/routing-decision/"):
        request_id = path.rsplit("/", 1)[-1]
        body = server_module._routing_decision_by_id_body(
            handler.server.config,
            handler.server.router,
            request_id,
        )
        handler._send_diagnostics_json(body)
        return True
    if path in {"/models", "/v1/models", "/api/v1/models"}:
        handler._send_json(
            {
                "object": "list",
                "data": server_module._openai_model_rows(
                    handler.server.config,
                    handler.server.router,
                    include_routing_details=handler.server.config.expose_routing_details,
                ),
            }
        )
        return True
    return False
