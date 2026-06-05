from __future__ import annotations

from datetime import datetime
import html
import json
from typing import Any

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


def _cost_dashboard_html(body: dict[str, Any]) -> str:
    summary = _dict(body.get("summary"))
    cards = [
        ("Known cost", _money(body.get("known_cost_usd"))),
        ("Average known cost", _money(body.get("average_known_cost_usd"))),
        ("Providers tracked", summary.get("providers_tracked", 0)),
        ("State", summary.get("data_state", "unknown")),
    ]
    content = "\n".join(
        [
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
        ("Samples", summary.get("sample_count", 0)),
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
    cards = [
        ("Reports", summary.get("report_count", len(reports))),
        ("Latest", summary.get("latest_report") or "none"),
        ("Results", summary.get("total_result_count", 0)),
        ("State", summary.get("data_state", "unknown")),
    ]
    table_rows = "".join(_benchmark_report_row_html(row) for row in reports if isinstance(row, dict))
    if not table_rows:
        table_rows = "<tr><td colspan=\"5\" class=\"muted\">No benchmark reports found.</td></tr>"
    content = f"""
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
    card_html = "".join(
        f"<div class=\"card\"><strong>{_html(value)}</strong><span>{_html(label)}</span></div>"
        for label, value in cards
    )
    payload = html.escape(json.dumps(body, indent=2, ensure_ascii=False))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_html(title)}</title>
<style>
:root{{color-scheme:dark}}
body{{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:#0f172a;color:#e5e7eb}}
header{{padding:24px 32px;border-bottom:1px solid #334155;background:#111827}}
main{{padding:24px 32px;max-width:1280px;margin:auto}}
h1{{margin:0 0 6px;font-size:28px}} h2{{margin:0 0 14px;font-size:18px}}
p{{color:#cbd5e1}} a{{color:#67e8f9}} code,pre{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}}
.card,.panel,.empty{{border:1px solid #334155;background:#111827;border-radius:12px;padding:16px}}
.card strong{{display:block;font-size:22px;margin-bottom:4px}} .card span,.muted{{color:#94a3b8}}
.panel{{margin:16px 0;overflow:auto}} .empty{{border-color:#475569;background:#172033}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:10px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}}
th{{color:#93c5fd;font-size:12px;text-transform:uppercase;letter-spacing:.05em}}
details{{margin-top:18px}} summary{{cursor:pointer;color:#67e8f9}} pre{{white-space:pre-wrap;word-break:break-word;background:#020617;padding:14px;border-radius:10px;overflow:auto}}
</style></head><body>
<header><h1>{_html(title)}</h1><p>{_html(subtitle)}</p></header>
<main>
  <p><a href="/dashboard">Back to Agent Hub</a> | <a href="{_html(json_path)}">JSON</a></p>
  <div class="cards">{card_html}</div>
  {empty}
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


def _leaderboard_row_html(row: dict[str, Any]) -> str:
    samples = _int(row.get("samples"))
    success = _percent(row.get("success_rate")) if samples else "waiting"
    cost = f"{_money(row.get('cost_per_million_input'))} in / {_money(row.get('cost_per_million_output'))} out"
    return (
        "<tr>"
        f"<td>{_html(row.get('rank', ''))}</td>"
        f"<td>{_html(row.get('agent'))}</td>"
        f"<td>{_html(row.get('provider'))}</td>"
        f"<td>{_html(row.get('model'))}</td>"
        f"<td>{_html(_number(row.get('overall_score')))}</td>"
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
    for key in ("success_rate_delta", "average_score_delta", "cost_savings_usd"):
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


def _latency(value: Any) -> str:
    number = _float(value)
    return "unknown" if number is None or number <= 0 else f"{number:.1f} ms"


def _timestamp(value: Any) -> str:
    number = _float(value)
    if number is None or number <= 0:
        return "unknown"
    return datetime.fromtimestamp(number).strftime("%Y-%m-%d %H:%M:%S")
