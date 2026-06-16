from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_hub.config import AgentConfig, load_config
from agent_hub.models import HubRequest
from agent_hub.providers.codex_cli import CodexCliProvider
from agent_hub.providers.errors import ProviderError
from agent_hub.providers.openai_compatible import OpenAICompatibleProvider
from agent_hub.research.capability_embedding import compute_capability_embedding
from agent_hub.research.model_clusters import compute_model_clusters
from agent_hub.research.model_distance import build_behavior_vectors, compute_distance_matrix
from agent_hub.research.telemetry import research_dir


MODELS = {
    "gemma4:31b-cloud": "ollama-gemma-cloud",
    "nemotron-3-super:cloud": "ollama-nemotron-cloud",
    "gpt-5.5": "codex-cli",
}
REPOSITORIES = ("Agent-Hub", "ytdl_site", "face")
CONTEXT_PERCENT = 50
FULL_CONTEXT_TOKENS = 12_000
MAX_OUTPUT_TOKENS = 360
RELEVANT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml", ".md", ".html", ".css"}
IGNORED_PARTS = {".git", ".agent-hub", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", "dist", "build", ".next"}


@dataclass(frozen=True, slots=True)
class FreshTask:
    id: str
    split: str
    repository: str
    task_type: str
    title: str
    prompt: str
    expected_keywords: tuple[str, ...]
    anchors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextFile:
    path: str
    text: str
    tokens: int
    score: int = 0


TASKS: tuple[FreshTask, ...] = (
    FreshTask(
        "pgx-20260616-001",
        "train",
        "Agent-Hub",
        "bug_fix",
        "Provider result normalization edge case",
        "Find a minimal bug fix for provider result normalization when a provider returns malformed or partial JSON. Return JSON with diagnosis, minimal_patch, validation_command, and residual_risk.",
        ("diagnosis", "patch", "validation", "risk", "provider"),
        ("providers", "response", "normalization", "errors"),
    ),
    FreshTask(
        "pgx-20260616-002",
        "train",
        "ytdl_site",
        "code_generation",
        "Download request status helper",
        "Design a small reusable helper for tracking download request status without changing the public Flask route contract. Return JSON with intent, code_sketch, integration_points, and tests.",
        ("helper", "status", "route", "tests", "flask"),
        ("app.py", "templates", "download", "request"),
    ),
    FreshTask(
        "pgx-20260616-003",
        "train",
        "face",
        "refactor",
        "Face script dependency boundary",
        "Propose a conservative refactor that separates image loading, face detection, and display/output concerns while preserving behavior. Return JSON with target, refactor_plan, invariants, and validation.",
        ("refactor", "image", "detection", "validation", "behavior"),
        ("Face.py", "cv2", "image", "face"),
    ),
    FreshTask(
        "pgx-20260616-004",
        "train",
        "Agent-Hub",
        "testing",
        "Routing memory privacy tests",
        "Propose focused tests for routing memory privacy behavior, especially prompt storage disabled/enabled boundaries. Return JSON with test_targets, cases, assertions, and command.",
        ("test", "privacy", "routing", "assertions", "command"),
        ("routing_memory", "privacy", "tests", "store"),
    ),
    FreshTask(
        "pgx-20260616-005",
        "train",
        "ytdl_site",
        "analysis",
        "Flask downloader risk analysis",
        "Analyze the data flow and operational risks in the downloader app from form submission through response rendering. Return JSON with summary, evidence, tradeoffs, and recommendation.",
        ("analysis", "data", "risk", "recommendation", "flask"),
        ("app.py", "templates", "requirements", "download"),
    ),
    FreshTask(
        "pgx-20260616-006",
        "predict",
        "face",
        "bug_fix",
        "Missing cascade/image failure handling",
        "Find a minimal bug fix for failed image reads or missing cascade resources in the face detection script. Return JSON with diagnosis, minimal_patch, validation_command, and residual_risk.",
        ("diagnosis", "cascade", "image", "validation", "risk"),
        ("Face.py", "cascade", "imread", "cv2"),
    ),
    FreshTask(
        "pgx-20260616-007",
        "predict",
        "Agent-Hub",
        "code_generation",
        "Research artifact manifest helper",
        "Design a small helper that writes a manifest for research artifacts produced by one experiment run. Return JSON with intent, code_sketch, integration_points, and tests.",
        ("manifest", "artifact", "code", "tests", "research"),
        ("research", "telemetry", "report", "json"),
    ),
    FreshTask(
        "pgx-20260616-008",
        "predict",
        "ytdl_site",
        "refactor",
        "Template rendering cleanup",
        "Propose a conservative refactor that makes template rendering paths clearer while preserving current user-visible behavior. Return JSON with target, refactor_plan, invariants, and validation.",
        ("refactor", "template", "behavior", "validation", "route"),
        ("templates", "index.html", "render_template", "app.py"),
    ),
    FreshTask(
        "pgx-20260616-009",
        "predict",
        "face",
        "testing",
        "Face detection failure mode tests",
        "Propose focused tests for face detection failure modes without requiring a live camera or GUI window. Return JSON with test_targets, cases, assertions, and command.",
        ("test", "failure", "mock", "assertions", "command"),
        ("Face.py", "cv2", "imshow", "detect"),
    ),
    FreshTask(
        "pgx-20260616-010",
        "predict",
        "Agent-Hub",
        "analysis",
        "Provider permission boundary analysis",
        "Analyze the provider permission boundary for local code, cloud models, and Codex CLI execution. Return JSON with summary, evidence, tradeoffs, and recommendation.",
        ("analysis", "permission", "provider", "tradeoffs", "recommendation"),
        ("providers", "permissions", "codex_cli", "security"),
    ),
)


def run_experiment(state_dir: str | Path, *, collect: bool, timeout_seconds: float | None) -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    roots = default_repo_roots(Path.cwd())
    if collect:
        collect_rows(directory, roots, timeout_seconds=timeout_seconds)
    rows = load_rows(directory / "prospective_geometry_runs.jsonl")
    return analyze_rows(directory, rows)


def collect_rows(directory: Path, roots: dict[str, Path], *, timeout_seconds: float | None) -> Path:
    path = directory / "prospective_geometry_runs.jsonl"
    seen = existing_keys(path)
    config = load_config(auto_detect=False)
    agents = resolve_agents(config, timeout_seconds=timeout_seconds)
    indexes = {repo: context_index(root) for repo, root in roots.items() if root.exists()}
    for task in TASKS:
        root = roots.get(task.repository)
        selected = select_context(indexes.get(task.repository, []), task)
        for model, agent_name in MODELS.items():
            key = f"{task.id}:{model}"
            if key in seen:
                continue
            agent = agents.get(model)
            if agent is None or root is None or not root.exists():
                error = f"agent or repository unavailable: agent={agent_name}, repository={task.repository}"
                row = failure_row(task, model, agent_name, selected, error)
            else:
                row = run_cell(task, model, agent, root, selected)
            append_jsonl(path, row)
            seen.add(key)
    return path


def resolve_agents(config: Any, *, timeout_seconds: float | None) -> dict[str, AgentConfig]:
    agents: dict[str, AgentConfig] = {}
    for model, agent_name in MODELS.items():
        agent = config.agents.get(agent_name)
        if agent is None:
            continue
        if timeout_seconds is not None:
            agent.timeout_seconds = timeout_seconds
        agents[model] = agent
    return agents


def run_cell(task: FreshTask, model: str, agent: AgentConfig, root: Path, selected: list[ContextFile]) -> dict[str, Any]:
    context = render_context(task, root, selected)
    prompt = render_prompt(task)
    request = HubRequest(
        messages=[{"role": "user", "content": prompt}],
        session_id=f"prospective-geometry-{uuid.uuid4().hex}",
        task=task.task_type,
        context=context,
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.1,
        raw={"agent_hub": {"context_budget_tokens": sum(item.tokens for item in selected), "context_usage": {"context_tokens": sum(item.tokens for item in selected), "selected_files": [item.path for item in selected]}}},
        metadata={"context_files": [item.path for item in selected]},
    )
    started = time.perf_counter()
    text = ""
    error = ""
    try:
        provider = CodexCliProvider(agent) if (agent.provider_type == "codex-cli" or agent.provider == "codex-cli") else OpenAICompatibleProvider(agent)
        result = provider.complete(request)
        text = result.text or ""
    except ProviderError as exc:
        error = f"{exc.error_type}: {exc}"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    score_payload = score_output(text, error, task)
    return {
        "object": "agent_hub.research.prospective_geometry_row",
        "row_id": uuid.uuid4().hex,
        "dedupe_key": f"{task.id}:{model}",
        "experiment_id": "prospective-capability-geometry-2026-06-16",
        "source": "prospective_geometry_runs.jsonl",
        "prospective": True,
        "context_percent": CONTEXT_PERCENT,
        "split": task.split,
        "model": model,
        "agent": agent.name,
        "provider": agent.provider,
        "provider_type": agent.provider_type or agent.provider,
        "repository": task.repository,
        "task_id": task.id,
        "task_type": task.task_type,
        "task_title": task.title,
        "context_tokens": sum(item.tokens for item in selected),
        "context_token_count": sum(item.tokens for item in selected),
        "selected_files": [item.path for item in selected],
        "file_count": len(selected),
        "success": score_payload["success"],
        "validation_score": score_payload["score"],
        "validation_reasons": score_payload["reasons"],
        "latency_ms": latency_ms,
        "cost_estimate": 0.0,
        "output_tokens": max(1, len(text) // 4) if text else 0,
        "retry_count": 0,
        "error": error,
        "timeout": "timeout" in error.lower(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "output_preview": text[:1200],
    }


def failure_row(task: FreshTask, model: str, agent_name: str, selected: list[ContextFile], error: str) -> dict[str, Any]:
    score_payload = score_output("", error, task)
    return {
        "object": "agent_hub.research.prospective_geometry_row",
        "row_id": uuid.uuid4().hex,
        "dedupe_key": f"{task.id}:{model}",
        "experiment_id": "prospective-capability-geometry-2026-06-16",
        "source": "prospective_geometry_runs.jsonl",
        "prospective": True,
        "context_percent": CONTEXT_PERCENT,
        "split": task.split,
        "model": model,
        "agent": agent_name,
        "provider": "",
        "provider_type": "",
        "repository": task.repository,
        "task_id": task.id,
        "task_type": task.task_type,
        "task_title": task.title,
        "context_tokens": sum(item.tokens for item in selected),
        "context_token_count": sum(item.tokens for item in selected),
        "selected_files": [item.path for item in selected],
        "file_count": len(selected),
        "success": score_payload["success"],
        "validation_score": score_payload["score"],
        "validation_reasons": score_payload["reasons"],
        "latency_ms": 0.0,
        "cost_estimate": 0.0,
        "output_tokens": 0,
        "retry_count": 0,
        "error": error,
        "timeout": "timeout" in error.lower(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "output_preview": "",
    }


def analyze_rows(directory: Path, rows: list[dict[str, Any]]) -> dict[str, Path]:
    tasks_path = directory / "prospective_geometry_tasks.json"
    tasks_path.write_text(json.dumps([task_payload(task) for task in TASKS], indent=2), encoding="utf-8")
    training = [row for row in rows if row.get("split") == "train"]
    prediction = [row for row in rows if row.get("split") == "predict"]
    behavior = build_behavior_vectors(training)
    distance = compute_distance_matrix(behavior)
    embedding = compute_capability_embedding(behavior)
    clusters = compute_model_clusters(behavior, distance)
    write_json(directory / "model_behavior_vectors_new.json", behavior)
    write_json(directory / "model_distance_matrix_new.json", distance)
    write_json(directory / "capability_embedding_new.json", embedding)
    write_json(directory / "model_clusters_new.json", clusters)

    prediction_payload = predict_from_geometry(training, prediction, distance)
    falsification_payload = falsify_geometry(rows, training, prediction, distance, clusters)
    stability_payload = bootstrap_stability(training, iterations=200)
    verdict_payload = verdict(prediction_payload, falsification_payload, stability_payload)

    write_json(directory / "geometry_prediction_metrics_new.json", prediction_payload)
    write_json(directory / "geometry_falsification_new.json", falsification_payload)
    write_json(directory / "geometry_stability_new.json", stability_payload)
    write_json(directory / "prospective_geometry_verdict.json", verdict_payload)
    (directory / "geometry_training_report.md").write_text(training_report(training, behavior, distance, embedding, clusters), encoding="utf-8")
    (directory / "geometry_prediction_report.md").write_text(prediction_report(prediction_payload), encoding="utf-8")
    (directory / "geometry_falsification_report.md").write_text(falsification_report(falsification_payload), encoding="utf-8")
    (directory / "geometry_stability_report.md").write_text(stability_report(stability_payload), encoding="utf-8")
    (directory / "prospective_geometry_verdict.md").write_text(verdict_report(verdict_payload), encoding="utf-8")
    return {
        "tasks": tasks_path,
        "runs": directory / "prospective_geometry_runs.jsonl",
        "behavior": directory / "model_behavior_vectors_new.json",
        "distance": directory / "model_distance_matrix_new.json",
        "embedding": directory / "capability_embedding_new.json",
        "training_report": directory / "geometry_training_report.md",
        "prediction_report": directory / "geometry_prediction_report.md",
        "falsification_report": directory / "geometry_falsification_report.md",
        "stability_report": directory / "geometry_stability_report.md",
        "verdict": directory / "prospective_geometry_verdict.md",
    }


def predict_from_geometry(training: list[dict[str, Any]], prediction: list[dict[str, Any]], distance: dict[str, Any]) -> dict[str, Any]:
    train_scores = {model: mean(row["validation_score"] for row in training if row["model"] == model) for model in MODELS}
    global_mean = mean(row["validation_score"] for row in training)
    rows = []
    actual: list[float] = []
    predicted: list[float] = []
    for row in prediction:
        model = row["model"]
        neighbors = [item for item in distance.get("nearest_neighbors", {}).get(model, []) if item["model"] in train_scores]
        if neighbors:
            weighted_sum = 0.0
            weight_total = 0.0
            for item in neighbors:
                weight = 1.0 / (float(item["distance"]) + 1e-6)
                weighted_sum += train_scores[item["model"]] * weight
                weight_total += weight
            pred = weighted_sum / weight_total if weight_total else global_mean
            method = "inverse_distance_neighbor_training_score"
        else:
            pred = global_mean
            method = "global_training_mean"
        act = float(row["validation_score"])
        actual.append(act)
        predicted.append(pred)
        rows.append({
            "task_id": row["task_id"],
            "task_type": row["task_type"],
            "repository": row["repository"],
            "model": model,
            "predicted": round(pred, 6),
            "actual": round(act, 6),
            "error": round(pred - act, 6),
            "method": method,
        })
    stats = regression_stats(actual, predicted)
    return {
        "object": "agent_hub.research.prospective_geometry_prediction",
        "training_task_count": len({row["task_id"] for row in training}),
        "prediction_task_count": len({row["task_id"] for row in prediction}),
        "prediction_rows": rows,
        **stats,
        "notes": [
            "Predictions use only Phase 1 geometry and training validation scores.",
            "No second-half tasks are used to rebuild distances, clusters, or embeddings.",
        ],
    }


def falsify_geometry(rows: list[dict[str, Any]], training: list[dict[str, Any]], prediction: list[dict[str, Any]], distance: dict[str, Any], clusters: dict[str, Any]) -> dict[str, Any]:
    all_scores = {(row["model"], row["task_id"]): float(row["validation_score"]) for row in rows}
    model_means = {model: mean(row["validation_score"] for row in rows if row["model"] == model) for model in MODELS}
    pairs = distance.get("pairs", [])
    close_threshold = percentile([float(row["composite"]) for row in pairs], 0.34)
    distant_threshold = percentile([float(row["composite"]) for row in pairs], 0.67)
    close_different = []
    distant_similar = []
    for pair in pairs:
        left = pair["model_i"]
        right = pair["model_j"]
        score_gap = abs(model_means.get(left, 0.0) - model_means.get(right, 0.0))
        task_gaps = [
            abs(all_scores.get((left, task.id), 0.0) - all_scores.get((right, task.id), 0.0))
            for task in TASKS
        ]
        max_task_gap = max(task_gaps) if task_gaps else 0.0
        record = {"model_i": left, "model_j": right, "distance": pair["composite"], "mean_score_gap": round(score_gap, 6), "max_task_gap": round(max_task_gap, 6)}
        if float(pair["composite"]) <= close_threshold and max_task_gap >= 0.35:
            close_different.append(record)
        if float(pair["composite"]) >= distant_threshold and score_gap <= 0.10:
            distant_similar.append(record)
    contradictory = []
    for task in TASKS:
        task_rows = [row for row in rows if row["task_id"] == task.id]
        scores = [float(row["validation_score"]) for row in task_rows]
        if scores and max(scores) - min(scores) >= 0.45:
            contradictory.append({
                "task_id": task.id,
                "split": task.split,
                "task_type": task.task_type,
                "repository": task.repository,
                "score_range": round(max(scores) - min(scores), 6),
                "scores": {row["model"]: row["validation_score"] for row in task_rows},
            })
    assignments = clusters.get("model_assignments", {})
    collapsed = len(set(assignments.values())) <= 1 if assignments else True
    return {
        "object": "agent_hub.research.prospective_geometry_falsification",
        "close_models_with_different_behavior": close_different,
        "distant_models_with_similar_behavior": distant_similar,
        "unstable_or_collapsed_training_clusters": collapsed,
        "contradictory_task_outcomes": contradictory,
        "falsification_found": bool(close_different or distant_similar or contradictory or collapsed),
        "notes": ["Falsification checks use held-out outcomes only as tests against the Phase 1 geometry."],
    }


def bootstrap_stability(training: list[dict[str, Any]], *, iterations: int) -> dict[str, Any]:
    task_ids = sorted({row["task_id"] for row in training})
    if not task_ids:
        return {"object": "agent_hub.research.prospective_geometry_stability", "distance_stability": 0.0, "cluster_stability": 0.0, "embedding_stability": 0.0, "bootstrap_rows": []}
    base_behavior = build_behavior_vectors(training)
    base_distance = compute_distance_matrix(base_behavior)
    base_clusters = compute_model_clusters(base_behavior, base_distance)
    base_embedding = compute_capability_embedding(base_behavior)
    base_distance_vec = pair_vector(base_distance, "composite")
    base_embedding_vec = embedding_distance_vector(base_embedding)
    random.seed(20260616)
    boot_rows = []
    for index in range(iterations):
        sampled = [random.choice(task_ids) for _ in task_ids]
        sample_rows = [row for task_id in sampled for row in training if row["task_id"] == task_id]
        behavior = build_behavior_vectors(sample_rows)
        distance = compute_distance_matrix(behavior)
        clusters = compute_model_clusters(behavior, distance)
        embedding = compute_capability_embedding(behavior)
        boot_rows.append({
            "iteration": index + 1,
            "sampled_tasks": sampled,
            "distance_correlation": round(correlation(base_distance_vec, pair_vector(distance, "composite")), 6),
            "cluster_stability": round(cluster_agreement(base_clusters, clusters), 6),
            "embedding_stability": round(correlation(base_embedding_vec, embedding_distance_vector(embedding)), 6),
        })
    return {
        "object": "agent_hub.research.prospective_geometry_stability",
        "iterations": iterations,
        "distance_stability": round(mean(row["distance_correlation"] for row in boot_rows), 6),
        "cluster_stability": round(mean(row["cluster_stability"] for row in boot_rows), 6),
        "embedding_stability": round(mean(row["embedding_stability"] for row in boot_rows), 6),
        "bootstrap_rows": boot_rows,
    }


def verdict(prediction: dict[str, Any], falsification: dict[str, Any], stability: dict[str, Any]) -> dict[str, Any]:
    pred_corr = float(prediction.get("correlation", 0.0))
    r2 = float(prediction.get("r2", 0.0))
    distance_stability = float(stability.get("distance_stability", 0.0))
    cluster_stability = float(stability.get("cluster_stability", 0.0))
    survives_success = pred_corr > 0.70 and r2 > 0.40 and distance_stability > 0.80 and cluster_stability > 0.80
    fails_failure = pred_corr < 0.55 or r2 < 0.25 or cluster_stability <= 0.0
    return {
        "object": "agent_hub.research.prospective_geometry_verdict",
        "does_geometry_predict_unseen_tasks": pred_corr > 0.55 and r2 >= 0.25,
        "is_geometry_stable": distance_stability > 0.80 and cluster_stability > 0.80,
        "does_geometry_survive_falsification": not bool(falsification.get("falsification_found")),
        "is_geometry_merely_descriptive": not survives_success,
        "should_geometry_remain_active_research_direction": survives_success or (pred_corr >= 0.55 and distance_stability >= 0.70),
        "success_criteria_met": survives_success,
        "failure_criteria_met": fails_failure,
        "metrics": {
            "prediction_correlation": pred_corr,
            "r2": r2,
            "mae": prediction.get("mae", 0.0),
            "rmse": prediction.get("rmse", 0.0),
            "distance_stability": distance_stability,
            "cluster_stability": cluster_stability,
            "embedding_stability": stability.get("embedding_stability", 0.0),
        },
    }


def default_repo_roots(cwd: Path) -> dict[str, Path]:
    downloads = cwd.parent
    return {"Agent-Hub": cwd, "ytdl_site": downloads / "ytdl_site", "face": downloads / "face"}


def context_index(root: Path) -> list[ContextFile]:
    rows: list[ContextFile] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in RELEVANT_SUFFIXES:
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        rows.append(ContextFile(rel, text[:8000], max(1, len(text) // 4)))
    return rows[:800]


def select_context(files: list[ContextFile], task: FreshTask) -> list[ContextFile]:
    token_budget = int(FULL_CONTEXT_TOKENS * (CONTEXT_PERCENT / 100.0))
    terms = {task.task_type.replace("_", ""), *task.expected_keywords, *task.anchors}
    scored = []
    for item in files:
        haystack = f"{item.path}\n{item.text[:1200]}".lower()
        score = sum(3 for term in terms if str(term).lower() in haystack)
        score += 2 if task.task_type == "testing" and "test" in item.path.lower() else 0
        score += 1 if item.path.endswith((".py", ".js", ".ts", ".html")) else 0
        scored.append(ContextFile(item.path, item.text, item.tokens, score))
    scored.sort(key=lambda item: (-item.score, item.tokens, item.path))
    selected: list[ContextFile] = []
    used = 0
    for item in scored:
        if selected and used + item.tokens > token_budget:
            continue
        if not selected and item.tokens > token_budget:
            continue
        selected.append(item)
        used += item.tokens
        if used >= token_budget:
            break
    return selected


def render_context(task: FreshTask, root: Path, selected: list[ContextFile]) -> str:
    lines = [
        f"Repository: {task.repository}",
        f"Repository root: {root}",
        f"Task id: {task.id}",
        f"Task type: {task.task_type}",
        f"Fixed context budget: {CONTEXT_PERCENT}%",
        "",
    ]
    for item in selected:
        lines.extend([f"--- FILE: {item.path} ---", item.text[:6000], ""])
    return "\n".join(lines)


def render_prompt(task: FreshTask) -> str:
    return (
        "Fresh prospective capability-geometry task. Do not modify files. "
        "Use only the provided context. Return one compact JSON object and no Markdown.\n\n"
        f"Title: {task.title}\n"
        f"Repository: {task.repository}\n"
        f"Task type: {task.task_type}\n"
        f"Request: {task.prompt}"
    )


def score_output(text: str, error: str, task: FreshTask) -> dict[str, Any]:
    lower = text.lower()
    reasons = []
    if error:
        return {"score": 0.0, "success": False, "reasons": [f"provider_error={error[:160]}"]}
    if not text.strip():
        return {"score": 0.0, "success": False, "reasons": ["empty_output"]}
    score = 0.10
    if looks_like_json(text):
        score += 0.20
        reasons.append("json_like")
    keyword_hits = sum(1 for keyword in task.expected_keywords if keyword.lower() in lower)
    score += min(0.25, keyword_hits * 0.05)
    reasons.append(f"keyword_hits={keyword_hits}/{len(task.expected_keywords)}")
    anchor_hits = sum(1 for anchor in task.anchors if anchor.lower() in lower)
    score += min(0.20, anchor_hits * 0.05)
    reasons.append(f"anchor_hits={anchor_hits}/{len(task.anchors)}")
    actionable_terms = ("minimal", "test", "validate", "risk", "integration", "assert", "command", "preserve", "edge")
    actionable_hits = sum(1 for term in actionable_terms if term in lower)
    score += min(0.15, actionable_hits * 0.03)
    reasons.append(f"actionable_hits={actionable_hits}")
    if len(text) >= 300:
        score += 0.10
        reasons.append("substantive_length")
    if "```" in text:
        score -= 0.05
        reasons.append("markdown_fence_penalty")
    score = max(0.0, min(1.0, score))
    return {"score": round(score, 6), "success": score >= 0.62, "reasons": reasons}


def looks_like_json(text: str) -> bool:
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return False
    try:
        json.loads(stripped)
        return True
    except json.JSONDecodeError:
        return False


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def existing_keys(path: Path) -> set[str]:
    return {row.get("dedupe_key", "") for row in load_rows(path)}


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def task_payload(task: FreshTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "split": task.split,
        "repository": task.repository,
        "task_type": task.task_type,
        "title": task.title,
        "prompt": task.prompt,
        "expected_keywords": list(task.expected_keywords),
        "anchors": list(task.anchors),
        "context_percent": CONTEXT_PERCENT,
    }


def regression_stats(actual: list[float], predicted: list[float]) -> dict[str, float]:
    errors = [p - a for a, p in zip(actual, predicted)]
    mae = mean(abs(err) for err in errors)
    rmse = math.sqrt(mean(err * err for err in errors))
    corr = correlation(actual, predicted)
    actual_mean = mean(actual)
    sse = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    sst = sum((a - actual_mean) ** 2 for a in actual)
    r2 = 1.0 - (sse / sst) if sst else 0.0
    return {"correlation": round(corr, 6), "r2": round(r2, 6), "mae": round(mae, 6), "rmse": round(rmse, 6)}


def pair_vector(distance: dict[str, Any], metric: str) -> list[float]:
    return [float(row[metric]) for row in sorted(distance.get("pairs", []), key=lambda item: (item["model_i"], item["model_j"]))]


def embedding_distance_vector(embedding: dict[str, Any]) -> list[float]:
    coords = embedding.get("embedding_nd") or embedding.get("embedding_3d") or {}
    models = sorted(coords)
    values = []
    for i, left in enumerate(models):
        for right in models[i + 1 :]:
            values.append(euclidean([float(x) for x in coords[left]], [float(x) for x in coords[right]]))
    return values


def cluster_agreement(base: dict[str, Any], other: dict[str, Any]) -> float:
    base_clusters = base.get("model_assignments", {})
    other_clusters = other.get("model_assignments", {})
    models = sorted(set(base_clusters) & set(other_clusters))
    if len(models) < 2:
        return 0.0
    agree = 0
    total = 0
    for i, left in enumerate(models):
        for right in models[i + 1 :]:
            total += 1
            base_same = base_clusters[left] == base_clusters[right]
            other_same = other_clusters[left] == other_clusters[right]
            agree += int(base_same == other_same)
    return agree / total if total else 0.0


def correlation(a: list[float], b: list[float]) -> float:
    pairs = [(float(x), float(y)) for x, y in zip(a, b)]
    if len(pairs) < 2:
        return 0.0
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = math.sqrt(sum(x * x for x in dx)) * math.sqrt(sum(y * y for y in dy))
    return sum(x * y for x, y in zip(dx, dy)) / denom if denom else 0.0


def mean(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(len(ordered) * q) - 1)))
    return ordered[index]


def euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def training_report(training: list[dict[str, Any]], behavior: dict[str, Any], distance: dict[str, Any], embedding: dict[str, Any], clusters: dict[str, Any]) -> str:
    lines = [
        "# Geometry Training Report",
        "",
        "Phase 1 used only the first five fresh tasks. No historical priors, routing memory, previous success rates, or previous theory outputs were used as evidence.",
        "",
        f"- Training rows: {len(training)}",
        f"- Training tasks: {len({row['task_id'] for row in training})}",
        f"- Fixed context budget: {CONTEXT_PERCENT}%",
        f"- Models: {', '.join(behavior.get('models', {}).keys())}",
        "",
        "## Distance Matrix",
        "",
        "| model i | model j | euclidean | cosine | correlation | composite |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in distance.get("pairs", []):
        lines.append(f"| {row['model_i']} | {row['model_j']} | {row['euclidean']} | {row['cosine']} | {row['correlation']} | {row['composite']} |")
    lines.extend(["", "## Embedding", "", f"- Method: {embedding.get('method')}", f"- Explained variance ratio: {embedding.get('explained_variance_ratio', [])[:3]}", "", "## Clusters"])
    for model, cluster in clusters.get("model_assignments", {}).items():
        lines.append(f"- {model}: {cluster}")
    lines.append("")
    return "\n".join(lines)


def prediction_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Geometry Prediction Report",
        "",
        "Phase 2 predicted second-half task behavior using only the Phase 1 geometry.",
        "",
        f"- Prediction correlation: {payload.get('correlation')}",
        f"- R2: {payload.get('r2')}",
        f"- MAE: {payload.get('mae')}",
        f"- RMSE: {payload.get('rmse')}",
        "",
        "| task | model | predicted | actual | error |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("prediction_rows", []):
        lines.append(f"| {row['task_id']} | {row['model']} | {row['predicted']} | {row['actual']} | {row['error']} |")
    lines.append("")
    return "\n".join(lines)


def falsification_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Geometry Falsification Report",
        "",
        f"- Falsification found: {payload.get('falsification_found')}",
        f"- Unstable or collapsed training clusters: {payload.get('unstable_or_collapsed_training_clusters')}",
        f"- Close/different cases: {len(payload.get('close_models_with_different_behavior', []))}",
        f"- Distant/similar cases: {len(payload.get('distant_models_with_similar_behavior', []))}",
        f"- Contradictory task outcomes: {len(payload.get('contradictory_task_outcomes', []))}",
        "",
        "## Contradictory Outcomes",
    ]
    for row in payload.get("contradictory_task_outcomes", []):
        lines.append(f"- {row['task_id']} ({row['repository']} {row['task_type']}): range={row['score_range']} scores={row['scores']}")
    lines.append("")
    return "\n".join(lines)


def stability_report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Geometry Stability Report",
            "",
            f"- Bootstrap iterations: {payload.get('iterations', 0)}",
            f"- Distance stability: {payload.get('distance_stability')}",
            f"- Cluster stability: {payload.get('cluster_stability')}",
            f"- Embedding stability: {payload.get('embedding_stability')}",
            "",
        ]
    )


def verdict_report(payload: dict[str, Any]) -> str:
    metrics = payload.get("metrics", {})
    answer = [
        "# Prospective Geometry Verdict",
        "",
        "This was a prospective experiment: first-half tasks built the geometry, second-half tasks tested predictions.",
        "",
        f"1. Does geometry predict unseen tasks? {'Yes' if payload.get('does_geometry_predict_unseen_tasks') else 'No'} (correlation={metrics.get('prediction_correlation')}, R2={metrics.get('r2')}).",
        f"2. Is geometry stable? {'Yes' if payload.get('is_geometry_stable') else 'No'} (distance={metrics.get('distance_stability')}, clusters={metrics.get('cluster_stability')}, embedding={metrics.get('embedding_stability')}).",
        f"3. Does geometry survive falsification? {'Yes' if payload.get('does_geometry_survive_falsification') else 'No'}.",
        f"4. Is geometry merely descriptive? {'Yes' if payload.get('is_geometry_merely_descriptive') else 'No'}.",
        f"5. Should geometry remain an active research direction? {'Yes' if payload.get('should_geometry_remain_active_research_direction') else 'No'}.",
        "",
        f"- Success criteria met: {payload.get('success_criteria_met')}",
        f"- Failure criteria met: {payload.get('failure_criteria_met')}",
        "",
        "Do not overclaim: this verdict is limited by the small sample size of 10 tasks and three models.",
        "",
    ]
    return "\n".join(answer)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fresh prospective capability geometry experiment.")
    parser.add_argument("--state-dir", default=".agent-hub/state")
    parser.add_argument("--no-collect", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=None)
    args = parser.parse_args()
    paths = run_experiment(args.state_dir, collect=not args.no_collect, timeout_seconds=args.timeout_seconds)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
