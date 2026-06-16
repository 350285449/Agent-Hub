from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .live_matrix_runner import ALLOWED_MODELS, CONTEXT_BUDGETS, expected_minimum_rows, live_matrix_path
from .task_generator import REPOSITORIES, TASK_CATEGORIES
from .telemetry import research_dir


FAILURE_MARKERS = {
    "auth_failure": ("unauthorized", "forbidden", "authentication", "api key", "login", "401", "403"),
    "subscription_error": ("subscription", "payment required", "billing", "upgrade", "quota", "usage limit"),
    "provider_failure": ("provider", "server error", "503", "502", "500", "connection", "malformed response"),
    "timeout_no_useful_output": ("timeout", "timed out"),
}
CODEX_MODEL = "gpt-5.5"


def data_quality_report_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "data_quality_report.md"


def data_quality_json_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "data_quality_report.json"


def load_audited_rows(path: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    usable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _load_jsonl(Path(path)):
        reason = exclusion_reason(row, seen)
        if reason:
            item = dict(row)
            item["excluded_reason"] = reason
            excluded.append(item)
        else:
            seen.add(str(row.get("dedupe_key") or _fallback_key(row)))
            usable.append(normalize_row(row))
    return usable, excluded


def run_data_quality_audit(state_dir: str | Path, *, matrix_path: str | Path | None = None) -> dict[str, str]:
    source = Path(matrix_path) if matrix_path else live_matrix_path(state_dir)
    rows, excluded = load_audited_rows(source)
    payload = build_data_quality_payload(source, rows, excluded)
    json_path = data_quality_json_path(state_dir)
    md_path = data_quality_report_path(state_dir)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"data_quality_json": str(json_path), "data_quality_report": str(md_path)}


def build_data_quality_payload(source: Path, usable: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter((row["model"], row["repository"], row["category"], int(row["context_budget"])) for row in usable)
    missing_cells = [
        {
            "model": model,
            "repository": repository,
            "category": category,
            "context_budget": budget,
            "usable_repetitions": counts[(model, repository, category, budget)],
        }
        for model in ALLOWED_MODELS
        for repository in REPOSITORIES
        for category in TASK_CATEGORIES
        for budget in CONTEXT_BUDGETS
        if counts[(model, repository, category, budget)] < 3
    ]
    exclusions_by_reason = Counter(row.get("excluded_reason", "unknown") for row in excluded)
    return {
        "object": "agent_hub.research.data_quality_audit",
        "source_file": str(source),
        "usable_rows": len(usable),
        "excluded_rows": len(excluded),
        "expected_minimum_usable_rows": expected_minimum_rows(),
        "target_usable_rows": expected_minimum_rows(repetitions=5),
        "minimum_complete": len(usable) >= expected_minimum_rows() and not missing_cells,
        "target_1000_plus_complete": len(usable) >= 1000,
        "exclusions_by_reason": dict(exclusions_by_reason),
        "duplicates": sum(1 for row in excluded if row.get("excluded_reason") == "duplicate"),
        "provider_failures": sum(1 for row in excluded if row.get("excluded_reason") == "provider_failure"),
        "auth_failures": sum(1 for row in excluded if row.get("excluded_reason") == "auth_failure"),
        "corrupted_rows": sum(1 for row in excluded if row.get("excluded_reason") == "corrupted_row"),
        "leakage_rows": sum(1 for row in excluded if row.get("excluded_reason") == "leakage"),
        "timeout_only_rows": sum(1 for row in excluded if row.get("excluded_reason") in {"timeout_only", "timeout_no_useful_output", "codex_timeout"}),
        "timeout_no_useful_output_rows": sum(1 for row in excluded if row.get("excluded_reason") == "timeout_no_useful_output"),
        "codex_config_disabled_rows": sum(1 for row in excluded if row.get("excluded_reason") == "codex_config_disabled"),
        "codex_timeout_rows": sum(1 for row in excluded if row.get("excluded_reason") == "codex_timeout"),
        "codex_usable_rows": sum(1 for row in usable if row.get("model") == CODEX_MODEL),
        "usable_by_model": dict(Counter(row["model"] for row in usable)),
        "usable_by_repository": dict(Counter(row["repository"] for row in usable)),
        "usable_by_category": dict(Counter(row["category"] for row in usable)),
        "usable_by_context_budget": {str(key): value for key, value in Counter(row["context_budget"] for row in usable).items()},
        "missing_minimum_cells": missing_cells,
    }


def exclusion_reason(row: dict[str, Any], seen: set[str]) -> str:
    if row.get("corrupted") or "raw_line" in row:
        return "corrupted_row"
    key = str(row.get("dedupe_key") or _fallback_key(row))
    if key in seen:
        return "duplicate"
    model = str(row.get("model") or "")
    if model not in ALLOWED_MODELS:
        return "disallowed_model"
    provider_type = str(row.get("provider_type") or row.get("provider") or "").lower()
    if provider_type in {"local-research", "echo", "ollama"}:
        return "local_deterministic_or_ollama_row"
    error = str(row.get("error") or "").lower()
    if model == CODEX_MODEL:
        if row.get("live") is not True and (
            provider_type == "configuration"
            or "allowed agent not configured or not enabled" in error
            or "codex_cli_agent_disabled" in error
        ):
            return "codex_config_disabled"
        if "timeout" in error or "timed out" in error:
            return "codex_timeout"
    if row.get("live") is not True:
        return "not_live"
    if _leakage(row):
        return "leakage"
    for reason, markers in FAILURE_MARKERS.items():
        if any(marker in error for marker in markers):
            return reason
    if error:
        return "provider_failure"
    if not str(row.get("output_preview") or "").strip() and not bool(row.get("success")):
        return "timeout_no_useful_output" if "timeout" in error else "empty_output"
    try:
        score = float(row.get("validation_score", 0.0))
    except (TypeError, ValueError):
        return "corrupted_row"
    if score < 0 or score > 1:
        return "corrupted_row"
    return ""


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "task": str(row.get("task") or row.get("task_id") or ""),
        "task_id": str(row.get("task_id") or row.get("task") or ""),
        "category": str(row.get("category") or row.get("task_type") or ""),
        "context_budget": int(row.get("context_budget", row.get("context budget", 0)) or 0),
        "context_tokens": int(float(row.get("context_tokens", 0) or 0)),
        "success": bool(row.get("success")),
        "validation_score": float(row.get("validation_score", 0.0) or 0.0),
        "latency": float(row.get("latency", row.get("latency_ms", 0.0)) or 0.0),
        "retries": int(float(row.get("retries", row.get("retry_count", 0)) or 0)),
    }


def _leakage(row: dict[str, Any]) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ("output_preview", "error")).lower()
    return any(marker in text for marker in ("expected answer", "gold label", "benchmark score", "synthetic score"))


def _fallback_key(row: dict[str, Any]) -> str:
    return "|".join(
        str(row.get(key) or "")
        for key in ("model", "repository", "task", "task_id", "category", "context_budget", "repetition")
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"corrupted": True, "raw_line": line})
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        else:
            rows.append({"corrupted": True, "raw_line": line})
    return rows


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Data Quality Report",
        "",
        f"- Source: `{payload['source_file']}`",
        f"- Usable rows: {payload['usable_rows']}",
        f"- Excluded rows: {payload['excluded_rows']}",
        f"- Minimum complete: {payload['minimum_complete']}",
        f"- 1000+ usable target complete: {payload['target_1000_plus_complete']}",
        f"- Expected minimum usable rows: {payload['expected_minimum_usable_rows']}",
        f"- Target usable rows: {payload['target_usable_rows']}",
        f"- Codex usable rows: {payload['codex_usable_rows']}",
        f"- Codex config-disabled rows: {payload['codex_config_disabled_rows']}",
        f"- Codex timeout rows: {payload['codex_timeout_rows']}",
        "",
        "## Exclusions",
        *[f"- {key}: {value}" for key, value in sorted(payload["exclusions_by_reason"].items())],
        "",
        "## Coverage",
        f"- Usable by model: {payload['usable_by_model']}",
        f"- Usable by repository: {payload['usable_by_repository']}",
        f"- Usable by category: {payload['usable_by_category']}",
        f"- Usable by context budget: {payload['usable_by_context_budget']}",
        "",
    ]
    if payload["missing_minimum_cells"]:
        lines.extend(["## Missing Minimum Cells"])
        for row in payload["missing_minimum_cells"][:120]:
            lines.append(f"- {row['model']} / {row['repository']} / {row['category']} / {row['context_budget']}%: {row['usable_repetitions']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Agent-Hub live research matrix quality.")
    parser.add_argument("--state-dir", default=".agent-hub/state")
    parser.add_argument("--matrix-path", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run_data_quality_audit(args.state_dir, matrix_path=args.matrix_path or None)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "build_data_quality_payload",
    "data_quality_json_path",
    "data_quality_report_path",
    "exclusion_reason",
    "load_audited_rows",
    "normalize_row",
    "run_data_quality_audit",
]
