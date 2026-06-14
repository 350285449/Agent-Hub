from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def build_report(rows: list[dict[str, Any]], *, baseline_model: str = "claude", hub_model: str = "agent-hub") -> dict[str, Any]:
    baseline_tokens = sum(int(row.get("baseline_tokens") or 0) for row in rows)
    hub_tokens = sum(int(row.get("hub_tokens") or 0) for row in rows)
    savings = 0.0 if baseline_tokens <= 0 else ((baseline_tokens - hub_tokens) / baseline_tokens) * 100.0
    passed = sum(1 for row in rows if row.get("tests_passed") is True)
    return {
        "object": "agent_hub.real_proof_benchmark",
        "created_at": time.time(),
        "baseline_model": baseline_model,
        "hub_model": hub_model,
        "task_count": len(rows),
        "baseline_tokens": baseline_tokens,
        "hub_tokens": hub_tokens,
        "savings": round(savings, 1),
        "tests_passed": passed == len(rows) if rows else False,
        "success_rate": round(passed / len(rows), 4) if rows else 0.0,
        "results": rows,
    }


def write_report(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "benchmark-report.json"
    markdown_path = directory / "benchmark-report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(format_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def format_markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Agent-Hub Benchmark Proof",
            "",
            f"Baseline: {report.get('baseline_model')}",
            f"Tasks: {report.get('task_count')}",
            f"Tokens saved: {report.get('savings')}%",
            f"Success rate: {float(report.get('success_rate') or 0) * 100:.1f}%",
        ]
    )
