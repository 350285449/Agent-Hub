from __future__ import annotations

from datetime import datetime
import html
import json
from typing import Any

from .middleware import request_query
from ..learning_proof import learning_dashboard_body
from ..measurement import usage_ledger_summary
from ..observability import usage_snapshot
from ..openapi import openapi_spec


def handle_get(handler: object, path: str) -> bool:
    from .. import server as server_module

    if path in {"/", ""}:
        handler._send_html(handler._root_html())
        return True
    if path == "/dashboard":
        handler._send_html(handler._root_html())
        return True
    if path == "/openapi.json":
        handler._send_cached_diagnostics_json("GET /openapi.json", openapi_spec)
        return True
    if path == "/dashboard/kernel":
        body = handler.server.runtime_kernel.snapshot(
            config=handler.server.config,
            router=handler.server.router,
            diagnostics_cache=handler.server.diagnostics_cache_stats(),
        )
        handler._send_html(_kernel_dashboard_html(body))
        return True
    if path == "/dashboard/optimization":
        handler._send_html(server_module._optimization_dashboard_html(handler.server.adaptive_service.optimization_summary()))
        return True
    if path == "/dashboard/learning":
        body = learning_dashboard_body(handler.server.config, handler.server.router)
        handler._send_html(_learning_dashboard_html(body))
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
        handler._send_html(_cost_dashboard_html(body))
        return True
    if path == "/dashboard/model-leaderboard":
        body = handler.server.diagnostics_service.model_leaderboard_body(handler.server.router)
        handler._send_html(_model_leaderboard_dashboard_html(body))
        return True
    if path == "/dashboard/benchmarks":
        body = handler.server.diagnostics_service.benchmark_results_body()
        handler._send_html(_benchmark_results_dashboard_html(body))
        return True
    if path == "/dashboard/proof":
        body = handler.server.diagnostics_service.proof_dashboard_body()
        handler._send_html(_proof_dashboard_html(body))
        return True
    if path == "/dashboard/status":
        body = server_module._status_body(
            handler.server.config,
            handler.server.router,
            provider_scores=handler.server.diagnostics_service.provider_scores(),
        )
        handler._send_html(_status_dashboard_html(body))
        return True
    if path == "/dashboard/provider-health":
        body = server_module._provider_health_body(handler.server.config, handler.server.router)
        handler._send_html(_provider_health_dashboard_html(body))
        return True
    if path == "/dashboard/system-health":
        from .health import _system_health_body

        handler._send_html(_system_health_dashboard_html(_system_health_body(handler)))
        return True
    if path == "/dashboard/production-check":
        body = handler.server.diagnostics_service.production_check_body(handler.server.router)
        handler._send_html(_production_check_dashboard_html(body))
        return True
    if path == "/dashboard/feature-scorecard":
        body = handler.server.diagnostics_service.feature_scorecard_body(handler.server.router)
        handler._send_html(_feature_scorecard_dashboard_html(body))
        return True
    if path == "/dashboard/limits":
        body = handler.server.diagnostics_service.limits_body(handler.server.router)
        handler._send_html(_limits_dashboard_html(body))
        return True
    if path == "/dashboard/usage":
        body = usage_snapshot(
            handler.server.config.state_dir,
            handler.server.router.health_snapshot(include_history=True),
        )
        body["usage_ledger"] = usage_ledger_summary(handler.server.config)
        handler._send_html(_usage_dashboard_html(body))
        return True
    if path == "/dashboard/events":
        body = server_module._events_body(handler.server.config)
        handler._send_html(_events_dashboard_html(body))
        return True
    if path == "/dashboard/tools":
        body = server_module._tools_body(handler.server.router)
        handler._send_html(_tools_dashboard_html(body))
        return True
    if path == "/dashboard/workflows":
        body = server_module._workflow_status_body(handler.server.config)
        handler._send_html(_workflows_dashboard_html(body))
        return True
    if path == "/dashboard/plugins":
        body = handler.server.diagnostics_service.plugins_body()
        handler._send_html(_plugins_dashboard_html(body))
        return True
    if path == "/dashboard/mcp":
        body = handler.server.diagnostics_service.mcp_status_body()
        handler._send_html(_mcp_dashboard_html(body))
        return True
    if path == "/dashboard/extension-contract":
        body = handler.server.diagnostics_service.extension_contract_body()
        handler._send_html(_extension_contract_dashboard_html(body))
        return True
    if path == "/dashboard/enterprise":
        body = handler.server.diagnostics_service.enterprise_status_body()
        handler._send_html(_enterprise_dashboard_html(body))
        return True
    if path == "/dashboard/provider-scores":
        body = handler.server.diagnostics_service.provider_scores_body()
        handler._send_html(_provider_scores_dashboard_html(body))
        return True
    if path == "/dashboard/routing-history":
        body = server_module._routing_history_body(handler.server.config)
        handler._send_html(_routing_history_dashboard_html(body))
        return True
    if path == "/dashboard/readiness":
        body = handler.server.diagnostics_service.readiness_body(handler.server.router)
        handler._send_html(_readiness_dashboard_html(body))
        return True
    if path == "/dashboard/repository-dna":
        dna = handler.server.router.repository_intelligence.repository_dna()
        body = dna.to_dict()
        handler._send_html(_repository_dna_dashboard_html(body))
        return True
    if path == "/dashboard/workspace-memory":
        body = handler.server.router.repository_intelligence.workspace_memory()
        handler._send_html(_workspace_memory_dashboard_html(body))
        return True
    if path == "/dashboard/night-mode":
        from ..repository_intelligence import build_autonomous_night_mode_plan

        dna = handler.server.router.repository_intelligence.repository_dna()
        body = build_autonomous_night_mode_plan(dna=dna, config=handler.server.config)
        handler._send_html(_night_mode_dashboard_html(body))
        return True
    if path == "/dashboard/inbox":
        body = handler.server.diagnostics_service.inbox_status_body()
        handler._send_html(_inbox_dashboard_html(body))
        return True
    if path == "/v1/kernel":
        handler._send_diagnostics_json(
            handler.server.runtime_kernel.snapshot(
                config=handler.server.config,
                router=handler.server.router,
                diagnostics_cache=handler.server.diagnostics_cache_stats(),
            )
        )
        return True
    if path == "/v1/events":
        handler._send_cached_diagnostics_json(
            "GET /v1/events",
            lambda: server_module._events_body(handler.server.config),
        )
        return True
    if path == "/v1/optimization":
        handler._send_cached_diagnostics_json(
            "GET /v1/optimization",
            lambda: handler.server.adaptive_service.optimization_summary(),
        )
        return True
    if path == "/v1/learning":
        handler._send_cached_diagnostics_json(
            "GET /v1/learning",
            lambda: learning_dashboard_body(handler.server.config, handler.server.router),
        )
        return True
    if path == "/v1/route-history":
        from ..learning_proof import route_history_body

        handler._send_cached_diagnostics_json(
            "GET /v1/route-history",
            lambda: route_history_body(handler.server.config),
        )
        return True
    if path == "/v1/cost-dashboard":
        handler._send_cached_diagnostics_json(
            "GET /v1/cost-dashboard",
            lambda: handler.server.diagnostics_service.cost_dashboard_body(
                handler.server.adaptive_service.optimization_summary()
            ),
        )
        return True
    if path == "/v1/model-leaderboard":
        handler._send_cached_diagnostics_json(
            "GET /v1/model-leaderboard",
            lambda: handler.server.diagnostics_service.model_leaderboard_body(handler.server.router),
        )
        return True
    if path == "/v1/benchmarks":
        handler._send_cached_diagnostics_json(
            "GET /v1/benchmarks",
            lambda: handler.server.diagnostics_service.benchmark_results_body(),
        )
        return True
    if path == "/api/benchmarks":
        handler._send_cached_diagnostics_json(
            "GET /api/benchmarks",
            lambda: handler.server.diagnostics_service.benchmark_results_body(),
        )
        return True
    if path in {"/v1/proof-dashboard", "/api/proof-dashboard"}:
        handler._send_cached_diagnostics_json(
            f"GET {path}",
            lambda: handler.server.diagnostics_service.proof_dashboard_body(),
        )
        return True
    if path == "/v1/workspace/checkpoints":
        handler._send_cached_diagnostics_json(
            "GET /v1/workspace/checkpoints",
            lambda: handler.server.diagnostics_service.workspace_checkpoints_body(),
        )
        return True
    if path == "/v1/workflow-presets":
        from ..workflows.selector import WORKFLOW_PRESETS

        handler._send_cached_diagnostics_json(
            "GET /v1/workflow-presets",
            lambda: {"object": "agent_hub.workflow_presets", "data": WORKFLOW_PRESETS},
        )
        return True
    if path == "/v1/routing-intelligence":
        handler._send_cached_diagnostics_json(
            "GET /v1/routing-intelligence",
            lambda: server_module._routing_intelligence_body(
                handler.server.config,
                handler.server.router,
                optimization=handler.server.adaptive_service.optimization_summary(),
            ),
        )
        return True
    if path == "/v1/repository-dna":
        handler._send_cached_diagnostics_json(
            "GET /v1/repository-dna",
            lambda: handler.server.router.repository_intelligence.repository_dna().to_dict(),
        )
        return True
    if path == "/v1/workspace-memory":
        handler._send_cached_diagnostics_json(
            "GET /v1/workspace-memory",
            lambda: handler.server.router.repository_intelligence.workspace_memory(),
        )
        return True
    if path == "/v1/night-mode":
        from ..repository_intelligence import build_autonomous_night_mode_plan

        handler._send_cached_diagnostics_json(
            "GET /v1/night-mode",
            lambda: build_autonomous_night_mode_plan(
                dna=handler.server.router.repository_intelligence.repository_dna(),
                config=handler.server.config,
            ),
        )
        return True
    if path == "/v1/inbox/status":
        handler._send_cached_diagnostics_json(
            "GET /v1/inbox/status",
            lambda: handler.server.diagnostics_service.inbox_status_body(),
        )
        return True
    if path == "/v1/tools":
        handler._send_cached_diagnostics_json(
            "GET /v1/tools",
            lambda: server_module._tools_body(handler.server.router),
        )
        return True
    if path == "/v1/workflows/status":
        handler._send_cached_diagnostics_json(
            "GET /v1/workflows/status",
            lambda: server_module._workflow_status_body(handler.server.config),
        )
        return True
    if path == "/v1/plugins":
        handler._send_cached_diagnostics_json(
            "GET /v1/plugins",
            lambda: handler.server.diagnostics_service.plugins_body(),
        )
        return True
    if path == "/v1/audit":
        from ..observability import audit_snapshot

        handler._send_cached_diagnostics_json(
            "GET /v1/audit",
            lambda: audit_snapshot(handler.server.config.state_dir),
        )
        return True
    if path == "/v1/mcp/status":
        handler._send_cached_diagnostics_json(
            "GET /v1/mcp/status",
            lambda: handler.server.diagnostics_service.mcp_status_body(),
        )
        return True
    if path == "/v1/extension-contract":
        handler._send_cached_diagnostics_json(
            "GET /v1/extension-contract",
            lambda: handler.server.diagnostics_service.extension_contract_body(),
        )
        return True
    if path == "/v1/enterprise/audit":
        handler._send_cached_diagnostics_json(
            f"GET {handler.path}",
            lambda: handler.server.diagnostics_service.enterprise_audit_body(request_query(handler.path)),
        )
        return True
    if path == "/v1/enterprise/status":
        handler._send_cached_diagnostics_json(
            "GET /v1/enterprise/status",
            lambda: handler.server.diagnostics_service.enterprise_status_body(),
        )
        return True
    return False


def handle_post(handler: object, path: str, payload: dict[str, Any]) -> bool:
    if path == "/api/benchmarks/run":
        from ..measurement.benchmark_runner import run_benchmark

        handler._send_diagnostics_json(run_benchmark(handler.server.config, payload))
        return True
    if path == "/v1/boost-mode":
        from ..boost import is_valid_boost_mode_value

        value = payload.get("boost_mode", payload.get("mode"))
        if not is_valid_boost_mode_value(value):
            handler._send_json(
                {
                    "object": "agent_hub.error",
                    "error": {
                        "type": "invalid_boost_mode",
                        "message": "Unknown Boost Mode. Use one of the returned options or a supported alias.",
                    },
                    "options": handler.server.config.boost_mode_options_for_advanced(True),
                },
                status=400,
            )
            return True
        mode = handler.server.config.set_boost_mode(
            value
        )
        handler._send_diagnostics_json(
            {
                "object": "agent_hub.boost_mode",
                "mode": mode,
                "label": handler.server.config.boost_mode_label,
                "context_mode": handler.server.config.context_mode,
                "options": handler.server.config.boost_mode_options,
            }
        )
        return True
    if path == "/v1/inbox/submit":
        from ..inbox import enqueue_task, inbox_task_preview

        try:
            task_path = enqueue_task(
                handler.server.config,
                payload,
                task_id=str(payload.get("task_id") or payload.get("id") or ""),
            )
        except ValueError as exc:
            handler._send_json(
                {
                    "object": "agent_hub.inbox_submission",
                    "accepted": False,
                    "error": {"type": "invalid_inbox_task", "message": str(exc)},
                },
                status=400,
            )
            return True
        handler._send_diagnostics_json(
            {
                "object": "agent_hub.inbox_submission",
                "accepted": True,
                "path": str(task_path),
                "task": inbox_task_preview(task_path),
                "status_url": "/v1/inbox/status",
            }
        )
        return True
    if path == "/v1/night-mode/run":
        from ..repository_intelligence import run_autonomous_night_mode_validation

        dna = handler.server.router.repository_intelligence.repository_dna()
        handler._send_diagnostics_json(
            run_autonomous_night_mode_validation(
                dna=dna,
                config=handler.server.config,
                timeout_seconds=_int(payload.get("timeout_seconds")) or 180,
            )
        )
        return True
    if path.startswith("/v1/plugins/") and path.endswith("/execute"):
        from ..plugins import execute_plugin

        plugin_id = path[len("/v1/plugins/") : -len("/execute")].strip("/")
        result = execute_plugin(
            handler.server.config,
            plugin_id=plugin_id,
            action=str(payload.get("action") or "execute"),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            requested_scopes=[
                str(scope)
                for scope in payload.get("requested_scopes", [])
                if isinstance(scope, str)
            ],
        )
        handler._send_diagnostics_json(
            {
                "object": "agent_hub.plugin_execution",
                "result": result.to_dict(),
            }
        )
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


def _kernel_dashboard_html(body: dict[str, Any]) -> str:
    telemetry = _dict(body.get("request_telemetry"))
    latency = _dict(telemetry.get("latency_ms"))
    cache = _dict(body.get("diagnostics_cache"))
    process = _dict(body.get("process_health"))
    process_memory = _dict(process.get("memory"))
    alerts = _dict(body.get("alerts"))
    trends = _dict(body.get("trends"))
    durability = _dict(body.get("durability"))
    actions = body.get("next_actions") if isinstance(body.get("next_actions"), list) else []
    alert_items = alerts.get("active") if isinstance(alerts.get("active"), list) else []
    subsystems = body.get("subsystems") if isinstance(body.get("subsystems"), list) else []
    routes = telemetry.get("routes") if isinstance(telemetry.get("routes"), list) else []
    slow_requests = (
        telemetry.get("recent_slow_requests")
        if isinstance(telemetry.get("recent_slow_requests"), list)
        else []
    )
    subsystem_rows = "".join(
        _kernel_subsystem_row_html(row)
        for row in subsystems
        if isinstance(row, dict)
    )
    if not subsystem_rows:
        subsystem_rows = "<tr><td colspan=\"4\" class=\"muted\">No subsystem data yet.</td></tr>"
    route_rows = "".join(
        _kernel_route_row_html(row)
        for row in routes[:20]
        if isinstance(row, dict)
    )
    if not route_rows:
        route_rows = "<tr><td colspan=\"8\" class=\"muted\">No completed HTTP requests yet.</td></tr>"
    slow_rows = "".join(
        _kernel_slow_request_row_html(row)
        for row in slow_requests[:20]
        if isinstance(row, dict)
    )
    if not slow_rows:
        slow_rows = "<tr><td colspan=\"6\" class=\"muted\">No slow requests crossed the kernel threshold.</td></tr>"
    alert_rows = "".join(
        _kernel_alert_row_html(row)
        for row in alert_items
        if isinstance(row, dict)
    )
    if not alert_rows:
        alert_rows = "<tr><td colspan=\"4\" class=\"muted\">No active alerts.</td></tr>"
    cache_rows = "".join(
        f"<tr><td>{_html(key)}</td><td>{_html(value)}</td></tr>"
        for key, value in sorted(cache.items(), key=lambda item: str(item[0]))
    ) or "<tr><td colspan=\"2\" class=\"muted\">No diagnostics cache stats available.</td></tr>"
    action_rows = "".join(
        _kernel_action_row_html(row)
        for row in actions
        if isinstance(row, dict)
    ) or "<tr><td colspan=\"5\" class=\"muted\">No recommended actions.</td></tr>"
    quick_links = _quick_link_grid_html(
        [
            ("Status", "/dashboard/status", "Provider state and routing summary"),
            ("Provider Health", "/dashboard/provider-health", "Availability, latency, cooldowns"),
            ("Routing Intelligence", "/dashboard/routing-intelligence", "Selection reasons and candidates"),
            ("Events", "/dashboard/events", "Recent backend events"),
        ]
    )
    content = f"""
{quick_links}
<section class="panel">
  <h2>Active Alerts</h2>
  <table>
    <thead><tr><th>Severity</th><th>ID</th><th>Title</th><th>Detail</th></tr></thead>
    <tbody>{alert_rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Recommended Actions</h2>
  <table>
    <thead><tr><th>Severity</th><th>Action</th><th>Detail</th><th>Open</th><th>Command</th></tr></thead>
    <tbody>{action_rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Subsystems</h2>
  <table>
    <thead><tr><th>Subsystem</th><th>State</th><th>Detail</th><th>Metrics</th></tr></thead>
    <tbody>{subsystem_rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Process Health</h2>
  <table>
    <thead><tr><th>Metric</th><th>Value</th></tr></thead>
    <tbody>
      <tr><td>PID</td><td>{_html(process.get('pid'))}</td></tr>
      <tr><td>Python</td><td>{_html(process.get('python'))}</td></tr>
      <tr><td>Platform</td><td>{_html(process.get('platform'))}</td></tr>
      <tr><td>Threads</td><td>{_html(process.get('thread_count'))}</td></tr>
      <tr><td>CPU</td><td>{_html(process.get('cpu_percent'))}% ({_html(process.get('cpu_state'))})</td></tr>
      <tr><td>RSS</td><td>{_html(process_memory.get('rss_mb'))} MB ({_html(process_memory.get('state'))})</td></tr>
      <tr><td>Python heap</td><td>{_html(process_memory.get('python_allocated_mb'))} MB current / {_html(process_memory.get('python_peak_allocated_mb'))} MB peak</td></tr>
    </tbody>
  </table>
</section>
<section class="panel">
  <h2>Trends And Durability</h2>
  <table>
    <thead><tr><th>Metric</th><th>Value</th></tr></thead>
    <tbody>
      <tr><td>Trend state</td><td>{_html(trends.get('state'))}</td></tr>
      <tr><td>Trend samples</td><td>{_html(trends.get('sample_count'))}</td></tr>
      <tr><td>Trend deltas</td><td><code>{_html(json.dumps(_dict(trends.get('deltas')), sort_keys=True, ensure_ascii=False))}</code></td></tr>
      <tr><td>History retained</td><td>{_html(durability.get('retained_snapshots'))}</td></tr>
      <tr><td>History path</td><td><code>{_html(durability.get('path'))}</code></td></tr>
      <tr><td>History error</td><td>{_html(durability.get('error'))}</td></tr>
    </tbody>
  </table>
</section>
<section class="panel">
  <h2>Request Routes</h2>
  <table>
    <thead><tr><th>Route</th><th>Count</th><th>Errors</th><th>Error Rate</th><th>Cache Hit Rate</th><th>Avg Latency</th><th>EWMA</th><th>Last</th></tr></thead>
    <tbody>{route_rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Diagnostics Cache</h2>
  <table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>{cache_rows}</tbody></table>
</section>
<section class="panel">
  <h2>Slow Requests</h2>
  <table>
    <thead><tr><th>Time</th><th>Method</th><th>Route</th><th>Status</th><th>Latency</th><th>Cache</th></tr></thead>
    <tbody>{slow_rows}</tbody>
  </table>
</section>"""
    cards = [
        ("Kernel state", body.get("state", "unknown")),
        ("Operational score", f"{_int(body.get('operational_score'))}/100"),
        ("Uptime", _duration(body.get("uptime_seconds"))),
        ("Requests", telemetry.get("total_requests", 0)),
        ("In flight", telemetry.get("in_flight", 0)),
        ("EWMA latency", _latency(latency.get("ewma"))),
        ("Alerts", f"{alerts.get('active_count', 0)} active"),
        ("Process CPU", f"{process.get('cpu_percent', 0)}%"),
        ("RSS", f"{process_memory.get('rss_mb', '--')} MB"),
        ("Trend", trends.get("state", "unknown")),
    ]
    return _dashboard_page(
        "Agent Hub Runtime Kernel",
        "Control-plane telemetry for request flow, subsystem readiness, cache behavior, and slow-path detection.",
        cards,
        content,
        body,
        json_path="/v1/kernel",
    )


def _cost_dashboard_html(body: dict[str, Any]) -> str:
    summary = _dict(body.get("summary"))
    ledger = _dict(body.get("usage_ledger"))
    ledger_sources = _dict(ledger.get("measurement_sources"))
    ledger_confidence = _dict(ledger.get("confidence"))
    cards = [
        ("Known cost", _money(body.get("known_cost_usd"))),
        ("Average known cost", _money(body.get("average_known_cost_usd"))),
        ("Ledger requests", ledger.get("request_count", 0)),
        ("Success / failure", f"{_int(ledger.get('success_count'))} / {_int(ledger.get('failure_count'))}"),
        ("Usage confidence", ledger_confidence.get("level", "none")),
        ("Actual usage", _percent((_float(ledger_confidence.get("actual_usage_pct")) or 0.0) / 100)),
        ("Pricing coverage", _percent(summary.get("pricing_coverage_rate"))),
        ("State", summary.get("data_state", "unknown")),
    ]
    pricing_rows = "".join(
        _pricing_catalog_row_html(row)
        for row in body.get("pricing_catalog", [])
        if isinstance(row, dict)
    )
    if not pricing_rows:
        pricing_rows = "<tr><td colspan=\"6\" class=\"muted\">No configured agents.</td></tr>"
    content = "\n".join(
        [
            _usage_ledger_section_html(ledger),
            f"""
<section class="panel">
  <h2>Pricing Coverage</h2>
  <table>
    <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Status</th><th>Input / Output per 1M</th><th>1K in + 500 out</th></tr></thead>
    <tbody>{pricing_rows}</tbody>
  </table>
</section>""",
            _mapping_table_html("Cost By Provider", _dict(body.get("cost_by_provider")), value_header="Cost"),
            _mapping_table_html("Cost By Model", _dict(body.get("cost_by_model")), value_header="Cost"),
            _mapping_table_html("Cost By Task Type", _dict(body.get("cost_by_task_type")), value_header="Cost"),
            _mapping_table_html("Cost By Day", _dict(body.get("cost_by_day")), value_header="Cost"),
        ]
    )
    return _dashboard_page(
        "Agent Hub Cost Dashboard",
        "Known spend, estimated savings, and cost breakdowns from recorded routing outcomes.",
        cards,
        content,
        body,
        json_path="/v1/cost-dashboard",
    )


def _model_leaderboard_dashboard_html(body: dict[str, Any]) -> str:
    summary = _dict(body.get("summary"))
    rows = body.get("data") if isinstance(body.get("data"), list) else []
    cards = [
        ("Agents", summary.get("agent_count", len(rows))),
        ("Measured agents", summary.get("measured_agent_count", 0)),
        ("Baseline agents", summary.get("baseline_agent_count", 0)),
        ("Best model", summary.get("best_model") or "waiting for data"),
    ]
    table_rows = "".join(_leaderboard_row_html(row) for row in rows if isinstance(row, dict))
    if not table_rows:
        table_rows = "<tr><td colspan=\"10\" class=\"muted\">No configured agents were reported.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Ranked Models</h2>
  <table>
    <thead><tr><th>Rank</th><th>Agent</th><th>Provider</th><th>Model</th><th>Score</th><th>Success</th><th>Samples</th><th>Latency</th><th>Cost</th><th>Status</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</section>"""
    return _dashboard_page(
        "Agent Hub Model Leaderboard",
        "Model ranking from benchmarks, live outcomes, latency, cost, and routing health.",
        cards,
        content,
        body,
        json_path="/v1/model-leaderboard",
    )


def _benchmark_results_dashboard_html(body: dict[str, Any]) -> str:
    summary = _dict(body.get("summary"))
    reports = body.get("reports") if isinstance(body.get("reports"), list) else []
    snapshot = _dict(body.get("coverage_snapshot"))
    snapshot_rows = snapshot.get("results") if isinstance(snapshot.get("results"), list) else []
    latest_summary = _dict(reports[0].get("summary")) if reports and isinstance(reports[0], dict) else {}
    latest_outcomes = _dict(latest_summary.get("outcome_metrics"))
    latest_comparison = _dict(latest_summary.get("comparison"))
    cards = [
        ("Reports", summary.get("report_count", len(reports))),
        ("Latest", summary.get("latest_report") or "none"),
        ("Tokens saved", _pct(latest_comparison.get("token_reduction")) if latest_comparison else "--"),
        ("Quality delta", _pp(latest_comparison.get("success_delta")) if latest_comparison else "--"),
        ("Cost saved", _money(latest_outcomes.get("cost_saved_usd")) if latest_outcomes else "--"),
        ("Prompt loops avoided", latest_outcomes.get("prompt_loops_avoided", "--")),
    ]
    table_rows = "".join(_benchmark_report_row_html(row) for row in reports if isinstance(row, dict))
    if not table_rows:
        table_rows = "<tr><td colspan=\"5\" class=\"muted\">No benchmark reports found.</td></tr>"
    snapshot_table_rows = "".join(
        _benchmark_snapshot_row_html(row) for row in snapshot_rows if isinstance(row, dict)
    )
    if not snapshot_table_rows:
        snapshot_table_rows = "<tr><td colspan=\"7\" class=\"muted\">No benchmark coverage rows.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Agent Hub vs Raw Agent</h2>
  <table>
    <thead><tr><th>Metric</th><th>Latest Result</th></tr></thead>
    <tbody>
      <tr><td>Tasks completed</td><td>{_html(latest_outcomes.get('tasks_completed', '--'))}</td></tr>
      <tr><td>Tokens used</td><td>{_html(_pct(latest_comparison.get('token_reduction')) if latest_comparison else '--')}</td></tr>
      <tr><td>Task success</td><td>{_html(_pp(latest_comparison.get('success_delta')) if latest_comparison else '--')}</td></tr>
      <tr><td>Cost</td><td>{_html(_pct(latest_comparison.get('cost_reduction')) if latest_comparison else '--')}</td></tr>
      <tr><td>Quality score</td><td>{_html(_number(latest_outcomes.get('quality_score')) if latest_outcomes else '--')}</td></tr>
      <tr><td>Time to working solution</td><td>{_html(_latency(latest_outcomes.get('time_to_working_solution_ms')) if latest_outcomes else '--')}</td></tr>
    </tbody>
  </table>
</section>
<section class="panel">
  <h2>Benchmark Coverage Snapshot</h2>
  <table>
    <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Readiness</th><th>Samples</th><th>Latency</th><th>Status</th></tr></thead>
    <tbody>{snapshot_table_rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Recent Reports</h2>
  <table>
    <thead><tr><th>Report</th><th>Updated</th><th>Winner</th><th>Results</th><th>Summary</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</section>"""
    return _dashboard_page(
        "Agent Hub Benchmark Results",
        "Stored benchmark-suite reports for comparing routing quality over time.",
        cards,
        content,
        body,
        json_path="/v1/benchmarks",
    )


def _proof_dashboard_html(body: dict[str, Any]) -> str:
    repository = _dict(body.get("repository"))
    cards_data = body.get("cards") if isinstance(body.get("cards"), list) else []
    performance = body.get("model_performance") if isinstance(body.get("model_performance"), list) else []
    cards = [
        (row.get("label", ""), row.get("value", "--"))
        for row in cards_data
        if isinstance(row, dict)
    ]
    rows = "".join(
        "<tr>"
        f"<td>{_html(row.get('task_type', ''))}</td>"
        f"<td>{_html(row.get('agent', ''))}</td>"
        f"<td>{_html(row.get('model', ''))}</td>"
        f"<td>{_html(row.get('success_rate', '--'))}</td>"
        f"<td>{_html(row.get('attempts', '--'))}</td>"
        f"<td>{_html(row.get('average_outcome_score', '--'))}</td>"
        "</tr>"
        for row in performance
        if isinstance(row, dict)
    )
    if not rows:
        rows = "<tr><td colspan=\"6\" class=\"muted\">No model performance samples yet.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Repository</h2>
  <table>
    <tbody>
      <tr><td>Name</td><td>{_html(repository.get('name', 'unknown'))}</td></tr>
      <tr><td>Path</td><td>{_html(repository.get('path', ''))}</td></tr>
    </tbody>
  </table>
</section>
<section class="panel">
  <h2>Model Performance</h2>
  <table>
    <thead><tr><th>Task</th><th>Agent</th><th>Model</th><th>Success</th><th>Attempts</th><th>Outcome</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""
    return _dashboard_page(
        "Agent Hub Proof Dashboard",
        "Per-repository proof for tokens saved, cost saved, success rate, retry reduction, and model performance.",
        cards,
        content,
        body,
        json_path="/v1/proof-dashboard",
    )


def _status_dashboard_html(body: dict[str, Any]) -> str:
    providers = body.get("providers") if isinstance(body.get("providers"), list) else []
    table_rows = "".join(_status_provider_row_html(row) for row in providers if isinstance(row, dict))
    if not table_rows:
        table_rows = "<tr><td colspan=\"7\" class=\"muted\">No providers configured.</td></tr>"
    quick_links = _quick_link_grid_html(
        [
            ("Readiness", "/dashboard/readiness", "Setup score and next action"),
            ("Provider Health", "/dashboard/provider-health", "Availability, latency, and failures"),
            ("Routing Intelligence", "/dashboard/routing-intelligence", "Why a model was selected"),
            ("Limits", "/dashboard/limits", "Quota, cooldown, and active model state"),
        ]
    )
    content = f"""
{quick_links}
<section class="panel">
  <h2>Providers</h2>
  <table>
    <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Available</th><th>Score</th><th>Latency</th><th>Reason</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</section>"""
    cards = [
        ("Status", body.get("status", "unknown")),
        ("Version", body.get("version", "unknown")),
        ("Active providers", len(body.get("active_providers", [])) if isinstance(body.get("active_providers"), list) else 0),
        ("Selected model", body.get("selected_model") or "none yet"),
    ]
    return _dashboard_page(
        "Agent Hub Status",
        "Current backend state, provider availability, and the most useful follow-up dashboards.",
        cards,
        content,
        body,
        json_path="/v1/status",
    )


def _provider_health_dashboard_html(body: dict[str, Any]) -> str:
    providers = body.get("providers") if isinstance(body.get("providers"), list) else []
    health = _dict(body.get("health"))
    rows = "".join(
        _provider_health_row_html(row, _dict(health.get(str(row.get("agent") or row.get("name") or ""))))
        for row in providers
        if isinstance(row, dict)
    )
    if not rows:
        rows = "<tr><td colspan=\"9\" class=\"muted\">No provider health rows are available.</td></tr>"
    failures = body.get("recent_failures") if isinstance(body.get("recent_failures"), list) else []
    failure_rows = "".join(_event_row_html(row) for row in failures[-25:] if isinstance(row, dict))
    if not failure_rows:
        failure_rows = "<tr><td colspan=\"5\" class=\"muted\">No recent provider failures.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Provider Health</h2>
  <table>
    <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Available</th><th>Degraded</th><th>Reliability</th><th>Latency</th><th>Cooldown</th><th>Last Error</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Recent Failures</h2>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Agent</th><th>Model</th><th>Detail</th></tr></thead>
    <tbody>{failure_rows}</tbody>
  </table>
</section>"""
    available = sum(1 for row in health.values() if isinstance(row, dict) and row.get("available"))
    cards = [
        ("Providers", len(providers)),
        ("Available", available),
        ("Recent failures", len(failures)),
        ("State", "healthy" if available else "needs provider"),
    ]
    return _dashboard_page(
        "Agent Hub Provider Health",
        "Provider readiness, reliability, latency, cooldowns, and recent failures.",
        cards,
        content,
        body,
        json_path="/v1/provider-health",
    )


def _system_health_dashboard_html(body: dict[str, Any]) -> str:
    components = body.get("components") if isinstance(body.get("components"), list) else []
    rows = "".join(
        f"<tr><td>{_html(row.get('component'))}</td><td>{_html(row.get('status'))}</td></tr>"
        for row in components
        if isinstance(row, dict)
    )
    if not rows:
        rows = "<tr><td colspan=\"2\" class=\"muted\">No component status is available.</td></tr>"
    content = f"""
<section class="panel">
  <h2>System Health</h2>
  <table>
    <thead><tr><th>Component</th><th>Status</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Support</h2>
  <p>Generate Support Bundle creates a redacted package with logs, config summary, provider status, and validation output.</p>
  <p><code>{_html(body.get('support_bundle') or 'agent-hub support-bundle')}</code></p>
</section>"""
    cards = [
        ("Status", body.get("status", "unknown")),
        ("Components", len(components)),
        ("Advanced", body.get("advanced_view", "/health")),
    ]
    return _dashboard_page(
        "Agent Hub System Health",
        "A safe health view for sharing status without secrets, local paths, raw payloads, or stack traces.",
        cards,
        content,
        body,
        json_path="/v1/system-health",
    )


def _production_check_dashboard_html(body: dict[str, Any]) -> str:
    checks = body.get("checks") if isinstance(body.get("checks"), list) else []
    check_rows = "".join(_production_check_row_html(row) for row in checks if isinstance(row, dict))
    if not check_rows:
        check_rows = "<tr><td colspan=\"6\" class=\"muted\">No production checks were reported.</td></tr>"
    failed = body.get("failed") if isinstance(body.get("failed"), list) else []
    warnings = body.get("warnings") if isinstance(body.get("warnings"), list) else []
    content = f"""
<section class="panel">
  <h2>Acceptance Checks</h2>
  <table>
    <thead><tr><th>Check</th><th>Severity</th><th>OK</th><th>Earned</th><th>Detail</th><th>Command</th></tr></thead>
    <tbody>{check_rows}</tbody>
  </table>
</section>"""
    cards = [
        ("Score", body.get("score", "unknown")),
        ("State", body.get("state", "unknown")),
        ("Failed", len(failed)),
        ("Warnings", len(warnings)),
    ]
    return _dashboard_page(
        "Agent Hub Production Check",
        "Strict release-readiness checks for provider health, safety, dashboards, and extension/backend alignment.",
        cards,
        content,
        body,
        json_path="/v1/production-check",
    )


def _feature_scorecard_dashboard_html(body: dict[str, Any]) -> str:
    areas = body.get("areas") if isinstance(body.get("areas"), list) else []
    rows = "".join(_feature_scorecard_row_html(row) for row in areas if isinstance(row, dict))
    if not rows:
        rows = "<tr><td colspan=\"5\" class=\"muted\">No feature scorecard rows were reported.</td></tr>"
    blockers = body.get("blockers") if isinstance(body.get("blockers"), list) else []
    runtime = _dict(body.get("runtime_usability"))
    content = f"""
<section class="panel">
  <h2>Area Ratings</h2>
  <table>
    <thead><tr><th>Area</th><th>Rating</th><th>State</th><th>Checks</th><th>Honest Take</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Scope</h2>
  <p>{_html(body.get('honesty'))}</p>
</section>"""
    cards = [
        ("Rating", f"{_number(body.get('rating'))}/10"),
        ("State", body.get("state", "unknown")),
        ("Runtime", f"{runtime.get('score', 0)}/100 {runtime.get('state', 'unknown')}" if runtime else "unknown"),
        ("All local 10s", str(bool(body.get("all_local_areas_10"))).lower()),
        ("Blockers", len(blockers)),
    ]
    return _dashboard_page(
        "Agent Hub Feature Scorecard",
        "Contract and foundation proof across routing, providers, APIs, agents, safety, dashboards, extension, workflows, plugins, and evaluation. Runtime usability is scored separately.",
        cards,
        content,
        body,
        json_path="/v1/feature-scorecard",
    )


def _limits_dashboard_html(body: dict[str, Any]) -> str:
    limits = body.get("limits") if isinstance(body.get("limits"), list) else []
    rows = "".join(_limit_row_html(row) for row in limits if isinstance(row, dict))
    if not rows:
        rows = "<tr><td colspan=\"8\" class=\"muted\">No enabled provider limits were reported.</td></tr>"
    active = _dict(body.get("active_model"))
    recommendations = body.get("recommendations") if isinstance(body.get("recommendations"), list) else []
    rec_rows = "".join(_recommendation_row_html(row) for row in recommendations if isinstance(row, dict))
    if not rec_rows:
        rec_rows = "<tr><td colspan=\"5\" class=\"muted\">No routing recommendations yet.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Limits And Cooldowns</h2>
  <table>
    <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Available</th><th>Requests</th><th>Tokens</th><th>Cooldown</th><th>Last Error</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Routing Recommendations</h2>
  <table>
    <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Available</th><th>Reason</th></tr></thead>
    <tbody>{rec_rows}</tbody>
  </table>
</section>"""
    cards = [
        ("Active model", active.get("model") or "none"),
        ("Available providers", len(body.get("active_providers", [])) if isinstance(body.get("active_providers"), list) else 0),
        ("Failed models", len(body.get("failed_models", [])) if isinstance(body.get("failed_models"), list) else 0),
        ("Fallback models", len(body.get("fallback_models", [])) if isinstance(body.get("fallback_models"), list) else 0),
    ]
    return _dashboard_page(
        "Agent Hub Limits",
        "Quota, cooldown, fallback, and active model information for configured providers.",
        cards,
        content,
        body,
        json_path="/v1/limits",
    )


def _usage_dashboard_html(body: dict[str, Any]) -> str:
    ledger = _dict(body.get("usage_ledger"))
    ledger_confidence = _dict(ledger.get("confidence"))
    tool_rows = "".join(_event_row_html(row) for row in body.get("recent_tool_executions", []) if isinstance(row, dict))
    if not tool_rows:
        tool_rows = "<tr><td colspan=\"5\" class=\"muted\">No recent tool executions.</td></tr>"
    permission_rows = "".join(_event_row_html(row) for row in body.get("recent_permissions", []) if isinstance(row, dict))
    if not permission_rows:
        permission_rows = "<tr><td colspan=\"5\" class=\"muted\">No recent permission events.</td></tr>"
    content = f"""
{_usage_ledger_section_html(ledger)}
<section class="panel">
  <h2>Recent Tool Executions</h2>
  <table><thead><tr><th>Time</th><th>Type</th><th>Agent</th><th>Model</th><th>Detail</th></tr></thead><tbody>{tool_rows}</tbody></table>
</section>
<section class="panel">
  <h2>Recent Permission Events</h2>
  <table><thead><tr><th>Time</th><th>Type</th><th>Agent</th><th>Model</th><th>Detail</th></tr></thead><tbody>{permission_rows}</tbody></table>
</section>"""
    cards = [
        ("Input tokens", body.get("input_tokens", 0)),
        ("Output tokens", body.get("output_tokens", 0)),
        ("Provider calls", _int(body.get("successful_provider_calls")) + _int(body.get("failed_provider_calls"))),
        ("Ledger requests", ledger.get("request_count", 0)),
        ("Routes success/failure", f"{_int(ledger.get('success_count'))}/{_int(ledger.get('failure_count'))}"),
        ("Confidence", ledger_confidence.get("level", "none")),
    ]
    return _dashboard_page(
        "Agent Hub Usage",
        "Token totals, provider call counts, tool execution counts, and permission activity.",
        cards,
        content,
        body,
        json_path="/v1/usage",
    )


def _events_dashboard_html(body: dict[str, Any]) -> str:
    sections = []
    for label, key in (
        ("Internal Events", "events"),
        ("Routing Events", "routing"),
        ("Workflow Events", "workflows"),
        ("Adaptive Events", "adaptive"),
    ):
        rows = "".join(_event_row_html(row) for row in body.get(key, []) if isinstance(row, dict))
        if not rows:
            rows = "<tr><td colspan=\"5\" class=\"muted\">No events yet.</td></tr>"
        sections.append(
            f"""
<section class="panel">
  <h2>{_html(label)}</h2>
  <table><thead><tr><th>Time</th><th>Type</th><th>Agent</th><th>Model</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>
</section>"""
        )
    cards = [
        ("Events", len(body.get("events", [])) if isinstance(body.get("events"), list) else 0),
        ("Routing", len(body.get("routing", [])) if isinstance(body.get("routing"), list) else 0),
        ("Workflows", len(body.get("workflows", [])) if isinstance(body.get("workflows"), list) else 0),
        ("Adaptive", len(body.get("adaptive", [])) if isinstance(body.get("adaptive"), list) else 0),
    ]
    return _dashboard_page(
        "Agent Hub Events",
        "Recent internal, routing, workflow, and adaptive learning events.",
        cards,
        "\n".join(sections),
        body,
        json_path="/v1/events",
    )


def _tools_dashboard_html(body: dict[str, Any]) -> str:
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    rows = "".join(_tool_row_html(row) for row in tools if isinstance(row, dict))
    if not rows:
        rows = "<tr><td colspan=\"5\" class=\"muted\">No tools registered.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Registered Tools</h2>
  <table><thead><tr><th>Name</th><th>Description</th><th>Permission</th><th>Required</th><th>Schema</th></tr></thead><tbody>{rows}</tbody></table>
</section>"""
    cards = [
        ("Tools", body.get("count", len(tools))),
        ("Privileged", sum(1 for row in tools if isinstance(row, dict) and row.get("permission"))),
        ("State", "ready" if tools else "no tools"),
    ]
    return _dashboard_page(
        "Agent Hub Tools",
        "Registered workspace tools, permissions, and argument schemas.",
        cards,
        content,
        body,
        json_path="/v1/tools",
    )


def _workflows_dashboard_html(body: dict[str, Any]) -> str:
    summary = _dict(body.get("summary"))
    runs = body.get("runs") if isinstance(body.get("runs"), list) else []
    presets = body.get("presets") if isinstance(body.get("presets"), list) else []
    run_rows = "".join(_workflow_run_row_html(row) for row in runs if isinstance(row, dict))
    if not run_rows:
        run_rows = "<tr><td colspan=\"7\" class=\"muted\">No workflow runs yet.</td></tr>"
    preset_rows = "".join(_workflow_preset_row_html(row) for row in presets if isinstance(row, dict))
    if not preset_rows:
        preset_rows = "<tr><td colspan=\"4\" class=\"muted\">No workflow presets reported.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Recent Runs</h2>
  <table><thead><tr><th>ID</th><th>Workflow</th><th>Pattern</th><th>Status</th><th>Stages</th><th>Started</th><th>Updated</th></tr></thead><tbody>{run_rows}</tbody></table>
</section>
<section class="panel">
  <h2>Presets</h2>
  <table><thead><tr><th>ID</th><th>Task Type</th><th>Pattern</th><th>Description</th></tr></thead><tbody>{preset_rows}</tbody></table>
</section>"""
    cards = [
        ("Runs", summary.get("recent_run_count", len(runs))),
        ("Active", summary.get("active_run_count", 0)),
        ("Finished", summary.get("finished_run_count", 0)),
        ("Presets", summary.get("preset_count", len(presets))),
    ]
    return _dashboard_page(
        "Agent Hub Workflows",
        "Workflow presets, recent runs, stage counts, and status.",
        cards,
        content,
        body,
        json_path="/v1/workflows/status",
    )


def _plugins_dashboard_html(body: dict[str, Any]) -> str:
    plugins = body.get("plugins") if isinstance(body.get("plugins"), list) else body.get("data")
    plugins = plugins if isinstance(plugins, list) else []
    rows = "".join(_plugin_row_html(row) for row in plugins if isinstance(row, dict))
    if not rows:
        rows = "<tr><td colspan=\"5\" class=\"muted\">No plugins discovered.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Discovered Plugins</h2>
  <table><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Enabled</th><th>Scopes</th></tr></thead><tbody>{rows}</tbody></table>
</section>"""
    cards = [
        ("Plugins", body.get("count", len(plugins))),
        ("Enabled", sum(1 for row in plugins if isinstance(row, dict) and row.get("enabled"))),
        ("State", body.get("state") or ("ready" if plugins else "none discovered")),
    ]
    return _dashboard_page(
        "Agent Hub Plugins",
        "Discovered provider, tool, workflow, routing, memory, and context plugins.",
        cards,
        content,
        body,
        json_path="/v1/plugins",
    )


def _mcp_dashboard_html(body: dict[str, Any]) -> str:
    servers = body.get("servers") if isinstance(body.get("servers"), list) else []
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    warnings = body.get("warnings") if isinstance(body.get("warnings"), list) else []
    server_rows = "".join(_mcp_server_row_html(row) for row in servers if isinstance(row, dict))
    tool_rows = "".join(_mcp_tool_row_html(row) for row in tools if isinstance(row, dict))
    if not server_rows:
        server_rows = "<tr><td colspan=\"6\" class=\"muted\">No MCP servers configured.</td></tr>"
    if not tool_rows:
        tool_rows = "<tr><td colspan=\"6\" class=\"muted\">No MCP tools declared.</td></tr>"
    content = "\n".join(
        [
            f"""
<section class="panel">
  <h2>MCP Servers</h2>
  <table><thead><tr><th>Name</th><th>Status</th><th>Enabled</th><th>Command</th><th>Tools</th><th>Warnings</th></tr></thead><tbody>{server_rows}</tbody></table>
</section>""",
            f"""
<section class="panel">
  <h2>MCP Tools</h2>
  <table><thead><tr><th>Name</th><th>Server</th><th>Status</th><th>Read only</th><th>Permissions</th><th>Inputs</th></tr></thead><tbody>{tool_rows}</tbody></table>
</section>""",
            _list_section_html("Warnings", warnings),
        ]
    )
    cards = [
        ("State", body.get("state", "unknown")),
        ("Servers", body.get("configured_server_count", 0)),
        ("Tools", body.get("declared_tool_count", 0)),
        ("Execution", str(bool(body.get("execution_enabled"))).lower()),
    ]
    return _dashboard_page(
        "Agent Hub MCP",
        "External MCP server and tool status with policy-gated stdio execution details.",
        cards,
        content,
        body,
        json_path="/v1/mcp/status",
    )


def _extension_contract_dashboard_html(body: dict[str, Any]) -> str:
    contract = _dict(body.get("contract"))
    summary = _dict(body.get("summary"))
    missing = contract.get("missing") if isinstance(contract.get("missing"), list) else []
    required = contract.get("required") if isinstance(contract.get("required"), list) else []
    content = "\n".join(
        [
            _key_value_section_html(
                "Contract",
                [
                    ("OK", str(bool(contract.get("ok"))).lower()),
                    ("Extension source available", str(bool(contract.get("available"))).lower()),
                    ("Backend version", body.get("backend_version")),
                    ("Required features", summary.get("required_count", 0)),
                    ("Missing features", summary.get("missing_count", 0)),
                    ("Detail", contract.get("detail")),
                ],
            ),
            _list_section_html("Required Backend Features", required),
            _list_section_html("Missing Backend Features", missing),
        ]
    )
    cards = [
        ("OK", str(bool(contract.get("ok"))).lower()),
        ("Required", summary.get("required_count", 0)),
        ("Missing", summary.get("missing_count", 0)),
        ("Version", body.get("backend_version", "unknown")),
    ]
    return _dashboard_page(
        "Agent Hub Extension Contract",
        "Machine-readable backend feature contract for the VS Code extension.",
        cards,
        content,
        body,
        json_path="/v1/extension-contract",
    )


def _enterprise_dashboard_html(body: dict[str, Any]) -> str:
    summary = _dict(body.get("summary"))
    warnings = body.get("warnings") if isinstance(body.get("warnings"), list) else []
    users = body.get("users") if isinstance(body.get("users"), list) else []
    roles = body.get("roles") if isinstance(body.get("roles"), list) else []
    workspaces = body.get("workspaces") if isinstance(body.get("workspaces"), list) else []
    warning_section = _list_section_html("Warnings", warnings)
    content = "\n".join(
        [
            warning_section,
            _enterprise_rows_section_html("Users", users),
            _enterprise_rows_section_html("Roles", roles),
            _enterprise_rows_section_html("Workspaces", workspaces),
        ]
    )
    cards = [
        ("Enabled", str(bool(body.get("enabled"))).lower()),
        ("State", body.get("state", "unknown")),
        ("Users", summary.get("users", len(users))),
        ("Audit events", summary.get("audit_events", 0)),
    ]
    return _dashboard_page(
        "Agent Hub Enterprise",
        "Enterprise users, roles, workspaces, grants, audit status, and configuration warnings.",
        cards,
        content,
        body,
        json_path="/v1/enterprise/status",
    )


def _provider_scores_dashboard_html(body: dict[str, Any]) -> str:
    scores = _dict(body.get("data"))
    rows = "".join(
        _provider_score_row_html(agent, row)
        for agent, row in sorted(scores.items())
        if isinstance(row, dict)
    )
    if not rows:
        rows = "<tr><td colspan=\"8\" class=\"muted\">No provider scores have been recorded yet.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Provider Scores</h2>
  <table>
    <thead><tr><th>Agent</th><th>Overall</th><th>Success</th><th>Failures</th><th>Samples</th><th>Latency</th><th>Cost</th><th>Task Scores</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""
    cards = [
        ("Scored agents", len(scores)),
        ("Benchmark types", len(body.get("benchmark_types", [])) if isinstance(body.get("benchmark_types"), list) else 0),
        ("State", "measured" if scores else "waiting for data"),
    ]
    return _dashboard_page(
        "Agent Hub Provider Scores",
        "Stored provider evaluation and live outcome scores used by routing.",
        cards,
        content,
        body,
        json_path="/v1/provider-scores",
    )


def _routing_history_dashboard_html(body: dict[str, Any]) -> str:
    events = body.get("data") if isinstance(body.get("data"), list) else []
    rows = "".join(_routing_history_row_html(row) for row in events[:100] if isinstance(row, dict))
    if not rows:
        rows = "<tr><td colspan=\"6\" class=\"muted\">No routing events have been recorded yet.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Recent Routing Events</h2>
  <table>
    <thead><tr><th>Time</th><th>Type</th><th>Agent</th><th>Provider</th><th>Model</th><th>Detail</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""
    cards = [
        ("Events", body.get("count", len(events))),
        ("Showing", len(events[:100])),
        ("State", "recording" if events else "waiting for events"),
    ]
    return _dashboard_page(
        "Agent Hub Routing History",
        "Recent routing selections, fallbacks, failures, and provider events.",
        cards,
        content,
        body,
        json_path="/v1/routing-history",
    )


def _learning_dashboard_html(body: dict[str, Any]) -> str:
    summary = _dict(body.get("summary"))
    models = body.get("models") if isinstance(body.get("models"), list) else []
    changes = body.get("routing_changes") if isinstance(body.get("routing_changes"), list) else []
    history = _dict(body.get("route_history"))
    model_rows = "".join(_learning_model_row_html(row) for row in models if isinstance(row, dict))
    if not model_rows:
        model_rows = "<tr><td colspan=\"8\" class=\"muted\">No learning samples have been recorded yet.</td></tr>"
    change_rows = "".join(_learning_change_row_html(row) for row in changes if isinstance(row, dict))
    if not change_rows:
        change_rows = "<tr><td colspan=\"5\" class=\"muted\">No adaptive routing changes have been recorded yet.</td></tr>"
    history_rows = "".join(
        _route_history_week_row_html(row)
        for row in history.get("weeks", [])
        if isinstance(row, dict)
    )
    if not history_rows:
        history_rows = "<tr><td colspan=\"3\" class=\"muted\">No route history events have been recorded yet.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Last 30 Days</h2>
  <table>
    <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Success</th><th>Failures</th><th>Latency</th><th>Adaptive</th><th>Samples</th></tr></thead>
    <tbody>{model_rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Routing Changed</h2>
  <table>
    <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Direction</th><th>Reason</th></tr></thead>
    <tbody>{change_rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Route History</h2>
  <table>
    <thead><tr><th>Week</th><th>Routes</th><th>Distribution</th></tr></thead>
    <tbody>{history_rows}</tbody>
  </table>
</section>"""
    cards = [
        ("Routes", summary.get("routes", 0)),
        ("Success", summary.get("successes", 0)),
        ("Failure", summary.get("failures", 0)),
        ("Routing changes", summary.get("routing_changes", 0)),
    ]
    return _dashboard_page(
        "Agent Hub Learning",
        "Adaptive routing proof from provider outcomes, route shifts, and recent distribution.",
        cards,
        content,
        body,
        json_path="/v1/learning",
    )


def _readiness_dashboard_html(body: dict[str, Any]) -> str:
    items = body.get("items") if isinstance(body.get("items"), list) else []
    feature_status = _dict(body.get("feature_status"))
    runtime = _dict(body.get("runtime_usability"))
    contract = _dict(body.get("contract_readiness"))
    item_rows = "".join(_readiness_item_row_html(row) for row in items if isinstance(row, dict))
    if not item_rows:
        item_rows = "<tr><td colspan=\"6\" class=\"muted\">No readiness items were reported.</td></tr>"
    feature_rows = "".join(
        _feature_status_row_html(name, row)
        for name, row in sorted(feature_status.items())
        if isinstance(row, dict)
    )
    if not feature_rows:
        feature_rows = "<tr><td colspan=\"4\" class=\"muted\">No feature states were reported.</td></tr>"
    content = f"""
<section class="panel">
  <h2>Runtime Usability</h2>
  <p>{_html(runtime.get('honesty') or 'Runtime usability reports whether this machine has live evidence for real route execution.')}</p>
  <table>
    <tbody>
      <tr><td>State</td><td>{_html(runtime.get('state', 'unknown'))}</td></tr>
      <tr><td>Score</td><td>{_html(runtime.get('score', 0))}/100</td></tr>
      <tr><td>Next step</td><td>{_html(_dict(runtime.get('next_step')).get('label') or 'none')}</td></tr>
    </tbody>
  </table>
</section>
<section class="panel">
  <h2>Readiness Scorecard</h2>
  <table>
    <thead><tr><th>Item</th><th>Status</th><th>Score</th><th>Weight</th><th>Detail</th><th>Command</th></tr></thead>
    <tbody>{item_rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Feature Maturity</h2>
  <table>
    <thead><tr><th>Feature</th><th>State</th><th>Ready</th><th>Detail</th></tr></thead>
    <tbody>{feature_rows}</tbody>
  </table>
</section>"""
    next_step = _dict(body.get("next_step"))
    cards = [
        ("Score", body.get("score", "unknown")),
        ("Contract", f"{contract.get('score', 'unknown')}/100 {contract.get('state', '')}" if contract else "unknown"),
        ("Rating", body.get("rating", "unknown")),
        ("State", body.get("state", "unknown")),
        ("Runtime", f"{runtime.get('score', 0)}/100 {runtime.get('state', 'unknown')}" if runtime else "unknown"),
        ("Next step", next_step.get("label") or "none"),
    ]
    return _dashboard_page(
        "Agent Hub Readiness",
        "Contract readiness, setup score, route maturity, and the separate live runtime usability state for this install.",
        cards,
        content,
        body,
        json_path="/v1/readiness",
    )


def _repository_dna_dashboard_html(body: dict[str, Any]) -> str:
    source_counts = _dict(body.get("source_counts"))
    commit_history = _dict(body.get("commit_history"))
    content = "\n".join(
        [
            _key_value_section_html(
                "Repository Profile",
                [
                    ("Root", body.get("root")),
                    ("Profile ID", body.get("profile_id")),
                    ("Fingerprint", body.get("fingerprint")),
                    ("Project", body.get("project")),
                    ("Primary language", body.get("language")),
                    ("Architecture", body.get("architecture")),
                    ("Code style", body.get("code_style")),
                    ("Testing", body.get("testing")),
                    ("Summary", body.get("summary")),
                ],
            ),
            _list_section_html("Frameworks", body.get("frameworks")),
            _list_section_html("Design Patterns", body.get("design_patterns")),
            _list_section_html("Dependencies", body.get("dependencies")),
            _list_section_html("Risk Areas", body.get("risk_areas")),
            _list_section_html("Package Files", body.get("package_files")),
            _mapping_section_html("Source Counts", source_counts),
            _mapping_section_html("Commit History", commit_history),
        ]
    )
    cards = [
        ("Project", body.get("project", "Repository")),
        ("Language", body.get("language", "unknown")),
        ("Frameworks", len(body.get("frameworks", [])) if isinstance(body.get("frameworks"), list) else 0),
        ("Confidence", _percent(body.get("confidence"))),
    ]
    return _dashboard_page(
        "Agent Hub Repository DNA",
        "Repository fingerprint, language/framework signals, risk areas, and context clues used by routing.",
        cards,
        content,
        body,
        json_path="/v1/repository-dna",
    )


def _workspace_memory_dashboard_html(body: dict[str, Any]) -> str:
    facts = body.get("facts") if isinstance(body.get("facts"), list) else []
    files = body.get("remembered_files") if isinstance(body.get("remembered_files"), list) else []
    content = "\n".join(
        [
            _list_section_html("Remembered Facts", facts),
            _list_section_html("Remembered Files", files),
            _key_value_section_html(
                "Memory Metadata",
                [
                    ("Last updated", _timestamp(body.get("last_updated_at"))),
                    ("Fact count", len(facts)),
                    ("File count", len(files)),
                ],
            ),
        ]
    )
    cards = [
        ("Facts", len(facts)),
        ("Files", len(files)),
        ("Last updated", _timestamp(body.get("last_updated_at"))),
    ]
    return _dashboard_page(
        "Agent Hub Workspace Memory",
        "Compact repository facts and files remembered for routing and context selection.",
        cards,
        content,
        body,
        json_path="/v1/workspace-memory",
    )


def _night_mode_dashboard_html(body: dict[str, Any]) -> str:
    last_run = _dict(body.get("last_run"))
    content = "\n".join(
        [
            _list_section_html("Planned Tasks", body.get("tasks")),
            _list_section_html("Validation Commands", body.get("validation_commands")),
            _list_section_html("Blocked Reasons", body.get("blocked_reasons")),
            _list_section_html("Safeguards", body.get("safeguards")),
            _key_value_section_html(
                "Plan Metadata",
                [
                    ("Enabled", str(bool(body.get("enabled"))).lower()),
                    ("Mode", body.get("mode")),
                    ("State", body.get("state")),
                    ("Repository profile", body.get("repository_profile_id")),
                    ("Run endpoint", body.get("run_endpoint")),
                    ("Last run status", last_run.get("status") or "none"),
                    ("Last run report", last_run.get("report_path") or "none"),
                ],
            ),
        ]
    )
    cards = [
        ("Enabled", str(bool(body.get("enabled"))).lower()),
        ("State", body.get("state", "unknown")),
        ("Mode", body.get("mode", "plan_only")),
        ("Tasks", len(body.get("tasks", [])) if isinstance(body.get("tasks"), list) else 0),
        ("Commands", len(body.get("validation_commands", [])) if isinstance(body.get("validation_commands"), list) else 0),
    ]
    return _dashboard_page(
        "Agent Hub Night Mode",
        "Autonomous validation plan and safeguards. Execution remains validation-only unless explicitly enabled.",
        cards,
        content,
        body,
        json_path="/v1/night-mode",
    )


def _inbox_dashboard_html(body: dict[str, Any]) -> str:
    counts = _dict(body.get("counts"))
    commands = _dict(body.get("commands"))
    health = _dict(body.get("queue_health"))
    submission = _dict(body.get("submission"))
    cards = [
        ("State", body.get("state", "unknown")),
        ("Pending", counts.get("pending", 0)),
        ("Invalid", counts.get("invalid_pending", 0)),
        ("Processing", counts.get("processing", 0)),
        ("Recent outputs", counts.get("recent_outputs", 0)),
    ]
    content = "\n".join(
        [
            _key_value_section_html(
                "Queue Health",
                [
                    ("Ready to process", str(bool(health.get("ready_to_process"))).lower()),
                    ("Oldest pending age seconds", health.get("oldest_pending_age_seconds", 0)),
                    ("Invalid files", ", ".join(str(item) for item in health.get("invalid_files", []) or []) or "none"),
                    ("Submit endpoint", submission.get("endpoint", "/v1/inbox/submit")),
                ],
            ),
            _key_value_section_html(
                "Directories",
                [(key, value) for key, value in _dict(body.get("directories")).items()],
            ),
            _inbox_file_table_html("Pending Tasks", body.get("pending")),
            _inbox_file_table_html("Processing Tasks", body.get("processing")),
            _inbox_file_table_html("Recent Outputs", body.get("recent_outputs")),
            _inbox_file_table_html("Recent Archive", body.get("recent_archive")),
            _key_value_section_html(
                "Commands",
                [(key, value) for key, value in commands.items()],
            ),
        ]
    )
    return _dashboard_page(
        "Agent Hub Inbox",
        "JSON task queue status for one-shot processing, watcher mode, and serve --watch-inbox.",
        cards,
        content,
        body,
        json_path="/v1/inbox/status",
    )


def _dashboard_page(
    title: str,
    subtitle: str,
    cards: list[tuple[str, Any]],
    content: str,
    body: dict[str, Any],
    *,
    json_path: str,
) -> str:
    empty = _empty_state_html(body.get("empty_state"))
    notice = _empty_state_html(body.get("measurement_notice"))
    card_html = "".join(
        f"<div class=\"card\"><strong>{_html(value)}</strong><span>{_html(label)}</span></div>"
        for label, value in cards
    )
    payload = html.escape(json.dumps(body, indent=2, ensure_ascii=False))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{_html(title)}</title>
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:#0f172a;color:#e5e7eb;line-height:1.45;overflow-x:hidden}}
header{{padding:24px 32px;border-bottom:1px solid #334155;background:#111827}}
main{{width:100%;max-width:1280px;margin:auto;padding:24px 32px;overflow-x:hidden}}
h1{{margin:0 0 6px;font-size:28px}} h2{{margin:0 0 14px;font-size:18px}}
p{{color:#cbd5e1;overflow-wrap:break-word}} a{{color:#67e8f9}} code,pre{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}}
.card,.panel,.empty{{max-width:100%;border:1px solid #334155;background:#111827;border-radius:8px;padding:16px}}
.card strong{{display:block;font-size:22px;line-height:1.14;margin-bottom:4px;overflow-wrap:anywhere}} .card span,.muted{{color:#94a3b8}}
.link-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:20px 0}}
.link-card{{display:block;border:1px solid #334155;background:#111827;border-radius:8px;padding:14px;text-decoration:none}}
.link-card strong,.link-card span{{display:block}} .link-card span{{color:#94a3b8;margin-top:4px}}
.link-card:hover{{border-color:#67e8f9;background:#172033}}
.panel{{margin:16px 0;overflow-x:auto}} .empty{{border-color:#475569;background:#172033}}
table{{width:100%;min-width:860px;border-collapse:collapse}} th,td{{min-width:110px;padding:10px;border-bottom:1px solid #334155;text-align:left;vertical-align:top;overflow-wrap:break-word;word-break:normal}}
th:first-child,td:first-child{{min-width:72px}}
th{{color:#93c5fd;font-size:12px;text-transform:uppercase;letter-spacing:0}}
details{{margin-top:18px}} summary{{cursor:pointer;color:#67e8f9}} pre{{white-space:pre-wrap;word-break:break-word;background:#020617;padding:14px;border-radius:8px;overflow:auto}}
@media(max-width:640px){{header,main{{padding:16px}}h1{{font-size:24px}}.cards,.link-grid{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>{_html(title)}</h1><p>{_html(subtitle)}</p></header>
<main>
  <p><a href="/dashboard">Back to Agent Hub</a> | <a href="{_html(json_path)}">JSON</a></p>
  <div class="cards">{card_html}</div>
  {empty}
  {notice}
  {content}
  <details><summary>Raw payload</summary><pre>{payload}</pre></details>
</main></body></html>"""


def _empty_state_html(value: Any) -> str:
    state = _dict(value)
    if not state:
        return ""
    actions = state.get("actions") if isinstance(state.get("actions"), list) else []
    action_items = "".join(f"<li>{_html(action)}</li>" for action in actions)
    return f"""
<section class="empty">
  <h2>{_html(state.get("title", "No data yet"))}</h2>
  <p>{_html(state.get("message", ""))}</p>
  <ul>{action_items}</ul>
</section>"""


def _mapping_table_html(title: str, values: dict[str, Any], *, value_header: str) -> str:
    rows = []
    for key, value in sorted(values.items(), key=lambda item: str(item[0])):
        rows.append(f"<tr><td>{_html(key)}</td><td>{_html(_money(value))}</td></tr>")
    if not rows:
        rows.append(f"<tr><td colspan=\"2\" class=\"muted\">No {title.lower()} data yet.</td></tr>")
    return f"""
<section class="panel">
  <h2>{_html(title)}</h2>
  <table><thead><tr><th>Name</th><th>{_html(value_header)}</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</section>"""


def _usage_ledger_section_html(ledger: dict[str, Any]) -> str:
    sources = _dict(ledger.get("measurement_sources"))
    confidence = _dict(ledger.get("confidence"))
    source_label = ", ".join(
        f"{name}: {_int(count)}"
        for name, count in sorted(sources.items())
    ) or "none"
    baseline_rows = "".join(
        _usage_ledger_baseline_row_html(row)
        for row in ledger.get("baseline_savings", [])
        if isinstance(row, dict)
    )
    if not baseline_rows:
        baseline_rows = "<tr><td colspan=\"5\" class=\"muted\">No baseline comparisons have been recorded yet.</td></tr>"
    recent_rows = "".join(
        _usage_ledger_request_row_html(row)
        for row in ledger.get("recent_requests", [])
        if isinstance(row, dict)
    )
    if not recent_rows:
        recent_rows = "<tr><td colspan=\"8\" class=\"muted\">No usage ledger requests have been recorded yet.</td></tr>"
    return f"""
<section class="panel">
  <h2>Usage Ledger Baselines</h2>
  <p class="muted">SQLite: {_html(ledger.get("path"))} | requests: {_html(ledger.get("request_count", 0))} | success/failure: {_html(_int(ledger.get("success_count")))}/{_html(_int(ledger.get("failure_count")))} | confidence: {_html(confidence.get("level", "none"))} | actual usage: {_html(confidence.get("actual_usage_pct", 0.0))}% | sources: {_html(source_label)}</p>
  <table>
    <thead><tr><th>Baseline</th><th>Requests</th><th>Priced</th><th>Baseline Cost</th><th>Savings</th></tr></thead>
    <tbody>{baseline_rows}</tbody>
  </table>
</section>
<section class="panel">
  <h2>Recent Ledger Requests</h2>
  <table>
    <thead><tr><th>Time</th><th>Route</th><th>Task</th><th>Provider</th><th>Model</th><th>Cost</th><th>Source</th><th>Status</th></tr></thead>
    <tbody>{recent_rows}</tbody>
  </table>
</section>"""


def _usage_ledger_baseline_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('baseline_name'))}</td>"
        f"<td>{_html(row.get('request_count', 0))}</td>"
        f"<td>{_html(row.get('priced_count', 0))}</td>"
        f"<td>{_html(_money(row.get('baseline_cost_usd')))}</td>"
        f"<td>{_html(_money(row.get('savings_usd')))}</td>"
        "</tr>"
    )


def _usage_ledger_request_row_html(row: dict[str, Any]) -> str:
    actual = _float(row.get("cost_usd_actual"))
    estimated = _float(row.get("cost_usd_estimated"))
    cost = actual if actual is not None else estimated
    return (
        "<tr>"
        f"<td>{_html(_timestamp(row.get('timestamp')))}</td>"
        f"<td>{_html(row.get('route'))}</td>"
        f"<td>{_html(row.get('task_type'))}</td>"
        f"<td>{_html(row.get('selected_provider'))}</td>"
        f"<td>{_html(row.get('selected_model'))}</td>"
        f"<td>{_html(_money(cost))}</td>"
        f"<td>{_html(row.get('measurement_source') or row.get('cost_source'))}</td>"
        f"<td>{_html('ok' if row.get('success') else 'failed')}</td>"
        "</tr>"
    )


def _leaderboard_row_html(row: dict[str, Any]) -> str:
    samples = _int(row.get("samples"))
    success = _percent(row.get("success_rate")) if samples else "waiting"
    cost = f"{_money(row.get('cost_per_million_input'))} in / {_money(row.get('cost_per_million_output'))} out"
    score = row.get("overall_score") if samples else row.get("ranking_score", row.get("baseline_score"))
    return (
        "<tr>"
        f"<td>{_html(row.get('rank', ''))}</td>"
        f"<td>{_html(row.get('agent'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(_number(score))}</td>"
        f"<td>{_html(success)}</td>"
        f"<td>{_html(samples)}</td>"
        f"<td>{_html(_latency(row.get('average_latency_ms')))}</td>"
        f"<td>{_html(cost)}</td>"
        f"<td>{_html(row.get('measurement_status') or 'unknown')}</td>"
        "</tr>"
    )


def _benchmark_report_row_html(row: dict[str, Any]) -> str:
    summary = _dict(row.get("summary"))
    comparison = _dict(summary.get("comparison"))
    winner = comparison.get("winner") or summary.get("winner") or "unknown"
    results = row.get("results") if isinstance(row.get("results"), list) else []
    detail = []
    for key in (
        "token_reduction",
        "cost_reduction",
        "success_delta",
        "average_score_delta",
        "prompt_loops_avoided",
    ):
        if key in comparison:
            detail.append(f"{key}: {comparison[key]}")
    return (
        "<tr>"
        f"<td>{_html(row.get('name'))}</td>"
        f"<td>{_html(_timestamp(row.get('updated_at')))}</td>"
        f"<td>{_html(winner)}</td>"
        f"<td>{_html(len(results))}</td>"
        f"<td>{_html(', '.join(detail) or 'summary unavailable')}</td>"
        "</tr>"
    )


def _pricing_catalog_row_html(row: dict[str, Any]) -> str:
    estimate = _dict(row.get("sample_estimate"))
    prices = (
        f"{_money(row.get('cost_per_million_input'))} / "
        f"{_money(row.get('cost_per_million_output'))}"
    )
    return (
        "<tr>"
        f"<td>{_html(row.get('agent'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(row.get('pricing_status'))}</td>"
        f"<td>{_html(prices)}</td>"
        f"<td>{_html(_money(estimate.get('estimated_cost_usd')))}</td>"
        "</tr>"
    )


def _benchmark_snapshot_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('agent'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(row.get('benchmark_readiness_score'))}/100</td>"
        f"<td>{_html(_int(row.get('sample_count')))}</td>"
        f"<td>{_html(_latency(row.get('average_latency_ms')))}</td>"
        f"<td>{_html(row.get('measurement_status'))}</td>"
        "</tr>"
    )


def _quick_link_grid_html(links: list[tuple[str, str, str]]) -> str:
    items = "".join(
        f"<a class=\"link-card\" href=\"{_html(href)}\"><strong>{_html(label)}</strong><span>{_html(detail)}</span></a>"
        for label, href, detail in links
    )
    return f"<section class=\"link-grid\">{items}</section>"


def _kernel_subsystem_row_html(row: dict[str, Any]) -> str:
    metrics = _dict(row.get("metrics"))
    metric_text = json.dumps(metrics, sort_keys=True, ensure_ascii=False) if metrics else ""
    return (
        "<tr>"
        f"<td>{_html(row.get('id'))}</td>"
        f"<td>{_html(row.get('state'))}</td>"
        f"<td>{_html(row.get('detail'))}</td>"
        f"<td><code>{_html(metric_text)}</code></td>"
        "</tr>"
    )


def _kernel_action_row_html(row: dict[str, Any]) -> str:
    path = str(row.get("path") or "")
    link = f"<a href=\"{_html(path)}\">{_html(path)}</a>" if path else ""
    command = str(row.get("command") or "")
    return (
        "<tr>"
        f"<td>{_html(row.get('severity'))}</td>"
        f"<td>{_html(row.get('title'))}</td>"
        f"<td>{_html(row.get('detail'))}</td>"
        f"<td>{link}</td>"
        f"<td><code>{_html(command)}</code></td>"
        "</tr>"
    )


def _kernel_alert_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('severity'))}</td>"
        f"<td>{_html(row.get('id'))}</td>"
        f"<td>{_html(row.get('title'))}</td>"
        f"<td>{_html(row.get('detail'))}</td>"
        "</tr>"
    )


def _kernel_route_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('path'))}</td>"
        f"<td>{_html(row.get('count', 0))}</td>"
        f"<td>{_html(row.get('error_count', 0))}</td>"
        f"<td>{_html(_percent(row.get('error_rate')))}</td>"
        f"<td>{_html(_percent(row.get('cache_hit_rate')))}</td>"
        f"<td>{_html(_latency(row.get('average_latency_ms')))}</td>"
        f"<td>{_html(_latency(row.get('ewma_latency_ms')))}</td>"
        f"<td>{_html(row.get('last_status'))} at {_html(row.get('last_seen'))}</td>"
        "</tr>"
    )


def _kernel_slow_request_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('timestamp'))}</td>"
        f"<td>{_html(row.get('method'))}</td>"
        f"<td>{_html(row.get('path'))}</td>"
        f"<td>{_html(row.get('status'))}</td>"
        f"<td>{_html(_latency(row.get('duration_ms')))}</td>"
        f"<td>{_html(row.get('cache_state'))}</td>"
        "</tr>"
    )


def _status_provider_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('agent') or row.get('name'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{str(bool(row.get('available'))).lower()}</td>"
        f"<td>{_html(_number(row.get('score') or row.get('provider_score')))}</td>"
        f"<td>{_html(_latency(row.get('average_latency_ms') or row.get('latency_ms')))}</td>"
        f"<td>{_html(row.get('unavailable_reason') or row.get('last_error_message') or row.get('reason'))}</td>"
        "</tr>"
    )


def _provider_health_row_html(row: dict[str, Any], health: dict[str, Any]) -> str:
    agent = row.get("agent") or row.get("name")
    return (
        "<tr>"
        f"<td>{_html(agent)}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{str(bool(health.get('available', row.get('available')))).lower()}</td>"
        f"<td>{str(bool(health.get('degraded'))).lower()}</td>"
        f"<td>{_html(_percent(health.get('reliability_score')))}</td>"
        f"<td>{_html(_latency(health.get('average_latency_ms') or row.get('average_latency_ms')))}</td>"
        f"<td>{_html(_timestamp(health.get('cooldown_until') or row.get('cooldown_until')))}</td>"
        f"<td>{_html(health.get('last_error_message') or row.get('last_error_message') or row.get('unavailable_reason'))}</td>"
        "</tr>"
    )


def _production_check_row_html(row: dict[str, Any]) -> str:
    earned = row.get("earned")
    weight = row.get("weight")
    score = f"{earned}/{weight}" if weight is not None else earned
    return (
        "<tr>"
        f"<td>{_html(row.get('label') or row.get('id'))}</td>"
        f"<td>{_html(row.get('severity'))}</td>"
        f"<td>{str(bool(row.get('ok'))).lower()}</td>"
        f"<td>{_html(score)}</td>"
        f"<td>{_html(row.get('detail'))}</td>"
        f"<td><code>{_html(row.get('command'))}</code></td>"
        "</tr>"
    )


def _feature_scorecard_row_html(row: dict[str, Any]) -> str:
    passed = f"{_int(row.get('passed_required'))}/{_int(row.get('required_count'))}"
    return (
        "<tr>"
        f"<td>{_html(row.get('area'))}</td>"
        f"<td>{_html(_number(row.get('rating')))} / 10</td>"
        f"<td>{_html(row.get('state'))}</td>"
        f"<td>{_html(passed)}</td>"
        f"<td>{_html(row.get('honest_take'))}</td>"
        "</tr>"
    )


def _limit_row_html(row: dict[str, Any]) -> str:
    requests = row.get("requests_remaining") if row.get("requests_remaining") is not None else row.get("remaining")
    tokens = row.get("tokens_remaining") if row.get("tokens_remaining") is not None else row.get("quota_remaining")
    return (
        "<tr>"
        f"<td>{_html(row.get('agent'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{str(bool(row.get('available'))).lower()}</td>"
        f"<td>{_html(requests)}</td>"
        f"<td>{_html(tokens)}</td>"
        f"<td>{_html(_timestamp(row.get('cooldown_until')))}</td>"
        f"<td>{_html(row.get('last_error_message') or row.get('unavailable_reason'))}</td>"
        "</tr>"
    )


def _recommendation_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('agent') or row.get('name'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{str(bool(row.get('available'))).lower()}</td>"
        f"<td>{_html(row.get('reason') or row.get('why') or row.get('unavailable_reason'))}</td>"
        "</tr>"
    )


def _event_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(_timestamp(row.get('time') or row.get('timestamp')))}</td>"
        f"<td>{_html(row.get('type') or row.get('name') or row.get('event'))}</td>"
        f"<td>{_html(row.get('agent') or row.get('provider'))}</td>"
        f"<td>{_html(row.get('model') or row.get('tool') or row.get('workflow'))}</td>"
        f"<td>{_html(row.get('message') or row.get('reason') or row.get('detail') or row.get('status'))}</td>"
        "</tr>"
    )


def _tool_row_html(row: dict[str, Any]) -> str:
    schema = _dict(row.get("input_schema") or row.get("parameters"))
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    properties = _dict(schema.get("properties"))
    return (
        "<tr>"
        f"<td>{_html(row.get('name'))}</td>"
        f"<td>{_html(row.get('description'))}</td>"
        f"<td>{_html(row.get('permission'))}</td>"
        f"<td>{_html(', '.join(str(item) for item in required))}</td>"
        f"<td>{_html(', '.join(properties.keys()))}</td>"
        "</tr>"
    )


def _workflow_run_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('workflow_id'))}</td>"
        f"<td>{_html(row.get('workflow'))}</td>"
        f"<td>{_html(row.get('workflow_pattern'))}</td>"
        f"<td>{_html(row.get('status'))}</td>"
        f"<td>{_html(row.get('stage_count'))}</td>"
        f"<td>{_html(_timestamp(row.get('started_at')))}</td>"
        f"<td>{_html(_timestamp(row.get('updated_at')))}</td>"
        "</tr>"
    )


def _workflow_preset_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('id'))}</td>"
        f"<td>{_html(row.get('task_type'))}</td>"
        f"<td>{_html(row.get('workflow_pattern'))}</td>"
        f"<td>{_html(row.get('description') or row.get('label'))}</td>"
        "</tr>"
    )


def _plugin_row_html(row: dict[str, Any]) -> str:
    scopes = row.get("scopes") if isinstance(row.get("scopes"), list) else row.get("requested_scopes")
    scopes_text = ", ".join(str(item) for item in scopes) if isinstance(scopes, list) else ""
    return (
        "<tr>"
        f"<td>{_html(row.get('id') or row.get('plugin_id'))}</td>"
        f"<td>{_html(row.get('name'))}</td>"
        f"<td>{_html(row.get('type') or row.get('kind'))}</td>"
        f"<td>{str(bool(row.get('enabled'))).lower()}</td>"
        f"<td>{_html(scopes_text)}</td>"
        "</tr>"
    )


def _mcp_server_row_html(row: dict[str, Any]) -> str:
    warnings = row.get("warnings") if isinstance(row.get("warnings"), list) else []
    return (
        "<tr>"
        f"<td>{_html(row.get('name'))}</td>"
        f"<td>{_html(row.get('status'))}</td>"
        f"<td>{str(bool(row.get('enabled'))).lower()}</td>"
        f"<td>{str(bool(row.get('command_configured'))).lower()}</td>"
        f"<td>{_html(row.get('tool_count', 0))}</td>"
        f"<td>{_html(', '.join(str(item) for item in warnings))}</td>"
        "</tr>"
    )


def _mcp_tool_row_html(row: dict[str, Any]) -> str:
    permissions = row.get("permissions") if isinstance(row.get("permissions"), list) else []
    inputs = row.get("input_properties") if isinstance(row.get("input_properties"), list) else []
    return (
        "<tr>"
        f"<td><code>{_html(row.get('qualified_name') or row.get('name'))}</code></td>"
        f"<td>{_html(row.get('server'))}</td>"
        f"<td>{_html(row.get('status'))}</td>"
        f"<td>{str(bool(row.get('read_only'))).lower()}</td>"
        f"<td>{_html(', '.join(str(item) for item in permissions))}</td>"
        f"<td>{_html(', '.join(str(item) for item in inputs))}</td>"
        "</tr>"
    )


def _enterprise_rows_section_html(title: str, rows: list[Any]) -> str:
    body = "".join(
        f"<tr><td>{_html(_dict(row).get('id') or _dict(row).get('name'))}</td><td>{_html(json.dumps(row, ensure_ascii=False, default=str))}</td></tr>"
        for row in rows
        if isinstance(row, dict)
    )
    if not body:
        body = "<tr><td colspan=\"2\" class=\"muted\">No rows configured.</td></tr>"
    return f"""
<section class="panel">
  <h2>{_html(title)}</h2>
  <table><thead><tr><th>ID</th><th>Details</th></tr></thead><tbody>{body}</tbody></table>
</section>"""


def _provider_score_row_html(agent: str, row: dict[str, Any]) -> str:
    successes = _int(row.get("successes"))
    failures = _int(row.get("failures"))
    samples = _int(row.get("sample_count")) or successes + failures
    task_scores = _dict(row.get("task_scores"))
    task_text = ", ".join(
        f"{key}: {_number(value)}" for key, value in sorted(task_scores.items())
    )
    success_rate = successes / samples if samples else None
    return (
        "<tr>"
        f"<td>{_html(agent)}</td>"
        f"<td>{_html(_number(row.get('overall_score')))}</td>"
        f"<td>{_html(_percent(success_rate))}</td>"
        f"<td>{_html(failures)}</td>"
        f"<td>{_html(samples)}</td>"
        f"<td>{_html(_latency(row.get('average_latency_ms')))}</td>"
        f"<td>{_html(_money(row.get('average_known_cost_usd')))}</td>"
        f"<td>{_html(task_text or 'waiting')}</td>"
        "</tr>"
    )


def _routing_history_row_html(row: dict[str, Any]) -> str:
    data = _dict(row.get("data"))
    return (
        "<tr>"
        f"<td>{_html(_timestamp(row.get('timestamp') or data.get('timestamp')))}</td>"
        f"<td>{_html(row.get('type') or row.get('event') or data.get('type'))}</td>"
        f"<td>{_html(row.get('agent') or data.get('agent'))}</td>"
        f"<td>{_html(row.get('provider') or data.get('provider'))}</td>"
        f"<td>{_html(row.get('model') or data.get('model'))}</td>"
        f"<td>{_html(row.get('reason') or row.get('message') or data.get('reason') or data.get('message'))}</td>"
        "</tr>"
    )


def _learning_model_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('agent'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(_percent(row.get('success_rate')))}</td>"
        f"<td>{_html(row.get('failures', 0))}</td>"
        f"<td>{_html(_number(row.get('average_latency_ms')))} ms</td>"
        f"<td>{_html(row.get('adaptive_bonus', 0.0))}</td>"
        f"<td>{_html(row.get('attempts', 0))}</td>"
        "</tr>"
    )


def _learning_change_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('agent'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(row.get('direction'))}</td>"
        f"<td>{_html(row.get('reason'))}</td>"
        "</tr>"
    )


def _route_history_week_row_html(row: dict[str, Any]) -> str:
    distribution = row.get("distribution") if isinstance(row.get("distribution"), dict) else {}
    label = ", ".join(
        f"{name}: {_number(item.get('percentage'))}%"
        for name, item in sorted(
            distribution.items(),
            key=lambda pair: -(_float(pair[1].get("percentage")) or 0.0)
            if isinstance(pair[1], dict)
            else 0.0,
        )
        if isinstance(item, dict)
    ) or "No routes"
    return (
        "<tr>"
        f"<td>{_html(row.get('week'))}</td>"
        f"<td>{_html(row.get('route_count', 0))}</td>"
        f"<td>{_html(label)}</td>"
        "</tr>"
    )


def _readiness_item_row_html(row: dict[str, Any]) -> str:
    score = row.get("score")
    max_score = row.get("max_score") or row.get("weight")
    score_text = f"{score}/{max_score}" if max_score is not None else score
    return (
        "<tr>"
        f"<td>{_html(row.get('label') or row.get('id'))}</td>"
        f"<td>{_html(row.get('status'))}</td>"
        f"<td>{_html(score_text)}</td>"
        f"<td>{_html(row.get('weight'))}</td>"
        f"<td>{_html(row.get('detail'))}</td>"
        f"<td><code>{_html(row.get('command'))}</code></td>"
        "</tr>"
    )


def _feature_status_row_html(name: str, row: dict[str, Any]) -> str:
    detail = row.get("detail") or row.get("message") or row.get("reason") or ""
    ready = row.get("ready")
    if ready is None:
        ready = row.get("state") == "ready"
    return (
        "<tr>"
        f"<td>{_html(name.replace('_', ' '))}</td>"
        f"<td>{_html(row.get('state'))}</td>"
        f"<td>{str(bool(ready)).lower()}</td>"
        f"<td>{_html(detail)}</td>"
        "</tr>"
    )


def _key_value_section_html(title: str, rows: list[tuple[str, Any]]) -> str:
    body = "".join(
        f"<tr><td>{_html(label)}</td><td>{_html(value)}</td></tr>"
        for label, value in rows
        if value not in (None, "")
    )
    if not body:
        body = "<tr><td colspan=\"2\" class=\"muted\">No data yet.</td></tr>"
    return f"""
<section class="panel">
  <h2>{_html(title)}</h2>
  <table><thead><tr><th>Signal</th><th>Value</th></tr></thead><tbody>{body}</tbody></table>
</section>"""


def _list_section_html(title: str, values: Any) -> str:
    rows = values if isinstance(values, list) else []
    body = "".join(f"<tr><td>{_html(value)}</td></tr>" for value in rows)
    if not body:
        body = "<tr><td class=\"muted\">No data yet.</td></tr>"
    return f"""
<section class="panel">
  <h2>{_html(title)}</h2>
  <table><tbody>{body}</tbody></table>
</section>"""


def _inbox_file_table_html(title: str, values: Any) -> str:
    rows = values if isinstance(values, list) else []
    body = "".join(
        "<tr>"
        f"<td>{_html(_dict(row).get('name'))}</td>"
        f"<td>{_html('yes' if _dict(row).get('valid', True) else 'no')}</td>"
        f"<td>{_html(_dict(row).get('api_shape') or '')}</td>"
        f"<td>{_html(_dict(row).get('message_count') if _dict(row).get('message_count') is not None else '')}</td>"
        f"<td>{_html(_dict(row).get('preview') or _dict(row).get('error') or '')}</td>"
        f"<td>{_html(_timestamp(_dict(row).get('modified_at')))}</td>"
        f"<td><code>{_html(_dict(row).get('path'))}</code></td>"
        "</tr>"
        for row in rows
        if isinstance(row, dict)
    )
    if not body:
        body = "<tr><td colspan=\"7\" class=\"muted\">No files.</td></tr>"
    return f"""
<section class="panel">
  <h2>{_html(title)}</h2>
  <table><thead><tr><th>Name</th><th>Valid</th><th>Shape</th><th>Messages</th><th>Preview/Error</th><th>Modified</th><th>Path</th></tr></thead><tbody>{body}</tbody></table>
</section>"""


def _mapping_section_html(title: str, values: dict[str, Any]) -> str:
    body = "".join(
        f"<tr><td>{_html(key)}</td><td>{_html(value)}</td></tr>"
        for key, value in sorted(values.items())
    )
    if not body:
        body = "<tr><td colspan=\"2\" class=\"muted\">No data yet.</td></tr>"
    return f"""
<section class="panel">
  <h2>{_html(title)}</h2>
  <table><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody>{body}</tbody></table>
</section>"""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _html(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> str:
    number = _float(value)
    return "unknown" if number is None else f"{number:.3f}".rstrip("0").rstrip(".")


def _money(value: Any) -> str:
    number = _float(value)
    return "unknown" if number is None else f"${number:.6f}".rstrip("0").rstrip(".")


def _percent(value: Any) -> str:
    number = _float(value)
    return "unknown" if number is None else f"{number * 100:.1f}%"


def _pct(value: Any) -> str:
    number = _float(value)
    return "unknown" if number is None else f"{number:.1f}%"


def _pp(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "unknown"
    return f"{number:+.1f} pp"


def _latency(value: Any) -> str:
    number = _float(value)
    return "unknown" if number is None or number <= 0 else f"{number:.1f} ms"


def _duration(value: Any) -> str:
    seconds = _float(value)
    if seconds is None or seconds < 0:
        return "unknown"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f} min"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} d"


def _timestamp(value: Any) -> str:
    number = _float(value)
    if number is None or number <= 0:
        return "unknown"
    return datetime.fromtimestamp(number).strftime("%Y-%m-%d %H:%M:%S")
