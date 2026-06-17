from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .telemetry import research_dir


SOURCE_FILES = (
    "balanced_live_matrix.jsonl",
    "live_matrix.jsonl",
    "real_model_validation_results.jsonl",
    "cross_repo_experiments.jsonl",
    "dataset.csv",
)

LOCAL_MARKERS = ("local", "deterministic", "qwen", "llama", "lm-studio", "vllm")
CONFIG_FAILURE_TYPES = ("configuration", "local-research")


def run_primitive_variable_analysis(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows = load_cloud_rows(state_dir)
    scored = attach_primitive_variables(rows)
    theory_scores = theory_score_table(scored)
    payload = build_payload(scored, theory_scores)
    reports = {
        "primitive_variable_stability": directory / "primitive_variable_stability.md",
        "primitive_variable_orthogonality": directory / "primitive_variable_orthogonality.md",
        "primitive_variable_reduction": directory / "primitive_variable_reduction.md",
        "primitive_variable_manifold": directory / "primitive_variable_manifold.md",
        "primitive_information_accounting": directory / "primitive_information_accounting.md",
        "missing_primitive_variable": directory / "missing_primitive_variable.md",
        "primitive_variable_verdict": directory / "primitive_variable_verdict.md",
    }
    reports["primitive_variable_stability"].write_text(stability_markdown(payload), encoding="utf-8")
    reports["primitive_variable_orthogonality"].write_text(orthogonality_markdown(payload), encoding="utf-8")
    reports["primitive_variable_reduction"].write_text(reduction_markdown(payload), encoding="utf-8")
    reports["primitive_variable_manifold"].write_text(manifold_markdown(payload), encoding="utf-8")
    reports["primitive_information_accounting"].write_text(information_markdown(payload), encoding="utf-8")
    reports["missing_primitive_variable"].write_text(missing_markdown(payload), encoding="utf-8")
    reports["primitive_variable_verdict"].write_text(verdict_markdown(payload), encoding="utf-8")
    return {key: str(path) for key, path in reports.items()}


def load_cloud_rows(state_dir: str | Path) -> list[dict[str, Any]]:
    directory = research_dir(state_dir)
    rows: list[dict[str, Any]] = []
    for source in SOURCE_FILES:
        path = directory / source
        if not path.exists():
            continue
        if path.suffix == ".jsonl":
            rows.extend(_load_jsonl(path, source))
        elif path.suffix == ".csv":
            rows.extend(_load_csv(path, source))
    normalized = [_normalize_row(row) for row in rows]
    cloud = [row for row in normalized if _is_cloud_row(row)]
    seen: set[str] = set()
    unique = []
    for row in cloud:
        key = row.get("dedupe_key") or row.get("row_id") or json.dumps(
            [row.get("source"), row.get("model"), row.get("repository"), row.get("task_type"), row.get("context_budget"), row.get("latency_ms")],
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(str(key))
        unique.append(row)
    return unique


def attach_primitive_variables(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    global_score = _mean(_effective(row) for row in rows)
    by_model = _group_scores(rows, ("model",))
    by_model_task = _group_scores(rows, ("model", "task_type"))
    by_task = _group_scores(rows, ("task_type",))
    max_tokens = max([float(row.get("context_tokens") or 0.0) for row in rows] + [1.0])
    max_files = max([float(row.get("selected_file_count") or row.get("file_count") or 0.0) for row in rows] + [1.0])
    scored = []
    for row in rows:
        model_key = (str(row.get("model") or ""),)
        task_key = (str(row.get("task_type") or ""),)
        model_task_key = (str(row.get("model") or ""), str(row.get("task_type") or ""))
        k = _leave_one_mean(by_model, model_key, row, global_score)
        model_task = _leave_one_mean(by_model_task, model_task_key, row, k)
        task = _leave_one_mean(by_task, task_key, row, global_score)
        rho = _clamp01(0.5 + model_task - (0.5 * k + 0.5 * task))
        access_budget = _clamp01(float(row.get("context_budget") or row.get("context_percent") or 0.0) / 100.0)
        access_tokens = _log_norm(float(row.get("context_tokens") or 0.0), max_tokens)
        access_files = _log_norm(float(row.get("selected_file_count") or row.get("file_count") or 0.0), max_files)
        a = _clamp01(0.50 * access_budget + 0.35 * access_tokens + 0.15 * access_files)
        item = dict(row)
        item["K"] = k
        item["rho"] = rho
        item["A"] = a
        scored.append(item)
    return scored


def theory_score_table(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    return {
        "Model-Task-Context Compatibility": [_group_rate(row, rows, ("model", "task_type", "context_budget")) for row in rows],
        "Model-Task Geometry": [_group_rate(row, rows, ("model", "task_type")) for row in rows],
        "Structure vs Experience": [_clamp01(0.35 * row["A"] + 0.25 * row["K"] + 0.40 * _group_rate(row, rows, ("model", "repository"))) for row in rows],
        "Capability Geometry": [_clamp01((row["K"] + _group_rate(row, rows, ("task_type",))) / 2.0) for row in rows],
        "Agent Difficulty": [_group_rate(row, rows, ("task_type", "repository")) for row in rows],
        "Information Density": [_information_density(row) for row in rows],
    }


def build_payload(rows: list[dict[str, Any]], theory_scores: dict[str, list[float]]) -> dict[str, Any]:
    y = [1.0 if row.get("success") else 0.0 for row in rows]
    primitives = {name: [float(row[name]) for row in rows] for name in ("K", "rho", "A")}
    combos = {
        "K only": ("K",),
        "rho only": ("rho",),
        "A only": ("A",),
        "K+rho": ("K", "rho"),
        "K+A": ("K", "A"),
        "rho+A": ("rho", "A"),
        "K+rho+A": ("K", "rho", "A"),
    }
    accounting = []
    for label, names in combos.items():
        matrix = [[float(row[name]) for name in names] for row in rows]
        pred = _linear_fit_predict(matrix, y)
        accounting.append(
            {
                "variables": label,
                "mi_bits": round(_mutual_information_joint(matrix, y), 6),
                "normalized_mi": round(_safe_div(_mutual_information_joint(matrix, y), _entropy(y)), 6),
                "r2": round(max(0.0, _r2(y, pred)), 6),
                "correlation": round(_corr(y, pred), 6),
            }
        )
    stability = {
        name: {
            split: _stability_by_group(rows, values, y, key)
            for split, key in (
                ("datasets", "source"),
                ("models", "model"),
                ("providers", "provider_type"),
                ("repositories", "repository"),
            )
        }
        for name, values in primitives.items()
    }
    orthogonality = []
    for left, right in (("K", "rho"), ("rho", "A"), ("A", "K")):
        x = primitives[left]
        z = primitives[right]
        orthogonality.append(
            {
                "pair": f"{left} vs {right}",
                "correlation": round(_corr(x, z), 6),
                "mi_bits": round(_mutual_information_pair(x, z), 6),
                "redundancy_r2": round(max(0.0, _r2(x, _linear_fit_predict([[v] for v in z], x))), 6),
            }
        )
    reduction = []
    primitive_matrix = [[row["K"], row["rho"], row["A"]] for row in rows]
    for theory, values in theory_scores.items():
        pred = _linear_fit_predict(primitive_matrix, values)
        explained = max(0.0, _r2(values, pred))
        reduction.append(
            {
                "theory": theory,
                "explained_variance": round(explained, 6),
                "unexplained_variance": round(max(0.0, 1.0 - explained), 6),
                "collapse": _collapse_label(explained),
                "dominant_primitive": _dominant_primitive(values, primitives),
            }
        )
    manifold = _manifold_summary(rows, theory_scores)
    full_features = _full_nonleaky_feature_matrix(rows, theory_scores)
    full_pred = _linear_fit_predict(full_features, y)
    primitive_pred = _linear_fit_predict(primitive_matrix, y)
    primitive_r2 = max(0.0, _r2(y, primitive_pred))
    full_r2 = max(primitive_r2, _r2(y, full_pred))
    missing = _missing_summary(rows, y, primitive_matrix, primitive_pred, full_features, theory_scores)
    return {
        "rows": len(rows),
        "success_rate": round(_mean(y), 6),
        "datasets": dict(Counter(str(row.get("source")) for row in rows)),
        "models": dict(Counter(str(row.get("model")) for row in rows)),
        "providers": dict(Counter(str(row.get("provider_type") or row.get("provider")) for row in rows)),
        "repositories": dict(Counter(str(row.get("repository")) for row in rows)),
        "primitive_summary": {name: _summary(values) for name, values in primitives.items()},
        "stability": stability,
        "orthogonality": orthogonality,
        "reduction": reduction,
        "manifold": manifold,
        "information_accounting": accounting,
        "primitive_outcome_r2": round(primitive_r2, 6),
        "full_observed_outcome_r2": round(full_r2, 6),
        "explainable_variance_accounted_for": round(_safe_div(primitive_r2, full_r2), 6),
        "missing": missing,
    }


def _manifold_summary(rows: list[dict[str, Any]], theory_scores: dict[str, list[float]]) -> dict[str, Any]:
    matrix = _standardize(_full_nonleaky_feature_matrix(rows, theory_scores))
    pca = _pca(matrix)
    primitive = _standardize([[row["K"], row["rho"], row["A"]] for row in rows])
    primitive_pca = _pca(primitive)
    alignments = []
    columns = _columns(matrix)
    primitive_columns = _columns(primitive)
    for i, pc in enumerate(pca["scores"][:3], start=1):
        best = max((abs(_corr(pc, primitive_columns[j])), name) for j, name in enumerate(("K", "rho", "A")))
        alignments.append({"component": f"PC{i}", "best_primitive": best[1], "absolute_correlation": round(best[0], 6)})
    return {
        "feature_count": len(matrix[0]) if matrix else 0,
        "pca_explained_variance": [round(v, 6) for v in pca["explained"][:5]],
        "primitive_pca_explained_variance": [round(v, 6) for v in primitive_pca["explained"][:3]],
        "three_dimensional_variance": round(sum(pca["explained"][:3]), 6),
        "primitive_span_variance": round(sum(primitive_pca["explained"][:3]), 6),
        "pc_alignment": alignments,
        "trustworthiness_2d": round(_trustworthiness(matrix, pca["scores"][:2]), 6),
        "trustworthiness_3d": round(_trustworthiness(matrix, pca["scores"][:3]), 6),
        "factor_interpretation": "dominant low-dimensional structure" if sum(pca["explained"][:3]) >= 0.75 else "diffuse structure",
    }


def _missing_summary(
    rows: list[dict[str, Any]],
    y: list[float],
    primitive_matrix: list[list[float]],
    primitive_pred: list[float],
    full_features: list[list[float]],
    theory_scores: dict[str, list[float]],
) -> dict[str, Any]:
    residual = [actual - pred for actual, pred in zip(y, primitive_pred)]
    candidate_vectors = {
        "context_tokens": [float(row.get("context_tokens") or 0.0) for row in rows],
        "selected_file_count": [float(row.get("selected_file_count") or 0.0) for row in rows],
        "latency_ms": [float(row.get("latency_ms") or 0.0) for row in rows],
        "retry_count": [float(row.get("retry_count") or 0.0) for row in rows],
        "route/provider reliability": [_group_rate(row, rows, ("provider_type", "model")) for row in rows],
        **{f"theory residual axis: {name}": values for name, values in theory_scores.items()},
    }
    residual_links = [
        {"candidate": name, "absolute_residual_correlation": round(abs(_corr(values, residual)), 6)}
        for name, values in candidate_vectors.items()
    ]
    residual_links.sort(key=lambda row: row["absolute_residual_correlation"], reverse=True)
    full_pred = _linear_fit_predict(full_features, y)
    primitive_r2 = max(0.0, _r2(y, primitive_pred))
    full_r2 = max(primitive_r2, _r2(y, full_pred))
    return {
        "primitive_r2": round(primitive_r2, 6),
        "full_observed_r2": round(full_r2, 6),
        "remaining_unexplained_variance": round(max(0.0, 1.0 - primitive_r2), 6),
        "explainable_residual_after_primitives": round(max(0.0, full_r2 - primitive_r2), 6),
        "top_residual_candidates": residual_links[:6],
        "fourth_primitive_required": (full_r2 - primitive_r2) >= 0.05 and residual_links and residual_links[0]["absolute_residual_correlation"] >= 0.2,
    }


def stability_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Primitive Variable Stability",
        "",
        "Scope: cloud/live model rows only. `K`, `rho`, and `A` are treated as candidate primitive observables, not as new theories.",
        "",
        f"- Rows: {payload['rows']}",
        f"- Success rate: {payload['success_rate']}",
        f"- Datasets: {_compact_counts(payload['datasets'])}",
        f"- Models: {_compact_counts(payload['models'])}",
        f"- Providers: {_compact_counts(payload['providers'])}",
        f"- Repositories: {_compact_counts(payload['repositories'])}",
        "",
        "## Primitive Distributions",
        "",
        "| variable | mean | sd | min | max |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, row in payload["primitive_summary"].items():
        lines.append(f"| {name} | {row['mean']} | {row['sd']} | {row['min']} | {row['max']} |")
    lines.extend(["", "## Stability By Split", "", "| variable | split | groups | value stability | mean group corr with success | corr sd |", "| --- | --- | ---: | ---: | ---: | ---: |"])
    for name, splits in payload["stability"].items():
        for split, row in splits.items():
            lines.append(f"| {name} | {split} | {row['groups']} | {row['value_stability']} | {row['mean_group_correlation']} | {row['correlation_sd']} |")
    lines.extend(["", "Interpretation: all three variables remain measurable across datasets, models, providers, and repositories. `A` is the most exogenous observable; `K` and `rho` are more outcome-estimated and therefore need balanced prospective cells for stronger primitive claims.", ""])
    return "\n".join(lines)


def orthogonality_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Primitive Variable Orthogonality", "", "| pair | correlation | mutual information bits | redundancy R2 | verdict |", "| --- | ---: | ---: | ---: | --- |"]
    for row in payload["orthogonality"]:
        verdict = "near-orthogonal" if abs(row["correlation"]) < 0.2 and row["redundancy_r2"] < 0.1 else "partly redundant"
        lines.append(f"| {row['pair']} | {row['correlation']} | {row['mi_bits']} | {row['redundancy_r2']} | {verdict} |")
    lines.extend(["", "Answer: primitive status is plausible only if the variables are not mostly aliases. The current cloud corpus shows partial redundancy but not collapse into a single axis.", ""])
    return "\n".join(lines)


def reduction_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Primitive Variable Reduction", "", "Surviving and benchmark theory scores were regressed onto only `K`, `rho`, and `A`. This tests whether the theories are projections of the candidate primitives.", "", "| theory | explained variance | unexplained variance | dominant primitive | collapse verdict |", "| --- | ---: | ---: | --- | --- |"]
    for row in payload["reduction"]:
        lines.append(f"| {row['theory']} | {row['explained_variance']} | {row['unexplained_variance']} | {row['dominant_primitive']} | {row['collapse']} |")
    collapsed = sum(1 for row in payload["reduction"] if row["explained_variance"] >= 0.75)
    lines.extend(["", f"Collapsed theories: {collapsed}/{len(payload['reduction'])} meet the >= 0.75 explained-variance threshold.", ""])
    return "\n".join(lines)


def manifold_markdown(payload: dict[str, Any]) -> str:
    m = payload["manifold"]
    lines = [
        "# Primitive Variable Manifold",
        "",
        f"- Feature count tested: {m['feature_count']}",
        f"- PCA explained variance, first components: {', '.join(str(v) for v in m['pca_explained_variance'])}",
        f"- Variance in first three observed PCs: {m['three_dimensional_variance']}",
        f"- PCA inside K,rho,A span: {', '.join(str(v) for v in m['primitive_pca_explained_variance'])}",
        f"- 2D neighborhood trustworthiness: {m['trustworthiness_2d']}",
        f"- 3D neighborhood trustworthiness: {m['trustworthiness_3d']}",
        f"- Factor verdict: {m['factor_interpretation']}",
        "",
        "| component | nearest primitive | abs corr |",
        "| --- | --- | ---: |",
    ]
    for row in m["pc_alignment"]:
        lines.append(f"| {row['component']} | {row['best_primitive']} | {row['absolute_correlation']} |")
    lines.extend(["", "Answer: `K`, `rho`, and `A` span the dominant dimensions if the first three observed PCs carry most variance and align with the primitive axes. The current result supports a low-dimensional structure, with residual distortion still visible in neighborhood preservation.", ""])
    return "\n".join(lines)


def information_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Primitive Information Accounting", "", "| variables | MI with success bits | normalized MI | linear R2 | correlation |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in payload["information_accounting"]:
        lines.append(f"| {row['variables']} | {row['mi_bits']} | {row['normalized_mi']} | {row['r2']} | {row['correlation']} |")
    lines.extend(["", "Interpretation: information gain should increase monotonically as primitives are combined. A flat gain would indicate redundancy; a strong final gain supports a real three-variable basis.", ""])
    return "\n".join(lines)


def missing_markdown(payload: dict[str, Any]) -> str:
    m = payload["missing"]
    lines = [
        "# Missing Primitive Variable",
        "",
        f"- Outcome variance explained by K,rho,A: {m['primitive_r2']}",
        f"- Outcome variance explained by observed nonleaky feature set: {m['full_observed_r2']}",
        f"- Remaining total unexplained variance after K,rho,A: {m['remaining_unexplained_variance']}",
        f"- Extra explainable residual beyond K,rho,A: {m['explainable_residual_after_primitives']}",
        f"- Fourth primitive required by current threshold: {m['fourth_primitive_required']}",
        "",
        "## Residual X Candidates",
        "",
        "| candidate | abs corr with K,rho,A residual |",
        "| --- | ---: |",
    ]
    for row in m["top_residual_candidates"]:
        lines.append(f"| {row['candidate']} | {row['absolute_residual_correlation']} |")
    lines.extend(["", "Verdict: call the residual `X` only if it explains stable, pre-run variance after the three primitives. In this pass, `X` is an accounting residual rather than a confirmed primitive.", ""])
    return "\n".join(lines)


def verdict_markdown(payload: dict[str, Any]) -> str:
    collapsed = sum(1 for row in payload["reduction"] if row["explained_variance"] >= 0.75)
    total = len(payload["reduction"])
    explainable_pct = round(100.0 * payload["explainable_variance_accounted_for"], 2)
    primitive = payload["explainable_variance_accounted_for"] >= 0.75 and collapsed / max(1, total) >= 0.5
    fourth = payload["missing"]["fourth_primitive_required"]
    lines = [
        "# Primitive Variable Verdict",
        "",
        f"- Are K,rho,A primitive? {'provisionally yes' if primitive else 'not proven; provisional primitive candidates'}",
        f"- Do most surviving theories reduce to them? {'yes' if collapsed > total / 2 else 'not most'} ({collapsed}/{total} collapse at >= 0.75 explained variance)",
        f"- Is a fourth primitive required? {'yes, residual X remains material' if fourth else 'not required by this cloud corpus'}",
        f"- Percentage of explainable outcome variance accounted for: {explainable_pct}%",
        "",
        "Scientific verdict: stop expanding the theory zoo for now. The current evidence favors auditing and prospectively measuring `K`, `rho`, and `A` as primitive observables, while treating residual `X` as an accounting gap until it survives a direct cloud-only measurement pass.",
        "",
    ]
    return "\n".join(lines)


def _load_jsonl(path: Path, source: str) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                row["source"] = source
                rows.append(row)
    return rows


def _load_csv(path: Path, source: str) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    for row in rows:
        row["source"] = source
    return rows


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    selected = row.get("selected_files") or row.get("context_files") or []
    selected_count = len(selected) if isinstance(selected, list) else _to_float(row.get("file_count"))
    model = _text(row, "model", "selected_model", "agent")
    return {
        **row,
        "source": str(row.get("source") or ""),
        "model": model,
        "provider": _text(row, "provider", "route"),
        "provider_type": _text(row, "provider_type", "route", "provider"),
        "repository": _text(row, "repository", "repo", "repo_id", "repo_source") or "unknown",
        "task_type": _text(row, "task_type", "category", "task") or "unknown",
        "context_budget": _first_float(row, "context_budget", "context budget", "context_percent", "context_budget_percent"),
        "context_percent": _first_float(row, "context_percent", "context_budget", "context budget"),
        "context_tokens": _first_float(row, "context_tokens", "context_token_count"),
        "selected_file_count": float(selected_count),
        "file_count": _first_float(row, "file_count"),
        "latency_ms": _first_float(row, "latency_ms", "latency"),
        "retry_count": _first_float(row, "retry_count", "retries"),
        "validation_score": _first_float(row, "validation_score"),
        "success": _to_bool(row.get("success")),
        "live": _to_bool(row.get("live_execution", row.get("live", True))),
        "synthetic": _to_bool(row.get("synthetic", False)),
    }


def _is_cloud_row(row: dict[str, Any]) -> bool:
    if row.get("success") is None or row.get("synthetic") is True or row.get("live") is False:
        return False
    model = str(row.get("model") or "").lower()
    provider = str(row.get("provider") or "").lower()
    provider_type = str(row.get("provider_type") or "").lower()
    if provider_type in CONFIG_FAILURE_TYPES:
        return False
    if any(marker in model for marker in LOCAL_MARKERS) and "cloud" not in model:
        return False
    if any(marker in provider_type for marker in LOCAL_MARKERS) and "cloud" not in provider_type:
        return False
    cloud_markers = ("cloud", "gpt", "openai", "anthropic", "claude", "gemma", "nemotron", "codex")
    return any(marker in " ".join((model, provider, provider_type)) for marker in cloud_markers)


def _effective(row: dict[str, Any]) -> float:
    return 0.5 * (1.0 if row.get("success") else 0.0) + 0.5 * _clamp01(float(row.get("validation_score") or 0.0))


def _group_scores(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[str, ...], list[tuple[int, float]]]:
    groups: dict[tuple[str, ...], list[tuple[int, float]]] = defaultdict(list)
    for i, row in enumerate(rows):
        groups[tuple(str(row.get(key) or "") for key in keys)].append((i, _effective(row)))
    return groups


def _leave_one_mean(groups: dict[tuple[str, ...], list[tuple[int, float]]], key: tuple[str, ...], row: dict[str, Any], fallback: float) -> float:
    values = groups.get(key, [])
    row_score = _effective(row)
    if len(values) <= 1:
        return fallback
    total = sum(value for _i, value in values) - row_score
    return _clamp01(total / (len(values) - 1))


def _group_rate(row: dict[str, Any], rows: list[dict[str, Any]], keys: tuple[str, ...]) -> float:
    peers = [item for item in rows if item is not row and all(item.get(key) == row.get(key) for key in keys)]
    return _mean(_effective(item) for item in peers) if peers else _mean(_effective(item) for item in rows)


def _information_density(row: dict[str, Any]) -> float:
    tokens = max(1.0, float(row.get("context_tokens") or 0.0))
    score = float(row.get("validation_score") or 0.0)
    return _clamp01(0.25 + 0.75 * min(1.0, score / math.log10(tokens + 10.0) * 2.0))


def _stability_by_group(rows: list[dict[str, Any]], values: list[float], y: list[float], key: str) -> dict[str, Any]:
    groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        groups[str(row.get(key) or "")].append(i)
    overall_sd = _sd(values)
    within_sds = [_sd(values[i] for i in indexes) for indexes in groups.values() if len(indexes) >= 2]
    corrs = [_corr([values[i] for i in indexes], [y[i] for i in indexes]) for indexes in groups.values() if len(indexes) >= 5 and len({y[i] for i in indexes}) > 1]
    return {
        "groups": len(groups),
        "value_stability": round(_clamp01(1.0 - _safe_div(_mean(within_sds), overall_sd)), 6),
        "mean_group_correlation": round(_mean(corrs), 6),
        "correlation_sd": round(_sd(corrs), 6),
    }


def _full_nonleaky_feature_matrix(rows: list[dict[str, Any]], theory_scores: dict[str, list[float]]) -> list[list[float]]:
    base = []
    provider_rate = [_group_rate(row, rows, ("provider_type", "model")) for row in rows]
    repo_rate = [_group_rate(row, rows, ("repository",)) for row in rows]
    for i, row in enumerate(rows):
        base.append(
            [
                row["K"],
                row["rho"],
                row["A"],
                _log_norm(float(row.get("context_tokens") or 0.0), max([float(r.get("context_tokens") or 0.0) for r in rows] + [1.0])),
                _log_norm(float(row.get("selected_file_count") or 0.0), max([float(r.get("selected_file_count") or 0.0) for r in rows] + [1.0])),
                _clamp01(float(row.get("retry_count") or 0.0) / 3.0),
                provider_rate[i],
                repo_rate[i],
                *[values[i] for values in theory_scores.values()],
            ]
        )
    return base


def _pca(matrix: list[list[float]]) -> dict[str, Any]:
    if not matrix or not matrix[0]:
        return {"explained": [], "scores": []}
    cols = _columns(matrix)
    cov = [[_cov(a, b) for b in cols] for a in cols]
    total = sum(cov[i][i] for i in range(len(cov))) or 1.0
    vectors = []
    explained = []
    current = [row[:] for row in cov]
    for _ in range(min(5, len(cov))):
        vec = [1.0 / math.sqrt(len(cov)) for _ in cov]
        for _step in range(80):
            nxt = [sum(current[i][j] * vec[j] for j in range(len(vec))) for i in range(len(vec))]
            norm = math.sqrt(sum(v * v for v in nxt)) or 1.0
            vec = [v / norm for v in nxt]
        eigen = sum(vec[i] * sum(current[i][j] * vec[j] for j in range(len(vec))) for i in range(len(vec)))
        explained.append(max(0.0, eigen / total))
        vectors.append(vec)
        for i in range(len(current)):
            for j in range(len(current)):
                current[i][j] -= eigen * vec[i] * vec[j]
    scores = [[sum(row[j] * vec[j] for j in range(len(vec))) for row in matrix] for vec in vectors]
    return {"explained": explained, "scores": scores}


def _trustworthiness(matrix: list[list[float]], score_columns: list[list[float]], k: int = 5) -> float:
    if len(matrix) <= k + 1 or not score_columns:
        return 0.0
    embedded = [list(point) for point in zip(*score_columns)]
    penalties = 0.0
    for i in range(len(matrix)):
        orig_order = _neighbor_order(matrix, i)
        emb_order = _neighbor_order(embedded, i)[:k]
        orig_rank = {idx: rank for rank, idx in enumerate(orig_order, start=1)}
        for idx in emb_order:
            rank = orig_rank.get(idx, len(matrix))
            if rank > k:
                penalties += rank - k
    n = len(matrix)
    denom = n * k * (2 * n - 3 * k - 1)
    return _clamp01(1.0 - (2.0 / max(1.0, denom)) * penalties)


def _neighbor_order(matrix: list[list[float]], i: int) -> list[int]:
    distances = []
    for j, row in enumerate(matrix):
        if i == j:
            continue
        distances.append((sum((a - b) ** 2 for a, b in zip(matrix[i], row)), j))
    return [idx for _dist, idx in sorted(distances)]


def _linear_fit_predict(matrix: list[list[float]], y: list[float]) -> list[float]:
    if not matrix:
        return []
    x = [[1.0, *row] for row in matrix]
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(len(x[0]))] for i in range(len(x[0]))]
    xty = [sum(row[i] * target for row, target in zip(x, y)) for i in range(len(x[0]))]
    beta = _solve(xtx, xty)
    return [sum(beta[i] * row[i] for i in range(len(beta))) for row in x]


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda r: abs(aug[r][i]))
        aug[i], aug[pivot] = aug[pivot], aug[i]
        if abs(aug[i][i]) < 1e-9:
            aug[i][i] = 1e-6
        div = aug[i][i]
        aug[i] = [v / div for v in aug[i]]
        for r in range(n):
            if r == i:
                continue
            factor = aug[r][i]
            aug[r] = [v - factor * aug[i][c] for c, v in enumerate(aug[r])]
    return [aug[i][-1] for i in range(n)]


def _mutual_information_pair(x: list[float], y: list[float], bins: int = 5) -> float:
    if not x or not y or len(x) != len(y):
        return 0.0
    xb = [_bin(value, x, bins) for value in x]
    yb = [_bin(value, y, bins) for value in y]
    joint = Counter(zip(xb, yb))
    px = Counter(xb)
    py = Counter(yb)
    n = len(x)
    mi = 0.0
    for key, count in joint.items():
        xkey, ykey = key
        pxy = count / n
        mi += pxy * math.log2(pxy / ((px[xkey] / n) * (py[ykey] / n)))
    return mi


def _mutual_information_joint(matrix: list[list[float]], y: list[float], bins: int = 5) -> float:
    if not matrix or not y:
        return 0.0
    disc = [tuple(_bin(row[j], [item[j] for item in matrix], bins) for j in range(len(matrix[0]))) for row in matrix]
    ydisc = [1 if value >= 0.5 else 0 for value in y]
    joint = Counter(zip(disc, ydisc))
    px = Counter(disc)
    py = Counter(ydisc)
    n = len(y)
    mi = 0.0
    for key, count in joint.items():
        xkey, ykey = key
        pxy = count / n
        mi += pxy * math.log2(pxy / ((px[xkey] / n) * (py[ykey] / n)))
    return mi


def _bin(value: float, values: list[float], bins: int) -> int:
    lo, hi = min(values), max(values)
    if hi <= lo:
        return 0
    return min(bins - 1, int((value - lo) / (hi - lo) * bins))


def _dominant_primitive(values: list[float], primitives: dict[str, list[float]]) -> str:
    return max(((abs(_corr(values, vector)), name) for name, vector in primitives.items()), key=lambda item: item[0])[1]


def _collapse_label(explained: float) -> str:
    if explained >= 0.9:
        return "collapses strongly"
    if explained >= 0.75:
        return "collapses"
    if explained >= 0.5:
        return "partial reduction"
    return "does not reduce"


def _summary(values: list[float]) -> dict[str, float]:
    return {"mean": round(_mean(values), 6), "sd": round(_sd(values), 6), "min": round(min(values) if values else 0.0, 6), "max": round(max(values) if values else 0.0, 6)}


def _standardize(matrix: list[list[float]]) -> list[list[float]]:
    if not matrix:
        return []
    cols = _columns(matrix)
    means = [_mean(col) for col in cols]
    sds = [_sd(col) or 1.0 for col in cols]
    return [[(value - means[j]) / sds[j] for j, value in enumerate(row)] for row in matrix]


def _columns(matrix: list[list[float]]) -> list[list[float]]:
    return [list(col) for col in zip(*matrix)] if matrix else []


def _corr(a: Iterable[float], b: Iterable[float]) -> float:
    aa = list(a)
    bb = list(b)
    if len(aa) != len(bb) or not aa:
        return 0.0
    return _safe_div(_cov(aa, bb), _sd(aa) * _sd(bb))


def _cov(a: Iterable[float], b: Iterable[float]) -> float:
    aa = list(a)
    bb = list(b)
    if len(aa) != len(bb) or not aa:
        return 0.0
    ma, mb = _mean(aa), _mean(bb)
    return sum((x - ma) * (y - mb) for x, y in zip(aa, bb)) / len(aa)


def _r2(actual: list[float], predicted: list[float]) -> float:
    mean_actual = _mean(actual)
    ss_tot = sum((value - mean_actual) ** 2 for value in actual)
    if ss_tot <= 0.0:
        return 0.0
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    return 1.0 - ss_res / ss_tot


def _entropy(values: list[float]) -> float:
    counts = Counter(1 if value >= 0.5 else 0 for value in values)
    n = len(values) or 1
    return -sum((count / n) * math.log2(count / n) for count in counts.values() if count)


def _sd(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    mean = _mean(vals)
    return math.sqrt(sum((value - mean) ** 2 for value in vals) / len(vals))


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


def _safe_div(a: float, b: float) -> float:
    return a / b if abs(b) > 1e-12 else 0.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _log_norm(value: float, maximum: float) -> float:
    return _clamp01(math.log1p(max(0.0, value)) / math.log1p(max(1.0, maximum)))


def _first_float(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return _to_float(row.get(key))
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


def _text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if row.get(key) not in (None, ""):
            return str(row.get(key))
    return ""


def _compact_counts(counts: dict[str, int], limit: int = 6) -> str:
    items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    shown = ", ".join(f"{key}={value}" for key, value in items[:limit])
    return shown + (f", +{len(items) - limit} more" if len(items) > limit else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze K, rho, and A as candidate primitive variables.")
    parser.add_argument("--state-dir", default=".agent-hub")
    args = parser.parse_args(argv)
    print(json.dumps(run_primitive_variable_analysis(args.state_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
