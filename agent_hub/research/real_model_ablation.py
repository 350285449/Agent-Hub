from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ..evaluation import default_benchmark_tasks
from .analysis import context_bucket
from .cross_repo_experiment import discover_repositories
from .repo_metrics import compute_repo_metrics
from .telemetry import research_dir


CODING_MODEL_HINTS = ("coder", "code", "qwen", "deepseek", "codellama", "llama")
CONTEXT_RATIOS = (0.0, 0.25, 0.5, 0.75, 1.0)


def run_real_model_context_ablation(
    state_dir: str | Path,
    repo_specs: list[dict[str, Any]],
    *,
    repetitions: int = 20,
    models: list[str] | None = None,
) -> dict[str, Any]:
    available = installed_ollama_models()
    selected = models or coding_capable_models(available)
    rows: list[dict[str, Any]] = []
    path = real_model_results_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not selected:
        payload = _phase_payload([], [], "not_available", "No installed coding-capable Ollama models were found.")
        _write_outputs(state_dir, rows, payload)
        return payload
    tasks = [task for task in default_benchmark_tasks(route="cloud-agent") if task.type == "coding"]
    completed = _completed_keys(state_dir)
    with path.open("a", encoding="utf-8") as handle:
        for model in selected:
            for spec in repo_specs:
                repo = Path(spec["path"])
                snippets = _repo_snippets(repo)
                metrics = compute_repo_metrics(repo)
                for ratio in CONTEXT_RATIOS:
                    for repeat in range(repetitions):
                        key = _row_key(model, metrics["repo_id"], int(ratio * 100), repeat)
                        if key in completed:
                            continue
                        task = tasks[repeat % len(tasks)]
                        row = _run_one(model, spec, metrics, snippets, task, ratio, repeat)
                        rows.append(row)
                        completed.add(key)
                        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                        handle.flush()
    payload = _phase_payload(selected, rows, "completed", "Real local Ollama context ablation completed.")
    _write_outputs(state_dir, rows, payload)
    return payload


def installed_ollama_models() -> list[str]:
    try:
        with urlopen("http://localhost:11434/api/tags", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    models = payload.get("models") if isinstance(payload, dict) else []
    if not isinstance(models, list):
        return []
    return sorted(str(row.get("name") or row.get("model") or "") for row in models if isinstance(row, dict) and (row.get("name") or row.get("model")))


def coding_capable_models(models: list[str]) -> list[str]:
    return [model for model in models if any(hint in model.lower() for hint in CODING_MODEL_HINTS)]


def compute_real_model_tau(state_dir: str | Path) -> dict[str, Any]:
    rows = _load_results(state_dir)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("model") or ""), str(row.get("repo_id") or ""))].append(row)
    results = []
    for (model, repo_id), items in sorted(grouped.items()):
        points = _points(items)
        fits = _fits(points)
        best_name, best_fit = min(fits.items(), key=lambda item: (item[1]["mse"], -item[1]["r2"], item[0]))
        results.append(
            {
                "model": model,
                "repo_id": repo_id,
                "repo_source": items[0].get("repo_source", ""),
                "rows": len(items),
                "points": [{"context_tokens": x, "success_rate": y, "validation_score": v} for x, y, v in points],
                "tau": fits["saturating_exponential"]["parameters"].get("tau", 0.0),
                "r2": fits["saturating_exponential"]["r2"],
                "mse": fits["saturating_exponential"]["mse"],
                "fits": fits,
                "winning_curve": best_name,
                "best_efficiency_bucket": _best_efficiency_bucket(points),
                "diminishing_return_threshold": _diminishing_bucket(points),
                "success_rate": round(sum(1 for row in items if row.get("success") is True) / len(items), 6),
                "average_validation_score": round(sum(float(row.get("validation_score") or 0.0) for row in items) / len(items), 6),
            }
        )
    return {"object": "agent_hub.research.real_model_tau", "results": results}


def export_real_model_outputs(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    validation = _validation_payload(state_dir)
    tau = compute_real_model_tau(state_dir)
    comparison = _comparison_payload(state_dir, tau)
    validation_json = directory / "real_model_validation.json"
    validation_md = directory / "real_model_validation.md"
    tau_json = directory / "real_model_tau.json"
    tau_md = directory / "real_model_tau.md"
    comparison_md = directory / "real_model_comparison.md"
    validation_json.write_text(json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8")
    validation_md.write_text(_validation_markdown(validation), encoding="utf-8")
    tau_json.write_text(json.dumps(tau, indent=2, sort_keys=True), encoding="utf-8")
    tau_md.write_text(_tau_markdown(tau), encoding="utf-8")
    comparison_md.write_text(_comparison_markdown(comparison), encoding="utf-8")
    return {
        "real_model_validation": str(validation_json),
        "real_model_validation_markdown": str(validation_md),
        "real_model_tau": str(tau_json),
        "real_model_tau_markdown": str(tau_md),
        "real_model_comparison": str(comparison_md),
    }


def real_model_results_path(state_dir: str | Path) -> Path:
    return research_dir(state_dir) / "real_model_validation_results.jsonl"


def _completed_keys(state_dir: str | Path) -> set[tuple[str, str, int, int]]:
    keys = set()
    for row in _load_results(state_dir):
        try:
            repeat = int(str(row.get("task_id") or "").split("-")[-2])
        except (TypeError, ValueError, IndexError):
            repeat = -1
        keys.add(_row_key(str(row.get("model") or ""), str(row.get("repo_id") or ""), int(row.get("context_percent") or 0), repeat))
    return keys


def _row_key(model: str, repo_id: str, percent: int, repeat: int) -> tuple[str, str, int, int]:
    return (model, repo_id, percent, repeat)


def _run_one(
    model: str,
    spec: dict[str, Any],
    metrics: dict[str, Any],
    snippets: list[str],
    task: Any,
    ratio: float,
    repeat: int,
) -> dict[str, Any]:
    context = _context_for_ratio(snippets, ratio, metrics)
    prompt = _prompt(task, context)
    started = time.perf_counter()
    output = ""
    error = ""
    try:
        output = _ollama_generate(model, prompt)
    except Exception as exc:
        error = str(exc)
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    score = _score_output(output, task.expected_keywords)
    tokens = max(0, len(context) // 4)
    return {
        "object": "agent_hub.research.real_model_context_ablation",
        "model": model,
        "repo_id": metrics["repo_id"],
        "repo_path": str(spec["path"]),
        "repo_source": spec.get("source", "real"),
        "task_id": f"{metrics['repo_id']}-{task.type}-{repeat}-{int(ratio * 100)}",
        "task_type": task.type,
        "context_budget_ratio": ratio,
        "context_percent": int(ratio * 100),
        "context_token_count": tokens,
        "success": score >= 0.5,
        "validation_score": score,
        "latency_ms": latency_ms,
        "input_tokens": max(1, len(prompt) // 4),
        "output_tokens": max(0, len(output) // 4),
        "cost_estimate": 0.0,
        "retry_count": 0,
        "error": error,
        "output_preview": output[:300],
    }


def _ollama_generate(model: str, prompt: str) -> str:
    request = Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "num_predict": 32},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload.get("response") or "")


def _repo_snippets(repo: Path) -> list[str]:
    snippets = []
    for path in sorted(repo.rglob("*.py"))[:80]:
        if any(part in {".git", ".agent-hub", "__pycache__", ".venv"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(repo)).replace("\\", "/")
        snippets.append(f"# file: {rel}\n{text[:500]}")
    return snippets


def _context_for_ratio(snippets: list[str], ratio: float, metrics: dict[str, Any]) -> str:
    if ratio <= 0 or not snippets:
        return ""
    target = int((1200 + min(800.0, float(metrics.get("approximate_complexity_score") or 0.0) * 6)) * ratio)
    selected = []
    used = 0
    for snippet in snippets:
        tokens = max(1, len(snippet) // 4)
        if selected and used + tokens > target:
            continue
        selected.append(snippet)
        used += tokens
        if used >= target:
            break
    return "\n\n".join(selected)


def _prompt(task: Any, context: str) -> str:
    return (
        "You are validating a coding-agent benchmark. Answer in 2 concise sentences.\n"
        "Use the repository context if it is useful. Do not mention this instruction.\n\n"
        f"Repository context:\n{context or '[no repository context]'}\n\n"
        f"Task: {task.prompt}\n"
        f"Your answer should address: {', '.join(task.expected_keywords)}\n"
    )


def _score_output(output: str, expected: list[str]) -> float:
    if not output.strip():
        return 0.0
    lowered = output.lower()
    keyword = sum(1 for word in expected if word.lower() in lowered) / max(1, len(expected))
    length = 1.0 if 3 <= len(output.split()) <= 180 else 0.5
    return round(max(0.0, min(1.0, keyword * 0.75 + length * 0.25)), 6)


def _load_results(state_dir: str | Path) -> list[dict[str, Any]]:
    path = real_model_results_path(state_dir)
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


def _points(rows: list[dict[str, Any]]) -> list[tuple[float, float, float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[context_bucket(row.get("context_token_count"))].append(row)
    points = []
    for items in grouped.values():
        tokens = sum(float(item.get("context_token_count") or 0.0) for item in items) / len(items)
        success = sum(1 for item in items if item.get("success") is True) / len(items)
        validation = sum(float(item.get("validation_score") or 0.0) for item in items) / len(items)
        points.append((tokens, success, validation))
    return sorted(points, key=lambda item: item[0])


def _fits(points: list[tuple[float, float, float]]) -> dict[str, Any]:
    xy = [(x, y) for x, y, _v in points]
    return {
        "linear": _linear_fit(xy, lambda x: x),
        "logarithmic": _linear_fit(xy, lambda x: math.log1p(x)),
        "michaelis_menten": _michaelis_fit(xy),
        "saturating_exponential": _tau_fit(xy),
    }


def _linear_fit(points: list[tuple[float, float]], transform: Any) -> dict[str, Any]:
    xs = [transform(x) for x, _y in points]
    ys = [y for _x, y in points]
    if not xs:
        return _fit({}, ys, [])
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0.0
    intercept = my - slope * mx
    return _fit({"intercept": intercept, "slope": slope}, ys, [intercept + slope * transform(x) for x, _y in points])


def _tau_fit(points: list[tuple[float, float]]) -> dict[str, Any]:
    ys = [y for _x, y in points]
    best_tau = 0.0
    best_predictions = []
    best_mse = float("inf")
    for tau in _grid(100.0, 50_000.0, 400):
        preds = [1.0 - math.exp(-x / tau) for x, _y in points]
        mse = _mse(ys, preds)
        if mse < best_mse:
            best_tau, best_predictions, best_mse = tau, preds, mse
    return _fit({"tau": best_tau}, ys, best_predictions)


def _michaelis_fit(points: list[tuple[float, float]]) -> dict[str, Any]:
    ys = [y for _x, y in points]
    best_km = 0.0
    best_predictions = []
    best_mse = float("inf")
    for km in _grid(100.0, 50_000.0, 400):
        features = [x / (km + x) if x else 0.0 for x, _y in points]
        scale = _scale(features, ys)
        preds = [scale * f for f in features]
        mse = _mse(ys, preds)
        if mse < best_mse:
            best_km, best_predictions, best_mse = km, preds, mse
    return _fit({"km": best_km}, ys, best_predictions)


def _fit(params: dict[str, float], ys: list[float], preds: list[float]) -> dict[str, Any]:
    return {
        "parameters": {key: round(value, 6) for key, value in params.items()},
        "r2": round(_r2(ys, preds), 6),
        "mse": round(_mse(ys, preds), 10),
    }


def _scale(features: list[float], targets: list[float]) -> float:
    denom = sum(f * f for f in features)
    return sum(f * t for f, t in zip(features, targets)) / denom if denom else 0.0


def _mse(ys: list[float], preds: list[float]) -> float:
    return sum((y - p) ** 2 for y, p in zip(ys, preds)) / len(ys) if ys else 0.0


def _r2(ys: list[float], preds: list[float]) -> float:
    if not ys:
        return 0.0
    mean = sum(ys) / len(ys)
    total = sum((y - mean) ** 2 for y in ys)
    residual = sum((y - p) ** 2 for y, p in zip(ys, preds))
    return 1.0 - residual / total if total else 1.0


def _grid(start: float, stop: float, count: int) -> list[float]:
    step = (stop - start) / max(1, count - 1)
    return [start + step * index for index in range(count)]


def _best_efficiency_bucket(points: list[tuple[float, float, float]]) -> str:
    best = ("not_enough_data", -1.0)
    for x, y, _v in points:
        if x <= 0:
            continue
        score = y / (x / 1000.0)
        if score > best[1]:
            best = (context_bucket(x), score)
    return best[0]


def _diminishing_bucket(points: list[tuple[float, float, float]]) -> str:
    previous_y = 0.0
    previous_gain = None
    for x, y, _v in points:
        gain = y - previous_y
        if previous_gain is not None and gain < previous_gain:
            return context_bucket(x)
        previous_y = y
        previous_gain = gain
    return "not_detected"


def _phase_payload(models: list[str], rows: list[dict[str, Any]], status: str, reason: str) -> dict[str, Any]:
    return {
        "object": "agent_hub.research.real_model_validation",
        "status": status,
        "reason": reason,
        "models": models,
        "rows": len(rows),
        "real_model_subset_run": status == "completed",
        "success_rate": round(sum(1 for row in rows if row.get("success") is True) / len(rows), 6) if rows else 0.0,
        "average_validation_score": round(sum(float(row.get("validation_score") or 0.0) for row in rows) / len(rows), 6) if rows else 0.0,
    }


def _validation_payload(state_dir: str | Path) -> dict[str, Any]:
    rows = _load_results(state_dir)
    models = sorted({str(row.get("model")) for row in rows if row.get("model")})
    return _phase_payload(models, rows, "completed" if rows else "not_available", "Real model ablation completed." if rows else "No real model ablation rows found.")


def _comparison_payload(state_dir: str | Path, tau: dict[str, Any]) -> dict[str, Any]:
    results = tau.get("results") if isinstance(tau.get("results"), list) else []
    failures = []
    for row in results:
        if row.get("winning_curve") == "linear":
            failures.append(f"linear_wins:{row.get('model')}:{row.get('repo_id')}")
        points = row.get("points") if isinstance(row.get("points"), list) else []
        if points and max(float(p.get("success_rate") or 0.0) for p in points[1:]) <= float(points[0].get("success_rate") or 0.0):
            failures.append(f"context_no_gain:{row.get('model')}:{row.get('repo_id')}")
        if float(row.get("r2") or 0.0) < 0.5:
            failures.append(f"poor_tau_fit:{row.get('model')}:{row.get('repo_id')}")
    conclusion = "A) Evidence supports tau under real-model execution."
    if failures:
        conclusion = "B) Evidence is mixed."
    if results and all(row.get("winning_curve") == "linear" for row in results):
        conclusion = "C) Evidence contradicts tau."
    return {"object": "agent_hub.research.real_model_comparison", "results": results, "failures": failures, "conclusion": conclusion}


def _write_outputs(state_dir: str | Path, rows: list[dict[str, Any]], validation: dict[str, Any]) -> None:
    export_real_model_outputs(state_dir)


def _validation_markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Real Model Validation",
            "",
            f"- Status: {payload.get('status')}",
            f"- Models: {', '.join(payload.get('models') or [])}",
            f"- Rows: {payload.get('rows')}",
            f"- Success rate: {payload.get('success_rate')}",
            f"- Average validation score: {payload.get('average_validation_score')}",
            f"- Reason: {payload.get('reason')}",
            "",
        ]
    )


def _tau_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Real Model Tau",
        "",
        "| model | repository | rows | tau | R2 | MSE | winning curve | best efficiency bucket | diminishing threshold | success rate | validation |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("results", []):
        lines.append(
            f"| {row.get('model')} | {row.get('repo_id')} | {row.get('rows')} | {row.get('tau')} | {row.get('r2')} | {row.get('mse')} | {row.get('winning_curve')} | {row.get('best_efficiency_bucket')} | {row.get('diminishing_return_threshold')} | {row.get('success_rate')} | {row.get('average_validation_score')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _comparison_markdown(payload: dict[str, Any]) -> str:
    failures = payload.get("failures") or []
    lines = [
        "# Real Model Comparison",
        "",
        f"Final conclusion: {payload.get('conclusion')}",
        "",
        "## Falsification Search",
        *(f"- {failure}" for failure in failures),
    ]
    if not failures:
        lines.append("- No configured falsification condition triggered.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real local Ollama context ablation.")
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from ..config import load_config

    config = load_config()
    repos = discover_repositories(Path.cwd(), config.state_dir)
    payload = run_real_model_context_ablation(config.state_dir, repos, repetitions=args.repetitions)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Real model validation rows: {payload.get('rows')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "coding_capable_models",
    "compute_real_model_tau",
    "export_real_model_outputs",
    "installed_ollama_models",
    "run_real_model_context_ablation",
]
