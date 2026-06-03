from __future__ import annotations

import time
from typing import Any

from ..api.compatibility import apply_model_routing, model_lookup_error, openai_model_rows
from ..application import BACKEND_FEATURES, BACKEND_VERSION, DiagnosticsApplicationService
from ..config import HubConfig
from ..models import HubRequest
from ..observability import recent_events, usage_snapshot
from ..core.router import AgentRouter

def _record_debug_request(server: AgentHubHTTPServer, entry: dict[str, Any]) -> None:
    entry = {"time": time.time(), **entry}
    server.debug_requests.append(entry)
    if len(server.debug_requests) > 100:
        del server.debug_requests[:-100]

def _debug_context_summary(server: AgentHubHTTPServer) -> dict[str, Any]:
    recent = server.debug_requests[-20:]
    if not recent:
        return {
            "request_count": 0,
            "incoming_token_count": 0,
            "compacted_token_count": 0,
            "protected_token_count": 0,
            "warning": "",
        }
    latest = recent[-1].get("diagnostics") if isinstance(recent[-1], dict) else {}
    diagnostics = latest if isinstance(latest, dict) else {}
    suspicious = [
        item
        for item in recent
        if isinstance(item.get("diagnostics"), dict)
        and item["diagnostics"].get("suspiciously_empty")
    ]
    return {
        "request_count": len(recent),
        "incoming_context_size": diagnostics.get("incoming_token_count", 0),
        "preserved_context_size": diagnostics.get("compacted_token_count", 0),
        "compacted_amount": diagnostics.get("dropped_token_count", 0),
        "incoming_token_count": diagnostics.get("incoming_token_count", 0),
        "compacted_token_count": diagnostics.get("compacted_token_count", 0),
        "protected_token_count": diagnostics.get("protected_token_count", 0),
        "preserved_tool_calls": diagnostics.get("preserved_tool_calls", 0),
        "preserved_tool_results": diagnostics.get("preserved_tool_results", 0),
        "preserved_todo_count": diagnostics.get("preserved_todo_count", 0),
        "active_files_detected": diagnostics.get("active_files_detected", []),
        "task_progress_present": diagnostics.get("task_progress_present", False),
        "suspiciously_empty": diagnostics.get("suspiciously_empty", False),
        "warning": (
            "Incoming context looks suspiciously empty; check Cline/Claude Code setup and active workspace state."
            if suspicious
            else ""
        ),
    }

def _routing_diagnostics_module() -> Any:
    return __import__("agent_hub.routing_diagnostics", fromlist=["routing_diagnostics"])

def _routing_failures(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _routing_diagnostics_module().routing_failures(events)

def _recent_workflow_stages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _routing_diagnostics_module().recent_workflow_stages(events)

def _routing_status_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    return _routing_diagnostics_module().routing_status_body(config, router)

def _routing_last_decision_body(config: HubConfig) -> dict[str, Any]:
    return _routing_diagnostics_module().routing_last_decision_body(config)

def _routing_test_failover_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    return _routing_diagnostics_module().routing_test_failover_body(config, router)

def _client_sources_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    return _routing_diagnostics_module().client_sources_body(config, router)

def _routing_history_body(config: HubConfig) -> dict[str, Any]:
    return _routing_diagnostics_module().routing_history_body(config)

def _provider_health_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    return _routing_diagnostics_module().provider_health_body(config, router)

def _routing_memory_stats_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    return _routing_diagnostics_module().routing_memory_stats_body(config, router)

def _routing_memory_recent_body(config: HubConfig, router: AgentRouter, *, limit: int = 50) -> dict[str, Any]:
    return _routing_diagnostics_module().routing_memory_recent_body(config, router, limit=limit)

def _routing_decision_by_id_body(config: HubConfig, router: AgentRouter, request_id: str) -> dict[str, Any]:
    return _routing_diagnostics_module().routing_decision_by_id_body(config, router, request_id)

def _status_body(
    config: HubConfig,
    router: AgentRouter,
    *,
    provider_scores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    health = router.health_snapshot(include_history=True)
    routing = recent_events(config.state_dir, "routing", limit=50)
    tools = recent_events(config.state_dir, "tools", limit=50)
    permissions = recent_events(config.state_dir, "permissions", limit=50)
    workflows = recent_events(config.state_dir, "workflows", limit=50)
    latest = routing[-1] if routing else {}
    latest_decision = latest.get("routing_decision") if isinstance(latest.get("routing_decision"), dict) else {}
    return {
        "object": "agent_hub.status",
        "status": "running",
        "running": True,
        "version": BACKEND_VERSION,
        "features": BACKEND_FEATURES,
        "workspace_dir": str(config.workspace_dir),
        "active_providers": _active_provider_names(config, router),
        "providers": router.provider_status(),
        "provider_health": health,
        "provider_scores": provider_scores if provider_scores is not None else dict(router.provider_scores),
        "selected_model": latest.get("model") or latest.get("selected_model"),
        "selected_provider": latest.get("provider") or latest_decision.get("selected_provider"),
        "routing_reason": latest_decision.get("reason") or latest.get("reason") or "",
        "routing_decision": latest_decision,
        "cost_context_estimate": _routing_diagnostics_module()._cost_context_estimate(latest),
        "stream_mode": latest.get("stream_mode") or ("native" if latest.get("type") == "streaming_decision" else "compatibility"),
        "token_usage": usage_snapshot(config.state_dir, health),
        "fallback_history": _routing_failures(routing),
        "workflow_stages": _recent_workflow_stages(routing),
        "workflow_progress": workflows[-25:],
        "permission_blocked_actions": [
            item
            for item in permissions
            if item.get("denied") is True or item.get("requires_approval") is True
        ][-25:],
        "tool_calls": tools[-25:],
        "routing_history_count": len(routing),
    }

def _events_body(config: HubConfig) -> dict[str, Any]:
    return {
        "object": "agent_hub.events",
        "events": recent_events(config.state_dir, "events", limit=100),
        "routing": recent_events(config.state_dir, "routing", limit=50),
        "workflows": recent_events(config.state_dir, "workflows", limit=50),
        "adaptive": recent_events(config.state_dir, "adaptive", limit=50),
    }

def _tools_body(router: AgentRouter) -> dict[str, Any]:
    tools = [tool.to_agent_hub_spec() for tool in router.tool_registry.list()]
    return {
        "object": "agent_hub.tools",
        "count": len(tools),
        "tools": tools,
    }

def _workflow_status_body(config: HubConfig) -> dict[str, Any]:
    events = recent_events(config.state_dir, "workflows", limit=100)
    return {
        "object": "agent_hub.workflow_status",
        "recent": events,
        "active": [],
        "count": len(events),
    }

def _plugins_body(config: HubConfig) -> dict[str, Any]:
    return DiagnosticsApplicationService(config).plugins_body()

def _enterprise_audit_body(config: HubConfig, query: dict[str, str] | None = None) -> dict[str, Any]:
    return DiagnosticsApplicationService(config).enterprise_audit_body(query)

def _provider_row_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(row.get('health'))}</td>"
        f"<td>{_html(row.get('score'))}</td>"
        f"<td>{_html(row.get('latency_ms'))} ms</td>"
        f"<td>{str(bool(row.get('supports_tools'))).lower()}</td>"
        "</tr>"
    )

def _optimization_dashboard_html(optimization: dict[str, Any]) -> str:
    workflow_rate = optimization.get("workflow_success_rate")
    workflow_rate = workflow_rate if isinstance(workflow_rate, dict) else {}
    avg_cost = optimization.get("average_known_cost_usd")
    avg_latency = optimization.get("average_latency_ms")
    recovered = optimization.get("failed_requests_recovered", 0)
    total_retries = optimization.get("total_retries", 0)
    avg_retries = optimization.get("average_retries", 0)
    dashboard = optimization.get("dashboard") if isinstance(optimization.get("dashboard"), dict) else {}
    recommendations = dashboard.get("recommendations") if isinstance(dashboard.get("recommendations"), list) else []
    task_winners = optimization.get("task_model_winners") if isinstance(optimization.get("task_model_winners"), dict) else {}
    role_winners = optimization.get("role_model_winners") if isinstance(optimization.get("role_model_winners"), dict) else {}
    model_rates = optimization.get("model_win_rates") if isinstance(optimization.get("model_win_rates"), list) else []
    providers = optimization.get("most_effective_providers") if isinstance(optimization.get("most_effective_providers"), list) else []
    workflow_analytics = optimization.get("workflow_analytics") if isinstance(optimization.get("workflow_analytics"), list) else []
    workflows = optimization.get("workflow_patterns") if isinstance(optimization.get("workflow_patterns"), list) else []
    recent = optimization.get("recent_optimization_decisions") if isinstance(optimization.get("recent_optimization_decisions"), list) else []
    routing_memory = optimization.get("routing_memory") if isinstance(optimization.get("routing_memory"), dict) else {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Hub Optimization</title>
  <style>
    body {{
      margin: 0;
      padding: 28px;
      color: #202124;
      background: #f6f7f9;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1180px; margin: 0 auto; }}
    header {{ margin-bottom: 18px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    h2 {{ margin: 28px 0 10px; font-size: 18px; }}
    p {{ margin: 0 0 14px; color: #5f6368; }}
    a {{ color: #0b57d0; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 12px;
      margin: 16px 0 8px;
    }}
    .card {{
      border: 1px solid #d8dde6;
      border-radius: 8px;
      padding: 14px;
      background: #fff;
    }}
    .card strong {{ display: block; font-size: 24px; color: #111827; }}
    .card span {{ display: block; margin-top: 3px; color: #5f6368; font-size: 13px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border: 1px solid #d8dde6;
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      padding: 9px 10px;
      border-bottom: 1px solid #e7eaf0;
      text-align: left;
      font-size: 13px;
      vertical-align: top;
    }}
    th {{ color: #374151; background: #eef2f7; font-weight: 650; }}
    tr:last-child td {{ border-bottom: 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }}
    .note {{ color: #5f6368; font-size: 13px; margin-top: 8px; }}
    code {{ padding: 2px 5px; border-radius: 4px; background: #eef2f7; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Optimization Dashboard</h1>
      <p>Adaptive routing, workflow selection, cost, latency, and provider effectiveness.</p>
      <p><a href="/dashboard">Back to Agent Hub</a> · <a href="/v1/optimization">JSON</a></p>
    </header>
    <section class="cards">
      <div class="card"><strong>{_html(_percent_label(workflow_rate.get("rate")))}</strong><span>workflow success over {_html(workflow_rate.get("attempts", 0))} sample(s)</span></div>
      <div class="card"><strong>{_html(_money_label(avg_cost))}</strong><span>average known cost</span></div>
      <div class="card"><strong>{_html(_ms_label(avg_latency))}</strong><span>average latency</span></div>
      <div class="card"><strong>{_html(recovered)}</strong><span>failed requests recovered</span></div>
      <div class="card"><strong>{_html(avg_retries)}</strong><span>average retries over {_html(total_retries)} total</span></div>
    </section>
    <section>
      <h2>Recommendations</h2>
      {_recommendation_list_html(recommendations)}
    </section>
    <section class="grid">
      <div>
        <h2>Best Models By Task</h2>
        {_task_winners_table_html(task_winners)}
      </div>
      <div>
        <h2>Best Models By Workflow Role</h2>
        {_role_winners_table_html(role_winners)}
      </div>
    </section>
    <section>
      <h2>Model Win Rates</h2>
      {_model_win_rates_table_html(model_rates)}
    </section>
    <section>
      <h2>Most Effective Providers</h2>
      {_provider_effectiveness_table_html(providers)}
    </section>
    <section>
      <h2>Routing Memory</h2>
      {_routing_memory_dashboard_html(routing_memory)}
    </section>
    <section>
      <h2>Workflow Analytics</h2>
      {_workflow_analytics_table_html(workflow_analytics)}
    </section>
    <section>
      <h2>Workflow Patterns</h2>
      {_workflow_patterns_table_html(workflows)}
    </section>
    <section>
      <h2>Recent Adaptive Decisions</h2>
      {_recent_adaptive_table_html(recent)}
      <p class="note">Use <code>POST /v1/routing/simulate</code> to preview routing and workflow choices without making a provider call.</p>
    </section>
  </main>
</body>
</html>"""

def _routing_memory_dashboard_html(memory: dict[str, Any]) -> str:
    if not memory:
        return '<p class="note">No routing memory samples yet.</p>'
    fallback = memory.get("fallback_frequency") if isinstance(memory.get("fallback_frequency"), dict) else {}
    winner = memory.get("cost_performance_winner") if isinstance(memory.get("cost_performance_winner"), dict) else {}
    success = memory.get("most_successful_models_by_task_type") if isinstance(memory.get("most_successful_models_by_task_type"), list) else []
    failure = memory.get("failure_prone_models_by_task_type") if isinstance(memory.get("failure_prone_models_by_task_type"), list) else []
    latency = memory.get("average_latency_by_provider") if isinstance(memory.get("average_latency_by_provider"), list) else []
    influence = memory.get("routing_memory_influence_per_request") if isinstance(memory.get("routing_memory_influence_per_request"), list) else []
    return f"""
      <div class="cards">
        <div class="card"><strong>{_html(memory.get("total_records", 0))}</strong><span>metadata outcome records</span></div>
        <div class="card"><strong>{_html(_percent_label(fallback.get("rate", 0)))}</strong><span>fallback frequency</span></div>
        <div class="card"><strong>{_html(_model_label(winner))}</strong><span>cost/performance winner</span></div>
      </div>
      <div class="grid">
        <div>
          <h2>Successful Models By Task</h2>
          {_memory_success_table_html(success)}
        </div>
        <div>
          <h2>Failure-Prone Models By Task</h2>
          {_memory_failure_table_html(failure)}
        </div>
      </div>
      <div class="grid">
        <div>
          <h2>Provider Latency</h2>
          {_memory_latency_table_html(latency)}
        </div>
        <div>
          <h2>Memory Influence</h2>
          {_memory_influence_table_html(influence)}
        </div>
      </div>
    """

def _task_winners_table_html(rows: dict[str, Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(task)}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(_percent_label(row.get('success_rate')))}</td>"
        f"<td>{_html(row.get('attempts', 0))}</td>"
        f"<td>{_html(_money_label(row.get('average_known_cost_usd')))}</td>"
        "</tr>"
        for task, row in sorted(rows.items())
        if isinstance(row, dict)
    )
    return _table_or_empty(
        ["Task", "Provider", "Model", "Success", "Samples", "Avg Cost"],
        body,
    )

def _role_winners_table_html(rows: dict[str, Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(role)}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(_percent_label(row.get('success_rate')))}</td>"
        f"<td>{_html(row.get('attempts', 0))}</td>"
        f"<td>{_html(_ms_label(row.get('average_latency_ms')))}</td>"
        "</tr>"
        for role, row in sorted(rows.items())
        if isinstance(row, dict)
    )
    return _table_or_empty(
        ["Role", "Provider", "Model", "Success", "Samples", "Avg Latency"],
        body,
    )

def _model_win_rates_table_html(rows: list[Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(row.get('task_type'))}</td>"
        f"<td>{_html(row.get('agent'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(_percent_label(row.get('success_rate')))}</td>"
        f"<td>{_html(row.get('attempts', 0))}</td>"
        f"<td>{_html(row.get('adaptive_bonus', 0.0))}</td>"
        "</tr>"
        for row in rows[:25]
        if isinstance(row, dict)
    )
    return _table_or_empty(
        ["Task", "Agent", "Provider", "Model", "Success", "Samples", "Adaptive Bonus"],
        body,
    )

def _provider_effectiveness_table_html(rows: list[Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(_percent_label(row.get('success_rate')))}</td>"
        f"<td>{_html(row.get('attempts', 0))}</td>"
        f"<td>{_html(_ms_label(row.get('average_latency_ms')))}</td>"
        f"<td>{_html(_money_label(row.get('average_known_cost_usd')))}</td>"
        f"<td>{_html(', '.join(row.get('models', [])[:4]) if isinstance(row.get('models'), list) else '')}</td>"
        "</tr>"
        for row in rows[:10]
        if isinstance(row, dict)
    )
    return _table_or_empty(
        ["Provider", "Success", "Samples", "Avg Latency", "Avg Cost", "Models"],
        body,
    )

def _memory_success_table_html(rows: list[Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(row.get('task_type'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(_percent_label(row.get('success_rate')))}</td>"
        f"<td>{_html(row.get('attempts', 0))}</td>"
        f"<td>{_html(row.get('average_outcome_score'))}</td>"
        "</tr>"
        for row in rows[:12]
        if isinstance(row, dict)
    )
    return _table_or_empty(
        ["Task", "Provider", "Model", "Success", "Samples", "Score"],
        body,
    )

def _memory_failure_table_html(rows: list[Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(row.get('task_type'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(_percent_label(row.get('failure_rate')))}</td>"
        f"<td>{_html(_percent_label(row.get('timeout_rate')))}</td>"
        f"<td>{_html(row.get('attempts', 0))}</td>"
        "</tr>"
        for row in rows[:12]
        if isinstance(row, dict)
    )
    return _table_or_empty(
        ["Task", "Provider", "Model", "Failure", "Timeout", "Samples"],
        body,
    )

def _memory_latency_table_html(rows: list[Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(_ms_label(row.get('average_latency_ms')))}</td>"
        f"<td>{_html(row.get('samples', 0))}</td>"
        "</tr>"
        for row in rows[:12]
        if isinstance(row, dict)
    )
    return _table_or_empty(["Provider", "Avg Latency", "Samples"], body)

def _memory_influence_table_html(rows: list[Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(row.get('request_id'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(row.get('memory_adjustment'))}</td>"
        f"<td>{_html(row.get('outcome_score'))}</td>"
        "</tr>"
        for row in rows[:12]
        if isinstance(row, dict)
    )
    return _table_or_empty(["Request", "Provider", "Model", "Adjustment", "Outcome"], body)

def _model_label(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict) or not row:
        return "learning pending"
    return " / ".join(str(row.get(key) or "") for key in ("provider", "model") if row.get(key)) or "learning pending"

def _workflow_analytics_table_html(rows: list[Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(row.get('label') or row.get('workflow_pattern'))}</td>"
        f"<td>{_html(row.get('task_type'))}</td>"
        f"<td>{_html(_percent_label(row.get('success_rate')))}</td>"
        f"<td>{_html(row.get('attempts', 0))}</td>"
        f"<td>{_html(_money_label(row.get('average_known_cost_usd')))}</td>"
        f"<td>{_html(_ms_label(row.get('average_latency_ms')))}</td>"
        f"<td>{_html(row.get('average_retries', 0))}</td>"
        f"<td>{_html(row.get('recovered_by_failover_count', 0))}</td>"
        f"<td>{_html(_role_label(row.get('best_planner')))}</td>"
        f"<td>{_html(_role_label(row.get('best_worker')))}</td>"
        "</tr>"
        for row in rows[:25]
        if isinstance(row, dict)
    )
    return _table_or_empty(
        ["Workflow", "Task", "Success", "Samples", "Avg Cost", "Avg Time", "Avg Retries", "Recovered", "Best Planner", "Best Worker"],
        body,
    )

def _workflow_patterns_table_html(rows: list[Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(row.get('workflow_pattern'))}</td>"
        f"<td>{_html(_percent_label(row.get('success_rate')))}</td>"
        f"<td>{_html(row.get('attempts', 0))}</td>"
        f"<td>{_html(_ms_label(row.get('average_latency_ms')))}</td>"
        f"<td>{_html(row.get('average_retries', 0))}</td>"
        f"<td>{_html(row.get('recovered_by_failover_count', 0))}</td>"
        "</tr>"
        for row in rows
        if isinstance(row, dict)
    )
    return _table_or_empty(
        ["Pattern", "Success", "Samples", "Avg Latency", "Avg Retries", "Recovered"],
        body,
    )

def _recent_adaptive_table_html(rows: list[Any]) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_html(row.get('task_type'))}</td>"
        f"<td>{_html(row.get('workflow_pattern'))}</td>"
        f"<td>{_html(row.get('agent'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{str(bool(row.get('success'))).lower()}</td>"
        f"<td>{_html(row.get('latency_ms'))}</td>"
        f"<td>{_html(_money_label(row.get('estimated_cost_usd')))}</td>"
        f"<td>{_html(row.get('retry_count', 0))}</td>"
        "</tr>"
        for row in rows[-25:]
        if isinstance(row, dict)
    )
    return _table_or_empty(
        ["Task", "Workflow", "Agent", "Model", "Success", "Latency ms", "Cost", "Retries"],
        body,
    )

def _recommendation_list_html(rows: list[Any]) -> str:
    items = [
        f"<li>{_html(row.get('message') if isinstance(row, dict) else row)}</li>"
        for row in rows
    ]
    return "<ul>" + "".join(items) + "</ul>" if items else "<p>No optimization recommendations yet.</p>"

def _table_or_empty(headers: list[str], body: str) -> str:
    if not body:
        return "<p>No samples yet.</p>"
    head = "".join(f"<th>{_html(header)}</th>" for header in headers)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

def _percent_label(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "--"

def _money_label(value: Any) -> str:
    try:
        return f"${float(value):.4f}"
    except (TypeError, ValueError):
        return "--"

def _ms_label(value: Any) -> str:
    try:
        return f"{float(value):.0f} ms"
    except (TypeError, ValueError):
        return "--"

def _role_label(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return " / ".join(str(row.get(key) or "") for key in ("provider", "model") if row.get(key))

def _html(value: Any) -> str:
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

def _limits_body(config: HubConfig, router: AgentRouter) -> dict[str, Any]:
    return DiagnosticsApplicationService(config).limits_body(router)

def _active_provider_names(config: HubConfig, router: AgentRouter) -> list[str]:
    return DiagnosticsApplicationService(config).active_provider_names(router)

def _available_model_ids(config: HubConfig, router: AgentRouter) -> list[str]:
    return DiagnosticsApplicationService(config).available_model_ids(router)

def _openai_model_rows(
    config: HubConfig,
    router: AgentRouter,
    *,
    include_routing_details: bool = False,
) -> list[dict[str, Any]]:
    return openai_model_rows(
        config,
        router,
        include_routing_details=include_routing_details,
    )

def _model_rows(config: HubConfig, router: AgentRouter) -> list[dict[str, Any]]:
    return DiagnosticsApplicationService(config).model_rows(router)

def _apply_model_routing(config: HubConfig, request: HubRequest) -> None:
    apply_model_routing(config, request)

def _model_lookup_error(config: HubConfig, request: HubRequest) -> dict[str, Any] | None:
    return model_lookup_error(config, request)

__all__ = [
    '_record_debug_request',
    '_debug_context_summary',
    '_routing_diagnostics_module',
    '_routing_failures',
    '_recent_workflow_stages',
    '_routing_status_body',
    '_routing_last_decision_body',
    '_routing_test_failover_body',
    '_client_sources_body',
    '_routing_history_body',
    '_provider_health_body',
    '_routing_memory_stats_body',
    '_routing_memory_recent_body',
    '_routing_decision_by_id_body',
    '_status_body',
    '_events_body',
    '_tools_body',
    '_workflow_status_body',
    '_plugins_body',
    '_enterprise_audit_body',
    '_provider_row_html',
    '_optimization_dashboard_html',
    '_task_winners_table_html',
    '_role_winners_table_html',
    '_model_win_rates_table_html',
    '_provider_effectiveness_table_html',
    '_workflow_analytics_table_html',
    '_workflow_patterns_table_html',
    '_recent_adaptive_table_html',
    '_recommendation_list_html',
    '_table_or_empty',
    '_percent_label',
    '_money_label',
    '_ms_label',
    '_role_label',
    '_html',
    '_limits_body',
    '_active_provider_names',
    '_available_model_ids',
    '_openai_model_rows',
    '_model_rows',
    '_apply_model_routing',
    '_model_lookup_error',
]
