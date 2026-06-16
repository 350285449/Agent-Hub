from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .context_embedding import load_context_observations
from .telemetry import research_dir


LEAKAGE_FIELDS = {
    "same_run_success",
    "same_run_validation_score",
    "same_run_error",
    "same_run_latency",
    "same_run_retry_count",
    "latency_ms",
    "retry_count",
}


@dataclass(slots=True)
class AgentStateVector:
    row_id: int
    model: str
    provider: str
    provider_type: str
    task_type: str
    repository: str
    route: str
    context_id: str
    task_key: str
    features: dict[str, float]
    targets: dict[str, float]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_agent_state_vectors(state_dir: str | Path, rows: list[dict[str, Any]] | None = None) -> list[AgentStateVector]:
    observations = rows if rows is not None else load_context_observations(state_dir)
    observations = [
        row
        for row in observations
        if row.get("model") and row.get("success") is not None and _is_cloud_or_codex_row(row)
    ]
    priors = _PriorTracker()
    vectors: list[AgentStateVector] = []
    for index, row in enumerate(observations):
        model = str(row.get("model") or "")
        task_type = str(row.get("task_type") or "unknown")
        repository = str(row.get("repository") or "unknown")
        route = str(row.get("route") or task_type or "unknown")
        provider = str(row.get("provider") or row.get("provider_type") or _provider_from_model(model))
        provider_type = str(row.get("provider_type") or provider)
        context_id = str(row.get("context_id") or "")
        task_key = str(row.get("task_key") or f"{repository}::{task_type}::observed")
        structure = _structure_features(row, model, provider, provider_type, task_type, repository, route)
        history = priors.features(row, model=model, provider=provider, task_type=task_type, repository=repository, route=route)
        features = {**structure, **history}
        _assert_no_leakage(features)
        vector = AgentStateVector(
            row_id=index,
            model=model,
            provider=provider,
            provider_type=provider_type,
            task_type=task_type,
            repository=repository,
            route=route,
            context_id=context_id,
            task_key=task_key,
            features={key: round(float(value), 8) for key, value in sorted(features.items())},
            targets={
                "success": 1.0 if row.get("success") is True else 0.0,
                "validation_score": _clamp01(_float(row.get("validation_score"))),
                "failure": 1.0 if row.get("success") is not True or bool(row.get("error")) else 0.0,
                "error": 1.0 if bool(row.get("error")) else 0.0,
                "latency_ms": max(0.0, _float(row.get("latency_ms"))),
                "estimated_cost": _estimated_cost(row, model, provider_type),
            },
            metadata={
                "source": row.get("source", ""),
                "live_execution": bool(row.get("live_execution")),
                "real_model_only": bool(row.get("real_model_only")),
                "selected_files": list(row.get("selected_files") or [])[:80],
                "sequence_index": index,
            },
        )
        vectors.append(vector)
        priors.update(row, model=model, provider=provider, task_type=task_type, repository=repository, route=route)
    return vectors


def export_agent_state_vectors(
    state_dir: str | Path,
    vectors: list[AgentStateVector] | None = None,
    *,
    sample_limit: int = 5000,
) -> tuple[Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows = vectors if vectors is not None else build_agent_state_vectors(state_dir)
    payload = {
        "object": "agent_hub.research.agent_state_vectors",
        "row_count": len(rows),
        "feature_count": len(rows[0].features) if rows else 0,
        "leakage_policy": {
            "scope": "Ollama Cloud and Codex CLI rows only; local model rows are excluded.",
            "allowed": [
                "model",
                "provider",
                "task type",
                "repository metrics",
                "context token count",
                "file count",
                "information-density stats",
                "route",
                "historical priors from previous rows only",
            ],
            "banned": sorted(LEAKAGE_FIELDS),
        },
        "feature_names": sorted(rows[0].features) if rows else [],
        "sample_limit": sample_limit,
        "sample_vectors": [row.to_dict() for row in rows[:sample_limit]],
        "note": "Metrics are computed over all state vectors in memory; this artifact stores a bounded sample to keep report generation practical.",
    }
    path = directory / "agent_state_vectors.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path, payload


def feature_names(vectors: list[AgentStateVector], family: str = "state_space") -> list[str]:
    if not vectors:
        return []
    names = sorted(vectors[0].features)
    if family == "structure_only":
        return [name for name in names if name.startswith("structure.")]
    if family == "history_only":
        return [name for name in names if name.startswith("history.")]
    if family == "structure_history":
        return [name for name in names if name.startswith(("structure.", "history."))]
    if family == "compatibility":
        return [name for name in names if name.startswith("compatibility.")]
    return names


def records_from_vectors(vectors: list[AgentStateVector]) -> list[dict[str, Any]]:
    return [
        {
            "id": row.row_id,
            "model": row.model,
            "provider": row.provider,
            "provider_type": row.provider_type,
            "task_type": row.task_type,
            "repository": row.repository,
            "route": row.route,
            "task_key": row.task_key,
            "live_execution": bool(row.metadata.get("live_execution")),
            "real_model_only": bool(row.metadata.get("real_model_only")),
            "source": row.metadata.get("source", ""),
            "features": row.features,
            **row.targets,
        }
        for row in vectors
    ]


class _PriorTracker:
    def __init__(self) -> None:
        self.buckets: dict[str, dict[Any, _Bucket]] = defaultdict(lambda: defaultdict(_Bucket))
        self.recent: dict[str, dict[Any, deque[float]]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=20)))

    def features(self, row: dict[str, Any], *, model: str, provider: str, task_type: str, repository: str, route: str) -> dict[str, float]:
        keys = self._keys(model=model, provider=provider, task_type=task_type, repository=repository, route=route)
        fallback = self.buckets["global"]["global"].prior()
        features: dict[str, float] = {}
        for name, key in keys.items():
            prior = self.buckets[name][key].prior(fallback=fallback)
            features[f"history.{name}.success_rate"] = prior["success_rate"]
            features[f"history.{name}.failure_rate"] = prior["failure_rate"]
            features[f"history.{name}.error_rate"] = prior["error_rate"]
            features[f"history.{name}.validation_score"] = prior["validation_score"]
            features[f"history.{name}.experience_count"] = _scale_log(prior["n"], 5000.0)
            recent_values = self.recent[name][key]
            features[f"history.{name}.recent_success_rate"] = sum(recent_values) / len(recent_values) if recent_values else prior["success_rate"]
        return features

    def update(self, row: dict[str, Any], *, model: str, provider: str, task_type: str, repository: str, route: str) -> None:
        success = 1.0 if row.get("success") is True else 0.0
        error = 1.0 if row.get("error") else 0.0
        validation = _clamp01(_float(row.get("validation_score")))
        for name, key in self._keys(model=model, provider=provider, task_type=task_type, repository=repository, route=route).items():
            self.buckets[name][key].add(success, error, validation)
            self.recent[name][key].append(success)

    def _keys(self, *, model: str, provider: str, task_type: str, repository: str, route: str) -> dict[str, Any]:
        return {
            "global": "global",
            "model": model,
            "provider": provider,
            "task": task_type,
            "repo": repository,
            "route": route,
            "model_task": (model, task_type),
            "model_repo": (model, repository),
            "task_repo": (task_type, repository),
            "model_task_context": (model, task_type, route),
        }


@dataclass(slots=True)
class _Bucket:
    n: float = 0.0
    success: float = 0.0
    error: float = 0.0
    validation: float = 0.0

    def add(self, success: float, error: float, validation: float) -> None:
        self.n += 1.0
        self.success += success
        self.error += error
        self.validation += validation

    def prior(self, fallback: dict[str, float] | None = None) -> dict[str, float]:
        if self.n <= 0:
            return fallback or {"n": 0.0, "success_rate": 0.5, "failure_rate": 0.5, "error_rate": 0.0, "validation_score": 0.5}
        success_rate = self.success / self.n
        return {
            "n": self.n,
            "success_rate": success_rate,
            "failure_rate": 1.0 - success_rate,
            "error_rate": self.error / self.n,
            "validation_score": self.validation / self.n,
        }


def _structure_features(row: dict[str, Any], model: str, provider: str, provider_type: str, task_type: str, repository: str, route: str) -> dict[str, float]:
    context_tokens = _float(row.get("context_tokens"))
    file_count = _float(row.get("file_count"))
    density = _float(row.get("average_information_density"))
    max_density = _float(row.get("max_information_density"))
    spread = _float(row.get("density_spread"))
    repo_complexity = _float(row.get("repo_complexity"))
    repo_file_count = _float(row.get("repo_file_count"))
    context_percent = _float(row.get("context_percent"))
    base = {
        "structure.context_tokens": _scale_log(context_tokens, 20000.0),
        "structure.context_token_fit": 1.0 / (1.0 + abs(context_tokens - 4000.0) / 4000.0),
        "structure.context_budget_percent": _clamp01(context_percent / 100.0),
        "structure.file_count": _scale_log(file_count, 400.0),
        "structure.file_count_fit": 1.0 / (1.0 + abs(file_count - 8.0) / 8.0) if file_count else 0.35,
        "structure.average_information_density": _scale_log(density * 100000.0, 100.0),
        "structure.max_information_density": _scale_log(max_density * 100000.0, 100.0),
        "structure.density_spread": _scale_log(spread * 100000.0, 100.0),
        "structure.redundancy_estimate": _clamp01(_float(row.get("redundancy_estimate"))),
        "structure.repo_complexity": _scale_log(repo_complexity, 5000.0),
        "structure.repo_file_count": _scale_log(repo_file_count, 5000.0),
        "structure.model_hash": _hash_unit(model),
        "structure.provider_hash": _hash_unit(provider),
        "structure.provider_type_hash": _hash_unit(provider_type),
        "structure.task_hash": _hash_unit(task_type),
        "structure.repo_hash": _hash_unit(repository),
        "structure.route_hash": _hash_unit(route),
        "compatibility.model_task": _hash_unit(f"{model}::{task_type}"),
        "compatibility.model_route": _hash_unit(f"{model}::{route}"),
        "compatibility.task_context": _hash_unit(f"{task_type}::{int(context_tokens // 500)}::{int(file_count)}"),
        "compatibility.model_task_context": _hash_unit(f"{model}::{task_type}::{int(context_tokens // 500)}::{int(file_count)}"),
        "compatibility.provider_task": _hash_unit(f"{provider}::{task_type}"),
        "compatibility.repo_task": _hash_unit(f"{repository}::{task_type}"),
    }
    base["compatibility.context_density_fit"] = base["structure.context_token_fit"] * (1.0 - min(1.0, base["structure.density_spread"]))
    base["compatibility.repo_context_load"] = base["structure.repo_complexity"] * base["structure.context_tokens"]
    return base


def _assert_no_leakage(features: dict[str, float]) -> None:
    bad = [name for name in features if any(part in name.lower() for part in LEAKAGE_FIELDS)]
    if bad:
        raise ValueError(f"state vector contains leakage features: {bad}")


def _estimated_cost(row: dict[str, Any], model: str, provider_type: str) -> float:
    tokens = max(1.0, _float(row.get("context_tokens")))
    provider = provider_type.lower()
    model_name = model.lower()
    if "codex" in provider or "gpt" in model_name:
        per_1k = 0.002
    elif "cloud" in provider or "cloud" in model_name:
        per_1k = 0.0005
    else:
        per_1k = 0.0
    return round(tokens / 1000.0 * per_1k, 8)


def _provider_from_model(model: str) -> str:
    if model.endswith(":cloud"):
        return "ollama-cloud"
    if "gpt" in model.lower() or "codex" in model.lower():
        return "codex-cli"
    return "unknown"


def _is_cloud_or_codex_row(row: dict[str, Any]) -> bool:
    provider_type = str(row.get("provider_type") or "").lower()
    provider = str(row.get("provider") or "").lower()
    model = str(row.get("model") or row.get("selected_model") or "")
    model_l = model.lower()
    return (
        provider_type in {"ollama-cloud", "codex-cli"}
        or provider in {"ollama-cloud", "codex-cli"}
        or model.endswith(":cloud")
        or "codex" in model_l
        or model_l.startswith("gpt-")
    )


def _hash_unit(value: Any) -> float:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return int(digest, 16) / float(16**12 - 1)


def _scale_log(value: Any, maximum: float) -> float:
    number = max(0.0, _float(value))
    return math.log1p(number) / math.log1p(maximum)


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = [
    "AgentStateVector",
    "build_agent_state_vectors",
    "export_agent_state_vectors",
    "feature_names",
    "records_from_vectors",
]
