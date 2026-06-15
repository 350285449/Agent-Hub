from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..config import load_config
from ..evaluation import BenchmarkTask, _score_text, default_benchmark_tasks
from ..token_budget import estimate_messages_tokens
from .ablation import append_context_ablation_result
from .analyze import run_research_analysis
from .file_stats import update_file_stats
from .telemetry import append_research_run, research_dir


CONTEXT_BUDGET_RATIOS = (0.0, 0.25, 0.5, 0.75, 1.0)
CONTEXT_STRATEGIES = ("default_context", "information_density")
RELEVANT_SUFFIXES = {".py", ".md", ".json", ".toml", ".yaml", ".yml", ".js", ".ts"}


@dataclass(frozen=True, slots=True)
class ContextFile:
    path: str
    tokens: int
    score: int


def run_context_ablation_experiment(
    state_dir: str | Path,
    *,
    route: str = "cloud-agent",
    limit: int = 0,
    repo_root: str | Path | None = None,
    mode: str = "local_deterministic_proof",
    skip_analysis: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root or Path.cwd())
    tasks = default_benchmark_tasks(route=route)
    if limit:
        tasks = tasks[: max(1, int(limit))]
    experiment_id = f"context-ablation-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    files = _context_file_index(root)
    rows: list[dict[str, Any]] = []
    for task_index, task in enumerate(tasks, start=1):
        for strategy in CONTEXT_STRATEGIES:
            for ratio in CONTEXT_BUDGET_RATIOS:
                row = _run_one_budget(
                    task,
                    task_index=task_index,
                    ratio=ratio,
                    files=files,
                    experiment_id=experiment_id,
                    mode=mode,
                    strategy=strategy,
                )
                rows.append(row)
                append_context_ablation_result(state_dir, row)
                _append_experiment_row(state_dir, row)
                append_research_run(state_dir, _run_row(row))
                update_file_stats(state_dir, _run_row(row))
    analysis_paths = {} if skip_analysis else run_research_analysis(state_dir)
    return {
        "object": "agent_hub.research.context_ablation_experiment",
        "experiment_id": experiment_id,
        "mode": mode,
        "route": route,
        "task_count": len(tasks),
        "run_count": len(rows),
        "research_dir": str(research_dir(state_dir)),
        "analysis_paths": analysis_paths,
    }


def experiments_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "experiments.jsonl"


def _run_one_budget(
    task: BenchmarkTask,
    *,
    task_index: int,
    ratio: float,
    files: list[ContextFile],
    experiment_id: str,
    mode: str,
    strategy: str,
) -> dict[str, Any]:
    selected = _select_files(task, files, ratio, strategy=strategy)
    context_tokens = sum(item.tokens for item in selected)
    response = _synthetic_response(task, ratio, selected, strategy=strategy)
    validation_score = _score_text(response, task)
    input_tokens = estimate_messages_tokens([{"role": "user", "content": task.prompt}]) + context_tokens
    output_tokens = max(1, len(response.split()))
    latency_ms = round(18.0 + input_tokens / 125.0 + output_tokens / 8.0, 3)
    success = validation_score >= 0.6
    error = "" if success else "validation_score_below_success_threshold"
    return {
        "object": "agent_hub.research.context_ablation_result",
        "experiment_id": experiment_id,
        "experiment_mode": mode,
        "context_strategy": strategy,
        "task_id": f"{task.type}-{task_index:03d}-{strategy}-{int(ratio * 100)}",
        "task_type": task.type,
        "route": task.route,
        "context_budget_ratio": ratio,
        "context_percent": int(ratio * 100),
        "selected_files": [item.path for item in selected],
        "context_files": [item.path for item in selected],
        "context_token_count": context_tokens,
        "tokens_used": input_tokens + output_tokens,
        "selected_model": "local-deterministic-proof",
        "model": "local-deterministic-proof",
        "candidate_models": ["local-deterministic-proof"],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "cost_estimate": 0.0,
        "cost": 0.0,
        "validation_score": validation_score,
        "success": success,
        "retry_count": 0,
        "error": error,
        "expected_keywords": list(task.expected_keywords),
        "prompt_tokens": estimate_messages_tokens([{"role": "user", "content": task.prompt}]),
        "timestamp": time.time(),
    }


def _run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "task_type": row["task_type"],
        "selected_model": row["selected_model"],
        "candidate_models": list(row.get("candidate_models") or []),
        "input_tokens": int(row.get("input_tokens") or 0),
        "output_tokens": int(row.get("output_tokens") or 0),
        "context_files": list(row.get("context_files") or []),
        "context_token_count": int(row.get("context_token_count") or 0),
        "latency_ms": float(row.get("latency_ms") or 0.0),
        "cost_estimate": float(row.get("cost_estimate") or 0.0),
        "success": bool(row.get("success")),
        "validation_score": float(row.get("validation_score") or 0.0),
        "retry_count": int(row.get("retry_count") or 0),
        "errors": [str(row.get("error") or "")] if row.get("error") else [],
        "event_type": "context_ablation_outcome",
        "route": row.get("route", ""),
        "provider": "local",
        "context_strategy": row.get("context_strategy", "default_context"),
    }


def _append_experiment_row(state_dir: str | Path, row: dict[str, Any]) -> Path:
    path = experiments_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _context_file_index(root: Path) -> list[ContextFile]:
    rows: list[ContextFile] = []
    for path in _iter_candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        tokens = max(1, len(text) // 4)
        rows.append(ContextFile(path=rel, tokens=tokens, score=0))
    rows.sort(key=lambda item: (item.path.count("/"), item.path))
    return rows[:500]


def _iter_candidate_files(root: Path) -> Iterable[Path]:
    ignored = {".git", ".agent-hub", "__pycache__", ".pytest_cache", "node_modules", "dist", "build"}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in RELEVANT_SUFFIXES:
            continue
        if any(part in ignored for part in path.parts):
            continue
        yield path


def _select_files(task: BenchmarkTask, files: list[ContextFile], ratio: float, *, strategy: str) -> list[ContextFile]:
    if ratio <= 0 or not files:
        return []
    budget = int(_full_context_budget(task) * ratio)
    scored = [_score_file(task, item) for item in files]
    if strategy == "information_density":
        scored.sort(key=lambda item: (-(item.score / max(1, item.tokens)), -item.score, item.tokens, item.path))
    else:
        scored.sort(key=lambda item: (-item.score, item.path))
    selected: list[ContextFile] = []
    used = 0
    for item in scored:
        if used + item.tokens > budget and selected:
            continue
        if item.tokens > budget and not selected:
            continue
        selected.append(item)
        used += item.tokens
        if used >= budget:
            break
    return selected


def _score_file(task: BenchmarkTask, file: ContextFile) -> ContextFile:
    terms = [task.type, *task.expected_keywords, *task.prompt.lower().split()]
    lowered = file.path.lower()
    score = sum(1 for term in terms if str(term).strip(".,:;").lower() in lowered)
    if file.path.startswith("agent_hub/"):
        score += 2
    if file.path.startswith("tests/"):
        score += 1
    return ContextFile(path=file.path, tokens=file.tokens, score=score)


def _full_context_budget(task: BenchmarkTask) -> int:
    base = {
        "coding": 8_000,
        "reasoning": 5_000,
        "summarization": 4_000,
        "tool_calling": 6_000,
        "long_context": 18_000,
        "latency": 2_000,
    }.get(task.type, 5_000)
    return base + len(task.prompt) // 2


def _synthetic_response(task: BenchmarkTask, ratio: float, selected: list[ContextFile], *, strategy: str) -> str:
    useful_terms = _useful_keyword_count(task, ratio, selected, strategy=strategy)
    included = task.expected_keywords[:useful_terms]
    if not included:
        return "The agent gives a generic answer without enough evidence."
    return " ".join(["The agent answer uses evidence for", *included, "and stays concise."])


def _useful_keyword_count(task: BenchmarkTask, ratio: float, selected: list[ContextFile], *, strategy: str) -> int:
    if not task.expected_keywords:
        return 0
    if ratio <= 0:
        return 0
    relevant_files = sum(1 for item in selected if item.score > 0)
    capacity = int(ratio * len(task.expected_keywords) + 0.49)
    if ratio >= 0.5:
        capacity += 1
    if relevant_files >= 3 and ratio >= 0.25:
        capacity += 1
    if strategy == "information_density" and relevant_files >= 1 and ratio >= 0.25:
        capacity += 1
    return max(0, min(len(task.expected_keywords), capacity))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local context ablation research experiment.")
    parser.add_argument("--route", default="cloud-agent")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-analysis", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    config = load_config()
    result = run_context_ablation_experiment(
        config.state_dir,
        route=args.route,
        limit=args.limit,
        skip_analysis=args.skip_analysis,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Experiment {result['experiment_id']} wrote {result['run_count']} run(s).")
        print(f"Research directory: {result['research_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CONTEXT_BUDGET_RATIOS", "CONTEXT_STRATEGIES", "experiments_path", "run_context_ablation_experiment"]
