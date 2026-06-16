from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..evaluation import _score_text, default_benchmark_tasks
from ..models import HubRequest
from ..providers import create_provider
from .agent_state_vector import build_agent_state_vectors, export_agent_state_vectors, feature_names, records_from_vectors
from .telemetry import research_dir


PREDICTORS = {
    "structure_only": "structure_only",
    "history_only": "history_only",
    "structure_history": "structure_history",
    "model_task_context_compatibility": "compatibility",
    "state_space_model": "state_space",
}
TARGETS = ("success", "validation_score", "failure")


def run_state_space_theory_research_program(
    state_dir: str | Path,
    *,
    run_live: bool = False,
    live_task_limit: int = 2,
) -> dict[str, str]:
    from .state_based_routing import export_state_based_routing
    from .state_generalization import export_state_generalization

    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    live_path = None
    if run_live:
        live_payload = run_live_state_space_validation(state_dir, task_limit=live_task_limit)
        live_path = live_payload.get("results_path")
    vectors = build_agent_state_vectors(state_dir)
    vectors_path, _vectors_payload = export_agent_state_vectors(state_dir, vectors)
    records = records_from_vectors(vectors)
    results = compute_state_space_results(records)
    results_path = directory / "state_space_results.json"
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    generalization_path, generalization = export_state_generalization(state_dir, vectors)
    transition_json, transition_md, transition = export_experience_transition_curve(state_dir, records)
    routing_path, routing = export_state_based_routing(state_dir, vectors)
    falsification_path = export_falsification_report(directory, results, generalization, routing, transition)
    summary_path = export_summary_report(directory, results, generalization, routing, transition)
    result = {
        "agent_state_vectors": str(vectors_path),
        "state_space_results": str(results_path),
        "state_generalization": str(generalization_path),
        "experience_transition_curve": str(transition_json),
        "experience_transition_curve_markdown": str(transition_md),
        "state_based_routing": str(routing_path),
        "state_space_falsification": str(falsification_path),
        "state_space_theory_summary": str(summary_path),
    }
    if live_path:
        result["live_state_space_validation"] = str(live_path)
    return result


def run_live_state_space_validation(state_dir: str | Path, *, task_limit: int = 2) -> dict[str, Any]:
    from ..config import load_config

    config = load_config()
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "real_model_validation_results.jsonl"
    tasks = default_benchmark_tasks(route="cloud-agent")[: max(1, int(task_limit))]
    agents = [
        agent
        for agent in config.agents.values()
        if agent.enabled and str(agent.provider_type or "").lower() == "ollama-cloud"
    ]
    codex = config.agents.get("codex-cli")
    if codex is not None:
        agents.append(replace(codex, enabled=True, timeout_seconds=min(float(codex.timeout_seconds or 60.0), 60.0)))

    experiment_id = f"state-space-live-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    files = _live_context_files(Path.cwd())
    rows: list[dict[str, Any]] = []
    with path.open("a", encoding="utf-8") as handle:
        for agent in agents:
            for task_index, task in enumerate(tasks, start=1):
                for context_percent in (0, 50):
                    row = _run_live_one(
                        agent,
                        task,
                        task_index=task_index,
                        context_percent=context_percent,
                        files=files,
                        experiment_id=experiment_id,
                    )
                    rows.append(row)
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
    payload = {
        "object": "agent_hub.research.live_state_space_validation",
        "experiment_id": experiment_id,
        "results_path": str(path),
        "rows": len(rows),
        "ollama_cloud_rows": sum(1 for row in rows if row.get("provider_type") == "ollama-cloud"),
        "codex_cli_rows": sum(1 for row in rows if row.get("provider_type") == "codex-cli"),
        "success_rate": round(sum(1 for row in rows if row.get("success") is True) / len(rows), 6) if rows else 0.0,
        "errors": [row for row in rows if row.get("error")][:10],
    }
    (directory / "live_state_space_validation.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def compute_state_space_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "object": "agent_hub.research.state_space_results",
        "row_count": len(records),
        "data_scope": _data_scope(records),
        "targets": {
            target: {
                name: evaluate_records(records, _feature_names(records, family), target)
                for name, family in PREDICTORS.items()
            }
            for target in TARGETS
        },
        "leakage_controls": [
            "Targets are stored outside feature vectors.",
            "History features are computed by a chronological prior tracker before each current row is added.",
            "Same-run success, validation_score, error, latency, and retry_count are not feature names.",
        ],
    }


def _data_scope(records: list[dict[str, Any]]) -> dict[str, Any]:
    provider_types: dict[str, int] = {}
    models: dict[str, int] = {}
    for record in records:
        provider_type = str(record.get("provider_type") or record.get("provider") or "unknown")
        model = str(record.get("model") or "unknown")
        provider_types[provider_type] = provider_types.get(provider_type, 0) + 1
        models[model] = models.get(model, 0) + 1
    return {
        "scope": "Ollama Cloud and Codex CLI only; local model rows are excluded.",
        "provider_type_counts": dict(sorted(provider_types.items())),
        "model_counts": dict(sorted(models.items())),
        "live_execution_rows": sum(1 for record in records if record.get("live_execution")),
        "real_model_only_rows": sum(1 for record in records if record.get("real_model_only")),
    }


def _run_live_one(
    agent: Any,
    task: Any,
    *,
    task_index: int,
    context_percent: int,
    files: list[tuple[str, str]],
    experiment_id: str,
) -> dict[str, Any]:
    selected = _select_live_context(task, files, context_percent)
    context = "\n\n".join(f"# file: {name}\n{text}" for name, text in selected)
    request = HubRequest(
        session_id=f"{experiment_id}-{agent.name}-{task_index}-{context_percent}",
        route="codex-cli" if str(agent.provider_type or "") == "codex-cli" else "cloud-agent",
        preferred_agent=agent.name,
        task=task.prompt,
        messages=[{"role": "user", "content": task.prompt}],
        context=context,
        max_tokens=128,
        temperature=0.0,
        record_session=False,
        raw={"agent_hub": {"state_space_live_validation": True, "context_budget_tokens": max(800, len(context) // 4)}},
        metadata={"context_files": [name for name, _text in selected]},
    )
    started = time.perf_counter()
    text = ""
    error = ""
    try:
        text = create_provider(agent).complete(request).text
    except Exception as exc:
        error = str(exc)
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    validation_score = _score_text(text, task) if text else 0.0
    success = bool(text) and validation_score >= 0.6 and not error
    return {
        "object": "agent_hub.research.state_space_live_validation_result",
        "experiment_id": experiment_id,
        "task_id": f"{experiment_id}-{task.type}-{task_index}-{agent.name}-{context_percent}",
        "task_type": task.type,
        "route": request.route,
        "selected_agent": agent.name,
        "provider": agent.provider,
        "provider_type": agent.provider_type or agent.provider,
        "selected_model": agent.model,
        "model": agent.model,
        "candidate_models": [agent.model],
        "repository": "Agent-Hub",
        "repo_id": "Agent-Hub",
        "repo_source": "live_state_space_validation",
        "context_percent": context_percent,
        "context_budget_ratio": context_percent / 100.0,
        "selected_files": [name for name, _text in selected],
        "context_files": [name for name, _text in selected],
        "context_token_count": max(0, len(context) // 4),
        "input_tokens": max(1, (len(task.prompt) + len(context)) // 4),
        "output_tokens": max(0, len(text) // 4),
        "latency_ms": latency_ms,
        "cost_estimate": 0.0,
        "validation_score": validation_score,
        "success": success,
        "retry_count": 0,
        "error": error,
        "output_preview": text[:500],
        "real_model_only": True,
        "live_execution": True,
        "timestamp": time.time(),
    }


def _live_context_files(root: Path) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    ignored = {".git", ".agent-hub", "__pycache__", ".pytest_cache", "dist", "build", "node_modules"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".json", ".toml"}:
            continue
        if any(part in ignored for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        result.append((str(path.relative_to(root)).replace("\\", "/"), text[:1200]))
        if len(result) >= 80:
            break
    return result


def _select_live_context(task: Any, files: list[tuple[str, str]], context_percent: int) -> list[tuple[str, str]]:
    if context_percent <= 0:
        return []
    terms = [task.type, *task.expected_keywords, *task.prompt.lower().split()]
    scored = []
    for name, text in files:
        haystack = f"{name}\n{text[:300]}".lower()
        score = sum(1 for term in terms if str(term).strip(".,:;").lower() in haystack)
        scored.append((score, name, text))
    budget = 2500 * context_percent // 100
    selected: list[tuple[str, str]] = []
    used = 0
    for _score, name, text in sorted(scored, key=lambda row: (-row[0], row[1])):
        tokens = max(1, len(text) // 4)
        if selected and used + tokens > budget:
            continue
        selected.append((name, text))
        used += tokens
        if used >= budget:
            break
    return selected


def evaluate_records(records: list[dict[str, Any]], features: list[str], target: str = "success") -> dict[str, float]:
    if not records or not features:
        return _stats([], [])
    split = max(1, int(len(records) * 0.8))
    if split >= len(records):
        split = max(1, len(records) - 1)
    train = records[:split]
    test = records[split:]
    return train_and_predict(train, test, features, target)


def train_and_predict(train: list[dict[str, Any]], test: list[dict[str, Any]], features: list[str], target: str = "success") -> dict[str, float]:
    if not train or not test or not features:
        return _stats([], [])
    model = fit_model(train, features, target)
    predictions = [predict_with_model(model, record) for record in test]
    actual = [float(record.get(target, 0.0)) for record in test]
    return _stats(actual, predictions)


def fit_model(records: list[dict[str, Any]], features: list[str], target: str = "success") -> dict[str, Any]:
    screened = _screen_features(records, features, target)
    xs = [[1.0] + [float(record["features"].get(feature, 0.0)) for feature in screened] for record in records]
    ys = [float(record.get(target, 0.0)) for record in records]
    return {"features": screened, "weights": _ridge_weights(xs, ys), "target": target}


def predict_with_model(model: dict[str, Any], record: dict[str, Any]) -> float:
    row = [1.0] + [float(record["features"].get(feature, 0.0)) for feature in model.get("features", [])]
    return _clamp(sum(float(weight) * value for weight, value in zip(model.get("weights", []), row)))


def export_experience_transition_curve(state_dir: str | Path, records: list[dict[str, Any]]) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    points = []
    for cap in (0, 5, 10, 50, 100):
        capped = [_cap_history(record, cap) for record in records]
        points.append(
            {
                "prior_runs": cap,
                "success": evaluate_records(capped, _feature_names(capped, "state_space"), "success"),
                "validation_score": evaluate_records(capped, _feature_names(capped, "state_space"), "validation_score"),
                "failure": evaluate_records(capped, _feature_names(capped, "state_space"), "failure"),
            }
        )
    payload = {
        "object": "agent_hub.research.experience_transition_curve",
        "points": points,
        "interpretation": "History count features are capped to simulate available prior-run budgets; rate priors remain chronological.",
    }
    json_path = directory / "experience_transition_curve.json"
    md_path = directory / "experience_transition_curve.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_transition_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def export_falsification_report(directory: Path, results: dict[str, Any], generalization: dict[str, Any], routing: dict[str, Any], transition: dict[str, Any]) -> Path:
    path = directory / "state_space_falsification.md"
    success = results["targets"]["success"]
    failures = []
    state_r2 = success["state_space_model"]["r2"]
    best_other = max(row["r2"] for name, row in success.items() if name != "state_space_model")
    unseen_repo = generalization["unseen_repository"]["state_space_model"]["r2"]
    if state_r2 <= best_other + 0.01:
        failures.append("State-space does not materially outperform the strongest simpler predictor.")
    if unseen_repo < 0.35:
        failures.append("Unseen-repository generalization is weak.")
    if success["history_only"]["r2"] > success["structure_only"]["r2"] and unseen_repo < state_r2 * 0.5:
        failures.append("History appears to overfit local repositories.")
    if routing["strategies"].get("state_based", {}).get("success_rate", 0.0) <= routing["strategies"].get("default_routing", {}).get("success_rate", 0.0):
        failures.append("State-based routing does not beat default routing in the offline benchmark.")
    lines = [
        "# State-Space Falsification",
        "",
        "This report searches for evidence against pre-execution state-space prediction.",
        "",
        "## Evidence Against",
        *[f"- {item}" for item in failures or ["No hard falsification trigger fired, but the evidence remains observational."]],
        "",
        "## Leakage Audit",
        "- Feature vectors exclude same-run success, validation_score, error, latency, and retry_count.",
        "- Historical priors are generated before each row is incorporated.",
        "- Targets and routing evaluation still use observed outcomes, so causal routing claims should be treated as offline counterfactuals.",
        "",
        "## Stress Results",
        f"- State-space success R2: {state_r2}",
        f"- Best non-state-space success R2: {round(best_other, 6)}",
        f"- Unseen-repository state-space R2: {unseen_repo}",
        f"- Unseen-task state-space R2: {generalization['unseen_task_type']['state_space_model']['r2']}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def export_summary_report(directory: Path, results: dict[str, Any], generalization: dict[str, Any], routing: dict[str, Any], transition: dict[str, Any]) -> Path:
    path = directory / "state_space_theory_summary.md"
    success = results["targets"]["success"]
    structure = success["structure_only"]
    history = success["history_only"]
    compatibility = success["model_task_context_compatibility"]
    state = success["state_space_model"]
    default_route = routing["strategies"].get("default_routing", {})
    state_route = routing["strategies"].get("state_based", {})
    outperforms = state["r2"] > max(structure["r2"], history["r2"], compatibility["r2"]) + 0.01
    repo_ok = generalization["unseen_repository"]["state_space_model"]["r2"] >= 0.35
    task_ok = generalization["unseen_task_type"]["state_space_model"]["r2"] >= 0.35
    routing_ok = state_route.get("success_rate", 0.0) > default_route.get("success_rate", 0.0)
    strongest = outperforms and repo_ok and task_ok and routing_ok
    lines = [
        "# AI Agent State-Space Theory Summary",
        "",
        "Theory tested: Success = f(Model, Task, Context, Repository, History).",
        "",
        "## Data Scope",
        f"- Rows: {results.get('row_count', 0)}",
        f"- Scope: {results.get('data_scope', {}).get('scope', 'Ollama Cloud and Codex CLI only.')}",
        f"- Provider types: {results.get('data_scope', {}).get('provider_type_counts', {})}",
        f"- Live execution rows: {results.get('data_scope', {}).get('live_execution_rows', 0)}",
        "",
        "## Final Answers",
        f"1. Does state-space modeling outperform previous theories? {'Yes, in this dataset' if outperforms else 'Not cleanly'}; success R2 is {state['r2']} versus structure {structure['r2']}, history {history['r2']}, and compatibility {compatibility['r2']}.",
        f"2. How much comes from structure? Structure-only success correlation {structure['correlation']} and R2 {structure['r2']}.",
        f"3. How much comes from history? History-only success correlation {history['correlation']} and R2 {history['r2']}; treat high values cautiously because history can be repository-local.",
        f"4. Does it generalize to unseen repositories? {'Moderately, by the local threshold' if repo_ok else 'No / weak in this run'}; unseen-repository state-space R2 {generalization['unseen_repository']['state_space_model']['r2']}.",
        f"5. Does it generalize to unseen tasks? {'Moderately, by the local threshold' if task_ok else 'No / weak in this run'}; unseen-task state-space R2 {generalization['unseen_task_type']['state_space_model']['r2']}.",
        f"6. Is state-based routing better than current routing? {'Yes in the offline benchmark' if routing_ok else 'No in the offline benchmark'}; state success {state_route.get('success_rate', 0.0)} vs default {default_route.get('success_rate', 0.0)}.",
        f"7. Is this the strongest research direction so far? {'Possibly, but still observational' if strongest else 'Not yet; the weak points above prevent that claim.'}",
        "",
        "## Cold Start vs Warm Start",
        f"- Cold start state-space R2 with history zeroed: {generalization['cold_start']['state_space_zero_history']['r2']}",
        f"- Warm start state-space R2: {generalization['warm_start']['state_space']['r2']}",
        "",
        "## Transition Curve",
        *[f"- {point['prior_runs']} prior runs: success R2 {point['success']['r2']}, calibration error {point['success']['calibration_error']}" for point in transition["points"]],
        "",
        "Do not overclaim: these are observational predictions from local telemetry and generated experiment artifacts, not randomized causal estimates.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _feature_names(records: list[dict[str, Any]], family: str) -> list[str]:
    if not records:
        return []
    names = sorted(records[0]["features"])
    if family == "structure_only":
        return [name for name in names if name.startswith("structure.")]
    if family == "history_only":
        return [name for name in names if name.startswith("history.")]
    if family == "structure_history":
        return [name for name in names if name.startswith(("structure.", "history."))]
    if family == "compatibility":
        return [name for name in names if name.startswith("compatibility.")]
    return names


def _cap_history(record: dict[str, Any], cap: int) -> dict[str, Any]:
    copy = {**record, "features": dict(record["features"])}
    for key, value in list(copy["features"].items()):
        if key.startswith("history.") and key.endswith(".experience_count"):
            copy["features"][key] = min(float(value), math.log1p(cap) / math.log1p(5000.0)) if cap else 0.0
        elif key.startswith("history.") and cap == 0:
            if key.endswith(".success_rate") or key.endswith(".recent_success_rate") or key.endswith(".validation_score"):
                copy["features"][key] = 0.5
            elif key.endswith(".failure_rate"):
                copy["features"][key] = 0.5
            else:
                copy["features"][key] = 0.0
    return copy


def _transition_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Experience Transition Curve",
        "",
        "| prior runs | success corr | success R2 | MAE | RMSE | calibration |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for point in payload["points"]:
        row = point["success"]
        lines.append(f"| {point['prior_runs']} | {row['correlation']} | {row['r2']} | {row['mae']} | {row['rmse']} | {row['calibration_error']} |")
    lines.append("")
    return "\n".join(lines)


def _screen_features(records: list[dict[str, Any]], features: list[str], target: str, limit: int = 12) -> list[str]:
    if len(features) <= limit:
        return features
    ys = [float(record.get(target, 0.0)) for record in records]
    scored = []
    for feature in features:
        xs = [float(record["features"].get(feature, 0.0)) for record in records]
        scored.append((abs(_pearson(xs, ys)), feature))
    return [feature for _score, feature in sorted(scored, reverse=True)[:limit]]


def _ridge_weights(xs: list[list[float]], ys: list[float], ridge: float = 1e-4) -> list[float]:
    if not xs:
        return []
    n = len(xs[0])
    xtx = [[sum(row[i] * row[j] for row in xs) + (ridge if i == j else 0.0) for j in range(n)] for i in range(n)]
    xty = [sum(row[i] * y for row, y in zip(xs, ys)) for i in range(n)]
    return _solve(xtx, xty)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [a[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        denom = aug[col][col] or 1e-12
        aug[col] = [value / denom for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [value - factor * aug[col][idx] for idx, value in enumerate(aug[row])]
    return [aug[row][-1] for row in range(n)]


def _stats(actual: list[float], predicted: list[float]) -> dict[str, float]:
    return {
        "correlation": round(_pearson(predicted, actual), 6),
        "r2": round(_r2(actual, predicted), 6),
        "mae": round(_mae(actual, predicted), 6),
        "rmse": round(_rmse(actual, predicted), 6),
        "calibration_error": round(_calibration_error(actual, predicted), 6),
    }


def _calibration_error(actual: list[float], predicted: list[float], bins: int = 10) -> float:
    if not actual:
        return 0.0
    total = 0.0
    for index in range(bins):
        lo = index / bins
        hi = (index + 1) / bins
        pairs = [(a, p) for a, p in zip(actual, predicted) if lo <= p <= hi or (index == bins - 1 and p == 1.0)]
        if pairs:
            total += (len(pairs) / len(actual)) * abs(sum(a for a, _p in pairs) / len(pairs) - sum(p for _a, p in pairs) / len(pairs))
    return total


def _mae(actual: list[float], predicted: list[float]) -> float:
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual) if actual else 0.0


def _rmse(actual: list[float], predicted: list[float]) -> float:
    return math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual)) if actual else 0.0


def _r2(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    mean = sum(actual) / len(actual)
    total = sum((value - mean) ** 2 for value in actual)
    residual = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    return 1.0 - residual / total if total else 0.0


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    ml = sum(left) / len(left)
    mr = sum(right) / len(right)
    numerator = sum((a - ml) * (b - mr) for a, b in zip(left, right))
    denom_l = math.sqrt(sum((a - ml) ** 2 for a in left))
    denom_r = math.sqrt(sum((b - mr) ** 2 for b in right))
    return numerator / (denom_l * denom_r) if denom_l and denom_r else 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AI Agent State-Space Theory research.")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--live", action="store_true", help="Run fresh Ollama Cloud/Codex CLI validation rows before analysis.")
    parser.add_argument("--live-task-limit", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        from ..config import load_config

        state_dir = load_config().state_dir
    result = run_state_space_theory_research_program(
        state_dir,
        run_live=args.live,
        live_task_limit=args.live_task_limit,
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
    "compute_state_space_results",
    "evaluate_records",
    "fit_model",
    "predict_with_model",
    "run_live_state_space_validation",
    "run_state_space_theory_research_program",
    "train_and_predict",
]
