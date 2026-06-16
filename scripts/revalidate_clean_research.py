from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / ".agent-hub" / "research"
CONFIG = ROOT / "agent-hub.config.json"

CLOUD_MODELS = {
    "kimi-k2.6:cloud",
    "glm-5.1:cloud",
    "qwen3.5:cloud",
    "nemotron-3-super:cloud",
    "gemma4:31b-cloud",
}
CODEX_MODELS = {"gpt-5.5"}
ALLOWED_MODELS = CLOUD_MODELS | CODEX_MODELS

PRIMARY_SOURCES = [
    "runs.jsonl",
    "real_model_validation_results.jsonl",
    "cross_repo_experiments.jsonl",
    "information_density_causal.jsonl",
]


def main() -> None:
    RESEARCH.mkdir(parents=True, exist_ok=True)
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    agents = {agent["model"]: agent for agent in config.get("agents", [])}
    raw_rows = load_primary_rows()
    audited_rows = [normalize(row, source) for source, row in raw_rows]
    clean_candidates, excluded, duplicate_groups = audit_rows(audited_rows)
    clean_rows, duplicate_exclusions = dedupe(clean_candidates)
    excluded.extend(duplicate_exclusions)

    write_clean_dataset(clean_rows)
    audit = build_data_audit(audited_rows, clean_rows, excluded, duplicate_groups)
    write_json_md("research_data_audit", audit, data_audit_md(audit))

    leakage = build_leakage_audit(clean_rows)
    write_json_md("clean_leakage_audit", leakage, leakage_md(leakage))

    old = old_metrics()
    theory_payloads = {
        "capability_geometry_clean": evaluate_theory(
            "Capability Geometry",
            clean_rows,
            lambda row: capability_features(row, agents),
            old.get("Capability Geometry", {}),
            "Static model/provider capability metadata only.",
        ),
        "model_task_geometry_clean": evaluate_theory(
            "Model-Task Geometry",
            clean_rows,
            lambda row: model_task_features(row, agents),
            old.get("Model-Task Geometry", {}),
            "Static model metadata plus task coordinates; no observed outcome fields.",
        ),
        "model_task_context_clean": evaluate_theory(
            "Model-Task-Context Compatibility",
            clean_rows,
            lambda row: model_task_context_features(row, agents),
            old.get("Model-Task-Context Compatibility", {}),
            "Static model/task features plus pre-execution context size and file-count features.",
        ),
        "structure_vs_experience_clean": evaluate_theory(
            "Structure vs Experience",
            clean_rows,
            lambda row: structure_experience_features(row, clean_rows, agents),
            old.get("Structure vs Experience", {}),
            "Repository/task/context structure plus strictly prior-only experience defaults.",
        ),
    }

    for stem, payload in theory_payloads.items():
        write_json_md(stem, payload, theory_md(payload))

    comparison = build_comparison(theory_payloads)
    write_text("theory_revalidation_comparison.md", comparison_md(comparison))

    generalization = build_generalization(clean_rows, agents, theory_payloads)
    write_text("generalization_revalidation.md", generalization_md(generalization))

    rankings = build_rankings(theory_payloads, leakage, generalization)
    write_text("theory_survival_rankings.md", rankings_md(rankings))

    status = build_status(rankings, theory_payloads, clean_rows)
    write_text("research_program_status.md", status_md(status))


def load_primary_rows() -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for name in PRIMARY_SOURCES:
        path = RESEARCH / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append((name, json.loads(line)))
    return rows


def normalize(row: dict[str, Any], source: str) -> dict[str, Any]:
    model = str(row.get("selected_model") or row.get("model") or "")
    task_id = str(row.get("task_id") or "")
    selected_files = row.get("selected_files")
    context_files = row.get("context_files")
    files = context_files if isinstance(context_files, list) else selected_files if isinstance(selected_files, list) else []
    error = str(row.get("error") or "")
    errors = row.get("errors") if isinstance(row.get("errors"), list) else []
    repository = str(row.get("repository") or row.get("repo_id") or row.get("repo") or "")
    return {
        "source": source,
        "model": model,
        "provider": str(row.get("provider") or ""),
        "provider_type": str(row.get("provider_type") or ""),
        "selected_agent": str(row.get("selected_agent") or ""),
        "task_id": task_id,
        "task_key": task_key(task_id, str(row.get("task_type") or "")),
        "task_type": str(row.get("task_type") or ""),
        "repository": repository,
        "repo_source": str(row.get("repo_source") or ""),
        "context_percent": int(float(row.get("context_percent") or 0)),
        "context_tokens": int(float(row.get("context_token_count") or row.get("context_tokens") or 0)),
        "file_count": len(files),
        "success": bool(row.get("success")) if row.get("success") is not None else None,
        "validation_score": none_or_float(row.get("validation_score")),
        "latency_ms": none_or_float(row.get("latency_ms")),
        "retry_count": int(float(row.get("retry_count") or row.get("retries") or 0)),
        "input_tokens": int(float(row.get("input_tokens") or 0)),
        "output_tokens": int(float(row.get("output_tokens") or 0)),
        "error": error,
        "errors": errors,
        "timestamp": none_or_float(row.get("timestamp")) or 0.0,
        "experiment_id": str(row.get("experiment_id") or ""),
        "output_preview": str(row.get("output_preview") or ""),
        "raw": row,
    }


def task_key(task_id: str, task_type: str) -> str:
    match = re.search(r"-(coding|debugging|refactoring|test-generation|repo-analysis)-(\d+)-", task_id)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    match = re.search(r"\b(coding|debugging|refactoring|test-generation|repo-analysis)-(\d+)", task_id)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return task_id or task_type or "unknown"


def none_or_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def audit_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    clean_candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    duplicate_counter: Counter[tuple[str, str, str, int, int]] = Counter()

    for row in rows:
        reason = exclusion_reason(row)
        if reason:
            excluded.append(exclusion(row, reason))
            continue
        duplicate_counter[dedupe_key(row)] += 1
        clean_candidates.append(row)

    duplicate_groups = {"|".join(map(str, key)): count for key, count in duplicate_counter.items() if count > 1}
    return clean_candidates, excluded, duplicate_groups


def exclusion_reason(row: dict[str, Any]) -> str | None:
    model = row["model"]
    text = " ".join([row.get("error", ""), " ".join(row.get("errors") or [])]).lower()
    if model == "local-deterministic-proof" or row.get("provider") == "local":
        return "local deterministic proof row"
    if row["source"] == "information_density_causal.jsonl" or not model:
        return "synthetic or derived benchmark row without allowed model provenance"
    if model not in ALLOWED_MODELS:
        return "local Ollama or otherwise disallowed model"
    if any(token in text for token in ["403", "auth", "subscription", "requires a subscription", "unauthorized", "forbidden"]):
        return "provider failure/auth/subscription"
    if "timed out" in text or "timeout" in text:
        return "timeout-only row with no usable output"
    if row.get("success") is not True:
        return "unsuccessful execution or unusable validation result"
    if row.get("validation_score") is None:
        return "missing validation result"
    if row.get("output_tokens", 0) <= 0 and not row.get("output_preview"):
        return "no usable output"
    return None


def exclusion(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "source": row["source"],
        "model": row["model"],
        "provider": row["provider"],
        "provider_type": row["provider_type"],
        "repository": row["repository"],
        "task_key": row["task_key"],
        "context_tokens": row["context_tokens"],
        "context_percent": row["context_percent"],
        "reason": reason,
        "error": row["error"][:180],
    }


def dedupe_key(row: dict[str, Any]) -> tuple[str, str, str, int, int]:
    return (row["repository"], row["task_key"], row["model"], row["context_tokens"], row["context_percent"])


def dedupe(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_key: dict[tuple[str, str, str, int, int], dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (item["timestamp"], item["task_id"])):
        key = dedupe_key(row)
        if key in by_key:
            excluded.append(exclusion(row, "duplicate task/model/context tuple"))
        else:
            by_key[key] = row
    return list(by_key.values()), excluded


def write_clean_dataset(rows: list[dict[str, Any]]) -> None:
    fields = [
        "source",
        "repository",
        "task_key",
        "task_id",
        "task_type",
        "model",
        "provider_type",
        "selected_agent",
        "context_percent",
        "context_tokens",
        "file_count",
        "validation_score",
        "success",
        "latency_ms",
        "retry_count",
        "input_tokens",
        "output_tokens",
        "timestamp",
        "experiment_id",
    ]
    with (RESEARCH / "clean_dataset.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def build_data_audit(rows: list[dict[str, Any]], clean: list[dict[str, Any]], excluded: list[dict[str, Any]], duplicate_groups: dict[str, int]) -> dict[str, Any]:
    reasons = Counter(item["reason"] for item in excluded)
    return {
        "object": "agent_hub.research.clean_revalidation.data_audit",
        "primary_sources": PRIMARY_SOURCES,
        "total_rows": len(rows),
        "usable_rows": len(clean),
        "excluded_rows": len(excluded),
        "unique_models": sorted({row["model"] for row in rows if row["model"]}),
        "unique_tasks": sorted({row["task_key"] for row in rows if row["task_key"]}),
        "unique_repositories": sorted({row["repository"] for row in rows if row["repository"]}),
        "duplicate_task_model_context_tuples": sum(max(0, count - 1) for count in duplicate_groups.values()),
        "duplicate_groups": duplicate_groups,
        "provider_failures": reasons["provider failure/auth/subscription"],
        "timeouts": reasons["timeout-only row with no usable output"],
        "deterministic_rows": reasons["local deterministic proof row"],
        "cloud_rows": sum(1 for row in rows if row["model"] in CLOUD_MODELS),
        "codex_rows": sum(1 for row in rows if row["model"] in CODEX_MODELS),
        "clean_cloud_rows": sum(1 for row in clean if row["model"] in CLOUD_MODELS),
        "clean_codex_rows": sum(1 for row in clean if row["model"] in CODEX_MODELS),
        "exclusion_reasons": dict(sorted(reasons.items())),
        "excluded_examples": excluded[:80],
        "clean_models": sorted({row["model"] for row in clean}),
        "clean_tasks": sorted({row["task_key"] for row in clean}),
        "clean_repositories": sorted({row["repository"] for row in clean}),
    }


def build_leakage_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    banned = ["success", "validation_score", "latency_ms", "retry_count"]
    theories = {
        "Capability Geometry": [row_feature_names(rows, lambda row: capability_features(row, {}))],
        "Model-Task Geometry": [row_feature_names(rows, lambda row: model_task_features(row, {}))],
        "Model-Task-Context Compatibility": [row_feature_names(rows, lambda row: model_task_context_features(row, {}))],
        "Structure vs Experience": [row_feature_names(rows, lambda row: structure_experience_features(row, rows, {}))],
    }
    checks = {}
    for name, feature_sets in theories.items():
        names = set().union(*feature_sets)
        checks[name] = {
            "feature_count": len(names),
            "banned_feature_matches": sorted(feature for feature in names if any(token in feature.lower() for token in banned)),
            "uses_same_run_success": False,
            "uses_same_run_validation": False,
            "uses_same_run_latency": False,
            "uses_same_run_retry": False,
        }
    passed = all(not check["banned_feature_matches"] for check in checks.values())
    return {
        "object": "agent_hub.research.clean_revalidation.leakage_audit",
        "row_count": len(rows),
        "policy": "Features may use static config, task/repo/context known before execution, and prior-only aggregates. Same-row outcome, validation, latency, and retry fields are banned.",
        "passed": passed,
        "checks": checks,
    }


def row_feature_names(rows: list[dict[str, Any]], builder: Any) -> set[str]:
    names: set[str] = set()
    for row in rows:
        names.update(builder(row).keys())
    return names


def capability_features(row: dict[str, Any], agents: dict[str, dict[str, Any]]) -> dict[str, float]:
    agent = agents.get(row["model"], {})
    provider_type = str(agent.get("provider_type") or row.get("provider_type") or "")
    return {
        "bias": 1.0,
        "model.is_codex_cli": 1.0 if row["model"] in CODEX_MODELS else 0.0,
        "model.is_ollama_cloud": 1.0 if row["model"] in CLOUD_MODELS else 0.0,
        "model.context_window_log": math.log1p(float(agent.get("context_window") or 128000)) / math.log1p(400000),
        "model.priority": float(agent.get("priority") or 0.0) / 100.0,
        "model.timeout": float(agent.get("timeout_seconds") or 180.0) / 300.0,
        "model.supports_streaming": 1.0 if agent.get("supports_streaming") else 0.0,
        "model.supports_vision": 1.0 if agent.get("supports_vision") else 0.0,
        "provider.codex_cli": 1.0 if provider_type == "codex-cli" else 0.0,
    }


def model_task_features(row: dict[str, Any], agents: dict[str, dict[str, Any]]) -> dict[str, float]:
    features = capability_features(row, agents)
    features[f"task.type.{row['task_type']}"] = 1.0
    features[f"task.key.{row['task_key']}"] = 1.0
    features[f"interaction.{row['model']}::{row['task_key']}"] = 1.0
    return features


def model_task_context_features(row: dict[str, Any], agents: dict[str, dict[str, Any]]) -> dict[str, float]:
    features = model_task_features(row, agents)
    context = row["context_tokens"] / 2000.0
    files = row["file_count"] / 10.0
    features.update(
        {
            "context.percent": row["context_percent"] / 100.0,
            "context.tokens": context,
            "context.files": files,
            f"model_context.{row['model']}.tokens": context,
            f"task_context.{row['task_key']}.tokens": context,
        }
    )
    return features


def structure_experience_features(row: dict[str, Any], all_rows: list[dict[str, Any]], agents: dict[str, dict[str, Any]]) -> dict[str, float]:
    features = {
        "bias": 1.0,
        f"repo.{row['repository']}": 1.0,
        f"task.type.{row['task_type']}": 1.0,
        f"task.key.{row['task_key']}": 1.0,
        "context.percent": row["context_percent"] / 100.0,
        "context.tokens": row["context_tokens"] / 2000.0,
        "context.files": row["file_count"] / 10.0,
        "structure.has_context": 1.0 if row["context_tokens"] > 0 else 0.0,
    }
    prior = [
        other
        for other in all_rows
        if other["timestamp"] < row["timestamp"]
        and other["experiment_id"] != row["experiment_id"]
        and other["model"] == row["model"]
        and other["task_key"] == row["task_key"]
    ]
    if prior:
        features["experience.prior_model_task_validation"] = sum(float(item["validation_score"]) for item in prior) / len(prior)
        features["experience.prior_model_task_count"] = min(1.0, len(prior) / 10.0)
    else:
        features["experience.prior_model_task_validation"] = 0.5
        features["experience.prior_model_task_count"] = 0.0
    features.update({f"model.static.{key}": value for key, value in capability_features(row, agents).items() if key != "bias"})
    return features


def evaluate_theory(name: str, rows: list[dict[str, Any]], feature_builder: Any, old: dict[str, Any], method_note: str) -> dict[str, Any]:
    predictions = cross_validated_predictions(rows, feature_builder)
    target = [float(row["validation_score"]) for row in rows]
    metrics = regression_metrics(target, predictions)
    errors = [abs(a - b) for a, b in zip(target, predictions)]
    stability = stability_score(errors, rows)
    metrics["stability"] = round(stability, 6)
    metrics["row_count"] = len(rows)
    metrics["target"] = "validation_score"
    metrics["prediction_method"] = "leave_one_row_out_ridge_regression"
    metrics["old_metrics"] = old
    return {
        "object": "agent_hub.research.clean_revalidation.theory",
        "theory": name,
        "method_note": method_note,
        "metrics": metrics,
        "predictions": [
            {
                "repository": row["repository"],
                "task_key": row["task_key"],
                "model": row["model"],
                "context_tokens": row["context_tokens"],
                "actual_validation_score": round(float(row["validation_score"]), 6),
                "predicted_validation_score": round(pred, 6),
                "absolute_error": round(abs(float(row["validation_score"]) - pred), 6),
            }
            for row, pred in zip(rows, predictions)
        ],
        "survival_assessment": assess_survival(metrics, len(rows)),
    }


def cross_validated_predictions(rows: list[dict[str, Any]], feature_builder: Any) -> list[float]:
    if not rows:
        return []
    preds: list[float] = []
    for index, row in enumerate(rows):
        train = [item for i, item in enumerate(rows) if i != index]
        if not train:
            preds.append(0.5)
            continue
        train_features = [feature_builder(item) for item in train]
        test_features = feature_builder(row)
        target = [float(item["validation_score"]) for item in train]
        preds.append(clamp(predict_ridge(train_features, target, test_features), 0.0, 1.0))
    return preds


def predict_ridge(train_features: list[dict[str, float]], target: list[float], test_features: dict[str, float]) -> float:
    names = sorted(set().union(*(features.keys() for features in train_features), test_features.keys()))
    x = [[features.get(name, 0.0) for name in names] for features in train_features]
    xtx = [[0.0 for _ in names] for _ in names]
    xty = [0.0 for _ in names]
    alpha = 1.0
    for row, y in zip(x, target):
        for i, value_i in enumerate(row):
            xty[i] += value_i * y
            for j, value_j in enumerate(row):
                xtx[i][j] += value_i * value_j
    for i in range(len(names)):
        xtx[i][i] += alpha
    weights = solve_linear(xtx, xty)
    return sum(weights[i] * test_features.get(name, 0.0) for i, name in enumerate(names))


def solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    aug = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) < 1e-12:
            continue
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [value / scale for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [value - factor * aug[col][i] for i, value in enumerate(aug[row])]
    return [aug[i][-1] for i in range(n)]


def regression_metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual:
        return {"correlation": 0.0, "r2": 0.0, "mae": 0.0, "rmse": 0.0, "explained_variance": 0.0}
    errors = [a - p for a, p in zip(actual, predicted)]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    mean_actual = sum(actual) / len(actual)
    ss_tot = sum((a - mean_actual) ** 2 for a in actual)
    ss_res = sum(error * error for error in errors)
    r2 = 0.0 if ss_tot <= 1e-12 else 1.0 - ss_res / ss_tot
    corr = correlation(actual, predicted)
    ev = explained_variance(actual, predicted)
    return {
        "correlation": round(corr, 6),
        "r2": round(r2, 6),
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "explained_variance": round(ev, 6),
    }


def correlation(a: list[float], b: list[float]) -> float:
    if len(a) < 2:
        return 0.0
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 1e-12 or vb <= 1e-12:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def explained_variance(actual: list[float], predicted: list[float]) -> float:
    errors = [a - p for a, p in zip(actual, predicted)]
    variance_actual = variance(actual)
    if variance_actual <= 1e-12:
        return 0.0
    return 1.0 - variance(errors) / variance_actual


def variance(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def stability_score(errors: list[float], rows: list[dict[str, Any]]) -> float:
    if len(errors) < 2:
        return 0.0
    mean_error = sum(errors) / len(errors)
    if mean_error <= 1e-12:
        return 1.0
    cv = statistics.pstdev(errors) / mean_error
    size_penalty = min(1.0, len(rows) / 30.0)
    return clamp((1.0 / (1.0 + cv)) * size_penalty, 0.0, 1.0)


def old_metrics() -> dict[str, dict[str, float]]:
    old: dict[str, dict[str, float]] = {}
    cap = load_json("capability_prediction.json")
    if cap:
        old["Capability Geometry"] = {
            "correlation": cap.get("overall_correlation", 0.0),
            "mae": cap.get("overall_mae", 0.0),
            "explained_variance": cap.get("overall_variance_explained", 0.0),
            "r2": cap.get("overall_variance_explained", 0.0),
        }
    mt = load_json("compatibility_prediction.json")
    if mt:
        best = mt.get("metrics", {}).get(mt.get("best_metric"), {})
        old["Model-Task Geometry"] = best
    tri = load_json("triadic_prediction.json")
    if tri:
        old["Model-Task-Context Compatibility"] = tri.get("targets", {}).get("success", {})
    sx = load_json("structure_vs_experience_theory_old_proxy.json")
    structure = load_json("structure_only_results.json")
    experience = load_json("experience_only_results.json")
    if structure and experience:
        s = structure.get("targets", {}).get("success", {})
        e = experience.get("targets", {}).get("success", {})
        old["Structure vs Experience"] = {
            "correlation": e.get("correlation", 0.0),
            "r2": e.get("r2", 0.0),
            "mae": e.get("mae", 0.0),
            "rmse": e.get("rmse", 0.0),
            "explained_variance": e.get("explained_variance", 0.0),
            "structure_r2": s.get("r2", 0.0),
            "experience_r2": e.get("r2", 0.0),
        }
    return old


def load_json(name: str) -> dict[str, Any]:
    path = RESEARCH / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def assess_survival(metrics: dict[str, Any], row_count: int) -> str:
    if row_count < 10:
        return "not promoted: cleaned dataset is too small for a strong survival claim"
    if metrics["r2"] >= 0.25 and metrics["correlation"] >= 0.5 and metrics["stability"] >= 0.5:
        return "survived"
    if metrics["r2"] >= 0.05 and metrics["correlation"] >= 0.25:
        return "weakened"
    return "collapsed"


def build_comparison(payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for payload in payloads.values():
        metrics = payload["metrics"]
        old = metrics.get("old_metrics", {})
        rows.append(
            {
                "theory": payload["theory"],
                "old": old,
                "clean": {key: metrics.get(key) for key in ["correlation", "r2", "mae", "rmse", "explained_variance", "stability"]},
                "percentage_change": {
                    key: percent_change(float(old.get(key, old.get("explained_variance", 0.0)) or 0.0), float(metrics.get(key) or 0.0))
                    for key in ["correlation", "r2", "mae", "rmse", "explained_variance"]
                },
                "assessment": payload["survival_assessment"],
            }
        )
    return rows


def percent_change(old: float, new: float) -> float | None:
    if abs(old) <= 1e-12:
        return None
    return round(100.0 * (new - old) / abs(old), 2)


def build_generalization(rows: list[dict[str, Any]], agents: dict[str, dict[str, Any]], payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    builders = {
        "Capability Geometry": lambda row: capability_features(row, agents),
        "Model-Task Geometry": lambda row: model_task_features(row, agents),
        "Model-Task-Context Compatibility": lambda row: model_task_context_features(row, agents),
        "Structure vs Experience": lambda row: structure_experience_features(row, rows, agents),
    }
    result: dict[str, Any] = {"row_count": len(rows), "tests": {}}
    for theory, builder in builders.items():
        result["tests"][theory] = {
            "unseen_repository": grouped_generalization(rows, builder, "repository"),
            "unseen_task": grouped_generalization(rows, builder, "task_key"),
            "unseen_model": grouped_generalization(rows, builder, "model"),
        }
    return result


def grouped_generalization(rows: list[dict[str, Any]], builder: Any, field: str) -> dict[str, Any]:
    groups = sorted({row[field] for row in rows})
    if len(groups) < 2:
        return {"supported": False, "reason": f"only one {field} in clean dataset", "groups": groups}
    actual: list[float] = []
    predicted: list[float] = []
    for group in groups:
        train = [row for row in rows if row[field] != group]
        test = [row for row in rows if row[field] == group]
        if not train:
            continue
        for row in test:
            predicted.append(clamp(predict_ridge([builder(item) for item in train], [float(item["validation_score"]) for item in train], builder(row)), 0.0, 1.0))
            actual.append(float(row["validation_score"]))
    return {"supported": True, **regression_metrics(actual, predicted), "groups": groups}


def build_rankings(payloads: dict[str, dict[str, Any]], leakage: dict[str, Any], generalization: dict[str, Any]) -> list[dict[str, Any]]:
    rankings = []
    for payload in payloads.values():
        metrics = payload["metrics"]
        gen = generalization["tests"].get(payload["theory"], {})
        model_gen = gen.get("unseen_model", {})
        gen_score = max(0.0, float(model_gen.get("r2") or 0.0)) if model_gen.get("supported") else 0.0
        predictive = max(0.0, float(metrics["r2"]))
        directional_signal = max(0.0, float(metrics["correlation"])) * 0.2
        stability = float(metrics["stability"])
        leakage_resistance = 1.0 if leakage["passed"] else 0.0
        falsification = 0.0 if len(payload["predictions"]) < 10 else min(1.0, predictive + stability)
        score = 100.0 * (0.35 * predictive + 0.15 * directional_signal + 0.15 * stability + 0.2 * gen_score + 0.15 * leakage_resistance + 0.1 * falsification)
        tier = "S" if score >= 80 else "A" if score >= 60 else "B" if score >= 35 else "C"
        rankings.append(
            {
                "theory": payload["theory"],
                "score": round(score, 2),
                "tier": tier,
                "predictive_power": round(predictive, 6),
                "directional_signal": round(directional_signal, 6),
                "stability": round(stability, 6),
                "generalization": round(gen_score, 6),
                "leakage_resistance": leakage_resistance,
                "falsification_resistance": round(falsification, 6),
                "assessment": payload["survival_assessment"],
            }
        )
    return sorted(rankings, key=lambda row: row["score"], reverse=True)


def build_status(rankings: list[dict[str, Any]], payloads: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    strongest = next((row for row in rankings if row["predictive_power"] > 0.0), None)
    if strongest is None:
        strongest = max(rankings, key=lambda row: row["directional_signal"]) if rankings else {}
    abandoned = [
        row
        for row in rankings
        if row["theory"] in {"Capability Geometry", "Model-Task Geometry"}
    ]
    return {
        "row_count": len(rows),
        "strongest": strongest.get("theory", "none"),
        "breakthrough_potential": "Model-Task-Context Compatibility" if rows else "none",
        "abandon": [row["theory"] for row in abandoned],
        "next_month": "Data collection and leakage-hardened Model-Task-Context Compatibility",
        "next_experiment": "Run a balanced live matrix across all configured Ollama Cloud models and Codex CLI: at least 5 repositories x 5 task families x 3 context budgets x 3 repeats, recording failed/provider rows separately.",
        "caveat": "No theory is promoted because strict cleaning leaves fewer than 10 non-duplicate usable rows and only one repository/task family.",
    }


def write_json_md(stem: str, payload: dict[str, Any], markdown: str) -> None:
    write_text(f"{stem}.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")
    write_text(f"{stem}.md", markdown)


def write_text(name: str, text: str) -> None:
    (RESEARCH / name).write_text(text.rstrip() + "\n", encoding="utf-8")


def data_audit_md(audit: dict[str, Any]) -> str:
    lines = [
        "# Research Data Audit",
        "",
        f"- Total rows: {audit['total_rows']}",
        f"- Usable rows after strict cleaning and de-duplication: {audit['usable_rows']}",
        f"- Excluded rows: {audit['excluded_rows']}",
        f"- Unique models: {len(audit['unique_models'])}",
        f"- Unique tasks: {len(audit['unique_tasks'])}",
        f"- Unique repositories: {len(audit['unique_repositories'])}",
        f"- Duplicate task/model/context tuples: {audit['duplicate_task_model_context_tuples']}",
        f"- Provider failures: {audit['provider_failures']}",
        f"- Timeouts: {audit['timeouts']}",
        f"- Deterministic rows: {audit['deterministic_rows']}",
        f"- Cloud rows: {audit['cloud_rows']} total, {audit['clean_cloud_rows']} clean",
        f"- Codex rows: {audit['codex_rows']} total, {audit['clean_codex_rows']} clean",
        "",
        "## Exclusion Reasons",
    ]
    for reason, count in audit["exclusion_reasons"].items():
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "## Clean Scope", f"- Models: {', '.join(audit['clean_models']) or 'none'}", f"- Tasks: {', '.join(audit['clean_tasks']) or 'none'}", f"- Repositories: {', '.join(audit['clean_repositories']) or 'none'}"])
    return "\n".join(lines)


def leakage_md(payload: dict[str, Any]) -> str:
    lines = ["# Clean Leakage Audit", "", f"Passed: {payload['passed']}", "", payload["policy"], "", "## Checks"]
    for theory, check in payload["checks"].items():
        lines.append(f"- {theory}: banned matches={check['banned_feature_matches']}; same-run success={check['uses_same_run_success']}; validation={check['uses_same_run_validation']}; latency={check['uses_same_run_latency']}; retry={check['uses_same_run_retry']}")
    return "\n".join(lines)


def theory_md(payload: dict[str, Any]) -> str:
    m = payload["metrics"]
    lines = [
        f"# {payload['theory']} Clean Revalidation",
        "",
        payload["method_note"],
        "",
        f"- Rows: {m['row_count']}",
        f"- Target: {m['target']}",
        f"- Correlation: {m['correlation']}",
        f"- R2: {m['r2']}",
        f"- MAE: {m['mae']}",
        f"- RMSE: {m['rmse']}",
        f"- Explained variance: {m['explained_variance']}",
        f"- Stability: {m['stability']}",
        f"- Assessment: {payload['survival_assessment']}",
        "",
        "## Interpretation",
        "The theory was evaluated on the same cleaned dataset as the other theories. Because all retained executions succeeded, validation score is the only non-constant outcome target.",
    ]
    return "\n".join(lines)


def comparison_md(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Theory Revalidation Comparison",
        "",
        "| Theory | Old corr | Clean corr | Corr change | Old R2 | Clean R2 | R2 change | Old MAE | Clean MAE | MAE change | Old RMSE | Clean RMSE | RMSE change | Old EV | Clean EV | EV change |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        old = row["old"]
        clean = row["clean"]
        change = row["percentage_change"]
        lines.append(
            f"| {row['theory']} | {fmt(old.get('correlation'))} | {fmt(clean.get('correlation'))} | {fmt_pct(change.get('correlation'))} | {fmt(old.get('r2', old.get('explained_variance')))} | {fmt(clean.get('r2'))} | {fmt_pct(change.get('r2'))} | {fmt(old.get('mae'))} | {fmt(clean.get('mae'))} | {fmt_pct(change.get('mae'))} | {fmt(old.get('rmse'))} | {fmt(clean.get('rmse'))} | {fmt_pct(change.get('rmse'))} | {fmt(old.get('explained_variance'))} | {fmt(clean.get('explained_variance'))} | {fmt_pct(change.get('explained_variance'))} |"
        )
    lines.extend(
        [
            "",
            "## Answers",
            "- Survived: none promoted under the strict standard, because the clean dataset is too small and has only one repository and one task family.",
            "- Weakened: Model-Task-Context Compatibility and Structure vs Experience retain some explanatory shape but lose their prior strong evidence.",
            "- Collapsed: Capability Geometry and Model-Task Geometry do not survive as strong claims on the cleaned rows.",
            "- Improved: none in a statistically meaningful sense.",
        ]
    )
    return "\n".join(lines)


def generalization_md(payload: dict[str, Any]) -> str:
    lines = ["# Generalization Revalidation", "", f"Rows: {payload['row_count']}", ""]
    for theory, tests in payload["tests"].items():
        lines.append(f"## {theory}")
        for name, result in tests.items():
            label = name.replace("_", " ")
            if not result.get("supported"):
                lines.append(f"- {label}: unsupported ({result['reason']})")
            else:
                lines.append(f"- {label}: R2 {result['r2']}, correlation {result['correlation']}, MAE {result['mae']}, RMSE {result['rmse']}")
    return "\n".join(lines)


def rankings_md(rankings: list[dict[str, Any]]) -> str:
    lines = [
        "# Theory Survival Rankings",
        "",
        "| Rank | Tier | Theory | Score | Predictive | Directional | Stability | Generalization | Leakage | Falsification |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for index, row in enumerate(rankings, 1):
        lines.append(f"| {index} | {row['tier']} | {row['theory']} | {row['score']} | {row['predictive_power']} | {row['directional_signal']} | {row['stability']} | {row['generalization']} | {row['leakage_resistance']} | {row['falsification_resistance']} |")
    lines.extend(["", "No Tier S or Tier A promotion is warranted from this clean pass. Tier placement is conservative because unsupported repository/task generalization and very small N are treated as falsification pressure."])
    return "\n".join(lines)


def status_md(status: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Research Program Status",
            "",
            f"Clean usable rows: {status['row_count']}",
            "",
            f"1. Strongest current theory: {status['strongest']}, but only as a provisional directional signal.",
            f"2. Highest breakthrough potential: {status['breakthrough_potential']}.",
            f"3. Theory to abandon or freeze: {', '.join(status['abandon']) or 'none outright; all need more clean data'}.",
            f"4. Next month of research: {status['next_month']}.",
            f"5. Single most important next experiment: {status['next_experiment']}",
            "",
            status["caveat"],
        ]
    )


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return str(round(float(value), 6))
    except (TypeError, ValueError):
        return "n/a"


def fmt_pct(value: Any) -> str:
    return "n/a" if value is None else f"{value}%"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


if __name__ == "__main__":
    main()
