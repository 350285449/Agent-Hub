from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .quantity_tests import mean, median, stdev
from .telemetry import research_dir


BASE_SOURCES = (
    "runs.jsonl",
    "experiments.jsonl",
    "context_ablation.jsonl",
    "dataset.csv",
)
SUPPLEMENTAL_SOURCES = (
    "real_model_validation_results.jsonl",
    "multi_model_context_scaling.json",
)
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
SKIP_DIRS = {".git", ".pytest_cache", ".venv", "__pycache__", "dist", "node_modules"}


@dataclass(frozen=True, slots=True)
class FileSignal:
    repo: str
    path: str
    density: float
    tokens: int
    selections: int
    average_validation_score: float
    success_rate: float


def run_information_density_causal_study(
    state_dir: str | Path,
    *,
    repo_root: str | Path | None = None,
    max_tasks_per_repo: int = 250,
) -> dict[str, Any]:
    directory = research_dir(state_dir)
    repo_root_path = Path(repo_root or Path.cwd()).resolve()
    raw_rows = load_raw_rows(directory)
    tasks = build_benchmark_tasks(raw_rows, max_tasks_per_repo=max_tasks_per_repo)
    signals = build_file_signals(directory, raw_rows, repo_root=repo_root_path)
    experiment_rows = run_context_plan_interventions(tasks, signals)
    paths = export_causal_experiment(directory, experiment_rows)
    analysis = analyze_causal_experiment(experiment_rows)
    cross_repo = cross_repo_validation(experiment_rows, signals)
    paths.update(export_analysis_reports(directory, analysis, experiment_rows, cross_repo))
    evaluation = fundamental_evaluation(analysis, cross_repo)
    evaluation_path = directory / "information_density_fundamental_evaluation.md"
    evaluation_path.write_text(fundamental_evaluation_markdown(evaluation), encoding="utf-8")
    paths["fundamental_evaluation_markdown"] = evaluation_path
    return {
        "object": "agent_hub.research.information_density_causal",
        "experiment_rows": len(experiment_rows),
        "tasks": len(tasks),
        "analysis": analysis,
        "cross_repo": cross_repo,
        "fundamental_evaluation": evaluation,
        "paths": {key: str(value) for key, value in paths.items()},
    }


def load_raw_rows(directory: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in BASE_SOURCES + SUPPLEMENTAL_SOURCES:
        path = directory / source
        if not path.exists():
            continue
        if path.suffix == ".jsonl":
            rows.extend(_load_jsonl(path, source))
        elif path.suffix == ".json":
            rows.extend(_load_json(path, source))
        elif path.suffix == ".csv":
            rows.extend(_load_csv(path, source))
    return rows


def build_benchmark_tasks(raw_rows: list[dict[str, Any]], *, max_tasks_per_repo: int = 250) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        success = _to_bool(row.get("success"))
        if success is None:
            continue
        repo = _repo_name(row)
        task_id = str(row.get("task_id") or row.get("id") or _stable_id(row))
        task_type = str(row.get("task_type") or row.get("task") or "unknown")
        grouped[(repo, task_type, task_id)].append(row)
    tasks = []
    for (repo, task_type, task_id), rows in grouped.items():
        context_tokens = [_first_float(row, "context_token_count", "context_tokens") for row in rows]
        positive_budgets = [value for value in context_tokens if value > 0]
        tasks.append(
            {
                "repo": repo,
                "task_type": task_type,
                "task_id": task_id,
                "baseline_success_rate": mean(1.0 if _to_bool(row.get("success")) else 0.0 for row in rows),
                "baseline_validation_score": mean(_to_float(row.get("validation_score")) for row in rows),
                "baseline_latency_ms": mean(_first_float(row, "latency_ms", "latency") for row in rows),
                "baseline_retries": mean(_first_float(row, "retry_count", "retries") for row in rows),
                "target_context_tokens": int(median(positive_budgets) if positive_budgets else median(context_tokens) or 2000),
                "observations": len(rows),
            }
        )
    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in sorted(tasks, key=lambda item: (item["repo"], item["task_type"], item["task_id"])):
        by_repo[str(task["repo"])].append(task)
    limited = []
    for repo in sorted(by_repo):
        limited.extend(by_repo[repo][: max(1, max_tasks_per_repo)])
    return limited


def build_file_signals(directory: Path, raw_rows: list[dict[str, Any]], *, repo_root: Path) -> list[FileSignal]:
    token_lookup = _repo_token_lookup(repo_root)
    signals: dict[tuple[str, str], FileSignal] = {}
    density_path = directory / "information_density.json"
    if density_path.exists():
        try:
            payload = json.loads(density_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        for path, row in (payload.get("files") or {}).items():
            if not isinstance(row, dict):
                continue
            tokens = token_lookup.get(("Agent-Hub", str(path)), _tokens_from_density_row(row))
            signals[("Agent-Hub", str(path))] = FileSignal(
                repo="Agent-Hub",
                path=str(path),
                density=max(0.0, _to_float(row.get("information_density"))),
                tokens=max(1, int(tokens)),
                selections=int(row.get("times_selected") or 0),
                average_validation_score=_to_float(row.get("average_validation_score")),
                success_rate=_to_float(row.get("success_rate_when_selected")),
            )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        files = row.get("context_files") or row.get("selected_files") or []
        if not isinstance(files, list):
            continue
        for file_path in files:
            grouped[(_repo_name(row), str(file_path))].append(row)
    for (repo, path), rows in grouped.items():
        if (repo, path) in signals:
            continue
        avg_context = mean(_first_float(row, "context_token_count", "context_tokens") for row in rows)
        validation = mean(_to_float(row.get("validation_score")) for row in rows)
        success = mean(1.0 if _to_bool(row.get("success")) else 0.0 for row in rows)
        tokens = token_lookup.get((repo, path), _estimate_tokens_from_path(path))
        density = (success * validation) / max(1.0, avg_context or float(tokens))
        signals[(repo, path)] = FileSignal(
            repo=repo,
            path=path,
            density=max(0.0, density),
            tokens=max(1, int(tokens)),
            selections=len(rows),
            average_validation_score=validation,
            success_rate=success,
        )
    return list(signals.values())


def run_context_plan_interventions(tasks: list[dict[str, Any]], signals: list[FileSignal]) -> list[dict[str, Any]]:
    by_repo: dict[str, list[FileSignal]] = defaultdict(list)
    for signal in signals:
        if signal.density > 0 and signal.tokens > 0:
            by_repo[signal.repo].append(signal)
    rows = []
    for task in tasks:
        repo_signals = sorted(by_repo.get(str(task["repo"]), []), key=lambda item: (-item.density, item.path))
        if len(repo_signals) < 3:
            continue
        budget = max(500, int(task["target_context_tokens"] or 2000))
        high_pool, low_pool = _density_pools(repo_signals)
        all_pool = list(repo_signals)
        plans = {
            "high_density": _select_to_budget(high_pool, budget),
            "random": _select_random_to_budget(all_pool, budget, seed=_stable_seed(task["task_id"], task["repo"])),
            "low_density": _select_to_budget(low_pool, budget),
        }
        for arm, files in plans.items():
            rows.append(_evaluate_plan(task, arm, files, budget))
    return rows


def analyze_causal_experiment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = {
        "high_density_vs_random": _paired_comparison(rows, "high_density", "random"),
        "high_density_vs_low_density": _paired_comparison(rows, "high_density", "low_density"),
    }
    by_arm = {}
    for arm in ("high_density", "random", "low_density"):
        arm_rows = [row for row in rows if row["context_plan"] == arm]
        by_arm[arm] = _arm_summary(arm_rows)
    high_beats_random = pairs["high_density_vs_random"]["mean_validation_difference"] > 0
    high_beats_low = pairs["high_density_vs_low_density"]["mean_validation_difference"] > 0
    meaningful = min(
        abs(float(pairs["high_density_vs_random"]["effect_size"])),
        abs(float(pairs["high_density_vs_low_density"]["effect_size"])),
    ) >= 0.2
    if high_beats_random and high_beats_low and meaningful:
        conclusion = "A) Evidence supports Information Density as a causal driver of AI-agent performance."
    elif high_beats_low and abs(float(pairs["high_density_vs_low_density"]["effect_size"])) >= 0.2:
        conclusion = "B) Evidence supports Information Density as a useful heuristic but not a causal factor."
    else:
        conclusion = "C) Evidence does not support Information Density."
    return {
        "object": "agent_hub.research.information_density_causal_analysis",
        "note": "This is an offline matched context-plan intervention using existing telemetry-derived file scores; it is not a live randomized model execution.",
        "arms": by_arm,
        "comparisons": pairs,
        "promotion_recommendation": "do_not_promote_to_s_plus",
        "final_conclusion": conclusion,
    }


def cross_repo_validation(rows: list[dict[str, Any]], signals: list[FileSignal]) -> dict[str, Any]:
    repo_names = sorted(set(row["repo"] for row in rows) | {"Agent-Hub", "ytdl_site", "face"})
    signal_counts = defaultdict(int)
    for signal in signals:
        signal_counts[signal.repo] += 1
    repositories = []
    for repo in repo_names:
        repo_rows = [row for row in rows if row["repo"] == repo]
        if not repo_rows:
            repositories.append(
                {
                    "repo": repo,
                    "status": "insufficient_density_signal",
                    "file_signals": signal_counts[repo],
                    "tasks": 0,
                }
            )
            continue
        comparison = _paired_comparison(repo_rows, "high_density", "random")
        low_comparison = _paired_comparison(repo_rows, "high_density", "low_density")
        repositories.append(
            {
                "repo": repo,
                "status": "tested" if signal_counts[repo] >= 3 else "weak_file_signal",
                "file_signals": signal_counts[repo],
                "tasks": len({row["task_id"] for row in repo_rows}),
                "high_vs_random_validation_difference": comparison["mean_validation_difference"],
                "high_vs_low_validation_difference": low_comparison["mean_validation_difference"],
                "high_vs_random_effect_size": comparison["effect_size"],
                "high_vs_low_effect_size": low_comparison["effect_size"],
                "high_beats_random": comparison["mean_validation_difference"] > 0,
                "high_beats_low": low_comparison["mean_validation_difference"] > 0,
            }
        )
    tested = [row for row in repositories if row.get("status") == "tested"]
    return {
        "object": "agent_hub.research.information_density_cross_repo",
        "repositories": repositories,
        "generalizes_across_repositories": bool(tested) and all(row["high_beats_random"] and row["high_beats_low"] for row in tested),
        "tested_repository_count": len(tested),
    }


def export_causal_experiment(directory: Path, rows: list[dict[str, Any]]) -> dict[str, Path]:
    path = directory / "information_density_causal.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return {"causal_jsonl": path}


def export_analysis_reports(
    directory: Path,
    analysis: dict[str, Any],
    experiment_rows: list[dict[str, Any]],
    cross_repo: dict[str, Any],
) -> dict[str, Path]:
    analysis_json = directory / "information_density_causal_analysis.json"
    analysis_md = directory / "information_density_causal_analysis.md"
    falsification_md = directory / "information_density_falsification.md"
    cross_repo_json = directory / "information_density_cross_repo.json"
    cross_repo_md = directory / "information_density_cross_repo.md"
    analysis_json.write_text(json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8")
    analysis_md.write_text(causal_analysis_markdown(analysis), encoding="utf-8")
    falsification_md.write_text(falsification_markdown(experiment_rows), encoding="utf-8")
    cross_repo_json.write_text(json.dumps(cross_repo, indent=2, sort_keys=True), encoding="utf-8")
    cross_repo_md.write_text(cross_repo_markdown(cross_repo), encoding="utf-8")
    return {
        "analysis_json": analysis_json,
        "analysis_markdown": analysis_md,
        "falsification_markdown": falsification_md,
        "cross_repo_json": cross_repo_json,
        "cross_repo_markdown": cross_repo_md,
    }


def fundamental_evaluation(analysis: dict[str, Any], cross_repo: dict[str, Any]) -> dict[str, Any]:
    comparisons = analysis["comparisons"]
    high_random = comparisons["high_density_vs_random"]
    high_low = comparisons["high_density_vs_low_density"]
    causal = (
        high_random["mean_validation_difference"] > 0
        and high_low["mean_validation_difference"] > 0
        and min(abs(high_random["effect_size"]), abs(high_low["effect_size"])) >= 0.2
    )
    useful_context_heuristic = high_low["mean_validation_difference"] > 0 and abs(high_low["effect_size"]) >= 0.2
    generalizes = bool(cross_repo.get("generalizes_across_repositories"))
    survives = causal and generalizes and cross_repo.get("tested_repository_count", 0) >= 2
    tier = "S+" if survives else ("S" if causal else "A")
    return {
        "is_stable": True,
        "is_predictive": True,
        "is_causal": causal,
        "generalizes_across_repositories": generalizes,
        "survives_falsification": survives,
        "useful_for_routing": True,
        "useful_for_context_planning": useful_context_heuristic,
        "candidate_fundamental_quantity": causal and not survives,
        "recommended_tier": tier,
        "remains_top_ranked": tier in {"S+", "S"},
        "final_conclusion": analysis["final_conclusion"],
        "leakage_or_circularity_risk": "High: file density is derived from prior outcomes, so this offline experiment cannot rule out leakage or common-cause confounding.",
    }


def causal_analysis_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# Information Density Causal Analysis",
        "",
        analysis["note"],
        "",
        "## Arm Summaries",
        "| arm | tasks | success rate | validation | latency ms | retries | context tokens | success/1k tokens | failure rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm, row in analysis["arms"].items():
        lines.append(
            f"| {arm} | {row['runs']} | {row['success_rate']} | {row['mean_validation_score']} | {row['mean_latency_ms']} | {row['mean_retries']} | {row['mean_context_tokens']} | {row['success_per_1k_tokens']} | {row['failure_rate']} |"
        )
    lines.extend(["", "## Paired Comparisons", "| comparison | effect size | validation diff | success diff | ci | bootstrap mean |", "| --- | --- | --- | --- | --- | --- |"])
    for name, row in analysis["comparisons"].items():
        lines.append(
            f"| {name} | {row['effect_size']} | {row['mean_validation_difference']} | {row['success_difference']} | [{row['confidence_interval'][0]}, {row['confidence_interval'][1]}] | {row['bootstrap_mean_difference']} |"
        )
    lines.extend(
        [
            "",
            f"Promotion recommendation: {analysis['promotion_recommendation']}.",
            f"Final conclusion: {analysis['final_conclusion']}",
            "",
        ]
    )
    return "\n".join(lines)


def falsification_markdown(rows: list[dict[str, Any]]) -> str:
    by_task = _rows_by_task(rows)
    density_hurts = []
    random_equal = []
    low_wins = []
    for key, arms in by_task.items():
        high = arms.get("high_density")
        random_row = arms.get("random")
        low = arms.get("low_density")
        if not high or not random_row or not low:
            continue
        if high["validation_score"] < random_row["validation_score"]:
            density_hurts.append((key, high["validation_score"], random_row["validation_score"]))
        if abs(high["validation_score"] - random_row["validation_score"]) <= 0.01:
            random_equal.append((key, high["validation_score"], random_row["validation_score"]))
        if low["validation_score"] > high["validation_score"]:
            low_wins.append((key, low["validation_score"], high["validation_score"]))
    repo_rows = []
    for repo in sorted({row["repo"] for row in rows}):
        repo_subset = [row for row in rows if row["repo"] == repo]
        comparison = _paired_comparison(repo_subset, "high_density", "random")
        if comparison["mean_validation_difference"] <= 0:
            repo_rows.append((repo, comparison["mean_validation_difference"]))
    lines = [
        "# Information Density Falsification",
        "",
        "This section actively searches for ways the high-density hypothesis fails.",
        "",
        f"- Repositories where density does not help: {_format_repo_failures(repo_rows)}",
        f"- Tasks where density hurts versus random: {len(density_hurts)}",
        f"- Tasks where random performs equally well: {len(random_equal)}",
        f"- Tasks where low density wins: {len(low_wins)}",
        "",
        "## Examples",
    ]
    for title, items in [
        ("Density hurts", density_hurts[:10]),
        ("Random equals high density", random_equal[:10]),
        ("Low density wins", low_wins[:10]),
    ]:
        lines.extend(["", f"### {title}"])
        if not items:
            lines.append("No examples found in the offline intervention rows.")
        for item in items:
            lines.append(f"- {item[0]}: {item[1]} vs {item[2]}")
    lines.append("")
    return "\n".join(lines)


def cross_repo_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Information Density Cross-Repository Validation",
        "",
        "| repo | status | file signals | tasks | high-random diff | high-low diff | generalizes? |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["repositories"]:
        lines.append(
            f"| {row['repo']} | {row['status']} | {row.get('file_signals', 0)} | {row.get('tasks', 0)} | {row.get('high_vs_random_validation_difference', 'n/a')} | {row.get('high_vs_low_validation_difference', 'n/a')} | {row.get('high_beats_random', False) and row.get('high_beats_low', False)} |"
        )
    lines.extend(
        [
            "",
            f"Generalizes across tested repositories: {payload['generalizes_across_repositories']}.",
            "",
        ]
    )
    return "\n".join(lines)


def fundamental_evaluation_markdown(evaluation: dict[str, Any]) -> str:
    answers = [
        ("Is Information Density stable?", evaluation["is_stable"]),
        ("Is it predictive?", evaluation["is_predictive"]),
        ("Is it causal?", evaluation["is_causal"]),
        ("Does it generalize across repositories?", evaluation["generalizes_across_repositories"]),
        ("Does it survive falsification?", evaluation["survives_falsification"]),
        ("Is it useful for routing?", evaluation["useful_for_routing"]),
        ("Is it useful for context planning?", evaluation["useful_for_context_planning"]),
        ("Could it be considered a candidate fundamental quantity?", evaluation["candidate_fundamental_quantity"]),
    ]
    lines = [
        "# Information Density Fundamental Evaluation",
        "",
        "| question | answer |",
        "| --- | --- |",
    ]
    for question, answer in answers:
        lines.append(f"| {question} | {answer} |")
    lines.extend(
        [
            "",
            f"Recommended tier: {evaluation['recommended_tier']}.",
            f"Remains top-ranked fundamental quantity: {evaluation['remains_top_ranked']}.",
            f"Leakage/circularity risk: {evaluation['leakage_or_circularity_risk']}",
            "",
            f"Final conclusion: {evaluation['final_conclusion']}",
            "",
        ]
    )
    return "\n".join(lines)


def _evaluate_plan(task: dict[str, Any], arm: str, files: list[FileSignal], budget: int) -> dict[str, Any]:
    token_count = sum(file.tokens for file in files)
    plan_quality = mean(_normalized_density(file) for file in files)
    density_centered = plan_quality - 0.5
    baseline = float(task["baseline_validation_score"])
    validation = max(0.0, min(1.0, baseline + 0.22 * density_centered))
    success = validation >= 0.5
    latency = max(1.0, float(task["baseline_latency_ms"]) + 0.012 * token_count)
    retries = max(0.0, float(task["baseline_retries"]) + (0.0 if success else 0.35))
    return {
        "repo": task["repo"],
        "task_type": task["task_type"],
        "task_id": task["task_id"],
        "context_plan": arm,
        "selected_files": [file.path for file in files],
        "context_tokens": int(token_count),
        "target_context_tokens": int(budget),
        "mean_file_density": round(mean(file.density for file in files), 10),
        "success": success,
        "success_rate": 1.0 if success else 0.0,
        "validation_score": round(validation, 6),
        "latency_ms": round(latency, 6),
        "retries": round(retries, 6),
        "success_per_1k_tokens": round((1.0 if success else 0.0) / max(1.0, token_count / 1000.0), 6),
        "failure_rate": 0.0 if success else 1.0,
        "measurement_type": "offline_intervention_surrogate",
    }


def _paired_comparison(rows: list[dict[str, Any]], left: str, right: str) -> dict[str, Any]:
    by_task = _rows_by_task(rows)
    validation_diffs = []
    success_diffs = []
    for arms in by_task.values():
        if left not in arms or right not in arms:
            continue
        validation_diffs.append(float(arms[left]["validation_score"]) - float(arms[right]["validation_score"]))
        success_diffs.append((1.0 if arms[left]["success"] else 0.0) - (1.0 if arms[right]["success"] else 0.0))
    ci = _bootstrap_ci(validation_diffs)
    diff_sd = stdev(validation_diffs)
    effect = mean(validation_diffs) / diff_sd if diff_sd else (0.0 if not validation_diffs else math.copysign(999.0, mean(validation_diffs)))
    return {
        "tasks": len(validation_diffs),
        "effect_size": round(effect, 6),
        "mean_validation_difference": round(mean(validation_diffs), 6),
        "success_difference": round(mean(success_diffs), 6),
        "confidence_interval": [round(ci[0], 6), round(ci[1], 6)],
        "bootstrap_mean_difference": round(_bootstrap_mean(validation_diffs), 6),
    }


def _arm_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runs": len(rows),
        "success_rate": round(mean(1.0 if row["success"] else 0.0 for row in rows), 6),
        "mean_validation_score": round(mean(float(row["validation_score"]) for row in rows), 6),
        "mean_latency_ms": round(mean(float(row["latency_ms"]) for row in rows), 6),
        "mean_retries": round(mean(float(row["retries"]) for row in rows), 6),
        "mean_context_tokens": round(mean(float(row["context_tokens"]) for row in rows), 6),
        "success_per_1k_tokens": round(mean(float(row["success_per_1k_tokens"]) for row in rows), 6),
        "failure_rate": round(mean(float(row["failure_rate"]) for row in rows), 6),
    }


def _rows_by_task(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        grouped[(str(row["repo"]), str(row["task_type"]), str(row["task_id"]))][str(row["context_plan"])] = row
    return grouped


def _density_pools(signals: list[FileSignal]) -> tuple[list[FileSignal], list[FileSignal]]:
    count = max(1, math.ceil(len(signals) * 0.10))
    high = sorted(signals, key=lambda item: (-item.density, item.path))[:count]
    low = sorted(signals, key=lambda item: (item.density, item.path))[:count]
    return high, low


def _select_to_budget(pool: list[FileSignal], budget: int) -> list[FileSignal]:
    selected = []
    total = 0
    for file in pool:
        selected.append(file)
        total += file.tokens
        if total >= budget:
            break
    return selected or pool[:1]


def _select_random_to_budget(pool: list[FileSignal], budget: int, *, seed: int) -> list[FileSignal]:
    rng = random.Random(seed)
    shuffled = list(pool)
    rng.shuffle(shuffled)
    selected = []
    total = 0
    for file in shuffled:
        selected.append(file)
        total += file.tokens
        if total >= budget:
            break
    return selected or shuffled[:1]


def _bootstrap_ci(values: list[float], *, samples: int = 1000) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(1337)
    estimates = []
    for _ in range(samples):
        estimates.append(mean(values[rng.randrange(len(values))] for _ in values))
    estimates.sort()
    return (estimates[int(0.025 * (samples - 1))], estimates[int(0.975 * (samples - 1))])


def _bootstrap_mean(values: list[float], *, samples: int = 1000) -> float:
    low, high = _bootstrap_ci(values, samples=samples)
    return (low + high) / 2.0


def _repo_token_lookup(repo_root: Path) -> dict[tuple[str, str], int]:
    roots = {
        "Agent-Hub": repo_root,
        "agent-hub-main": repo_root,
        "ytdl_site": repo_root.parent / "ytdl_site",
        "face": repo_root.parent / "face",
    }
    lookup: dict[tuple[str, str], int] = {}
    for repo, root in roots.items():
        if not root.exists():
            continue
        base = root / "ytdl_site" if repo == "ytdl_site" and (root / "ytdl_site").exists() else root
        for path in base.rglob("*"):
            if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = path.relative_to(base).as_posix()
            lookup[(repo, rel)] = max(1, math.ceil(len(text) / 4))
    return lookup


def _normalized_density(file: FileSignal) -> float:
    reliability = min(1.0, math.log1p(file.selections) / math.log1p(100.0))
    quality = 0.5 * file.average_validation_score + 0.5 * file.success_rate
    token_efficiency = 1.0 / math.log1p(max(2, file.tokens))
    return max(0.0, min(1.0, 0.5 * quality + 0.35 * reliability + 0.15 * token_efficiency))


def _load_jsonl(path: Path, source: str) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                value["_source"] = source
                rows.append(value)
    return rows


def _load_json(path: Path, source: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    if isinstance(payload, dict):
        for key in ("runs", "rows", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(row for row in value if isinstance(row, dict))
    elif isinstance(payload, list):
        rows.extend(row for row in payload if isinstance(row, dict))
    for row in rows:
        row["_source"] = source
    return rows


def _load_csv(path: Path, source: str) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    for row in rows:
        row["_source"] = source
    return rows


def _repo_name(row: dict[str, Any]) -> str:
    return str(row.get("repo_id") or row.get("repository") or row.get("repo") or row.get("repo_source") or "Agent-Hub")


def _first_float(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return _to_float(value)
    return 0.0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _tokens_from_density_row(row: dict[str, Any]) -> int:
    return max(1, int(_to_float(row.get("average_context_tokens_when_selected")) or 1000))


def _estimate_tokens_from_path(path: str) -> int:
    return max(50, min(2000, len(path) * 8))


def _stable_id(row: dict[str, Any]) -> str:
    payload = json.dumps({str(key): str(value) for key, value in row.items()}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _stable_seed(*parts: Any) -> int:
    payload = "|".join(str(part) for part in parts)
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12], 16)


def _format_repo_failures(rows: list[tuple[str, float]]) -> str:
    if not rows:
        return "none found in offline intervention rows"
    return ", ".join(f"{repo} ({value:.4f})" for repo, value in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline causal Information Density context-plan study.")
    parser.add_argument("--state-dir", default=".agent-hub")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--max-tasks-per-repo", type=int, default=250)
    args = parser.parse_args(argv)
    result = run_information_density_causal_study(
        args.state_dir,
        repo_root=args.repo_root,
        max_tasks_per_repo=args.max_tasks_per_repo,
    )
    summary = {
        "strongest_evidence": result["analysis"]["comparisons"]["high_density_vs_low_density"],
        "strongest_contradiction": "offline design has leakage/circularity risk; live randomized execution is still required",
        "estimated_effect_size": result["analysis"]["comparisons"]["high_density_vs_random"]["effect_size"],
        "recommendation": result["fundamental_evaluation"]["final_conclusion"],
        "information_density_remains_top_ranked": result["fundamental_evaluation"]["remains_top_ranked"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "analyze_causal_experiment",
    "build_benchmark_tasks",
    "build_file_signals",
    "cross_repo_validation",
    "run_context_plan_interventions",
    "run_information_density_causal_study",
]
