from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .candidate_quantities import evaluate_all_candidates
from .research_portfolio import export_research_portfolio, rank_research_portfolio
from .telemetry import research_dir


SOURCE_FILES = (
    "runs.jsonl",
    "experiments.jsonl",
    "context_ablation.jsonl",
    "real_model_validation_results.jsonl",
    "multi_model_context_scaling.json",
    "dataset.csv",
)


def run_fundamental_research_lab(state_dir: str | Path) -> dict[str, Any]:
    rows = load_research_observations(state_dir)
    results = evaluate_all_candidates(rows)
    paths = export_research_portfolio(state_dir, results)
    portfolio = rank_research_portfolio(results)
    return {
        "object": "agent_hub.research.fundamental_lab",
        "observation_count": len(rows),
        "quantities": results,
        "portfolio": portfolio,
        "paths": {key: str(value) for key, value in paths.items()},
    }


def load_research_observations(state_dir: str | Path) -> list[dict[str, Any]]:
    directory = research_dir(state_dir)
    rows: list[dict[str, Any]] = []
    for name in SOURCE_FILES:
        path = directory / name
        if not path.exists():
            continue
        if path.suffix == ".jsonl":
            rows.extend(_load_jsonl(path, source=name))
        elif path.suffix == ".json":
            rows.extend(_load_json(path, source=name))
        elif path.suffix == ".csv":
            rows.extend(_load_csv(path, source=name))
    observations = [_normalize_row(row) for row in rows]
    return [row for row in observations if row.get("success") is not None]


def _load_jsonl(path: Path, *, source: str) -> list[dict[str, Any]]:
    rows = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    value["_source"] = source
                    rows.append(value)
    except OSError:
        return []
    return rows


def _load_json(path: Path, *, source: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("runs", "rows", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(row for row in value if isinstance(row, dict))
        per_model = payload.get("per_model")
        if isinstance(per_model, dict):
            for model, row in per_model.items():
                if isinstance(row, dict) and row.get("runs"):
                    rows.append({"model": model, **row})
    elif isinstance(payload, list):
        rows.extend(row for row in payload if isinstance(row, dict))
    for row in rows:
        row["_source"] = source
    return rows


def _load_csv(path: Path, *, source: str) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []
    for row in rows:
        row["_source"] = source
    return rows


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    model = _first_text(row, "selected_model", "model", "agent", "selected_agent") or "unknown"
    task_id = _first_text(row, "task_id", "id") or _stable_task_id(row)
    task_type = _first_text(row, "task_type", "task", "category") or "unknown"
    context_files = row.get("context_files") or row.get("selected_files") or []
    if not isinstance(context_files, list):
        context_files = []
    errors = row.get("errors")
    if isinstance(errors, list):
        error_count = len([item for item in errors if str(item)])
    else:
        error_text = str(row.get("error") or "")
        error_count = 1 if error_text else 0
    context_percent = _first_float(row, "context_percent", "context_budget_percent")
    if context_percent == 0.0 and row.get("context_budget_ratio") not in (None, ""):
        context_percent = _to_float(row.get("context_budget_ratio")) * 100.0
    return {
        "source": _first_text(row, "_source") or "",
        "task_id": task_id,
        "task_type": task_type,
        "model": model,
        "route": _first_text(row, "route", "provider_type", "provider") or "",
        "repo": _first_text(row, "repo_id", "repository", "repo", "repo_source") or "unknown",
        "success": _to_bool(row.get("success")),
        "validation_score": _to_float(row.get("validation_score")),
        "context_tokens": _first_float(row, "context_token_count", "context_tokens"),
        "context_percent": max(0.0, context_percent),
        "file_count": _first_float(row, "file_count") or float(len(context_files)),
        "latency_ms": _first_float(row, "latency_ms", "latency"),
        "cost_estimate": _first_float(row, "cost_estimate", "cost"),
        "retry_count": _first_float(row, "retry_count", "retries"),
        "input_tokens": _first_float(row, "input_tokens"),
        "output_tokens": _first_float(row, "output_tokens"),
        "error_count": float(error_count),
    }


def summarize_fundamental_lab(result: dict[str, Any]) -> dict[str, Any]:
    ranked = list(result.get("portfolio", {}).get("ranked_quantities") or [])
    if not ranked:
        return {}
    top = ranked[0]
    weakest = ranked[-1]
    surprising = max(
        ranked,
        key=lambda row: (
            float(row.get("predictive_power") or 0.0)
            + float(row.get("usefulness_for_routing") or 0.0)
            - float(row.get("stability") or 0.0)
        ),
    )
    best_next = next((row for row in ranked if row.get("continue_or_kill") == "continue"), top)
    return {
        "top_ranked_quantity": top["name"],
        "weakest_quantity": weakest["name"],
        "most_surprising_result": surprising["name"],
        "best_next_research_direction": best_next.get("next_experiment", ""),
        "highest_chance_of_becoming_fundamental": top["name"],
    }


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _first_float(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return _to_float(value)
    return 0.0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    return str(value)


def _stable_task_id(row: dict[str, Any]) -> str:
    source = _first_text(row, "_source") or "row"
    digest = hashlib.sha256(json.dumps(_safe(row), sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"{source}-{digest}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rank candidate fundamental quantities for Agent-Hub research.")
    parser.add_argument("--state-dir", default=".agent-hub")
    args = parser.parse_args(argv)
    result = run_fundamental_research_lab(args.state_dir)
    print(json.dumps(summarize_fundamental_lab(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SOURCE_FILES",
    "load_research_observations",
    "run_fundamental_research_lab",
    "summarize_fundamental_lab",
]
