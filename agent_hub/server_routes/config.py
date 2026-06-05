from __future__ import annotations

import html
import json

from .middleware import request_query


def handle_get(handler: object, path: str) -> bool:
    from .. import server as server_module

    if path in {"/", ""}:
        handler._send_html(handler._root_html())
        return True
    if path == "/dashboard":
        handler._send_html(handler._root_html())
        return True
    if path == "/dashboard/optimization":
        handler._send_html(server_module._optimization_dashboard_html(handler.server.adaptive_service.optimization_summary()))
        return True
    if path == "/dashboard/routing-intelligence":
        optimization = handler.server.adaptive_service.optimization_summary()
        intelligence = server_module._routing_intelligence_body(
            handler.server.config,
            handler.server.router,
            optimization=optimization,
        )
        handler._send_html(server_module._routing_intelligence_dashboard_html(intelligence))
        return True
    if path == "/dashboard/costs":
        body = handler.server.diagnostics_service.cost_dashboard_body(
            handler.server.adaptive_service.optimization_summary()
        )
        handler._send_html(_json_dashboard("Agent Hub Cost Dashboard", body))
        return True
    if path == "/dashboard/model-leaderboard":
        body = handler.server.diagnostics_service.model_leaderboard_body(handler.server.router)
        handler._send_html(_json_dashboard("Agent Hub Model Leaderboard", body))
        return True
    if path == "/dashboard/benchmarks":
        body = handler.server.diagnostics_service.benchmark_results_body()
        handler._send_html(_json_dashboard("Agent Hub Benchmark Results", body))
        return True
    if path == "/v1/events":
        handler._send_diagnostics_json(server_module._events_body(handler.server.config))
        return True
    if path == "/v1/optimization":
        handler._send_diagnostics_json(handler.server.adaptive_service.optimization_summary())
        return True
    if path == "/v1/cost-dashboard":
        handler._send_diagnostics_json(
            handler.server.diagnostics_service.cost_dashboard_body(
                handler.server.adaptive_service.optimization_summary()
            )
        )
        return True
    if path == "/v1/model-leaderboard":
        handler._send_diagnostics_json(
            handler.server.diagnostics_service.model_leaderboard_body(handler.server.router)
        )
        return True
    if path == "/v1/benchmarks":
        handler._send_diagnostics_json(handler.server.diagnostics_service.benchmark_results_body())
        return True
    if path == "/v1/workspace/checkpoints":
        handler._send_diagnostics_json(handler.server.diagnostics_service.workspace_checkpoints_body())
        return True
    if path == "/v1/workflow-presets":
        from ..workflows.selector import WORKFLOW_PRESETS

        handler._send_diagnostics_json(
            {"object": "agent_hub.workflow_presets", "data": WORKFLOW_PRESETS}
        )
        return True
    if path == "/v1/routing-intelligence":
        optimization = handler.server.adaptive_service.optimization_summary()
        handler._send_diagnostics_json(
            server_module._routing_intelligence_body(
                handler.server.config,
                handler.server.router,
                optimization=optimization,
            )
        )
        return True
    if path == "/v1/repository-dna":
        dna = handler.server.router.repository_intelligence.repository_dna()
        handler._send_diagnostics_json(dna.to_dict())
        return True
    if path == "/v1/workspace-memory":
        handler._send_diagnostics_json(handler.server.router.repository_intelligence.workspace_memory())
        return True
    if path == "/v1/night-mode":
        from ..repository_intelligence import build_autonomous_night_mode_plan

        dna = handler.server.router.repository_intelligence.repository_dna()
        handler._send_diagnostics_json(
            build_autonomous_night_mode_plan(dna=dna, config=handler.server.config)
        )
        return True
    if path == "/v1/tools":
        handler._send_diagnostics_json(server_module._tools_body(handler.server.router))
        return True
    if path == "/v1/workflows/status":
        handler._send_diagnostics_json(server_module._workflow_status_body(handler.server.config))
        return True
    if path == "/v1/plugins":
        handler._send_diagnostics_json(handler.server.diagnostics_service.plugins_body())
        return True
    if path == "/v1/enterprise/audit":
        handler._send_diagnostics_json(handler.server.diagnostics_service.enterprise_audit_body(request_query(handler.path)))
        return True
    return False


def _json_dashboard(title: str, body: dict[str, object]) -> str:
    payload = html.escape(json.dumps(body, indent=2, ensure_ascii=False))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;margin:0;background:#111827;color:#e5e7eb}}
header{{padding:18px 24px;border-bottom:1px solid #374151;background:#0f172a}}
main{{padding:24px;max-width:1280px;margin:auto}} pre{{white-space:pre-wrap;word-break:break-word}}
a{{color:#67e8f9}}
</style></head><body><header><strong>{html.escape(title)}</strong></header>
<main><p><a href="/dashboard">Back to Agent Hub</a></p><pre>{payload}</pre></main></body></html>"""
