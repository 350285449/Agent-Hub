from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from .telemetry import research_dir


BUDGETS = (0, 25, 50, 75, 100)
CURVES = ("linear", "logarithmic", "saturating_exponential", "michaelis_menten")
SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
TEXT_EXTENSIONS = {
    ".bat",
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yml",
    ".yaml",
}


@dataclass(frozen=True, slots=True)
class RepoSpec:
    name: str
    path: Path
    expected_keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    agent_name: str
    provider: str
    provider_type: str
    size_class: str
    runnable: bool
    model: str = ""
    base_url: str = ""
    timeout_seconds: float = 120.0
    reason: str = ""


def run_multi_model_context_scaling(
    state_dir: str | Path,
    *,
    repo_root: str | Path | None = None,
    timeout_seconds: int = 90,
    max_context_tokens: int = 12_000,
    model_scope: str = "all",
) -> dict[str, str]:
    root = Path(repo_root or Path.cwd()).resolve()
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    repos = _repo_specs(root)
    models = _filter_models(_model_specs(), model_scope)
    rows = []
    for model in models:
        if not model.runnable:
            continue
        for repo in repos:
            files = _ranked_files(repo.path)
            total_tokens = min(max_context_tokens, sum(item["tokens"] for item in files))
            for budget in BUDGETS:
                selected, context, tokens = _select_context(files, budget, total_tokens)
                rows.append(
                    _run_model_case(
                        model=model,
                        repo=repo,
                        budget=budget,
                        selected_files=selected,
                        context=context,
                        context_tokens=tokens,
                        timeout_seconds=timeout_seconds,
                    )
                )
    payload = _analysis_payload(rows, models, repos, timeout_seconds, max_context_tokens)
    paths = _write_outputs(directory, payload)
    return {key: str(value) for key, value in paths.items()}


def _filter_models(models: list[ModelSpec], model_scope: str) -> list[ModelSpec]:
    scope = str(model_scope or "all").strip().lower()
    if scope in {"cloud-ollama-codex", "ollama-cloud-codex", "cloud"}:
        return [
            model
            for model in models
            if model.provider == "codex" or model.provider_type == "ollama-cloud"
        ]
    if scope in {"ollama-cloud", "cloud-ollama"}:
        return [model for model in models if model.provider_type == "ollama-cloud"]
    if scope in {"codex", "codex-cli"}:
        return [model for model in models if model.provider == "codex"]
    return models


def _repo_specs(root: Path) -> list[RepoSpec]:
    downloads = root.parent
    return [
        RepoSpec("Agent-Hub", root, ("agent", "hub", "python", "research", "tests")),
        RepoSpec("ytdl_site", downloads / "ytdl_site", ("python", "flask", "youtube", "download", "html")),
        RepoSpec("face", downloads / "face", ("python", "face", "image", "opencv")),
    ]


def _model_specs() -> list[ModelSpec]:
    models: list[ModelSpec] = []
    try:
        from ..config import load_config

        config = load_config(auto_detect=False)
        for agent in config.agents.values():
            if not agent.enabled:
                continue
            if agent.provider == "openai-compatible" and str(agent.base_url or "").rstrip("/") == "http://127.0.0.1:11434":
                provider_type = "ollama-cloud" if str(agent.provider_type or "") == "ollama-cloud" or str(agent.model).endswith(":cloud") else "ollama-local"
                models.append(
                    ModelSpec(
                        name=str(agent.model),
                        agent_name=agent.name,
                        provider="ollama",
                        provider_type=provider_type,
                        size_class=_size_class(str(agent.model)),
                        runnable=True,
                        model=str(agent.model),
                        base_url=str(agent.base_url or "http://127.0.0.1:11434"),
                        timeout_seconds=float(agent.timeout_seconds or 120.0),
                    )
                )
    except Exception:
        models = []
    known = {model.name for model in models}
    for name in _ollama_models():
        if name in known:
            continue
        models.append(
            ModelSpec(
                name=name,
                agent_name=name,
                provider="ollama",
                provider_type="ollama-local",
                size_class=_size_class(name),
                runnable=True,
                model=name,
                base_url="http://127.0.0.1:11434",
            )
        )
    codex = shutil.which("codex")
    if codex:
        codex_model = _codex_model()
        models.append(
            ModelSpec(
                name=codex_model,
                agent_name="codex-cli",
                provider="codex",
                provider_type="codex-cli",
                size_class="codex",
                runnable=True,
                model=codex_model,
                timeout_seconds=300.0,
            )
        )
    return models


def _codex_model() -> str:
    try:
        from ..config import load_config

        config = load_config(auto_detect=False)
        agent = config.agents.get("codex-cli")
        if agent and agent.model:
            return str(agent.model)
    except Exception:
        pass
    return "codex-cli-default"


def _ollama_models() -> list[str]:
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return []
    rows = payload.get("models") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return sorted(str(row.get("name")) for row in rows if isinstance(row, dict) and row.get("name"))


def _ranked_files(repo: Path) -> list[dict[str, Any]]:
    files = []
    base = repo
    if repo.name == "ytdl_site" and (repo / "ytdl_site").exists():
        base = repo / "ytdl_site"
    for path in base.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not text.strip():
            continue
        rel = path.relative_to(base).as_posix()
        priority = _file_priority(rel)
        files.append({"path": rel, "text": text, "tokens": _token_count(text), "priority": priority})
    return sorted(files, key=lambda item: (item["priority"], item["path"]))


def _file_priority(path: str) -> int:
    lower = path.lower()
    if lower.endswith("readme.md") or lower in {"pyproject.toml", "package.json", "requirements.txt"}:
        return 0
    if "/tests/" in f"/{lower}" or lower.startswith("tests/"):
        return 1
    if lower.endswith((".py", ".ts", ".js")):
        return 2
    if lower.endswith((".md", ".html", ".json", ".yml", ".yaml")):
        return 3
    return 4


def _select_context(files: list[dict[str, Any]], budget: int, total_tokens: int) -> tuple[list[str], str, int]:
    if budget <= 0 or total_tokens <= 0:
        return [], "", 0
    target = max(1, int(total_tokens * budget / 100.0))
    selected = []
    chunks = []
    used = 0
    for item in files:
        if used >= target:
            break
        remaining = target - used
        text = str(item["text"])
        if item["tokens"] > remaining:
            text = text[: max(200, remaining * 4)]
        used += _token_count(text)
        selected.append(str(item["path"]))
        chunks.append(f"### {item['path']}\n{text}")
    return selected, "\n\n".join(chunks), used


def _run_model_case(
    *,
    model: ModelSpec,
    repo: RepoSpec,
    budget: int,
    selected_files: list[str],
    context: str,
    context_tokens: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    prompt = _prompt(repo.name, budget, context)
    started = time.perf_counter()
    output = ""
    error = ""
    timed_out = False
    try:
        if model.provider == "codex":
            output = _codex_generate(model.model, prompt, timeout_seconds)
        else:
            output = _ollama_chat(model, prompt, timeout_seconds)
    except TimeoutError as exc:
        error = str(exc)
        timed_out = True
    except Exception as exc:
        error = str(exc)
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    validation_score = _validation_score(output, repo.expected_keywords)
    return {
        "model": model.name,
        "agent": model.agent_name,
        "provider": model.provider,
        "provider_type": model.provider_type,
        "model_class": model.size_class,
        "repository": repo.name,
        "context_percent": budget,
        "context_tokens": context_tokens,
        "selected_files": selected_files,
        "success": bool(output) and not error and validation_score >= 0.5,
        "validation_score": validation_score,
        "error": error,
        "timeout": timed_out,
        "latency_ms": latency_ms,
        "output_preview": output[:500],
        "timestamp": time.time(),
    }


def _prompt(repo_name: str, budget: int, context: str) -> str:
    return (
        "You are evaluating a software repository from source context.\n"
        f"Repository: {repo_name}\n"
        f"Context budget: {budget}%\n\n"
        "Return exactly four short bullet points:\n"
        "- primary language/framework\n"
        "- repository purpose\n"
        "- one concrete risk or missing test\n"
        "- whether the provided context was sufficient\n\n"
        "Use only the context below. If no context is provided, say that context is absent.\n\n"
        f"{context if context else '[no repository context provided]'}"
    )


def _ollama_chat(model: ModelSpec, prompt: str, timeout_seconds: int) -> str:
    url = model.base_url.rstrip("/") + "/v1/chat/completions"
    body = json.dumps(
        {
            "model": model.model or model.name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 64,
            "stream": False,
        }
    ).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except TimeoutError:
        raise TimeoutError(f"timed out after {timeout_seconds}s")
    choices = payload.get("choices") if isinstance(payload, dict) else []
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        if isinstance(message, dict):
            return str(message.get("content") or "")
    return str(payload.get("response") or "")


def _codex_generate(model: str, prompt: str, timeout_seconds: int) -> str:
    output_path = Path.cwd() / ".agent-hub" / "research" / f"codex-last-{time.time_ns()}.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-last-message",
        str(output_path),
    ]
    if model and model not in {"codex-cli-default", "default"}:
        command.extend(["--model", model])
    command.append("-")
    try:
        completed = subprocess.run(
            command,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=timeout_seconds,
            cwd=Path.cwd(),
        )
        text = output_path.read_text(encoding="utf-8", errors="ignore") if output_path.exists() else ""
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(stderr[:1000] or f"Codex CLI exited with {completed.returncode}")
        return text.strip() or completed.stdout.strip()
    finally:
        try:
            output_path.unlink()
        except OSError:
            pass


def _analysis_payload(
    rows: list[dict[str, Any]],
    models: list[ModelSpec],
    repos: list[RepoSpec],
    timeout_seconds: int,
    max_context_tokens: int,
) -> dict[str, Any]:
    per_model = {model.name: _model_analysis(rows, model) for model in models}
    by_context = _by_context(rows)
    answers = _answers(per_model, by_context)
    return {
        "object": "agent_hub.research.multi_model_context_scaling",
        "real_model_only": True,
        "deterministic_proof_results_mixed": False,
        "timeout_seconds": timeout_seconds,
        "max_context_tokens": max_context_tokens,
        "repositories": [{"name": repo.name, "path": str(repo.path)} for repo in repos],
        "models": [
            {
                "name": model.name,
                "agent": model.agent_name,
                "provider": model.provider,
                "provider_type": model.provider_type,
                "model_class": model.size_class,
                "runnable": model.runnable,
                "reason": model.reason,
            }
            for model in models
        ],
        "runs": rows,
        "by_context": by_context,
        "per_model": per_model,
        "answers": answers,
    }


def _model_analysis(rows: list[dict[str, Any]], model: ModelSpec) -> dict[str, Any]:
    items = [row for row in rows if row["model"] == model.name and row.get("agent") == model.agent_name]
    if not items:
        return {
            "runnable": model.runnable,
            "provider": model.provider,
            "provider_type": model.provider_type,
            "model_class": model.size_class,
            "reason": model.reason or "No real rows were produced.",
        }
    buckets = _bucket_rows(items)
    points = [(float(row["context_percent"]), float(row["average_validation_score"])) for row in buckets if row["runs"]]
    fits = _fits(points)
    best_curve = min(fits.items(), key=lambda item: (item[1]["mse"], -item[1]["r2"], item[0]))[0]
    best_bucket = max(buckets, key=lambda row: (row["effective_success"], row["average_validation_score"], -row["average_latency_ms"]))
    tolerance = _tolerance_score(buckets)
    efficiency = _efficiency_score(buckets)
    trend = buckets[-1]["average_validation_score"] - buckets[0]["average_validation_score"] if len(buckets) > 1 else 0.0
    return {
        "runnable": True,
        "provider": model.provider,
        "provider_type": model.provider_type,
        "model_class": model.size_class,
        "runs": len(items),
        "success_rate": round(sum(1 for row in items if row["success"]) / len(items), 6),
        "average_validation_score": round(_avg(row["validation_score"] for row in items), 6),
        "error_rate": round(sum(1 for row in items if row["error"]) / len(items), 6),
        "timeout_rate": round(sum(1 for row in items if row["timeout"]) / len(items), 6),
        "latency_ms": round(_avg(row["latency_ms"] for row in items), 6),
        "buckets": buckets,
        "fits": fits,
        "best_fit_curve": best_curve,
        "best_context_bucket": best_bucket["context_percent"],
        "context_trend": round(trend, 6),
        "benefits_from_more_context": trend > 0.05,
        "degrades_with_more_context": trend < -0.05,
        "times_out_at_high_context": any(row["context_percent"] >= 75 and row["timeout_rate"] > 0 for row in buckets),
        "context_tolerance_score": tolerance,
        "context_efficiency_score": efficiency,
    }


def _bucket_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for budget in BUDGETS:
        rows = [row for row in items if row["context_percent"] == budget]
        error_rate = sum(1 for row in rows if row["error"]) / len(rows) if rows else 0.0
        validation = _avg(row["validation_score"] for row in rows)
        result.append(
            {
                "context_percent": budget,
                "runs": len(rows),
                "success_rate": round(sum(1 for row in rows if row["success"]) / len(rows), 6) if rows else 0.0,
                "average_validation_score": round(validation, 6),
                "error_rate": round(error_rate, 6),
                "timeout_rate": round(sum(1 for row in rows if row["timeout"]) / len(rows), 6) if rows else 0.0,
                "average_latency_ms": round(_avg(row["latency_ms"] for row in rows), 6),
                "average_context_tokens": round(_avg(row["context_tokens"] for row in rows), 6),
                "effective_success": round(validation * (1.0 - error_rate), 6),
            }
        )
    return result


def _by_context(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for budget in BUDGETS:
        items = [row for row in rows if row["context_percent"] == budget]
        result.append(
            {
                "context_percent": budget,
                "runs": len(items),
                "error_rate": round(sum(1 for row in items if row["error"]) / len(items), 6) if items else 0.0,
                "timeout_rate": round(sum(1 for row in items if row["timeout"]) / len(items), 6) if items else 0.0,
                "average_latency_ms": round(_avg(row["latency_ms"] for row in items), 6),
                "average_validation_score": round(_avg(row["validation_score"] for row in items), 6),
            }
        )
    return result


def _fits(points: list[tuple[float, float]]) -> dict[str, Any]:
    return {
        "linear": _fit_linear(points, lambda x: x),
        "logarithmic": _fit_linear(points, lambda x: math.log1p(x)),
        "saturating_exponential": _fit_saturating(points),
        "michaelis_menten": _fit_michaelis(points),
    }


def _fit_linear(points: list[tuple[float, float]], transform: Callable[[float], float]) -> dict[str, Any]:
    xs = [transform(x) for x, _ in points]
    ys = [y for _, y in points]
    if not points:
        return _fit_result({}, [], [])
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0.0
    intercept = my - slope * mx
    return _fit_result({"intercept": intercept, "slope": slope}, ys, [intercept + slope * transform(x) for x, _ in points])


def _fit_saturating(points: list[tuple[float, float]]) -> dict[str, Any]:
    ys = [y for _, y in points]
    best = (float("inf"), 0.0, 0.0, [])
    for tau in _grid(1.0, 200.0, 250):
        features = [1.0 - math.exp(-x / tau) for x, _ in points]
        asymptote = _scale(features, ys)
        predictions = [asymptote * value for value in features]
        mse = _mse(ys, predictions)
        if mse < best[0]:
            best = (mse, tau, asymptote, predictions)
    return _fit_result({"tau": best[1], "asymptote": best[2]}, ys, best[3])


def _fit_michaelis(points: list[tuple[float, float]]) -> dict[str, Any]:
    ys = [y for _, y in points]
    best = (float("inf"), 0.0, 0.0, [])
    for km in _grid(1.0, 200.0, 250):
        features = [x / (km + x) if x > 0 else 0.0 for x, _ in points]
        vmax = _scale(features, ys)
        predictions = [vmax * value for value in features]
        mse = _mse(ys, predictions)
        if mse < best[0]:
            best = (mse, km, vmax, predictions)
    return _fit_result({"km": best[1], "vmax": best[2]}, ys, best[3])


def _fit_result(parameters: dict[str, float], ys: list[float], predictions: list[float]) -> dict[str, Any]:
    return {
        "parameters": {key: round(value, 6) for key, value in parameters.items()},
        "r2": round(_r2(ys, predictions), 6),
        "mse": round(_mse(ys, predictions), 10),
        "predictions": [round(value, 6) for value in predictions],
    }


def _answers(per_model: dict[str, Any], by_context: list[dict[str, Any]]) -> dict[str, Any]:
    runnable = {name: row for name, row in per_model.items() if row.get("runnable") and row.get("runs")}
    return {
        "benefit_from_more_context": [name for name, row in runnable.items() if row["benefits_from_more_context"]],
        "degrade_with_more_context": [name for name, row in runnable.items() if row["degrades_with_more_context"]],
        "timeout_at_high_context": [name for name, row in runnable.items() if row["times_out_at_high_context"]],
        "tau_valid_for_model_class": {
            name: row["best_fit_curve"] == "saturating_exponential" for name, row in runnable.items()
        },
        "logarithmic_fits_local_models_better": _logarithmic_answer(runnable),
        "codex_stronger_context_tolerance": _codex_tolerance_answer(runnable),
        "recommended_context_budget_by_model": {
            name: row["best_context_bucket"] for name, row in runnable.items()
        },
        "error_rate_by_context_size": by_context,
    }


def _logarithmic_answer(rows: dict[str, Any]) -> bool:
    local = [row for row in rows.values() if row.get("provider") == "ollama"]
    return bool(local) and all(row.get("best_fit_curve") == "logarithmic" for row in local)


def _codex_tolerance_answer(rows: dict[str, Any]) -> str:
    codex = [row for row in rows.values() if row.get("provider") == "codex"]
    ollama = [row for row in rows.values() if row.get("provider") == "ollama"]
    if not codex:
        return "not tested; no Codex CLI rows were produced"
    if not ollama:
        return "not comparable; no Ollama rows were produced"
    codex_score = max(float(row.get("context_tolerance_score") or 0.0) for row in codex)
    ollama_score = max(float(row.get("context_tolerance_score") or 0.0) for row in ollama)
    return "yes" if codex_score > ollama_score else "no"


def _write_outputs(directory: Path, payload: dict[str, Any]) -> dict[str, Path]:
    scaling_json = directory / "multi_model_context_scaling.json"
    scaling_md = directory / "multi_model_context_scaling.md"
    tolerance_json = directory / "model_context_tolerance.json"
    tolerance_md = directory / "model_context_tolerance.md"
    codex_md = directory / "codex_vs_ollama.md"
    scaling_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    scaling_md.write_text(_scaling_markdown(payload), encoding="utf-8")
    tolerance_payload = _tolerance_payload(payload)
    tolerance_json.write_text(json.dumps(tolerance_payload, indent=2, sort_keys=True), encoding="utf-8")
    tolerance_md.write_text(_tolerance_markdown(tolerance_payload), encoding="utf-8")
    codex_md.write_text(_codex_markdown(payload), encoding="utf-8")
    return {
        "multi_model_context_scaling_json": scaling_json,
        "multi_model_context_scaling_markdown": scaling_md,
        "model_context_tolerance_json": tolerance_json,
        "model_context_tolerance_markdown": tolerance_md,
        "codex_vs_ollama_markdown": codex_md,
    }


def _tolerance_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for name, row in payload["per_model"].items():
        rows.append(
            {
                "model": name,
                "provider": row.get("provider"),
                "provider_type": row.get("provider_type"),
                "model_class": row.get("model_class"),
                "runnable": row.get("runnable"),
                "best_fit_curve": row.get("best_fit_curve"),
                "best_context_bucket": row.get("best_context_bucket"),
                "context_tolerance_score": row.get("context_tolerance_score", 0.0),
                "context_efficiency_score": row.get("context_efficiency_score", 0.0),
                "error_rate": row.get("error_rate"),
                "timeout_rate": row.get("timeout_rate"),
                "reason": row.get("reason", ""),
            }
        )
    return {"object": "agent_hub.research.model_context_tolerance", "models": rows}


def _scaling_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Multi-Model Context Scaling",
        "",
        "Real model rows only. Deterministic proof results are not mixed into this report.",
        "",
        "## Models",
        "| model | provider | type | class | runs | best curve | best budget | tolerance | efficiency | error | timeout |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in payload["per_model"].items():
        lines.append(
            f"| {name} | {row.get('provider')} | {row.get('provider_type')} | {row.get('model_class')} | {row.get('runs', 0)} | {row.get('best_fit_curve', 'n/a')} | {row.get('best_context_bucket', 'n/a')} | {row.get('context_tolerance_score', 0)} | {row.get('context_efficiency_score', 0)} | {row.get('error_rate', 'n/a')} | {row.get('timeout_rate', 'n/a')} |"
        )
    lines.extend(["", "## Context Buckets", "| budget | runs | validation | error | timeout | latency ms |", "| --- | --- | --- | --- | --- | --- |"])
    for row in payload["by_context"]:
        lines.append(
            f"| {row['context_percent']}% | {row['runs']} | {row['average_validation_score']} | {row['error_rate']} | {row['timeout_rate']} | {row['average_latency_ms']} |"
        )
    answers = payload["answers"]
    lines.extend(
        [
            "",
            "## Required Answers",
            f"1. Which models benefit from more context? {', '.join(answers['benefit_from_more_context']) or 'None detected.'}",
            f"2. Which models degrade with more context? {', '.join(answers['degrade_with_more_context']) or 'None detected.'}",
            f"3. Which models time out at high context? {', '.join(answers['timeout_at_high_context']) or 'None detected.'}",
            f"4. Is tau valid for any model class? {_tau_answer(payload)}",
            f"5. Does logarithmic scaling fit local models better? {'Yes' if answers['logarithmic_fits_local_models_better'] else 'No'}",
            f"6. Does Codex show stronger context tolerance? {answers['codex_stronger_context_tolerance']}",
            f"7. What context budget should Agent-Hub use per model? {_budget_answer(answers)}",
            "",
        ]
    )
    return "\n".join(lines)


def _tolerance_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Model Context Tolerance", "", "| model | class | best budget | tolerance | efficiency | curve |", "| --- | --- | --- | --- | --- | --- |"]
    for row in payload["models"]:
        lines.append(
            f"| {row['model']} | {row.get('model_class')} | {row.get('best_context_bucket')} | {row.get('context_tolerance_score')} | {row.get('context_efficiency_score')} | {row.get('best_fit_curve')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _codex_markdown(payload: dict[str, Any]) -> str:
    codex = [row for row in payload["models"] if row["provider"] == "codex"]
    ollama = [row for row in payload["models"] if row["provider"] == "ollama"]
    codex_tested = any(payload["per_model"].get(row["name"], {}).get("runs") for row in codex)
    lines = [
        "# Codex vs Ollama",
        "",
        f"- Ollama models tested: {', '.join(row['name'] for row in ollama) or 'none'}",
        f"- Codex detected: {'yes' if codex else 'no'}",
        f"- Codex tested: {'yes' if codex_tested else 'no'}",
        "- Reason: Codex CLI was explicitly requested and is reported as a separate model class.",
        "",
        "Conclusion: compare Codex and Ollama using the real rows in the scaling report; provider failures and timeouts are preserved as observations.",
        "",
    ]
    return "\n".join(lines)


def _tau_answer(payload: dict[str, Any]) -> str:
    winners = [
        f"{name} ({row.get('model_class')})"
        for name, row in payload["per_model"].items()
        if row.get("best_fit_curve") == "saturating_exponential"
    ]
    return ", ".join(winners) if winners else "No; saturating exponential did not win for any real-tested model."


def _budget_answer(answers: dict[str, Any]) -> str:
    return ", ".join(f"{name}: {budget}%" for name, budget in answers["recommended_context_budget_by_model"].items()) or "No runnable models."


def _size_class(model: str) -> str:
    lower = model.lower()
    if ":cloud" in lower or lower.endswith("-cloud"):
        return "ollama-cloud"
    for marker in ("0.5b", "1b", "1.5b", "3b"):
        if marker in lower:
            return "small-local"
    for marker in ("7b", "8b", "9b"):
        if marker in lower:
            return "larger-local"
    for marker in ("13b", "14b", "27b", "32b", "70b"):
        if marker in lower:
            return "larger-local"
    return "local"


def _validation_score(output: str, keywords: tuple[str, ...]) -> float:
    if not output.strip():
        return 0.0
    lowered = output.lower()
    keyword_score = sum(1 for word in keywords if word in lowered) / max(1, len(keywords))
    structure_score = min(1.0, output.count("-") / 4.0)
    return round(0.75 * keyword_score + 0.25 * structure_score, 6)


def _tolerance_score(buckets: list[dict[str, Any]]) -> float:
    high = [row for row in buckets if row["context_percent"] >= 75]
    if not high:
        return 0.0
    return round(_avg(row["effective_success"] for row in high), 6)


def _efficiency_score(buckets: list[dict[str, Any]]) -> float:
    scored = []
    for row in buckets:
        latency = max(1.0, float(row["average_latency_ms"] or 0.0))
        tokens = max(1.0, float(row["average_context_tokens"] or 0.0))
        scored.append(row["effective_success"] / math.log1p(tokens) / math.log1p(latency))
    return round(max(scored) if scored else 0.0, 6)


def _token_count(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _avg(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


def _mse(ys: list[float], predictions: list[float]) -> float:
    return sum((y - p) ** 2 for y, p in zip(ys, predictions)) / len(ys) if ys else 0.0


def _r2(ys: list[float], predictions: list[float]) -> float:
    if not ys or not predictions:
        return 0.0
    mean = sum(ys) / len(ys)
    total = sum((y - mean) ** 2 for y in ys)
    residual = sum((y - p) ** 2 for y, p in zip(ys, predictions))
    return 1.0 - residual / total if total else 1.0


def _scale(features: list[float], targets: list[float]) -> float:
    denom = sum(value * value for value in features)
    return sum(feature * target for feature, target in zip(features, targets)) / denom if denom else 0.0


def _grid(start: float, stop: float, count: int) -> list[float]:
    step = (stop - start) / max(1, count - 1)
    return [start + index * step for index in range(count)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local real-model context scaling study.")
    parser.add_argument("--state-dir", default=".agent-hub")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--max-context-tokens", type=int, default=12_000)
    parser.add_argument("--model-scope", default="all")
    args = parser.parse_args(argv)
    paths = run_multi_model_context_scaling(
        args.state_dir,
        repo_root=args.repo_root,
        timeout_seconds=args.timeout_seconds,
        max_context_tokens=args.max_context_tokens,
        model_scope=args.model_scope,
    )
    print(json.dumps(paths, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_multi_model_context_scaling"]
