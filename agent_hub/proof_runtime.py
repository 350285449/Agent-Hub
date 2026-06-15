from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .application import DiagnosticsApplicationService
from .architecture import architecture_guardrail_report
from .config import AgentConfig, HubConfig, RouteRule
from .core.router import AgentRouter
from .models import HubRequest
from .plugins.lifecycle import PluginLifecycleManager
from .providers import create_provider
from .providers.echo import EchoProvider
from .server import AgentHubHandler
from .tools.workspace_state import create_workspace_checkpoint, restore_workspace_checkpoint
from .version import backend_version


@dataclass(slots=True)
class ProofCheck:
    id: str
    ok: bool
    detail: str
    required: bool = True
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "ok": bool(self.ok),
            "required": bool(self.required),
            "detail": self.detail,
        }
        if self.data:
            payload["data"] = self.data
        return payload


def runtime_proof_report(
    config: HubConfig,
    *,
    route: str = "cloud-agent",
    full: bool = False,
    benchmark_report: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a local, no-network release proof report for CI and packaging gates."""

    started = time.time()
    workspace = Path(root or config.workspace_dir or Path.cwd()).resolve()
    checks = [
        _backend_startup_check(),
        _diagnostics_check(config),
        _provider_availability_check(config),
        _routing_check(config, route),
        _agent_execution_check(),
        _patch_and_rollback_check(),
        _extension_connectivity_check(workspace),
        _plugin_safety_check(),
        _architecture_guardrails_check(workspace),
    ]
    if benchmark_report is not None:
        checks.append(_benchmark_check(benchmark_report))
    required = [check for check in checks if check.required]
    passed = sum(1 for check in checks if check.ok)
    required_passed = sum(1 for check in required if check.ok)
    return {
        "object": "agent_hub.release_proof",
        "version": backend_version(),
        "mode": "full" if full else "standard",
        "ok": required_passed == len(required),
        "rating": round((passed / max(1, len(checks))) * 10.0, 1),
        "summary": {
            "passed": passed,
            "total": len(checks),
            "required_passed": required_passed,
            "required_total": len(required),
            "duration_ms": round((time.time() - started) * 1000, 2),
        },
        "checks": [check.to_dict() for check in checks],
        "benchmark": _compact_benchmark(benchmark_report),
        "ci_gate": {
            "release_blocking": required_passed != len(required),
            "required_checks": [check.id for check in required],
        },
    }


def write_runtime_proof_report(report: dict[str, Any], target: str | Path) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def format_runtime_proof_report(report: dict[str, Any]) -> str:
    lines = [
        "Agent-Hub release proof",
        f"Mode: {report.get('mode')}",
        f"Status: {'ok' if report.get('ok') else 'fail'}",
        f"Rating: {report.get('rating')}/10",
        "",
    ]
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        status = "ok" if check.get("ok") else "fail"
        required = "" if check.get("required", True) else " optional"
        lines.append(f"- {check.get('id')}: {status}{required} - {check.get('detail')}")
    return "\n".join(lines) + "\n"


def _backend_startup_check() -> ProofCheck:
    ok = AgentHubHandler is not None
    return ProofCheck(
        "backend_startup",
        ok,
        "Backend HTTP handler imports without starting a public listener.",
        data={"handler": f"{AgentHubHandler.__module__}.{AgentHubHandler.__name__}"},
    )


def _diagnostics_check(config: HubConfig) -> ProofCheck:
    body = DiagnosticsApplicationService(config).provider_scores_body()
    return ProofCheck(
        "diagnostics",
        body.get("object") == "agent_hub.provider_scores",
        "Diagnostics application service returns provider score payloads.",
        data={"object": body.get("object")},
    )


def _provider_availability_check(config: HubConfig) -> ProofCheck:
    rows: list[dict[str, Any]] = []
    for name, agent in sorted(config.agents.items()):
        try:
            provider = create_provider(agent)
            health = provider.health_check()
            rows.append(
                {
                    "agent": name,
                    "provider": agent.provider,
                    "model": agent.model,
                    "available": bool(health.available),
                    "status": health.status,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "agent": name,
                    "provider": agent.provider,
                    "model": agent.model,
                    "available": False,
                    "status": "error",
                    "error": str(exc),
                }
            )
    available = [row for row in rows if row.get("available")]
    return ProofCheck(
        "provider_availability",
        bool(available),
        f"{len(available)} of {len(rows)} configured provider adapters are locally constructible.",
        data={"providers": rows},
    )


def _routing_check(config: HubConfig, route: str) -> ProofCheck:
    decision = AgentRouter(config).decide(
        HubRequest(
            session_id="proof-routing",
            route=route,
            messages=[{"role": "user", "content": "prove routing without calling a provider"}],
        )
    )
    return ProofCheck(
        "routing",
        bool(decision.selected_agent),
        "Router produced a deterministic local routing decision.",
        data={
            "route": route,
            "agent": decision.selected_agent,
            "provider": decision.selected_provider,
            "model": decision.selected_model,
            "reason": decision.reason,
        },
    )


def _agent_execution_check() -> ProofCheck:
    agent = AgentConfig(name="proof-echo", provider="echo", model="local-echo", free=True)
    response = EchoProvider(agent).complete(
        HubRequest(
            session_id="proof-agent",
            messages=[{"role": "user", "content": "agent execution"}],
        )
    )
    return ProofCheck(
        "agent_execution",
        "agent execution" in response.text,
        "In-process agent execution path returns a provider result.",
        data={"model": response.model, "finish_reason": response.finish_reason},
    )


def _patch_and_rollback_check() -> ProofCheck:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = root / ".agent-hub" / "state"
        target = root / "proof.txt"
        target.write_text("before\n", encoding="utf-8")
        checkpoint = create_workspace_checkpoint(root, ["proof.txt"], state_dir=state, retention=2)
        target.write_text("after\n", encoding="utf-8")
        rollback = restore_workspace_checkpoint(checkpoint, root=root)
        restored = target.read_text(encoding="utf-8") == "before\n"
    return ProofCheck(
        "patching_rollback",
        restored and bool(rollback.get("ok")),
        "Workspace checkpoint rollback restores edited files.",
        data={"checkpoint_id": rollback.get("checkpoint_id"), "restored_files": rollback.get("restored_files", [])},
    )


def _extension_connectivity_check(root: Path) -> ProofCheck:
    required = [
        root / "vscode-extension" / "extension.js",
        root / "vscode-extension" / "src" / "api" / "typedClient.js",
        root / "vscode-extension" / "src" / "state" / "stateManager.js",
        root / "vscode-extension" / "src" / "commands" / "registry.js",
    ]
    missing = [path.relative_to(root).as_posix() for path in required if not path.exists()]
    return ProofCheck(
        "extension_connectivity",
        not missing,
        "VS Code extension entrypoint and connectivity modules are present.",
        data={"missing": missing},
    )


def _plugin_safety_check() -> ProofCheck:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "source"
        source.mkdir()
        (source / "plugin.json").write_text(
            json.dumps({"id": "proof-plugin", "name": "Proof Plugin", "type": "provider"}),
            encoding="utf-8",
        )
        manager = PluginLifecycleManager(Path(tmp) / "plugins")
        install = manager.install(source)
        audit = manager.audit("proof-plugin")
        remove = manager.remove("proof-plugin")
    return ProofCheck(
        "plugin_safety",
        bool(install.ok and audit.ok and remove.ok),
        "Plugin lifecycle install, audit, and remove run through manifest safety checks.",
        data={"install": install.to_dict(), "audit": audit.to_dict(), "remove": remove.to_dict()},
    )


def _architecture_guardrails_check(root: Path) -> ProofCheck:
    report = architecture_guardrail_report(root, enforce=False)
    return ProofCheck(
        "architecture_guardrails",
        report.ok,
        "Architecture guardrails are available in advisory mode for current monolith debt.",
        required=False,
        data={
            "checked_files": report.checked_files,
            "file_findings": len(report.findings),
            "function_findings": len(report.function_findings),
            "import_cycle_findings": len(report.import_cycle_findings),
            "layer_violation_findings": len(report.layer_violation_findings),
            "api_stability_findings": len(report.api_stability_findings),
        },
    )


def _benchmark_check(report: dict[str, Any]) -> ProofCheck:
    ok = report.get("object") == "agent_hub.benchmark_proof" and int(report.get("task_count") or 0) > 0
    return ProofCheck(
        "benchmark_validation",
        ok,
        "Benchmark proof report is attached and has at least one task result.",
        data=_compact_benchmark(report),
    )


def _compact_benchmark(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    dataset = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    comparison = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    return {
        "object": report.get("object"),
        "task_count": report.get("task_count"),
        "dataset": dataset.get("name") or report.get("dataset_name"),
        "fingerprint": dataset.get("fingerprint") or report.get("dataset_fingerprint"),
        "cost_reduction": comparison.get("cost_reduction") or report.get("cost_reduction"),
        "latency_reduction": comparison.get("latency_reduction") or report.get("latency_reduction"),
        "success_delta": comparison.get("success_delta") or report.get("success_delta"),
    }


def proof_config() -> HubConfig:
    """Return a tiny local config useful for embedding proof checks in tests."""

    return HubConfig(
        default_route=["proof-echo"],
        routes=[RouteRule(name="cloud-agent", agents=["proof-echo"])],
        agents={
            "proof-echo": AgentConfig(name="proof-echo", provider="echo", model="local-echo", free=True),
        },
    )


__all__ = [
    "ProofCheck",
    "format_runtime_proof_report",
    "proof_config",
    "runtime_proof_report",
    "write_runtime_proof_report",
]
