from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import AgentConfig, load_config
from ..models import HubRequest
from ..providers.codex_cli import CodexCliProvider
from ..providers.errors import ProviderError
from ..providers.openai_compatible import OpenAICompatibleProvider
from ..token_budget import estimate_messages_tokens
from .telemetry import research_dir


MODELS = {
    "gemma4:31b-cloud": "ollama-gemma-cloud",
    "nemotron-3-super:cloud": "ollama-nemotron-cloud",
    "gpt-5.5": "codex-cli",
}
REPOSITORIES = ("Agent-Hub", "ytdl_site", "face")
TASK_TYPES = ("bug_fix", "code_generation", "refactor", "analysis", "testing")
CONTEXT_BUDGETS = (0, 25, 50, 75, 100)
FULL_CONTEXT_TOKENS = 12_000
RELEVANT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml", ".md", ".html", ".css"}
EXCLUDE_MARKERS = {
    "auth_error": ("unauthorized", "forbidden", "api key", "login", "authentication", "401", "403"),
    "subscription_failure": ("subscription", "payment required", "billing", "upgrade", "quota", "usage limit"),
    "timeout_no_useful_output": ("timed out", "timeout"),
    "provider_error": ("provider", "malformed response", "server error", "503", "502", "500", "connection"),
}


@dataclass(frozen=True, slots=True)
class MatrixTask:
    task_type: str
    prompt: str
    expected_keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextFile:
    path: str
    tokens: int
    text: str
    score: int


TASKS = {
    "bug_fix": MatrixTask(
        "bug_fix",
        "Find a likely defect or fragile edge case in this repository area and propose a minimal fix. Return JSON with keys diagnosis, patch_plan, validation, risk.",
        ("bug", "fix", "validation", "risk"),
    ),
    "code_generation": MatrixTask(
        "code_generation",
        "Design a small reusable implementation for this repository. Return JSON with keys intent, code_sketch, integration, validation.",
        ("implementation", "code", "integration", "validation"),
    ),
    "refactor": MatrixTask(
        "refactor",
        "Identify a conservative refactor that improves maintainability without changing behavior. Return JSON with keys target, refactor_plan, invariants, validation.",
        ("refactor", "behavior", "invariants", "validation"),
    ),
    "analysis": MatrixTask(
        "analysis",
        "Analyze the architecture or data flow relevant to the provided context. Return JSON with keys summary, evidence, tradeoffs, recommendation.",
        ("architecture", "evidence", "tradeoffs", "recommendation"),
    ),
    "testing": MatrixTask(
        "testing",
        "Propose focused tests for the provided repository context. Return JSON with keys test_targets, cases, assertions, command.",
        ("test", "cases", "assertions", "command"),
    ),
}


def run_balanced_live_matrix_experiment(
    state_dir: str | Path,
    *,
    repo_roots: dict[str, Path] | None = None,
    repetitions: int = 3,
    target_repetitions: int = 5,
    max_runs: int = 0,
    collect: bool = True,
    analyze: bool = True,
    timeout_seconds: float | None = None,
) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    roots = repo_roots or default_repo_roots(Path.cwd())
    if collect:
        collect_balanced_live_rows(
            state_dir,
            roots,
            repetitions=max(1, int(repetitions)),
            max_runs=max(0, int(max_runs)),
            timeout_seconds=timeout_seconds,
        )
    return analyze_balanced_live_matrix(state_dir, target_repetitions=target_repetitions) if analyze else {"balanced_live_matrix": str(matrix_path(state_dir))}


def collect_balanced_live_rows(
    state_dir: str | Path,
    repo_roots: dict[str, Path],
    *,
    repetitions: int,
    max_runs: int = 0,
    timeout_seconds: float | None = None,
) -> Path:
    config = load_config(auto_detect=False)
    path = matrix_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = _existing_keys(path)
    executed = 0
    indexes = {repo: _context_index(root) for repo, root in repo_roots.items()}
    agents: dict[str, AgentConfig] = {}
    for model, agent_name in MODELS.items():
        agent = config.agents.get(agent_name)
        if agent is None:
            row = _configuration_row(model, agent_name, "configured agent not found")
            _append_jsonl(path, row)
            seen.add(row["dedupe_key"])
        else:
            if timeout_seconds is not None:
                agent.timeout_seconds = timeout_seconds
            agents[model] = agent
    for repo in REPOSITORIES:
        root = repo_roots.get(repo)
        if root is None or not root.exists():
            for model, agent_name in MODELS.items():
                row = _configuration_row(model, agent_name, f"repository not found: {repo}")
                _append_jsonl(path, row)
                seen.add(row["dedupe_key"])
            continue
        for task_type in TASK_TYPES:
            task = TASKS[task_type]
            for budget in CONTEXT_BUDGETS:
                selected = _select_context(indexes[repo], task, budget)
                for repetition in range(1, repetitions + 1):
                    for model in MODELS:
                        agent = agents.get(model)
                        if agent is None:
                            continue
                        key = _dedupe_key(model, repo, task_type, budget, repetition)
                        if key in seen:
                            continue
                        row = _run_live_cell(agent, model, repo, root, task, budget, repetition, selected)
                        _append_jsonl(path, row)
                        seen.add(key)
                        executed += 1
                        if max_runs and executed >= max_runs:
                            return path
    return path


def analyze_balanced_live_matrix(state_dir: str | Path, *, target_repetitions: int = 5) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows, excluded = load_clean_balanced_rows(state_dir)
    audit = build_audit(state_dir, rows, excluded, target_repetitions=target_repetitions)
    audit_json = directory / "balanced_live_matrix_audit.json"
    audit_md = directory / "balanced_live_matrix_audit.md"
    audit_json.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    audit_md.write_text(_audit_markdown(audit), encoding="utf-8")

    capability_md = directory / "capability_geometry_balanced.md"
    model_task_md = directory / "model_task_geometry_balanced.md"
    mtc_md = directory / "model_task_context_balanced.md"
    sve_md = directory / "structure_vs_experience_balanced.md"
    general_md = directory / "balanced_generalization.md"
    rankings_md = directory / "balanced_theory_rankings.md"
    summary_md = directory / "balanced_live_research_summary.md"

    capability = evaluate_capability_geometry(rows)
    model_task = evaluate_model_task_geometry(rows)
    mtc = evaluate_model_task_context(rows)
    sve = evaluate_structure_vs_experience(rows)
    general = evaluate_generalization(rows, capability, model_task, mtc, sve)
    rankings = rank_theories(capability, model_task, mtc, sve, general)

    capability_md.write_text(_theory_markdown("Capability Geometry", capability), encoding="utf-8")
    model_task_md.write_text(_theory_markdown("Model-Task Geometry", model_task), encoding="utf-8")
    mtc_md.write_text(_theory_markdown("Model-Task-Context Compatibility", mtc), encoding="utf-8")
    sve_md.write_text(_theory_markdown("Structure vs Experience", sve), encoding="utf-8")
    general_md.write_text(_generalization_markdown(general), encoding="utf-8")
    rankings_md.write_text(_rankings_markdown(rankings), encoding="utf-8")
    summary_md.write_text(_summary_markdown(rows, excluded, rankings, capability, model_task, mtc, sve, general), encoding="utf-8")
    return {
        "balanced_live_matrix": str(matrix_path(state_dir)),
        "balanced_live_matrix_audit": str(audit_json),
        "balanced_live_matrix_audit_markdown": str(audit_md),
        "capability_geometry_balanced": str(capability_md),
        "model_task_geometry_balanced": str(model_task_md),
        "model_task_context_balanced": str(mtc_md),
        "structure_vs_experience_balanced": str(sve_md),
        "balanced_generalization": str(general_md),
        "balanced_theory_rankings": str(rankings_md),
        "balanced_live_research_summary": str(summary_md),
    }


def matrix_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "balanced_live_matrix.jsonl"


def default_repo_roots(cwd: Path) -> dict[str, Path]:
    downloads = cwd.parent
    return {
        "Agent-Hub": cwd,
        "ytdl_site": downloads / "ytdl_site",
        "face": downloads / "face",
    }


def load_clean_balanced_rows(state_dir: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    usable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _load_jsonl(matrix_path(state_dir)):
        reason = _exclusion_reason(row, seen)
        if reason:
            row = dict(row)
            row["excluded_reason"] = reason
            excluded.append(row)
            continue
        seen.add(row["dedupe_key"])
        usable.append(_normalize_clean_row(row))
    return usable, excluded


def build_audit(state_dir: str | Path, rows: list[dict[str, Any]], excluded: list[dict[str, Any]], *, target_repetitions: int) -> dict[str, Any]:
    expected_min = len(MODELS) * len(REPOSITORIES) * len(TASK_TYPES) * len(CONTEXT_BUDGETS) * 3
    expected_target = len(MODELS) * len(REPOSITORIES) * len(TASK_TYPES) * len(CONTEXT_BUDGETS) * target_repetitions
    matrix_counts = Counter((row["model"], row["repository"], row["task_type"], row["context_budget"]) for row in rows)
    missing_min = [
        {"model": model, "repository": repo, "task_type": task, "context_budget": budget, "usable_repetitions": matrix_counts[(model, repo, task, budget)]}
        for model in MODELS
        for repo in REPOSITORIES
        for task in TASK_TYPES
        for budget in CONTEXT_BUDGETS
        if matrix_counts[(model, repo, task, budget)] < 3
    ]
    return {
        "object": "agent_hub.research.balanced_live_matrix_audit",
        "source_file": str(matrix_path(state_dir)),
        "allowed_models": list(MODELS),
        "repositories": list(REPOSITORIES),
        "task_types": list(TASK_TYPES),
        "context_budgets": list(CONTEXT_BUDGETS),
        "expected_minimum_rows": expected_min,
        "expected_target_rows": expected_target,
        "usable_rows": len(rows),
        "excluded_rows": len(excluded),
        "complete_minimum_matrix": len(rows) >= expected_min and not missing_min,
        "missing_minimum_cells": missing_min,
        "exclusions_by_reason": dict(Counter(row.get("excluded_reason", "unknown") for row in excluded)),
        "usable_rows_by_model": dict(Counter(row["model"] for row in rows)),
        "usable_rows_by_repository": dict(Counter(row["repository"] for row in rows)),
        "usable_rows_by_task_type": dict(Counter(row["task_type"] for row in rows)),
        "usable_rows_by_context_budget": {str(key): value for key, value in Counter(row["context_budget"] for row in rows).items()},
    }


def evaluate_capability_geometry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vectors = _model_vectors(rows)
    pairs = _pairwise_model_distances(vectors)
    stability = _split_stability(rows, lambda rs: _pairwise_model_distances(_model_vectors(rs)), "distance_correlation")
    prediction = _leave_one_model_prediction(rows)
    score = _score(prediction["correlation"], stability["mean"], 1.0 - _avg(row["distance"] for row in pairs))
    return {
        "score": score,
        "predictive_power": prediction["correlation"],
        "stability": stability["mean"],
        "generalization": 0.0,
        "leakage_resistance": _leakage_resistance(rows),
        "falsification_resistance": _falsification_resistance(score, stability["mean"]),
        "summary": _verdict(score, "behavioral distance has useful signal", "capability distances are unstable or weak"),
        "evidence": {
            "model_vectors": vectors,
            "pairwise_distances": pairs,
            "leave_one_model_prediction": prediction,
            "split_stability": stability,
        },
    }


def evaluate_model_task_geometry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cells = _group_summary(rows, ("model", "task_type"))
    prediction = _predict_by_group(rows, ("model", "task_type"))
    task_rank_stability = _split_rank_stability(rows, "repository", ("model", "task_type"))
    score = _score(prediction["correlation"], task_rank_stability, _coverage_score(cells, len(MODELS) * len(TASK_TYPES)))
    return {
        "score": score,
        "predictive_power": prediction["correlation"],
        "stability": task_rank_stability,
        "generalization": 0.0,
        "leakage_resistance": _leakage_resistance(rows),
        "falsification_resistance": _falsification_resistance(score, task_rank_stability),
        "summary": _verdict(score, "model-task compatibility survives", "model-task effects do not predict clean rows well"),
        "evidence": {"cells": cells, "leave_one_cell_prediction": prediction},
    }


def evaluate_model_task_context(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cells = _group_summary(rows, ("model", "task_type", "context_budget"))
    prediction = _predict_by_group(rows, ("model", "task_type", "context_budget"))
    context_monotonicity = _context_monotonicity(rows)
    stability = _split_rank_stability(rows, "repository", ("model", "task_type", "context_budget"))
    score = _score(prediction["correlation"], stability, context_monotonicity)
    return {
        "score": score,
        "predictive_power": prediction["correlation"],
        "stability": stability,
        "generalization": 0.0,
        "leakage_resistance": _leakage_resistance(rows),
        "falsification_resistance": _falsification_resistance(score, stability),
        "summary": _verdict(score, "triadic model-task-context compatibility survives", "context does not add stable compatibility signal"),
        "evidence": {"cells": cells, "prediction": prediction, "context_monotonicity": context_monotonicity},
    }


def evaluate_structure_vs_experience(rows: list[dict[str, Any]]) -> dict[str, Any]:
    structure = _structure_predictions(rows)
    experience = _experience_predictions(rows)
    combined = [(a + b) / 2.0 for a, b in zip(structure["predictions"], experience["predictions"])]
    actual = [1.0 if row["success"] else 0.0 for row in rows]
    combined_stats = _stats(actual, combined)
    improvement = max(0.0, combined_stats["r2"] - max(structure["r2"], experience["r2"]))
    score = _score(combined_stats["correlation"], improvement, _leakage_resistance(rows))
    return {
        "score": score,
        "predictive_power": combined_stats["correlation"],
        "stability": _avg([structure["correlation"], experience["correlation"], combined_stats["correlation"]]),
        "generalization": 0.0,
        "leakage_resistance": _leakage_resistance(rows),
        "falsification_resistance": _falsification_resistance(score, improvement),
        "summary": _verdict(score, "structure plus experience improves prediction", "structure plus experience does not beat simpler group priors"),
        "evidence": {"structure": structure, "experience": experience, "combined": combined_stats, "r2_improvement": improvement},
    }


def evaluate_generalization(rows: list[dict[str, Any]], *theories: dict[str, Any]) -> dict[str, Any]:
    results = {
        "unseen_repository": _generalization_split(rows, "repository"),
        "unseen_task": _generalization_split(rows, "task_type"),
        "unseen_model": _generalization_split(rows, "model"),
    }
    mean_generalization = _avg(item["correlation"] for item in results.values())
    names = ("capability_geometry", "model_task_geometry", "model_task_context", "structure_vs_experience")
    for name, theory in zip(names, theories):
        theory["generalization"] = mean_generalization
    return {"results": results, "mean_generalization": round(mean_generalization, 6)}


def rank_theories(
    capability: dict[str, Any],
    model_task: dict[str, Any],
    mtc: dict[str, Any],
    sve: dict[str, Any],
    general: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for name, theory in (
        ("Capability Geometry", capability),
        ("Model-Task Geometry", model_task),
        ("Model-Task-Context Compatibility", mtc),
        ("Structure vs Experience", sve),
    ):
        total = round(
            100.0
            * _avg(
                [
                    theory["predictive_power"],
                    theory["stability"],
                    theory["generalization"],
                    theory["leakage_resistance"],
                    theory["falsification_resistance"],
                ]
            ),
            2,
        )
        rows.append({"theory": name, "score": total, "tier": _tier(total), **{key: round(float(theory[key]), 6) for key in ("predictive_power", "stability", "generalization", "leakage_resistance", "falsification_resistance")}})
    return sorted(rows, key=lambda row: row["score"], reverse=True)


def _run_live_cell(
    agent: AgentConfig,
    model: str,
    repo: str,
    root: Path,
    task: MatrixTask,
    budget: int,
    repetition: int,
    selected: list[ContextFile],
) -> dict[str, Any]:
    context = _render_context(repo, root, selected, budget)
    prompt = _prompt(repo, task, budget, repetition)
    messages = [{"role": "user", "content": prompt}]
    request = HubRequest(
        messages=messages,
        session_id=f"balanced-live-{uuid.uuid4().hex}",
        task=task.task_type,
        context=context,
        max_tokens=260,
        temperature=0.1,
        raw={"agent_hub": {"context_budget_tokens": max(1, sum(item.tokens for item in selected)), "context_usage": {"context_tokens": sum(item.tokens for item in selected), "selected_files": [item.path for item in selected]}}},
        metadata={"context_files": [item.path for item in selected]},
    )
    started = time.perf_counter()
    text = ""
    error = ""
    retries = 0
    try:
        provider = CodexCliProvider(agent) if agent.provider_type == "codex-cli" or agent.provider == "codex-cli" else OpenAICompatibleProvider(agent)
        result = provider.complete(request)
        text = result.text or ""
    except ProviderError as exc:
        error = f"{exc.error_type}: {exc}"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    validation = _validate_output(text, task, repo)
    if error and _useful_text(text):
        validation["score"] = max(validation["score"], 0.25)
    return {
        "object": "agent_hub.research.balanced_live_matrix_row",
        "row_id": uuid.uuid4().hex,
        "dedupe_key": _dedupe_key(model, repo, task.task_type, budget, repetition),
        "live_execution": True,
        "synthetic": False,
        "model": model,
        "agent": agent.name,
        "provider": agent.provider,
        "provider_type": agent.provider_type or agent.provider,
        "repository": repo,
        "repository_root": str(root),
        "task_type": task.task_type,
        "context_budget": budget,
        "context_percent": budget,
        "context_tokens": sum(item.tokens for item in selected),
        "context_token_count": sum(item.tokens for item in selected),
        "selected_files": [item.path for item in selected],
        "file_count": len(selected),
        "success": validation["success"],
        "validation_score": validation["score"],
        "validation_reasons": validation["reasons"],
        "latency": latency_ms,
        "latency_ms": latency_ms,
        "retries": retries,
        "retry_count": retries,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "output_preview": text[:800],
    }


def _configuration_row(model: str, agent: str, error: str) -> dict[str, Any]:
    return {
        "object": "agent_hub.research.balanced_live_matrix_row",
        "row_id": uuid.uuid4().hex,
        "dedupe_key": f"configuration::{model}::{agent}::{hashlib.sha256(error.encode()).hexdigest()[:8]}",
        "live_execution": False,
        "synthetic": False,
        "model": model,
        "agent": agent,
        "provider": "",
        "provider_type": "",
        "repository": "",
        "task_type": "",
        "context_budget": 0,
        "context_percent": 0,
        "context_tokens": 0,
        "success": False,
        "validation_score": 0.0,
        "latency": 0.0,
        "latency_ms": 0.0,
        "retries": 0,
        "retry_count": 0,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "output_preview": "",
    }


def _context_index(root: Path) -> list[ContextFile]:
    rows: list[ContextFile] = []
    ignored = {".git", ".agent-hub", "__pycache__", ".pytest_cache", "node_modules", "dist", "build", ".next"}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in RELEVANT_SUFFIXES:
            continue
        if any(part in ignored for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        rows.append(ContextFile(rel, max(1, len(text) // 4), text[:6000], 0))
    return rows[:700]


def _select_context(files: list[ContextFile], task: MatrixTask, budget: int) -> list[ContextFile]:
    if budget <= 0:
        return []
    token_budget = int(FULL_CONTEXT_TOKENS * (budget / 100.0))
    terms = {task.task_type.replace("_", ""), *task.expected_keywords, *task.prompt.lower().split()}
    scored = []
    for item in files:
        lower_path = item.path.lower()
        score = sum(2 for term in terms if str(term).strip(".,:;_").lower() in lower_path)
        if "test" in lower_path:
            score += 2 if task.task_type == "testing" else 1
        if item.path.endswith((".py", ".js", ".ts")):
            score += 1
        scored.append(ContextFile(item.path, item.tokens, item.text, score))
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


def _render_context(repo: str, root: Path, selected: list[ContextFile], budget: int) -> str:
    if not selected:
        return ""
    lines = [f"Repository: {repo}", f"Root: {root}", f"Context budget: {budget}%", ""]
    for item in selected:
        lines.extend([f"File: {item.path}", "```", item.text[: min(len(item.text), item.tokens * 4)], "```", ""])
    return "\n".join(lines)


def _prompt(repo: str, task: MatrixTask, budget: int, repetition: int) -> str:
    return "\n".join(
        [
            "Balanced Live Research Matrix task.",
            f"Repository: {repo}",
            f"Task type: {task.task_type}",
            f"Context budget: {budget}%",
            f"Repetition: {repetition}",
            task.prompt,
            "Do not edit files. Use only the provided context. If context is empty, answer from the repository/task description and say what evidence is missing.",
            "Return concise valid JSON only.",
        ]
    )


def _validate_output(text: str, task: MatrixTask, repo: str) -> dict[str, Any]:
    reasons = []
    score = 0.0
    lowered = text.lower()
    if _useful_text(text):
        score += 0.2
        reasons.append("useful_text")
    try:
        parsed = json.loads(_json_slice(text))
        if isinstance(parsed, dict) and len(parsed) >= 3:
            score += 0.25
            reasons.append("valid_json_object")
    except json.JSONDecodeError:
        parsed = None
    hits = sum(1 for word in task.expected_keywords if word.lower() in lowered)
    keyword_score = hits / max(1, len(task.expected_keywords))
    score += 0.35 * keyword_score
    if hits:
        reasons.append(f"keyword_coverage={hits}/{len(task.expected_keywords)}")
    if repo.lower().replace("-", "")[:4] in lowered.replace("-", "") or "repository" in lowered:
        score += 0.1
        reasons.append("repo_awareness")
    if any(marker in lowered for marker in ("validation", "test", "command", "risk", "assert")):
        score += 0.1
        reasons.append("verification_awareness")
    score = round(min(1.0, score), 6)
    return {"score": score, "success": score >= 0.6, "reasons": reasons}


def _json_slice(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _useful_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 20:
        return False
    if "provider returned malformed response" in stripped.lower():
        return False
    return True


def _exclusion_reason(row: dict[str, Any], seen: set[str]) -> str:
    key = str(row.get("dedupe_key") or "")
    if key in seen:
        return "duplicate_run"
    if row.get("synthetic") or not row.get("live_execution"):
        return "non_live_or_synthetic"
    if row.get("model") not in MODELS:
        return "disallowed_model"
    if row.get("provider_type") not in {"ollama-cloud", "codex-cli"} and not str(row.get("model", "")).endswith(":cloud"):
        return "disallowed_provider"
    error = str(row.get("error") or "")
    text = str(row.get("output_preview") or "")
    if error:
        classified = _classify_error(error)
        if classified in {"auth_error", "subscription_failure", "provider_error"}:
            return classified
        if classified == "timeout_no_useful_output" and not _useful_text(text):
            return classified
    if not _useful_text(text):
        return "no_useful_output"
    return ""


def _classify_error(error: str) -> str:
    lowered = error.lower()
    for reason, markers in EXCLUDE_MARKERS.items():
        if any(marker in lowered for marker in markers):
            return reason
    return "provider_error"


def _normalize_clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "context_budget": int(float(row.get("context_budget", row.get("context_percent", 0)) or 0)),
        "context_percent": int(float(row.get("context_percent", row.get("context_budget", 0)) or 0)),
        "context_tokens": int(float(row.get("context_tokens", row.get("context_token_count", 0)) or 0)),
        "validation_score": float(row.get("validation_score") or 0.0),
        "success": bool(row.get("success")),
        "latency_ms": float(row.get("latency_ms", row.get("latency", 0.0)) or 0.0),
        "retry_count": int(float(row.get("retry_count", row.get("retries", 0)) or 0)),
        "selected_files": list(row.get("selected_files") or []),
    }


def _model_vectors(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    vectors: dict[str, dict[str, float]] = {}
    for model in sorted({row["model"] for row in rows}):
        model_rows = [row for row in rows if row["model"] == model]
        vector = {
            "overall_success": _rate(model_rows),
            "overall_validation": _avg(row["validation_score"] for row in model_rows),
            "latency_score": 1.0 / (1.0 + _avg(row["latency_ms"] for row in model_rows) / 30_000.0),
        }
        for task in TASK_TYPES:
            task_rows = [row for row in model_rows if row["task_type"] == task]
            vector[f"task.{task}.success"] = _rate(task_rows)
            vector[f"task.{task}.validation"] = _avg(row["validation_score"] for row in task_rows)
        for budget in CONTEXT_BUDGETS:
            budget_rows = [row for row in model_rows if row["context_budget"] == budget]
            vector[f"context.{budget}.success"] = _rate(budget_rows)
            vector[f"context.{budget}.validation"] = _avg(row["validation_score"] for row in budget_rows)
        vectors[model] = {key: round(value, 6) for key, value in vector.items()}
    return vectors


def _pairwise_model_distances(vectors: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    models = sorted(vectors)
    features = sorted({key for vector in vectors.values() for key in vector})
    rows = []
    for index, left in enumerate(models):
        for right in models[index + 1 :]:
            a = [vectors[left].get(feature, 0.0) for feature in features]
            b = [vectors[right].get(feature, 0.0) for feature in features]
            rows.append({"left": left, "right": right, "distance": round(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))) / max(1.0, math.sqrt(len(features))), 6)})
    return rows


def _leave_one_model_prediction(rows: list[dict[str, Any]]) -> dict[str, float]:
    actual, predicted = [], []
    global_rate = _rate(rows)
    for row in rows:
        peers = [item for item in rows if item is not row and item["task_type"] == row["task_type"] and item["context_budget"] == row["context_budget"] and item["repository"] == row["repository"]]
        actual.append(1.0 if row["success"] else 0.0)
        predicted.append(_rate(peers) if peers else global_rate)
    return _stats(actual, predicted)


def _group_summary(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[key] for key in keys)].append(row)
    return [
        {**{key: value for key, value in zip(keys, group)}, "rows": len(items), "success_rate": round(_rate(items), 6), "validation_score": round(_avg(item["validation_score"] for item in items), 6)}
        for group, items in sorted(grouped.items())
    ]


def _predict_by_group(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, float]:
    actual, predicted = [], []
    global_rate = _rate(rows)
    for row in rows:
        peers = [item for item in rows if item is not row and all(item[key] == row[key] for key in keys)]
        actual.append(1.0 if row["success"] else 0.0)
        predicted.append(_rate(peers) if peers else global_rate)
    return _stats(actual, predicted)


def _context_monotonicity(rows: list[dict[str, Any]]) -> float:
    scores = []
    for model in MODELS:
        for task in TASK_TYPES:
            means = [_avg(row["validation_score"] for row in rows if row["model"] == model and row["task_type"] == task and row["context_budget"] == budget) for budget in CONTEXT_BUDGETS]
            pairs = sum(1 for a, b in zip(means, means[1:]) if b >= a)
            scores.append(pairs / max(1, len(CONTEXT_BUDGETS) - 1))
    return round(_avg(scores), 6)


def _split_stability(rows: list[dict[str, Any]], fn: Any, value_name: str) -> dict[str, Any]:
    full = fn(rows)
    split_scores = []
    for field in ("repository", "task_type", "context_budget"):
        for value in sorted({row[field] for row in rows}):
            subset = [row for row in rows if row[field] != value]
            if len({row["model"] for row in subset}) < 3:
                continue
            split = fn(subset)
            split_scores.append({"split": f"without_{field}:{value}", value_name: _distance_list_correlation(full, split)})
    return {"mean": round(_avg(row[value_name] for row in split_scores), 6), "splits": split_scores}


def _split_rank_stability(rows: list[dict[str, Any]], split_field: str, keys: tuple[str, ...]) -> float:
    full = _summary_map(rows, keys)
    scores = []
    for value in sorted({row[split_field] for row in rows}):
        subset = [row for row in rows if row[split_field] != value]
        split = _summary_map(subset, keys)
        common = sorted(set(full) & set(split))
        scores.append(_pearson([full[key] for key in common], [split[key] for key in common]) if len(common) >= 2 else 0.0)
    return round(_avg(scores), 6)


def _summary_map(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[Any, ...], float]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[key] for key in keys)].append(row)
    return {key: _avg(row["validation_score"] for row in items) for key, items in grouped.items()}


def _distance_list_correlation(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> float:
    lookup = {(row["left"], row["right"]): row["distance"] for row in right}
    common = [(row["distance"], lookup[(row["left"], row["right"])]) for row in left if (row["left"], row["right"]) in lookup]
    return round(_pearson([a for a, _ in common], [b for _, b in common]), 6) if len(common) >= 2 else 0.0


def _structure_predictions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    actual = [1.0 if row["success"] else 0.0 for row in rows]
    predictions = []
    for row in rows:
        budget = float(row["context_budget"]) / 100.0
        token_score = 1.0 / (1.0 + abs(float(row["context_tokens"]) - 4000.0) / 4000.0)
        file_score = 1.0 / (1.0 + abs(len(row.get("selected_files") or []) - 8.0) / 8.0)
        predictions.append(max(0.0, min(1.0, 0.2 + 0.35 * budget + 0.25 * token_score + 0.2 * file_score)))
    return {**_stats(actual, predictions), "predictions": predictions}


def _experience_predictions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    actual, predictions = [], []
    global_rate = _rate(rows)
    for row in rows:
        previous = [
            item
            for item in rows
            if item is not row and (item["model"] == row["model"] or item["task_type"] == row["task_type"] or item["repository"] == row["repository"])
        ]
        actual.append(1.0 if row["success"] else 0.0)
        predictions.append(_rate(previous) if previous else global_rate)
    return {**_stats(actual, predictions), "predictions": predictions}


def _generalization_split(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    actual, predicted = [], []
    for value in sorted({row[field] for row in rows}):
        train = [row for row in rows if row[field] != value]
        test = [row for row in rows if row[field] == value]
        prior = _rate(train)
        for row in test:
            peers = [item for item in train if item["task_type"] == row["task_type"] or item["context_budget"] == row["context_budget"]]
            actual.append(1.0 if row["success"] else 0.0)
            predicted.append(_rate(peers) if peers else prior)
    return _stats(actual, predicted)


def _stats(actual: list[float], predicted: list[float]) -> dict[str, float]:
    return {
        "correlation": round(max(0.0, _pearson(actual, predicted)), 6),
        "r2": round(max(0.0, _r2(actual, predicted)), 6),
        "mae": round(_avg(abs(a - b) for a, b in zip(actual, predicted)), 6),
    }


def _score(*values: float) -> float:
    return round(max(0.0, min(1.0, _avg(max(0.0, min(1.0, float(value))) for value in values))), 6)


def _coverage_score(cells: list[dict[str, Any]], expected: int) -> float:
    return min(1.0, len(cells) / max(1, expected))


def _leakage_resistance(rows: list[dict[str, Any]]) -> float:
    keys = [row["dedupe_key"] for row in rows]
    duplicate_penalty = 1.0 - (len(set(keys)) / max(1, len(keys)))
    return round(max(0.0, 1.0 - duplicate_penalty), 6)


def _falsification_resistance(score: float, stability: float) -> float:
    return round(max(0.0, min(1.0, (float(score) + max(0.0, float(stability))) / 2.0)), 6)


def _verdict(score: float, survives: str, collapses: str) -> str:
    if score >= 0.66:
        return survives
    if score >= 0.4:
        return f"mixed: {survives}, but evidence is not decisive"
    return collapses


def _tier(score: float) -> str:
    if score >= 80:
        return "Tier S"
    if score >= 65:
        return "Tier A"
    if score >= 45:
        return "Tier B"
    return "Tier C"


def _rate(rows: list[dict[str, Any]]) -> float:
    return sum(1 for row in rows if row.get("success")) / len(rows) if rows else 0.0


def _avg(values: Iterable[float]) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    ml = sum(left) / len(left)
    mr = sum(right) / len(right)
    dl = math.sqrt(sum((value - ml) ** 2 for value in left))
    dr = math.sqrt(sum((value - mr) ** 2 for value in right))
    if not dl or not dr:
        return 0.0
    return sum((a - ml) * (b - mr) for a, b in zip(left, right)) / (dl * dr)


def _r2(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    mean = sum(actual) / len(actual)
    total = sum((value - mean) ** 2 for value in actual)
    residual = sum((a - b) ** 2 for a, b in zip(actual, predicted))
    return 1.0 - residual / total if total else 0.0


def _dedupe_key(model: str, repo: str, task_type: str, budget: int, repetition: int) -> str:
    return f"{model}|{repo}|{task_type}|{budget}|{repetition}"


def _existing_keys(path: Path) -> set[str]:
    return {str(row.get("dedupe_key")) for row in _load_jsonl(path) if row.get("dedupe_key")}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _audit_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Balanced Live Matrix Audit",
        "",
        f"- Usable rows: {payload['usable_rows']}",
        f"- Excluded rows: {payload['excluded_rows']}",
        f"- Expected minimum rows: {payload['expected_minimum_rows']}",
        f"- Expected target rows: {payload['expected_target_rows']}",
        f"- Complete minimum matrix: {payload['complete_minimum_matrix']}",
        "",
        "## Exclusions By Reason",
        *[f"- {key}: {value}" for key, value in sorted(payload["exclusions_by_reason"].items())],
        "",
        "## Usable Rows By Model",
        *[f"- {key}: {value}" for key, value in sorted(payload["usable_rows_by_model"].items())],
        "",
        "## Usable Rows By Repository",
        *[f"- {key}: {value}" for key, value in sorted(payload["usable_rows_by_repository"].items())],
        "",
        "## Usable Rows By Task Type",
        *[f"- {key}: {value}" for key, value in sorted(payload["usable_rows_by_task_type"].items())],
        "",
    ]
    if payload["missing_minimum_cells"]:
        lines.extend(["## Missing Minimum Cells", *[f"- {row['model']} / {row['repository']} / {row['task_type']} / {row['context_budget']}%: {row['usable_repetitions']} usable" for row in payload["missing_minimum_cells"][:80]], ""])
    return "\n".join(lines)


def _theory_markdown(title: str, payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {title} Balanced Revalidation",
            "",
            f"- Score: {round(payload['score'] * 100.0, 2)}/100",
            f"- Predictive power: {payload['predictive_power']}",
            f"- Stability: {payload['stability']}",
            f"- Generalization: {payload['generalization']}",
            f"- Leakage resistance: {payload['leakage_resistance']}",
            f"- Falsification resistance: {payload['falsification_resistance']}",
            f"- Result: {payload['summary']}",
            "",
            "This report uses only strict clean rows from `balanced_live_matrix.jsonl`.",
            "",
        ]
    )


def _generalization_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Balanced Generalization", "", f"- Mean generalization correlation: {payload['mean_generalization']}", "", "| split | correlation | R2 | MAE |", "| --- | --- | --- | --- |"]
    for name, row in payload["results"].items():
        lines.append(f"| {name} | {row['correlation']} | {row['r2']} | {row['mae']} |")
    lines.append("")
    return "\n".join(lines)


def _rankings_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Balanced Theory Rankings",
        "",
        "| rank | theory | tier | score | predictive power | stability | generalization | leakage resistance | falsification resistance |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(f"| {index} | {row['theory']} | {row['tier']} | {row['score']} | {row['predictive_power']} | {row['stability']} | {row['generalization']} | {row['leakage_resistance']} | {row['falsification_resistance']} |")
    lines.append("")
    return "\n".join(lines)


def _summary_markdown(
    rows: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    rankings: list[dict[str, Any]],
    capability: dict[str, Any],
    model_task: dict[str, Any],
    mtc: dict[str, Any],
    sve: dict[str, Any],
    general: dict[str, Any],
) -> str:
    expected_minimum = len(MODELS) * len(REPOSITORIES) * len(TASK_TYPES) * len(CONTEXT_BUDGETS) * 3
    complete = len(rows) >= expected_minimum
    best = rankings[0] if rankings else {"theory": "none", "tier": "Tier C", "score": 0.0}
    weakest = rankings[-1] if rankings else best
    improved = max((row for row in rankings), key=lambda row: row["falsification_resistance"], default=best)
    breakthrough = max((row for row in rankings), key=lambda row: (row["generalization"], row["predictive_power"]), default=best)
    strongest = _strongest_result(rankings, rows, excluded, general)
    survival = f"{best['theory']} survives best under the clean balanced matrix." if complete else "No theory survives yet; the clean live matrix is incomplete."
    collapse = f"{weakest['theory']} is weakest in this clean run." if complete else "No theory can be fairly declared collapsed yet; missing cells dominate the evidence."
    improves = f"{improved['theory']} improves most by falsification resistance in the clean-only ranking." if complete else "No clean-data improvement claim is valid yet; the current rows are only a pipeline smoke sample."
    breakthrough_text = f"{breakthrough['theory']}, because it has the strongest generalization/predictive combination." if complete else "Undetermined until the minimum 675 clean live rows exist."
    next_month = f"{best['theory']}." if complete else "Finish the balanced live matrix before spending a month on any theory."
    return "\n".join(
        [
            "# Balanced Live Research Summary",
            "",
            f"- Usable clean live rows: {len(rows)}",
            f"- Excluded rows: {len(excluded)}",
            f"- Minimum clean rows required: {expected_minimum}",
            f"- Minimum matrix complete: {complete}",
            f"- Best-ranked theory: {best['theory']} ({best['tier']}, score {best['score']})",
            "",
            "## Answers",
            f"1. Which theory survives? {survival}",
            f"2. Which theory collapses? {collapse}",
            f"3. Which theory improves with clean data? {improves}",
            f"4. Which theory has the highest breakthrough potential? {breakthrough_text}",
            f"5. Which theory should receive the next month of research? {next_month}",
            f"6. What is the strongest result in the entire research program? {strongest}",
            "",
            "## Theory Scores",
            *[f"- {row['theory']}: {row['tier']} score={row['score']} predictive={row['predictive_power']} stability={row['stability']} generalization={row['generalization']}" for row in rankings],
            "",
        ]
    )


def _strongest_result(rankings: list[dict[str, Any]], rows: list[dict[str, Any]], excluded: list[dict[str, Any]], general: dict[str, Any]) -> str:
    if not rows:
        return "No theory result is meaningful until clean live rows exist."
    if len(rows) < len(MODELS) * len(REPOSITORIES) * len(TASK_TYPES) * len(CONTEXT_BUDGETS) * 3:
        return "The strongest result is methodological: strict cleaning prevents overclaiming from an incomplete live matrix."
    best = rankings[0]
    return f"{best['theory']} ranks first on {len(rows)} clean live balanced rows with mean generalization {general['mean_generalization']}."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the balanced live research matrix experiment.")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--target-repetitions", type=int, default=5)
    parser.add_argument("--max-runs", type=int, default=0, help="Stop after this many new live cells; 0 means full requested matrix.")
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        state_dir = load_config(auto_detect=False).state_dir
    result = run_balanced_live_matrix_experiment(
        state_dir,
        repetitions=args.repetitions,
        target_repetitions=args.target_repetitions,
        max_runs=args.max_runs,
        collect=not args.analyze_only,
        analyze=not args.collect_only,
        timeout_seconds=args.timeout_seconds or None,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "analyze_balanced_live_matrix",
    "collect_balanced_live_rows",
    "load_clean_balanced_rows",
    "matrix_path",
    "run_balanced_live_matrix_experiment",
]
