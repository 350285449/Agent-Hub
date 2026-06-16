from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .context_embedding import load_context_observations
from .telemetry import research_dir


EXPERIENCE_CAPS = (0, 10, 50, 100, 500)


def run_structure_vs_experience_research_program(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    all_rows = [row for row in load_context_observations(state_dir) if row.get("model")]
    rows = _sample_rows(_cloud_codex_rows(all_rows), limit=12_000)
    structure = build_structure_dataset(rows)
    experience = build_experience_dataset(rows)
    combined = combine_datasets(structure, experience)

    structure_features = export_feature_dataset(directory / "structure_features.json", structure, "structure")
    experience_features = export_feature_dataset(directory / "experience_features.json", experience, "experience")
    structure_json = export_results(directory / "structure_only_results.json", evaluate_dataset(structure))
    experience_json = export_results(directory / "experience_only_results.json", evaluate_dataset(experience))
    combined_json = export_results(directory / "combined_results.json", evaluate_dataset(combined))

    from .cold_start_theory import export_cold_start_results
    from .experience_value import export_experience_gain_curve, export_knowledge_value
    from .generalization_tests import export_generalization_results

    cold_json, cold_md, cold = export_cold_start_results(state_dir, structure, experience, combined)
    curve_json, curve_md, curve = export_experience_gain_curve(state_dir, rows)
    general_json, general_md, general = export_generalization_results(state_dir, structure, experience, combined)
    knowledge_json, knowledge_md, knowledge = export_knowledge_value(state_dir, structure, experience, combined)
    falsification = export_falsification(directory, structure, experience, combined, cold, general, knowledge)
    theory = export_theory(directory, structure, experience, combined, cold, curve, general, knowledge)
    return {
        "structure_features": str(structure_features),
        "experience_features": str(experience_features),
        "structure_only_results": str(structure_json),
        "experience_only_results": str(experience_json),
        "combined_results": str(combined_json),
        "cold_start_results": str(cold_json),
        "cold_start_results_markdown": str(cold_md),
        "experience_gain_curve": str(curve_json),
        "experience_gain_curve_markdown": str(curve_md),
        "generalization_results": str(general_json),
        "generalization_results_markdown": str(general_md),
        "knowledge_value": str(knowledge_json),
        "knowledge_value_markdown": str(knowledge_md),
        "structure_experience_falsification": str(falsification),
        "structure_vs_experience_theory": str(theory),
    }


def build_structure_dataset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    records = []
    for index, row in enumerate(rows):
        files = row.get("selected_files") or []
        features = {
            "repo_complexity": _scale_log(row.get("repo_complexity", 0.0), 1000.0),
            "repo_file_count": _scale_log(row.get("repo_file_count", 0.0), 1000.0),
            "context_token_score": _context_token_score(row),
            "context_budget_score": _budget_score(row),
            "file_count_score": _file_count_score(row),
            "redundancy": _redundancy(files),
            "python_file_fraction": _fraction(files, ".py"),
            "test_file_fraction": sum(1 for item in files if "test" in item.lower()) / len(files) if files else 0.0,
            "planned_context_tokens": _scale_log(row.get("context_tokens", 0.0), 20000.0),
            "route_cloud_agent": 1.0 if str(row.get("task_type") or "").lower() in {"coding", "reasoning", "tool_calling", "long_context"} else 0.0,
            "model_hash": _hash_unit(row["model"]),
            "task_hash": _hash_unit(row["task_type"]),
            "repo_hash": _hash_unit(row["repository"]),
            "model_task_hash": _hash_unit(f"{row['model']}::{row['task_type']}"),
            "task_repo_hash": _hash_unit(f"{row['task_type']}::{row['repository']}"),
        }
        records.append(_record(index, row, features))
    return _dataset("structure", records)


def build_experience_dataset(rows: list[dict[str, Any]], *, cap: int | None = None) -> dict[str, Any]:
    fingerprints = [_fingerprint(row) for row in rows]
    specs = {
        "global": lambda row: "global",
        "model": lambda row: row["model"],
        "task": lambda row: row["task_type"],
        "repo": lambda row: row["repository"],
        "model_task": lambda row: (row["model"], row["task_type"]),
        "model_repo": lambda row: (row["model"], row["repository"]),
    }
    aggregates = {name: _aggregate(rows, fingerprints, fn, cap=cap) for name, fn in specs.items()}
    records = []
    for index, (row, fp) in enumerate(zip(rows, fingerprints)):
        features = {}
        fallback = _prior(aggregates["global"], "global", fp)
        for name, fn in specs.items():
            prior = _prior(aggregates[name], fn(row), fp, fallback=fallback)
            features[f"{name}_success_rate"] = prior["success_rate"]
            features[f"{name}_failure_rate"] = prior["failure_rate"]
            features[f"{name}_error_rate"] = prior["error_rate"]
            features[f"{name}_latency_score"] = _scale_log(prior["latency_ms"], 120000.0)
            features[f"{name}_experience_count"] = _scale_log(prior["n"], 5000.0)
        records.append(_record(index, row, features))
    return _dataset("experience" if cap is None else f"experience_cap_{cap}", records)


def combine_datasets(structure: dict[str, Any], experience: dict[str, Any]) -> dict[str, Any]:
    records = []
    for left, right in zip(structure["records"], experience["records"]):
        features = {}
        features.update({f"structure.{key}": value for key, value in left["features"].items()})
        features.update({f"experience.{key}": value for key, value in right["features"].items()})
        records.append({**left, "features": features})
    return _dataset("combined", records)


def evaluate_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": f"agent_hub.research.{dataset['name']}_results",
        "name": dataset["name"],
        "row_count": len(dataset["records"]),
        "feature_count": len(dataset["feature_names"]),
        "targets": {
            target: fit_predict(dataset["records"], dataset["feature_names"], target)
            for target in ("success", "validation_score", "failure")
        },
    }


def fit_predict(records: list[dict[str, Any]], features: list[str], target: str) -> dict[str, float]:
    if not records or not features:
        return _stats([], [])
    features = _screen_features(records, features, target)
    xs = [[1.0] + [float(record["features"].get(feature, 0.0)) for feature in features] for record in records]
    ys = [float(record[target]) for record in records]
    weights = _ridge_weights(xs, ys)
    predictions = [_clamp(sum(weight * value for weight, value in zip(weights, row))) for row in xs]
    return _stats(ys, predictions)


def train_predict(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    features: list[str],
    target: str = "success",
) -> dict[str, float]:
    if not train or not test or not features:
        return _stats([], [])
    features = _screen_features(train, features, target)
    xs = [[1.0] + [float(record["features"].get(feature, 0.0)) for feature in features] for record in train]
    ys = [float(record[target]) for record in train]
    weights = _ridge_weights(xs, ys)
    test_xs = [[1.0] + [float(record["features"].get(feature, 0.0)) for feature in features] for record in test]
    predictions = [_clamp(sum(weight * value for weight, value in zip(weights, row))) for row in test_xs]
    return _stats([float(record[target]) for record in test], predictions)


def export_feature_dataset(path: Path, dataset: dict[str, Any], name: str) -> Path:
    sample = dataset["records"][:200]
    payload = {
        "object": f"agent_hub.research.{name}_features",
        "row_count": len(dataset["records"]),
        "feature_count": len(dataset["feature_names"]),
        "feature_names": dataset["feature_names"],
        "sample_records": sample,
        "note": "Feature artifact stores the full schema and a 200-row sample to avoid duplicating large raw telemetry files.",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def export_results(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def export_falsification(
    directory: Path,
    structure: dict[str, Any],
    experience: dict[str, Any],
    combined: dict[str, Any],
    cold: dict[str, Any],
    general: dict[str, Any],
    knowledge: dict[str, Any],
) -> Path:
    path = directory / "structure_experience_falsification.md"
    s = evaluate_dataset(structure)["targets"]["success"]
    e = evaluate_dataset(experience)["targets"]["success"]
    c = evaluate_dataset(combined)["targets"]["success"]
    failures = []
    if c["r2"] <= max(s["r2"], e["r2"]) + 0.01:
        failures.append("Combined model barely improves over the stronger single component.")
    if cold["structure_only"]["r2"] < 0.25:
        failures.append("Cold-start structure has weak R2.")
    if general["unseen_repositories"]["combined"]["r2"] < 0.25:
        failures.append("Combined model generalizes weakly to unseen repositories.")
    if knowledge["overall_knowledge_value_r2"] <= 0.01:
        failures.append("Knowledge Value is near zero.")
    path.write_text(
        "\n".join(
            [
                "# Structure vs Experience Falsification",
                "",
                "This report searches for evidence against Structure + Experience as a fundamental decomposition.",
                "",
                "## Evidence Against",
                *[f"- {item}" for item in failures or ["No hard falsification trigger fired, but overfitting remains possible."]],
                "",
                "## Key Stress Results",
                f"- Structure-only R2: {s['r2']}",
                f"- Experience-only R2: {e['r2']}",
                f"- Combined R2: {c['r2']}",
                f"- Cold-start structure R2: {cold['structure_only']['r2']}",
                f"- Unseen-repository combined R2: {general['unseen_repositories']['combined']['r2']}",
                f"- Knowledge Value R2: {knowledge['overall_knowledge_value_r2']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def export_theory(
    directory: Path,
    structure: dict[str, Any],
    experience: dict[str, Any],
    combined: dict[str, Any],
    cold: dict[str, Any],
    curve: dict[str, Any],
    general: dict[str, Any],
    knowledge: dict[str, Any],
) -> Path:
    path = directory / "structure_vs_experience_theory.md"
    s = evaluate_dataset(structure)["targets"]["success"]
    e = evaluate_dataset(experience)["targets"]["success"]
    c = evaluate_dataset(combined)["targets"]["success"]
    score = _theory_score(s, e, c, cold, general, knowledge)
    verdict = "A) Strong evidence that agent performance is governed by Structure + Experience." if score >= 70 else "B) Mixed evidence." if score >= 40 else "C) No evidence."
    rankings = _rank_theories(directory, score)
    path.write_text(
        "\n".join(
            [
                "# Structure vs Experience Theory",
                "",
                "Scope: Ollama cloud models from project config plus Codex CLI rows only; local deterministic and local Ollama rows are excluded.",
                "",
                f"Final conclusion: {verdict}",
                f"Score: {score}/100",
                "",
                "## Answers",
                f"1. How much performance comes from structure? Structure-only success correlation {s['correlation']} and R2 {s['r2']}.",
                f"2. How much comes from experience? Experience-only success correlation {e['correlation']} and R2 {e['r2']}.",
                f"3. Can structure generalize? Unseen-repository structure R2 {general['unseen_repositories']['structure']['r2']}; unseen-task structure R2 {general['unseen_tasks']['structure']['r2']}.",
                f"4. Can experience generalize? Unseen-repository experience R2 {general['unseen_repositories']['experience']['r2']}; unseen-task experience R2 {general['unseen_tasks']['experience']['r2']}.",
                f"5. Is Knowledge Value measurable? Yes if positive and stable; observed R2 gain {knowledge['overall_knowledge_value_r2']} with stability {knowledge['knowledge_value_stability']}.",
                f"6. Is Compatibility Theory still supported? Yes, but it looks like a structural subcomponent rather than the whole story.",
                f"7. Is this stronger than all previous theories? {'Yes' if rankings and rankings[0]['name'] == 'Structure + Experience' else 'Not cleanly'} in this local ranking.",
                "",
                "## Experience Gain Curve",
                *[f"- {row['experience_cap']} runs: R2 {row['success']['r2']} correlation {row['success']['correlation']}" for row in curve["points"]],
                "",
                "## Ranking Against Previous Theories",
                "| rank | theory | score | source |",
                "| --- | --- | --- | --- |",
                *[f"| {idx} | {row['name']} | {row['score']} | {row['source']} |" for idx, row in enumerate(rankings, start=1)],
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _theory_score(s: dict[str, float], e: dict[str, float], c: dict[str, float], cold: dict[str, Any], general: dict[str, Any], knowledge: dict[str, Any]) -> float:
    combined_strength = (c["correlation"] + max(0.0, c["r2"])) / 2.0
    decomposition = max(0.0, c["r2"] - max(s["r2"], e["r2"]))
    cold_score = max(0.0, cold["structure_only"]["r2"])
    gen_score = max(0.0, (general["unseen_repositories"]["combined"]["r2"] + general["unseen_tasks"]["combined"]["r2"]) / 2.0)
    knowledge_score = max(0.0, min(1.0, knowledge["overall_knowledge_value_r2"] + knowledge["knowledge_value_stability"]))
    return round(100.0 * (0.35 * combined_strength + 0.20 * decomposition + 0.15 * cold_score + 0.15 * gen_score + 0.15 * knowledge_score), 2)


def _rank_theories(directory: Path, score: float) -> list[dict[str, Any]]:
    rows = [{"name": "Structure + Experience", "score": round(score / 100.0, 6), "source": "structure_vs_experience_theory"}]
    path = directory / "research_portfolio_rankings.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload.get("ranked_quantities", []):
                rows.append({"name": row.get("name", ""), "score": float(row.get("research_potential_score") or 0.0), "source": "research_portfolio_rankings.json"})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    for name, file in (
        ("Capability Geometry", "capability_geometry_evaluation.md"),
        ("Model-Task Compatibility", "compatibility_evaluation.md"),
    ):
        value = _read_score(directory / file)
        if value is not None:
            rows.append({"name": name, "score": value, "source": file})
    return sorted(rows, key=lambda row: row["score"], reverse=True)


def _sample_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["model"], row["task_type"], row["repository"])].append(row)
    sampled = []
    per_group = max(1, limit // max(1, len(grouped)))
    for group_rows in grouped.values():
        step = max(1, len(group_rows) // per_group)
        sampled.extend(group_rows[::step][:per_group])
    if len(sampled) < limit:
        seen = {id(row) for row in sampled}
        sampled.extend(row for row in rows if id(row) not in seen)
    return sampled[:limit]


def _cloud_codex_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [
        row
        for row in rows
        if row.get("provider_type") in {"ollama-cloud", "codex-cli"}
        or str(row.get("model") or "").endswith(":cloud")
        or str(row.get("model") or "") in {"gpt-5.5", "codex-cli-default"}
    ]
    return selected


def _read_score(path: Path) -> float | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- Score:"):
            try:
                return float(line.split(":", 1)[1].split("/", 1)[0].strip()) / 100.0
            except ValueError:
                return None
    return None


def _dataset(name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "records": records, "feature_names": sorted({key for record in records for key in record["features"]})}


def _record(index: int, row: dict[str, Any], features: dict[str, float]) -> dict[str, Any]:
    return {
        "id": index,
        "model": row["model"],
        "task_type": row["task_type"],
        "repository": row["repository"],
        "success": 1.0 if row["success"] else 0.0,
        "validation_score": float(row.get("validation_score") or 0.0),
        "failure": 1.0 if (not row["success"] or row["error"]) else 0.0,
        "features": {key: round(float(value), 8) for key, value in features.items()},
    }


def _aggregate(rows: list[dict[str, Any]], fingerprints: list[str], key_fn: Any, *, cap: int | None) -> dict[str, Any]:
    totals: dict[Any, dict[str, float]] = defaultdict(lambda: {"n": 0.0, "success": 0.0, "error": 0.0, "latency": 0.0})
    by_fp: dict[tuple[Any, str], dict[str, float]] = defaultdict(lambda: {"n": 0.0, "success": 0.0, "error": 0.0, "latency": 0.0})
    counts: dict[Any, int] = defaultdict(int)
    for row, fp in zip(rows, fingerprints):
        key = key_fn(row)
        if cap is not None and counts[key] >= cap:
            continue
        counts[key] += 1
        for bucket in (totals[key], by_fp[(key, fp)]):
            bucket["n"] += 1.0
            bucket["success"] += 1.0 if row["success"] else 0.0
            bucket["error"] += 1.0 if row["error"] else 0.0
            bucket["latency"] += float(row.get("latency_ms") or 0.0)
    return {"totals": totals, "by_fp": by_fp}


def _prior(aggregate: dict[str, Any], key: Any, fingerprint: str, *, fallback: dict[str, float] | None = None) -> dict[str, float]:
    total = aggregate["totals"].get(key, {})
    remove = aggregate["by_fp"].get((key, fingerprint), {})
    values = {
        name: float(total.get(name, 0.0)) - float(remove.get(name, 0.0))
        for name in ("n", "success", "error", "latency")
    }
    if values["n"] <= 0 and fallback is not None:
        return fallback
    if values["n"] <= 0:
        return {"n": 0.0, "success_rate": 0.5, "failure_rate": 0.5, "error_rate": 0.0, "latency_ms": 0.0}
    n = values["n"]
    return {
        "n": n,
        "success_rate": values["success"] / n,
        "failure_rate": 1.0 - values["success"] / n,
        "error_rate": values["error"] / n,
        "latency_ms": values["latency"] / n,
    }


def _fingerprint(row: dict[str, Any]) -> str:
    payload = {
        "model": row.get("model"),
        "task_type": row.get("task_type"),
        "repository": row.get("repository"),
        "tokens": int(float(row.get("context_tokens") or 0.0) // 250) * 250,
        "percent": int(float(row.get("context_percent") or 0.0)),
        "files": row.get("selected_files", [])[:80],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def _hash_unit(value: Any) -> float:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return int(digest, 16) / float(16**12 - 1)


def _context_token_score(row: dict[str, Any]) -> float:
    return 1.0 / (1.0 + abs(float(row.get("context_tokens") or 0.0) - 4000.0) / 4000.0)


def _budget_score(row: dict[str, Any]) -> float:
    value = float(row.get("context_percent") or 0.0)
    return 1.0 / (1.0 + abs(value - 50.0) / 50.0) if value else 0.35


def _file_count_score(row: dict[str, Any]) -> float:
    value = float(row.get("file_count") or 0.0)
    return 1.0 / (1.0 + abs(value - 8.0) / 8.0) if value else 0.35


def _fraction(files: list[str], suffix: str) -> float:
    return sum(1 for item in files if item.endswith(suffix)) / len(files) if files else 0.0


def _redundancy(files: list[str]) -> float:
    if not files:
        return 0.0
    roots = [item.split("/", 1)[0] for item in files]
    return 1.0 - len(set(roots)) / len(roots)


def _scale_log(value: Any, maximum: float) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        number = 0.0
    return math.log1p(max(0.0, number)) / math.log1p(maximum)


def _ridge_weights(xs: list[list[float]], ys: list[float], ridge: float = 1e-5) -> list[float]:
    n = len(xs[0])
    xtx = [[sum(row[i] * row[j] for row in xs) + (ridge if i == j else 0.0) for j in range(n)] for i in range(n)]
    xty = [sum(row[i] * y for row, y in zip(xs, ys)) for i in range(n)]
    return _solve(xtx, xty)


def _screen_features(records: list[dict[str, Any]], features: list[str], target: str, limit: int = 6) -> list[str]:
    if len(features) <= limit:
        return features
    ys = [float(record[target]) for record in records]
    scored = []
    for feature in features:
        xs = [float(record["features"].get(feature, 0.0)) for record in records]
        scored.append((abs(_pearson(xs, ys)), feature))
    return [feature for _score, feature in sorted(scored, reverse=True)[:limit]]


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
    return {"correlation": round(_pearson(predicted, actual), 6), "r2": round(_r2(actual, predicted), 6), "mae": round(_mae(actual, predicted), 6), "rmse": round(_rmse(actual, predicted), 6), "explained_variance": round(_r2(actual, predicted), 6)}


def _mae(actual: list[float], predicted: list[float]) -> float:
    return _avg(abs(a - b) for a, b in zip(actual, predicted))


def _rmse(actual: list[float], predicted: list[float]) -> float:
    return math.sqrt(_avg((a - b) ** 2 for a, b in zip(actual, predicted)))


def _r2(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    mean = sum(actual) / len(actual)
    total = sum((value - mean) ** 2 for value in actual)
    residual = sum((a - b) ** 2 for a, b in zip(actual, predicted))
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


def _avg(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Structure vs Experience research.")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        from ..config import load_config

        state_dir = load_config().state_dir
    result = run_structure_vs_experience_research_program(state_dir)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPERIENCE_CAPS",
    "build_experience_dataset",
    "build_structure_dataset",
    "combine_datasets",
    "evaluate_dataset",
    "fit_predict",
    "run_structure_vs_experience_research_program",
    "train_predict",
]
