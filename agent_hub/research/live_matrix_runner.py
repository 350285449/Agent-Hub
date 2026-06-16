from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AgentConfig, load_config
from ..models import HubRequest
from ..providers.codex_cli import CodexCliProvider
from ..providers.errors import ProviderError
from ..providers.openai_compatible import OpenAICompatibleProvider
from ..token_budget import estimate_messages_tokens
from .task_generator import (
    RELEVANT_SUFFIXES,
    REPOSITORIES,
    TASK_CATEGORIES,
    benchmark_tasks_path,
    default_repo_roots,
    load_benchmark_tasks,
    write_benchmark_tasks,
)
from .telemetry import research_dir


ALLOWED_MODELS = {
    "gemma4:31b-cloud": "ollama-gemma-cloud",
    "nemotron-3-super:cloud": "ollama-nemotron-cloud",
    "gpt-5.5": "codex-cli",
}
CONTEXT_BUDGETS = (0, 25, 50, 75, 100)
MIN_REPETITIONS = 3
TARGET_REPETITIONS = 5
FULL_CONTEXT_TOKENS = 12_000
FORBIDDEN_PROVIDER_TYPES = {"local-research", "echo", "ollama"}
CODEX_MODEL = "gpt-5.5"
CODEX_AGENT_NAME = "codex-cli"
CODEX_DEFAULT_TIMEOUT_SECONDS = 180.0


def live_matrix_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "live_matrix.jsonl"


def codex_preflight_status_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "codex_preflight_status.json"


def codex_preflight_report_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "codex_preflight_report.md"


def expected_minimum_rows(*, tasks_per_category: int = 10, repetitions: int = MIN_REPETITIONS) -> int:
    return len(ALLOWED_MODELS) * len(REPOSITORIES) * len(TASK_CATEGORIES) * tasks_per_category * len(CONTEXT_BUDGETS) * repetitions


def collect_live_matrix(
    state_dir: str | Path,
    *,
    repo_roots: dict[str, Path] | None = None,
    repetitions: int = MIN_REPETITIONS,
    max_runs: int = 0,
    timeout_seconds: float | None = None,
    tasks_path: str | Path | None = None,
    include_disabled_codex: bool = False,
    fill_missing_first: bool = False,
    repo_filter: str | None = None,
    category_filter: str | None = None,
    model_filter: str | None = None,
    max_new_rows: int | None = None,
    progress: bool = False,
    require_live_provider: bool = False,
) -> Path:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    tasks_file = Path(tasks_path) if tasks_path else benchmark_tasks_path(state_dir)
    if not tasks_file.exists():
        write_benchmark_tasks(state_dir, repo_roots or default_repo_roots())
    tasks = load_benchmark_tasks(tasks_file)
    tasks = _filter_tasks(tasks, repo_filter=repo_filter, category_filter=category_filter)
    models = _filter_models(model_filter)
    roots = repo_roots or default_repo_roots()
    config = load_config(auto_detect=False)
    if CODEX_MODEL in models:
        preflight = run_codex_preflight(
            state_dir,
            config.agents,
            timeout_seconds=timeout_seconds,
            include_disabled_codex=include_disabled_codex,
        )
        if not preflight["usable_for_matrix"]:
            if require_live_provider:
                raise RuntimeError(f"gpt-5.5 unavailable for live matrix collection: {preflight['reason']}")
            models = [model for model in models if model != CODEX_MODEL]
    agents = _allowed_agents(
        config.agents,
        timeout_seconds=timeout_seconds,
        include_disabled_codex=include_disabled_codex,
    )
    if require_live_provider:
        unavailable = [model for model in models if model not in agents]
        if unavailable:
            raise RuntimeError(f"selected live provider unavailable: {', '.join(unavailable)}")
    path = live_matrix_path(state_dir)
    seen = _existing_keys(path)
    executed = 0
    limit = _row_limit(max_runs=max_runs, max_new_rows=max_new_rows)
    context_indexes = {repo: _context_index(root) for repo, root in roots.items() if repo in {str(task["repository"]) for task in tasks}}
    attempts = _scheduled_attempts(
        state_dir,
        tasks,
        context_indexes,
        seen,
        repetitions=max(MIN_REPETITIONS, int(repetitions)),
        models=models,
        fill_missing_first=fill_missing_first,
    )
    for attempt in attempts:
        model = attempt["model"]
        task = attempt["task"]
        budget = int(attempt["budget"])
        repetition = int(attempt["repetition"])
        key = _dedupe_key(model, str(task["task_id"]), budget, repetition)
        if key in seen:
            continue
        agent_name = ALLOWED_MODELS[model]
        agent = agents.get(model)
        if agent is None:
            if require_live_provider:
                raise RuntimeError(f"{model} unavailable for live matrix collection")
            if model == CODEX_MODEL:
                continue
            row = _skipped_row(model, agent_name, task, budget, repetition, "allowed agent not configured or not enabled")
        else:
            row = _run_live_row(agent, model, task, budget, repetition, attempt["selected"])
        _append_jsonl(path, row)
        seen.add(key)
        executed += 1
        if progress:
            _print_progress(executed, limit, row)
        if limit and executed >= limit:
            return path
    return path


def run_codex_preflight(
    state_dir: str | Path,
    agents: dict[str, AgentConfig],
    *,
    timeout_seconds: float | None,
    include_disabled_codex: bool,
) -> dict[str, Any]:
    status = _codex_preflight_status(
        agents,
        timeout_seconds=timeout_seconds,
        include_disabled_codex=include_disabled_codex,
        run_smoke=True,
    )
    _write_codex_preflight_files(state_dir, status)
    return status


def run_codex_only_smoke_test(
    state_dir: str | Path,
    *,
    timeout_seconds: float | None,
    include_disabled_codex: bool,
) -> dict[str, Any]:
    config = load_config(auto_detect=False)
    status = _codex_preflight_status(
        config.agents,
        timeout_seconds=timeout_seconds,
        include_disabled_codex=include_disabled_codex,
        run_smoke=True,
    )
    _write_codex_preflight_files(state_dir, status)
    return {
        "object": "agent_hub.research.codex_only_smoke_test",
        "model": CODEX_MODEL,
        "live": bool(status["live"]),
        "latency": status["latency"],
        "latency_ms": status["latency_ms"],
        "output_preview": status["output_preview"],
        "error_reason": status["reason"],
        "usable_for_matrix_collection": bool(status["usable_for_matrix"]),
        "preflight_status": str(codex_preflight_status_path(state_dir)),
        "preflight_report": str(codex_preflight_report_path(state_dir)),
    }


def _codex_preflight_status(
    agents: dict[str, AgentConfig],
    *,
    timeout_seconds: float | None,
    include_disabled_codex: bool,
    run_smoke: bool,
) -> dict[str, Any]:
    installed_path = shutil.which("codex")
    agent = agents.get(CODEX_AGENT_NAME)
    base: dict[str, Any] = {
        "object": "agent_hub.research.codex_preflight_status",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": CODEX_MODEL,
        "agent": CODEX_AGENT_NAME,
        "codex_cli_installed": bool(installed_path),
        "codex_cli_path": installed_path or "",
        "config_file_checked": str((Path.cwd() / "agent-hub.config.json").resolve()),
        "blocking_setting": "",
        "user_action_needed": "",
        "agent_configured": agent is not None,
        "agent_enabled": bool(agent.enabled) if agent is not None else False,
        "include_disabled_codex": bool(include_disabled_codex),
        "activated_disabled_agent": False,
        "live": False,
        "latency": 0.0,
        "latency_ms": 0.0,
        "output_preview": "",
        "error": "",
        "reason": "",
        "usable_for_matrix": False,
    }
    if not installed_path:
        base["reason"] = "codex_cli_not_installed"
        base["blocking_setting"] = "PATH"
        base["user_action_needed"] = "Install the Codex CLI and make sure `codex --version` works in this shell."
        return base
    if agent is None:
        base["reason"] = "codex_cli_agent_not_configured"
        base["blocking_setting"] = "agents[].name=codex-cli"
        base["user_action_needed"] = "Add a codex-cli agent entry to agent-hub.config.json."
        return base
    if not (agent.provider_type == "codex-cli" or agent.provider == "codex-cli"):
        base["reason"] = "codex_cli_agent_wrong_provider"
        base["blocking_setting"] = "agents[codex-cli].provider_type"
        base["user_action_needed"] = "Set the codex-cli agent provider/provider_type to `codex-cli`."
        return base
    if agent.model != CODEX_MODEL:
        base["reason"] = "codex_cli_agent_wrong_model"
        base["blocking_setting"] = "agents[codex-cli].model"
        base["user_action_needed"] = f"Set the codex-cli agent model to `{CODEX_MODEL}`."
        return base
    if not agent.enabled:
        if not include_disabled_codex:
            base["reason"] = "codex_cli_agent_disabled"
            base["blocking_setting"] = "agents[codex-cli].enabled"
            base["user_action_needed"] = "Set `enabled` to true for the codex-cli agent or pass --include-disabled-codex for an explicit one-off collection run."
            return base
        agent = replace(agent, enabled=True)
        base["activated_disabled_agent"] = True
    agent.timeout_seconds = _codex_timeout(timeout_seconds, agent.timeout_seconds)
    if not run_smoke:
        base["live"] = True
        base["reason"] = "available_not_smoked"
        base["usable_for_matrix"] = True
        return base
    request = HubRequest(
        messages=[
            {
                "role": "user",
                "content": "Return JSON only with keys summary, validation, risks. Say this is a Codex CLI live matrix smoke test.",
            }
        ],
        session_id=f"research-codex-smoke-{uuid.uuid4().hex}",
        task="codex_smoke_test",
        context="",
        max_tokens=120,
        temperature=0.0,
        raw={"agent_hub": {"context_budget_tokens": 0, "context_usage": {"context_tokens": 0, "selected_files": []}}},
        metadata={"context_files": []},
    )
    started = time.perf_counter()
    try:
        result = CodexCliProvider(agent).complete(request)
        text = result.text or ""
        base["output_preview"] = text[:800]
        base["live"] = bool(text.strip())
        base["reason"] = "usable" if text.strip() else "empty_output"
        base["usable_for_matrix"] = bool(text.strip())
        if not text.strip():
            base["blocking_setting"] = "codex_cli_response"
            base["user_action_needed"] = "Run `codex exec` directly and confirm the signed-in CLI can return text."
    except ProviderError as exc:
        base["error"] = str(exc)
        base["reason"] = _provider_error_reason(exc)
        base["blocking_setting"] = "codex_cli_runtime"
        base["user_action_needed"] = "Run `codex login` or inspect Codex CLI availability if the runtime error persists."
    except Exception as exc:
        base["error"] = str(exc)
        base["reason"] = f"{type(exc).__name__}"
        base["blocking_setting"] = "codex_cli_runtime"
        base["user_action_needed"] = "Run `codex exec` directly and resolve the reported runtime error."
    elapsed = time.perf_counter() - started
    base["latency"] = round(elapsed, 6)
    base["latency_ms"] = round(elapsed * 1000.0, 3)
    return base


def _write_codex_preflight_files(state_dir: str | Path, status: dict[str, Any]) -> None:
    json_path = codex_preflight_status_path(state_dir)
    md_path = codex_preflight_report_path(state_dir)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_codex_preflight_markdown(status), encoding="utf-8")


def _codex_preflight_markdown(status: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Codex Preflight Report",
            "",
            f"- Model: {status['model']}",
            f"- Agent: {status['agent']}",
            f"- Codex CLI installed: {status['codex_cli_installed']}",
            f"- Codex CLI path: `{status['codex_cli_path']}`",
            f"- Config file checked: `{status.get('config_file_checked', '')}`",
            f"- Agent configured: {status['agent_configured']}",
            f"- Agent enabled: {status['agent_enabled']}",
            f"- Include disabled Codex: {status['include_disabled_codex']}",
            f"- Activated disabled agent for run: {status['activated_disabled_agent']}",
            f"- Live response: {status['live']}",
            f"- Latency ms: {status['latency_ms']}",
            f"- Reason: {status['reason']}",
            f"- Blocking setting: {status.get('blocking_setting') or 'none'}",
            f"- User action needed: {status.get('user_action_needed') or 'none'}",
            f"- Usable for matrix collection: {status['usable_for_matrix']}",
            "",
            "## Output Preview",
            "",
            "```text",
            str(status.get("output_preview") or "")[:800],
            "```",
            "",
            "## Error",
            "",
            "```text",
            str(status.get("error") or "")[:800],
            "```",
            "",
        ]
    )


def summarize_live_matrix(state_dir: str | Path, *, tasks_per_category: int = 10) -> dict[str, Any]:
    path = live_matrix_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    rows = _load_jsonl(path)
    usable = [row for row in rows if _is_usable_live_row(row)]
    return {
        "live_matrix": str(path),
        "total_rows": len(rows),
        "usable_live_rows": len(usable),
        "excluded_rows": len(rows) - len(usable),
        "expected_minimum_usable_rows": expected_minimum_rows(tasks_per_category=tasks_per_category, repetitions=MIN_REPETITIONS),
        "target_usable_rows": expected_minimum_rows(tasks_per_category=tasks_per_category, repetitions=TARGET_REPETITIONS),
        "allowed_models": list(ALLOWED_MODELS),
        "context_budgets": list(CONTEXT_BUDGETS),
        "minimum_complete": len(usable) >= expected_minimum_rows(tasks_per_category=tasks_per_category, repetitions=MIN_REPETITIONS),
        "target_complete": len(usable) >= expected_minimum_rows(tasks_per_category=tasks_per_category, repetitions=TARGET_REPETITIONS),
    }


def _allowed_agents(
    agents: dict[str, AgentConfig],
    *,
    timeout_seconds: float | None,
    include_disabled_codex: bool = False,
) -> dict[str, AgentConfig]:
    selected: dict[str, AgentConfig] = {}
    for public_model, agent_name in ALLOWED_MODELS.items():
        agent = agents.get(agent_name)
        if agent is None:
            continue
        if not agent.enabled:
            if not (
                include_disabled_codex
                and agent_name == "codex-cli"
                and (agent.provider_type == "codex-cli" or agent.provider == "codex-cli")
                and shutil.which("codex")
            ):
                continue
            agent.enabled = True
        if not agent.enabled:
            continue
        provider_type = str(agent.provider_type or agent.provider or "").lower()
        if provider_type in FORBIDDEN_PROVIDER_TYPES:
            continue
        if agent.model != public_model:
            continue
        if public_model == CODEX_MODEL:
            agent.timeout_seconds = _codex_timeout(timeout_seconds, agent.timeout_seconds)
        elif timeout_seconds is not None:
            agent.timeout_seconds = timeout_seconds
        selected[public_model] = agent
    return selected


def _run_live_row(
    agent: AgentConfig,
    model: str,
    task: dict[str, Any],
    budget: int,
    repetition: int,
    selected: list[dict[str, Any]],
) -> dict[str, Any]:
    context = _render_context(selected)
    prompt = _prompt(task, budget, repetition)
    request = HubRequest(
        messages=[{"role": "user", "content": prompt}],
        session_id=f"research-live-{uuid.uuid4().hex}",
        task=str(task["category"]),
        context=context,
        max_tokens=500,
        temperature=0.1,
        raw={
            "agent_hub": {
                "context_budget_tokens": sum(int(item["tokens"]) for item in selected),
                "context_usage": {
                    "context_tokens": sum(int(item["tokens"]) for item in selected),
                    "selected_files": [item["path"] for item in selected],
                },
            }
        },
        metadata={"context_files": [item["path"] for item in selected]},
    )
    started = time.perf_counter()
    text = ""
    error = ""
    retries = 0
    try:
        provider = CodexCliProvider(agent) if (agent.provider_type == "codex-cli" or agent.provider == "codex-cli") else OpenAICompatibleProvider(agent)
        result = provider.complete(request)
        text = result.text or ""
    except ProviderError as exc:
        reason = _provider_error_reason(exc)
        error = f"{reason}: {exc}"
        retries = 1 if exc.retryable else 0
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    latency = round(elapsed, 6)
    latency_ms = round(elapsed * 1000.0, 3)
    validation_score = _validate_response(text, task)
    return {
        "object": "agent_hub.research.live_matrix_row",
        "row_id": uuid.uuid4().hex,
        "dedupe_key": _dedupe_key(model, str(task["task_id"]), budget, repetition),
        "live": True,
        "model": model,
        "repository": task["repository"],
        "task": task["task_id"],
        "task_id": task["task_id"],
        "category": task["category"],
        "context_budget": budget,
        "context budget": budget,
        "context_tokens": sum(int(item["tokens"]) for item in selected),
        "success": bool(text and validation_score >= 0.5 and not error),
        "validation_score": validation_score,
        "latency": latency,
        "latency_ms": latency_ms,
        "retries": retries,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": agent.provider,
        "provider_type": agent.provider_type or agent.provider,
        "selected_files": [item["path"] for item in selected],
        "output_preview": text[:800],
    }


def _skipped_row(model: str, agent_name: str, task: dict[str, Any], budget: int, repetition: int, error: str) -> dict[str, Any]:
    return {
        "object": "agent_hub.research.live_matrix_row",
        "row_id": uuid.uuid4().hex,
        "dedupe_key": _dedupe_key(model, str(task["task_id"]), budget, repetition),
        "live": False,
        "model": model,
        "repository": task["repository"],
        "task": task["task_id"],
        "task_id": task["task_id"],
        "category": task["category"],
        "context_budget": budget,
        "context budget": budget,
        "context_tokens": 0,
        "success": False,
        "validation_score": 0.0,
        "latency": 0.0,
        "latency_ms": 0.0,
        "retries": 0,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": agent_name,
        "provider_type": "configuration",
        "selected_files": [],
        "output_preview": "",
    }


def _provider_error_reason(exc: ProviderError) -> str:
    text = f"{exc.error_type}: {exc}".lower()
    if exc.error_type == "timeout" or "timed out" in text or "timeout" in text:
        return "timeout_no_useful_output"
    return str(exc.error_type or "provider_failure")


def _codex_timeout(timeout_seconds: float | None, configured_timeout: float | None) -> float:
    if timeout_seconds is not None:
        return float(timeout_seconds)
    if configured_timeout:
        return max(float(configured_timeout), CODEX_DEFAULT_TIMEOUT_SECONDS)
    return CODEX_DEFAULT_TIMEOUT_SECONDS


def _context_index(root: Path | None) -> list[dict[str, Any]]:
    if root is None or not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in RELEVANT_SUFFIXES:
            continue
        parts = {part.lower() for part in path.parts}
        if parts & {".git", "__pycache__", ".pytest_cache", "node_modules", "dist", "build"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            relative = path.relative_to(root).as_posix()
        except OSError:
            continue
        tokens = max(1, len(text) // 4)
        rows.append({"path": relative, "text": text[:8000], "tokens": tokens})
    return sorted(rows, key=lambda item: item["path"])[:600]


def _select_context(index: list[dict[str, Any]], budget: int, task: dict[str, Any]) -> list[dict[str, Any]]:
    if budget <= 0 or not index:
        return []
    token_budget = max(1, int(FULL_CONTEXT_TOKENS * (budget / 100.0)))
    focus = {str(path).lower() for path in task.get("focus_files", [])}
    words = {word.lower().strip(".,:/_-") for word in str(task.get("description", "")).split() if len(word) >= 5}
    ranked = sorted(index, key=lambda item: (-_context_score(item, focus, words), item["tokens"], item["path"]))
    selected: list[dict[str, Any]] = []
    used = 0
    for item in ranked:
        if used + int(item["tokens"]) > token_budget and selected:
            continue
        selected.append(item)
        used += int(item["tokens"])
        if used >= token_budget:
            break
    return selected


def _context_score(item: dict[str, Any], focus: set[str], words: set[str]) -> int:
    path = str(item["path"]).lower()
    text = str(item["text"]).lower()
    score = 0
    if path in focus:
        score += 100
    score += sum(3 for word in words if word and word in path)
    score += sum(1 for word in list(words)[:20] if word and word in text)
    return score


def _render_context(selected: list[dict[str, Any]]) -> str:
    lines = []
    for item in selected:
        lines.append(f"File: {item['path']}")
        lines.append(str(item["text"])[:6000])
    return "\n\n".join(lines)


def _prompt(task: dict[str, Any], budget: int, repetition: int) -> str:
    return "\n".join(
        [
            "You are participating in the Agent-Hub controlled research benchmark.",
            "Return JSON only. Use keys: summary, evidence, proposal, validation, risks.",
            "Do not claim tests were run unless the prompt includes their output.",
            f"Repository: {task['repository']}",
            f"Category: {task['category']}",
            f"Expected output type: {task['expected_output_type']}",
            f"Context budget: {budget}%",
            f"Repetition: {repetition}",
            f"Task: {task['description']}",
        ]
    )


def _validate_response(text: str, task: dict[str, Any]) -> float:
    if not text.strip():
        return 0.0
    lowered = text.lower()
    required = ("validation", "risk", str(task["category"]).split("_")[0])
    score = 0.25
    score += 0.15 * sum(1 for word in required if word in lowered)
    if "{" in text and "}" in text:
        score += 0.2
    if str(task["repository"]).lower() in lowered:
        score += 0.1
    if len(text) >= 300:
        score += 0.1
    return round(max(0.0, min(1.0, score)), 6)


def _dedupe_key(model: str, task_id: str, budget: int, repetition: int) -> str:
    return f"{model}|{task_id}|{budget}|{repetition}"


def _filter_tasks(
    tasks: list[dict[str, Any]],
    *,
    repo_filter: str | None,
    category_filter: str | None,
) -> list[dict[str, Any]]:
    rows = tasks
    if repo_filter:
        rows = [task for task in rows if str(task.get("repository")) == repo_filter]
    if category_filter:
        rows = [task for task in rows if str(task.get("category")) == category_filter]
    return rows


def _filter_models(model_filter: str | None) -> list[str]:
    if not model_filter:
        return list(ALLOWED_MODELS)
    if model_filter not in ALLOWED_MODELS:
        raise ValueError(f"model must be one of {', '.join(ALLOWED_MODELS)}: {model_filter}")
    return [model_filter]


def _row_limit(*, max_runs: int, max_new_rows: int | None) -> int:
    if max_new_rows is not None:
        return max(0, int(max_new_rows))
    return max(0, int(max_runs))


def _scheduled_attempts(
    state_dir: str | Path,
    tasks: list[dict[str, Any]],
    context_indexes: dict[str, list[dict[str, Any]]],
    seen: set[str],
    *,
    repetitions: int,
    models: list[str],
    fill_missing_first: bool,
) -> list[dict[str, Any]]:
    counts = _usable_cell_counts(state_dir)
    report_missing, report_zero = _reported_missing_cells(state_dir)
    attempts_by_cell: dict[tuple[str, str, str, int], list[dict[str, Any]]] = {}
    cell_priority: dict[tuple[str, str, str, int], tuple[int, int, int, int]] = {}
    order = 0
    for task in tasks:
        repository = str(task["repository"])
        category = str(task["category"])
        for budget in CONTEXT_BUDGETS:
            selected = _select_context(context_indexes.get(repository, []), budget, task)
            for repetition in range(1, repetitions + 1):
                for model in models:
                    key = _dedupe_key(model, str(task["task_id"]), budget, repetition)
                    if key in seen:
                        continue
                    cell = (model, repository, category, int(budget))
                    usable = counts[cell]
                    if fill_missing_first:
                        if cell in report_zero or usable == 0:
                            priority = 0
                        elif cell in report_missing or usable < MIN_REPETITIONS:
                            priority = 1
                        else:
                            priority = 2
                    else:
                        priority = 2
                    collection_priority = _collection_priority(model, repository, category)
                    attempt = {
                        "priority": priority,
                        "usable": usable,
                        "collection_priority": collection_priority,
                        "order": order,
                        "model": model,
                        "task": task,
                        "budget": budget,
                        "repetition": repetition,
                        "selected": selected,
                    }
                    attempts_by_cell.setdefault(cell, []).append(attempt)
                    cell_priority.setdefault(cell, (priority, usable, collection_priority, order))
                    order += 1
    if not fill_missing_first:
        return [attempt for attempts in attempts_by_cell.values() for attempt in attempts]
    cells = sorted(attempts_by_cell, key=lambda cell: cell_priority[cell])
    ordered: list[dict[str, Any]] = []
    max_depth = max((len(attempts) for attempts in attempts_by_cell.values()), default=0)
    for depth in range(max_depth):
        for cell in cells:
            attempts = attempts_by_cell[cell]
            if depth < len(attempts):
                ordered.append(attempts[depth])
    return ordered


def _collection_priority(model: str, repository: str, category: str) -> int:
    repo_order = {"face": 0, "ytdl_site": 1, "Agent-Hub": 3}
    category_order = {
        "documentation": 0,
        "analysis": 1,
        "architecture": 2,
        "testing": 3,
        "refactor": 4,
        "code_generation": 5,
        "bug_fix": 6,
    }
    if model == CODEX_MODEL:
        return repo_order.get(repository, 2) * 10 + category_order.get(category, 9)
    return category_order.get(category, 9)


def _usable_cell_counts(state_dir: str | Path) -> Counter[tuple[str, str, str, int]]:
    try:
        from .data_quality_audit import load_audited_rows

        usable, _excluded = load_audited_rows(live_matrix_path(state_dir))
    except Exception:
        usable = [row for row in _load_jsonl(live_matrix_path(state_dir)) if _is_usable_live_row(row)]
    return Counter(
        (
            str(row.get("model")),
            str(row.get("repository")),
            str(row.get("category")),
            int(row.get("context_budget", row.get("context budget", 0)) or 0),
        )
        for row in usable
    )


def _reported_missing_cells(state_dir: str | Path) -> tuple[set[tuple[str, str, str, int]], set[tuple[str, str, str, int]]]:
    path = research_dir(state_dir) / "data_quality_report.json"
    missing: set[tuple[str, str, str, int]] = set()
    zero: set[tuple[str, str, str, int]] = set()
    if not path.exists():
        return missing, zero
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return missing, zero
    for row in payload.get("missing_minimum_cells", []):
        try:
            cell = (str(row["model"]), str(row["repository"]), str(row["category"]), int(row["context_budget"]))
        except (KeyError, TypeError, ValueError):
            continue
        missing.add(cell)
        if int(row.get("usable_repetitions", 0) or 0) == 0:
            zero.add(cell)
    return missing, zero


def _print_progress(completed: int, limit: int, row: dict[str, Any]) -> None:
    reason = _row_exclusion_reason(row)
    status = "usable" if reason == "usable" else "excluded"
    print(
        f"[{completed}/{limit or 'all'}] "
        f"model={row.get('model')} repository={row.get('repository')} "
        f"category={row.get('category')} context_budget={row.get('context_budget')} "
        f"status={status} reason={reason}",
        file=sys.stderr,
        flush=True,
    )


def _row_exclusion_reason(row: dict[str, Any]) -> str:
    try:
        from .data_quality_audit import exclusion_reason

        reason = exclusion_reason(row, set())
        return reason or "usable"
    except Exception:
        return "usable" if _is_usable_live_row(row) else "excluded"


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
            rows.append({"corrupted": True, "raw_line": line})
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _is_usable_live_row(row: dict[str, Any]) -> bool:
    if row.get("model") not in ALLOWED_MODELS:
        return False
    if row.get("live") is not True:
        return False
    if row.get("error"):
        return False
    if not row.get("output_preview"):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect the controlled live Agent-Hub research matrix.")
    parser.add_argument("--state-dir", default=".agent-hub/state")
    parser.add_argument("--repetitions", type=int, default=MIN_REPETITIONS)
    parser.add_argument("--max-runs", type=int, default=0)
    parser.add_argument("--max-new-rows", type=int, default=25)
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    parser.add_argument("--fill-missing-first", action="store_true")
    parser.add_argument("--repo", choices=list(REPOSITORIES), default="")
    parser.add_argument("--category", choices=list(TASK_CATEGORIES), default="")
    parser.add_argument("--model", choices=list(ALLOWED_MODELS), default="")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--include-disabled-codex", action="store_true")
    parser.add_argument("--require-live-provider", action="store_true")
    parser.add_argument("--codex-only-smoke-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    timeout_seconds = args.timeout_seconds or None
    if args.codex_only_smoke_test:
        if args.model and args.model != CODEX_MODEL:
            raise SystemExit("--codex-only-smoke-test requires --model gpt-5.5 or no --model")
        result = run_codex_only_smoke_test(
            args.state_dir,
            timeout_seconds=timeout_seconds,
            include_disabled_codex=args.include_disabled_codex,
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            for key, value in result.items():
                print(f"{key}: {value}")
        if args.require_live_provider and not result["usable_for_matrix_collection"]:
            return 2
        return 0
    if not args.summarize_only:
        try:
            collect_live_matrix(
                args.state_dir,
                repetitions=args.repetitions,
                max_runs=args.max_runs,
                max_new_rows=args.max_new_rows,
                timeout_seconds=timeout_seconds,
                include_disabled_codex=args.include_disabled_codex,
                fill_missing_first=args.fill_missing_first,
                repo_filter=args.repo or None,
                category_filter=args.category or None,
                model_filter=args.model or None,
                progress=True,
                require_live_provider=args.require_live_provider,
            )
        except RuntimeError as exc:
            if args.json:
                print(json.dumps({"error": str(exc), "live_matrix": str(live_matrix_path(args.state_dir))}, indent=2, sort_keys=True))
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 2
    summary = summarize_live_matrix(args.state_dir)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        for key, value in summary.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALLOWED_MODELS",
    "CONTEXT_BUDGETS",
    "MIN_REPETITIONS",
    "TARGET_REPETITIONS",
    "collect_live_matrix",
    "codex_preflight_report_path",
    "codex_preflight_status_path",
    "expected_minimum_rows",
    "live_matrix_path",
    "run_codex_only_smoke_test",
    "run_codex_preflight",
    "summarize_live_matrix",
]
