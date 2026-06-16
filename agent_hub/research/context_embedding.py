from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .telemetry import research_dir


SOURCE_FILES = (
    "runs.jsonl",
    "experiments.jsonl",
    "context_ablation.jsonl",
    "real_model_validation_results.jsonl",
    "multi_model_context_scaling.json",
    "dataset.csv",
)


def load_context_observations(state_dir: str | Path) -> list[dict[str, Any]]:
    directory = research_dir(state_dir)
    rows: list[dict[str, Any]] = []
    for name in SOURCE_FILES:
        path = directory / name
        if not path.exists():
            continue
        if path.suffix == ".jsonl":
            rows.extend(_load_jsonl(path, name))
        elif path.suffix == ".json":
            rows.extend(_load_json(path, name))
        elif path.suffix == ".csv":
            rows.extend(_load_csv(path, name))
    density = _load_file_density(directory / "information_density.json")
    repo_metrics = _load_repo_metrics(directory / "repo_metrics.json")
    return [_normalize(row, density, repo_metrics) for row in rows]


def build_context_embeddings(state_dir: str | Path, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = rows if rows is not None else load_context_observations(state_dir)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["context_id"]].append(row)
    contexts = {}
    for context_id, items in sorted(grouped.items()):
        first = items[0]
        vector = {
            "context_tokens": _avg(row["context_tokens"] for row in items),
            "file_count": _avg(row["file_count"] for row in items),
            "average_information_density": _avg(row["average_information_density"] for row in items),
            "max_information_density": _avg(row["max_information_density"] for row in items),
            "density_spread": _avg(row["density_spread"] for row in items),
            "context_budget_percent": _avg(row["context_percent"] for row in items),
            "redundancy_estimate": _avg(row["redundancy_estimate"] for row in items),
            "repo_complexity": _avg(row["repo_complexity"] for row in items),
            "repo_file_count": _avg(row["repo_file_count"] for row in items),
            "observed_success_rate": _avg(1.0 if row["success"] else 0.0 for row in items),
            "observed_validation_score": _avg(row["validation_score"] for row in items),
            "observed_error_rate": _avg(1.0 if row["error"] else 0.0 for row in items),
        }
        contexts[context_id] = {
            "runs": len(items),
            "repository": first["repository"],
            "selected_files": first["selected_files"][:40],
            "raw_vector": {key: round(value, 8) for key, value in vector.items()},
            "embedding_3d": [
                round(_log1p(vector["context_tokens"]), 6),
                round(vector["average_information_density"] * 10000.0, 6),
                round(vector["context_budget_percent"] / 100.0 - vector["redundancy_estimate"], 6),
            ],
        }
    return {
        "object": "agent_hub.research.context_embedding",
        "context_count": len(contexts),
        "observation_count": len(rows),
        "contexts": contexts,
        "rows": rows,
        "notes": [
            "Context embeddings use selected files, token budget, file-density statistics, repository metrics, and redundancy estimates.",
            "Observed success/validation/error fields are included for diagnostics but are not used as predictors in triadic formulas.",
        ],
    }


def export_context_embeddings(state_dir: str | Path, rows: list[dict[str, Any]] | None = None) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = build_context_embeddings(state_dir, rows)
    json_path = directory / "context_embedding.json"
    md_path = directory / "context_embedding.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(context_embedding_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def context_embedding_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Context Embedding",
        "",
        f"- Context plans: {payload['context_count']}",
        f"- Observations: {payload['observation_count']}",
        "",
        "| context | runs | repo | tokens | files | avg density | max density | redundancy | success | error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for context_id, row in list(payload["contexts"].items())[:120]:
        vector = row["raw_vector"]
        lines.append(
            f"| {context_id[:12]} | {row['runs']} | {row['repository']} | {round(vector['context_tokens'], 3)} | {round(vector['file_count'], 3)} | {vector['average_information_density']} | {vector['max_information_density']} | {vector['redundancy_estimate']} | {vector['observed_success_rate']} | {vector['observed_error_rate']} |"
        )
    if len(payload["contexts"]) > 120:
        lines.append(f"| ... | ... | ... | ... | ... | ... | ... | ... | ... | {len(payload['contexts']) - 120} more contexts omitted |")
    lines.append("")
    return "\n".join(lines)


def _load_jsonl(path: Path, source: str) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row["_source"] = source
        rows.append(row)
    return rows


def _load_csv(path: Path, source: str) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    for row in rows:
        row["_source"] = source
    return rows


def _load_json(path: Path, source: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    rows = []
    if isinstance(payload, dict):
        value = payload.get("runs")
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    elif isinstance(payload, list):
        rows.extend(row for row in payload if isinstance(row, dict))
    for row in rows:
        row["_source"] = source
    return rows


def _load_file_density(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {
        name: float(row.get("information_density") or 0.0)
        for name, row in (payload.get("files") or {}).items()
        if isinstance(row, dict)
    }


def _load_repo_metrics(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    result = {}
    for row in payload.get("repositories", []):
        repo_id = str(row.get("repo_id") or row.get("name") or "")
        if repo_id:
            result[repo_id] = {
                "repo_complexity": _float(row.get("approximate_complexity_score")),
                "repo_file_count": _float(row.get("file_count")),
            }
    return result


def _normalize(raw: dict[str, Any], density: dict[str, float], repo_metrics: dict[str, dict[str, float]]) -> dict[str, Any]:
    selected = raw.get("context_files") or raw.get("selected_files") or []
    selected = [str(item) for item in selected] if isinstance(selected, list) else []
    densities = [density.get(name, 0.0) for name in selected]
    repository = str(raw.get("repository") or raw.get("repo_id") or raw.get("repo_source") or "unknown")
    repo = repo_metrics.get(repository, {})
    context_tokens = _float(raw.get("context_token_count", raw.get("context_tokens", 0.0)))
    file_count = float(len(selected)) if selected else _float(raw.get("file_count"))
    context_percent = _float(raw.get("context_percent"))
    if context_percent == 0.0 and raw.get("context_budget_ratio") not in (None, ""):
        context_percent = _float(raw.get("context_budget_ratio")) * 100.0
    error_text = str(raw.get("error") or "")
    errors = raw.get("errors")
    error = bool(error_text) or (isinstance(errors, list) and any(str(item) for item in errors))
    row = {
        "source": str(raw.get("_source") or ""),
        "model": str(raw.get("model") or raw.get("selected_model") or ""),
        "provider": str(raw.get("provider") or ""),
        "provider_type": str(raw.get("provider_type") or ""),
        "task_type": str(raw.get("task_type") or raw.get("route") or "unknown"),
        "task_id": str(raw.get("task_id") or ""),
        "task_key": _task_key(raw, repository),
        "repository": repository,
        "context_tokens": context_tokens,
        "context_percent": context_percent,
        "file_count": file_count,
        "selected_files": selected,
        "average_information_density": _avg(densities),
        "max_information_density": max(densities, default=0.0),
        "density_spread": (max(densities) - min(densities)) if densities else 0.0,
        "redundancy_estimate": _redundancy(selected, file_count),
        "repo_complexity": repo.get("repo_complexity", 0.0),
        "repo_file_count": repo.get("repo_file_count", 0.0),
        "latency_ms": _float(raw.get("latency_ms", raw.get("latency", 0.0))),
        "retry_count": _float(raw.get("retry_count")),
        "success": _bool(raw.get("success")),
        "validation_score": _float(raw.get("validation_score")),
        "error": error,
        "live_execution": bool(raw.get("live_execution")),
        "real_model_only": bool(raw.get("real_model_only")),
    }
    row["context_id"] = _context_id(row)
    return row


def _task_key(raw: dict[str, Any], repository: str) -> str:
    task_type = str(raw.get("task_type") or raw.get("route") or "unknown")
    task_id = str(raw.get("task_id") or "")
    if task_id:
        return f"{repository}::{task_type}::{task_id.rsplit('-', 1)[0]}"
    return f"{repository}::{task_type}::observed"


def _context_id(row: dict[str, Any]) -> str:
    payload = {
        "repo": row["repository"],
        "tokens": int(row["context_tokens"] // 250) * 250,
        "percent": int(row["context_percent"]),
        "files": row["selected_files"][:80],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def _redundancy(files: list[str], file_count: float) -> float:
    if not files or not file_count:
        return 0.0
    roots = [item.split("/", 1)[0] for item in files]
    return 1.0 - (len(set(roots)) / max(1.0, float(len(roots))))


def _log1p(value: float) -> float:
    return math.log1p(max(0.0, value))


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _avg(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


__all__ = ["build_context_embeddings", "context_embedding_markdown", "export_context_embeddings", "load_context_observations"]
