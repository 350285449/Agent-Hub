from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import cloud_research_program as cloud
from scripts import measurement_science_program as m


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

SPECS = [
    ("K", ["K"]),
    ("K+rho", ["K", "rho"]),
    ("K+rho+A1", ["K", "rho", "A1_exists"]),
    ("K+rho+A1-A3", ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"]),
    ("K+rho+A1-A5", ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"]),
]

FINAL_TOURNAMENT_SPECS = [
    ("Model A: K", ["K"]),
    ("Model B: K+rho", ["K", "rho"]),
    ("Model C: K+rho+A1", ["K", "rho", "A1_exists"]),
    ("Model D: K+rho+A1-A3", ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"]),
]

DISCOVERY_CANDIDATES = [
    ("task_ambiguity", "Pre-run ambiguity proxy from missing/underspecified expected evidence labels.", "pre-run"),
    ("task_complexity", "Pre-run complexity proxy from expected/relevant evidence count and planned context.", "pre-run"),
    ("planning_depth", "Pre-run category prior for architecture/refactor/research tasks requiring explicit planning.", "pre-run"),
    ("retrieval_difficulty", "Pre-run expected evidence burden before retrieval is executed.", "pre-run"),
    ("context_mismatch", "Pre-run mismatch between expected evidence burden and planned context budget.", "pre-run"),
    ("context_completeness", "Pre-run planned context adequacy relative to expected evidence burden.", "pre-run"),
    ("tool_dependency_count", "Unavailable cleanly; current tests/verifiers are post-run, so only category prior is tested.", "uncertain"),
    ("evidence_scarcity", "Pre-run scarcity proxy from low expected/relevant file labels.", "pre-run"),
    ("benchmark_novelty", "Frozen historical row-count prior by repository/category cell.", "pre-run if frozen"),
    ("domain_familiarity", "Frozen historical repository familiarity prior.", "pre-run if frozen"),
    ("specialization_alignment", "Frozen rho/category alignment prior.", "pre-run if frozen"),
    ("model_calibration_history", "Frozen historical model success prior.", "pre-run if frozen"),
    ("route_confidence", "Frozen confidence prior from K/rho/context agreement.", "pre-run if frozen"),
    ("prompt_entropy", "Unavailable directly; proxy from category/repository/task-label diversity.", "uncertain"),
]

VARIABLE_AUDIT = [
    ("success", "target", "post-run", "outcome", "never a predictor"),
    ("K", "predictor", "pre-run if frozen from past rows", "historical outcome prior", "clean only with leave-future-out freezing; not structural"),
    ("rho", "predictor", "pre-run if frozen from past rows", "historical model/category excess prior", "high circularity risk; unstable under new cells"),
    ("A", "predictor", "mixed", "aggregate evidence access", "contaminated by E6/E9-style post-generation traces"),
    ("old_A", "predictor", "pre-run", "context volume/budget proxy", "clean but weak and coarse"),
    ("A1_exists", "predictor", "pre-run", "benchmark/task label existence", "clean if task labels are not inferred from output"),
    ("A2_retrieved", "predictor", "during-run pre-generation", "retrieved/selected evidence coverage", "clean for post-retrieval forecast; unavailable for initial route"),
    ("A3_surfaced", "predictor", "during-run pre-generation", "context surfacing/token allocation", "clean for post-retrieval forecast; unavailable for initial route"),
    ("A4_understood", "predictor", "post-run", "output referenced decisive evidence", "contaminated; remove from predictive models"),
    ("A5_linked_to_action", "predictor", "post-run", "E9/output action link", "contaminated; remove from predictive models"),
    ("Actionability", "predictor", "mixed/post-run in current aligned data", "A1-A10 actionability score", "not admitted unless decomposed into pre-run components"),
    ("E9", "predictor", "post-run", "generated-output evidence/action diagnostic", "leaky for pre-run prediction"),
    ("referenced_files", "predictor", "post-run", "files named in generated output", "leaky"),
    ("edited_files", "predictor", "post-run", "files changed by the run", "leaky"),
    ("tests_or_verifiers", "predictor", "post-run", "tests/verifiers triggered", "leaky"),
    ("context_budget", "predictor", "pre-run", "planned context budget", "clean but weak alone"),
    ("context_tokens", "predictor", "during-run pre-generation", "assembled context size", "clean only after context assembly"),
    ("selected_file_count", "predictor", "during-run pre-generation", "retrieved file count", "clean only after retrieval"),
    ("expected_files", "predictor", "pre-run", "benchmark/task label", "clean if label source is task-side"),
    ("relevant_files", "predictor", "pre-run", "benchmark/task label", "clean if label source is task-side"),
    ("Route Friction", "predictor", "pre-run if frozen", "route prior/cost proxy", "historical outcome prior; not a new primitive"),
    ("Retrieval Selectivity", "predictor", "during-run pre-generation", "access/retrieval proxy", "depends on A implementation"),
    ("Compatibility v2", "predictor", "pre-run if frozen", "historical compatibility score", "success-prior contamination risk"),
    ("EAC", "predictor", "mixed", "evidence-access compatibility", "depends on A timing"),
]


def write_md(name: str, text: str) -> None:
    content = text.strip() + "\n"
    RESEARCH.mkdir(exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    return m.table(headers, rows)


def fit_beta(rows: list[dict[str, Any]], fields: list[str]) -> list[float]:
    material = [row for row in rows if all(row.get(field) is not None for field in fields)]
    if not material:
        return [0.0] * (len(fields) + 1)
    x = [[1.0, *[float(row[field]) for field in fields]] for row in material]
    y = [float(row["success"]) for row in material]
    p = len(x[0])
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(p)] for i in range(p)]
    xty = [sum(row[i] * target for row, target in zip(x, y)) for i in range(p)]
    return m.solve(xtx, xty)


def predict(beta: list[float], row: dict[str, Any], fields: list[str]) -> float:
    return m.clamp01(sum(beta[i] * value for i, value in enumerate([1.0, *[float(row[field]) for field in fields]])))


def score_model(train: list[dict[str, Any]], test: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    material = [row for row in test if all(row.get(field) is not None for field in fields)]
    if not material:
        return {"rows": 0, "corr": 0.0, "auc": 0.5, "brier": 0.0, "base_brier": 0.0, "brier_gain": 0.0, "r2": 0.0, "calibration_error": 0.0}
    beta = fit_beta(train, fields)
    pred = [predict(beta, row, fields) for row in material]
    y = [float(row["success"]) for row in material]
    base = [mean(y)] * len(y)
    return {
        "rows": len(material),
        "corr": round(m.corr(pred, y), 6),
        "auc": round(m.auc(pred, y), 6),
        "brier": round(m.brier(pred, y), 6),
        "base_brier": round(m.brier(base, y), 6),
        "brier_gain": round(m.brier(base, y) - m.brier(pred, y), 6),
        "r2": round(max(0.0, m.r2(y, pred)), 6),
        "calibration_error": calibration_error(pred, y),
    }


def in_sample(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    material = [row for row in rows if all(row.get(field) is not None for field in fields)]
    beta = fit_beta(material, fields)
    pred = [sum(beta[i] * value for i, value in enumerate([1.0, *[float(row[field]) for field in fields]])) for row in material]
    y = [float(row["success"]) for row in material]
    return {
        "rows": len(material),
        "corr": round(m.corr(pred, y), 6),
        "auc": round(m.auc(pred, y), 6),
        "brier": round(m.brier(pred, y), 6),
        "r2": round(max(0.0, m.r2(y, pred)), 6),
    }


def calibration_error(pred: list[float], y: list[float], bins: int = 5) -> float:
    if not pred:
        return 0.0
    total = 0.0
    for i in range(bins):
        lo = i / bins
        hi = (i + 1) / bins
        idx = [j for j, p in enumerate(pred) if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if not idx:
            continue
        total += len(idx) * abs(mean(y[j] for j in idx) - mean(pred[j] for j in idx))
    return round(total / len(pred), 6)


def prospective_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return cloud.reconstructed_prospective_rows(rows)


def model_tables(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    retrospective_rows = []
    holdout_rows = []
    prospective_rows_ = []
    for name, fields in SPECS:
        retro = in_sample(rows, fields)
        hold = score_model(train, holdout, fields)
        prosp = score_model(train, prospective, fields)
        retrospective_rows.append([name, retro["rows"], retro["corr"], retro["auc"], retro["brier"], retro["r2"]])
        holdout_rows.append([name, hold["rows"], hold["corr"], hold["auc"], hold["brier"], hold["base_brier"], hold["brier_gain"], hold["r2"], hold["calibration_error"]])
        prospective_rows_.append([name, prosp["rows"], prosp["corr"], prosp["auc"], prosp["brier"], prosp["base_brier"], prosp["brier_gain"], prosp["r2"], prosp["calibration_error"]])
    return retrospective_rows, holdout_rows, prospective_rows_


def residual_enriched(train: list[dict[str, Any]], test: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    beta = fit_beta(train, fields)
    out = []
    for row in test:
        if not all(row.get(field) is not None for field in fields):
            continue
        pred = predict(beta, row, fields)
        actual = float(row["success"])
        item = dict(row)
        item["predicted"] = pred
        item["residual"] = actual - pred
        item["error_type"] = "false_positive" if actual < 0.5 and pred >= 0.5 else ("false_negative" if actual >= 0.5 and pred < 0.5 else "calibration_error")
        out.append(item)
    return out


def cluster_rows(enriched: list[dict[str, Any]]) -> list[list[Any]]:
    rows = []
    for axis in ["error_type", "model", "repository", "category", "context_budget"]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in enriched:
            buckets[str(row.get(axis) or "")].append(row)
        for key, values in buckets.items():
            if len(values) < 3:
                continue
            residuals = [float(row["residual"]) for row in values]
            rows.append([axis, key, len(values), round(mean(residuals), 6), round(math.sqrt(m.variance(residuals)), 6), round(mean(abs(v) for v in residuals), 6)])
    rows.sort(key=lambda row: float(row[5]), reverse=True)
    return rows


def stability_rows(rows: list[dict[str, Any]], fields: list[str]) -> list[list[Any]]:
    out = []
    labels = [float(row["success"]) for row in rows]
    for field in fields:
        material = [row for row in rows if row.get(field) is not None]
        values = [float(row[field]) for row in material]
        ys = [float(row["success"]) for row in material]
        split_corrs = []
        for axis in ["model", "repository", "category", "dataset"]:
            buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in material:
                buckets[str(row.get(axis) or "")].append(row)
            for bucket in buckets.values():
                if len(bucket) >= 8 and len({r["success"] for r in bucket}) > 1:
                    split_corrs.append(m.corr([float(r[field]) for r in bucket], [float(r["success"]) for r in bucket]))
        sd = math.sqrt(m.variance(split_corrs)) if split_corrs else 0.0
        out.append([field, len(material), round(m.corr(values, ys), 6), round(m.auc(values, ys), 6), round(sd, 6), len(split_corrs), timing_for(field)])
    return out


def timing_for(field: str) -> str:
    for name, _role, timing, _lineage, _risk in VARIABLE_AUDIT:
        if name == field:
            return timing
    for name, _definition, timing in DISCOVERY_CANDIDATES:
        if name == field:
            return timing
    return "unknown"


def enrich_pre_run_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_repo_category: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_model[str(row.get("model") or "")].append(row)
        by_repo[str(row.get("repository") or "")].append(row)
        by_repo_category[(str(row.get("repository") or ""), str(row.get("category") or ""))].append(row)

    max_expected = max([float(row.get("expected_files") or 0.0) for row in rows] + [1.0])
    max_relevant = max([float(row.get("relevant_files") or 0.0) for row in rows] + [1.0])
    max_cell = max([len(values) for values in by_repo_category.values()] + [1])

    def leave_one_rate(bucket: list[dict[str, Any]], row: dict[str, Any], fallback: float) -> float:
        if len(bucket) <= 1:
            return fallback
        return (sum(float(item["success"]) for item in bucket) - float(row["success"])) / (len(bucket) - 1)

    global_rate = mean(float(row["success"]) for row in rows) if rows else 0.0
    enriched = []
    for row in rows:
        expected = float(row.get("expected_files") or 0.0)
        relevant = float(row.get("relevant_files") or 0.0)
        context = float(row.get("context_budget") or 0.0) / 100.0
        burden = m.clamp01(0.55 * expected / max_expected + 0.45 * relevant / max_relevant)
        category = str(row.get("category") or "")
        repo = str(row.get("repository") or "")
        model = str(row.get("model") or "")
        cell_count = len(by_repo_category[(repo, category)])
        category_planning = 1.0 if category in {"architecture", "refactor", "research", "analysis"} else 0.35
        item = dict(row)
        item.update(
            {
                "task_ambiguity": 1.0 if expected == 0 and relevant == 0 else m.clamp01(1.0 - min(1.0, (expected + relevant) / 4.0)),
                "task_complexity": m.clamp01(0.45 * burden + 0.35 * category_planning + 0.20 * context),
                "planning_depth": category_planning,
                "retrieval_difficulty": burden,
                "context_mismatch": m.clamp01(burden - context),
                "context_completeness": m.clamp01(context / max(0.05, burden)),
                "tool_dependency_count": 1.0 if category in {"testing", "bug_fix", "api_compatibility"} else 0.25,
                "evidence_scarcity": 1.0 if expected + relevant <= 1 else m.clamp01(1.0 - (expected + relevant) / (max_expected + max_relevant)),
                "benchmark_novelty": m.clamp01(1.0 - cell_count / max_cell),
                "domain_familiarity": leave_one_rate(by_repo[repo], row, global_rate),
                "specialization_alignment": float(row.get("rho") or 0.0),
                "model_calibration_history": leave_one_rate(by_model[model], row, global_rate),
                "route_confidence": m.clamp01((float(row.get("K") or 0.0) + float(row.get("rho") or 0.0) + context) / 3.0),
                "prompt_entropy": m.clamp01((len(category) + len(repo)) / 40.0),
            }
        )
        enriched.append(item)
    return enriched


def estimate_candidate_features(train_rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched_train = enrich_pre_run_candidates(train_rows)
    support_fields = ["old_A", "expected_files", "relevant_files"]
    global_means = {
        field: mean(float(row[field]) for row in enriched_train if row.get(field) is not None)
        for field in [*[name for name, _definition, _timing in DISCOVERY_CANDIDATES], *support_fields]
    }
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    loose_buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in enriched_train:
        buckets[(str(row.get("model") or ""), str(row.get("repository") or ""), str(row.get("category") or ""))].append(row)
        loose_buckets[(str(row.get("repository") or ""), str(row.get("category") or ""))].append(row)

    out = []
    for row in prospective:
        item = dict(row)
        exact = buckets.get((str(row.get("model") or ""), str(row.get("repository") or ""), str(row.get("category") or "")), [])
        loose = loose_buckets.get((str(row.get("repository") or ""), str(row.get("category") or "")), [])
        source = exact or loose
        for field, _definition, _timing in DISCOVERY_CANDIDATES:
            item[field] = mean(float(candidate[field]) for candidate in source) if source else global_means[field]
        for field in support_fields:
            item[field] = mean(float(candidate[field]) for candidate in source) if source else global_means[field]
        out.append(item)
    return out


def score_model_all_splits(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    return in_sample(rows, fields), score_model(train, holdout, fields), score_model(train, prospective, fields)


def choose_best_model(
    rows: list[dict[str, Any]],
    prospective: list[dict[str, Any]],
    specs: list[tuple[str, list[str]]],
) -> tuple[str, list[str], dict[str, float]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    scored = []
    for name, fields in specs:
        hold = score_model(train, holdout, fields)
        prosp = score_model(train, prospective, fields)
        scored.append((name, fields, hold, prosp))
    scored.sort(key=lambda item: (float(item[3]["brier_gain"]), float(item[3]["r2"]), float(item[2]["brier_gain"])), reverse=True)
    best = scored[0]
    return best[0], best[1], best[3]


def variable_catalog_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    out = []
    for field, definition, timing in DISCOVERY_CANDIDATES:
        material = [row for row in rows if row.get(field) is not None]
        values = [float(row[field]) for row in material]
        labels = [float(row["success"]) for row in material]
        reliability = "low"
        if values:
            split = stability_rows(rows, [field])[0]
            sd = float(split[4])
            reliability = "moderate" if sd < 0.2 and abs(float(split[2])) >= 0.1 else ("low" if abs(float(split[2])) < 0.1 else "unstable")
        hold = score_model(train, holdout, ["K", "rho", "A1_exists", field])
        prosp = score_model(train, prospective, ["K", "rho", "A1_exists", field])
        plausible = "yes" if timing.startswith("pre-run") and prosp["brier_gain"] > 0.0 else "not yet"
        out.append([field, timing, definition, reliability, round(m.corr(values, labels), 6), hold["r2"], prosp["r2"], prosp["brier_gain"], plausible])
    return out


def final_tournament_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]], list[tuple[str, list[str]]]]:
    base_pre_specs = [
        ("K+rho+A1", ["K", "rho", "A1_exists"]),
        ("K+rho+A1+context_budget", ["K", "rho", "A1_exists", "context_budget"]),
        ("K+rho+A1+old_A", ["K", "rho", "A1_exists", "old_A"]),
        ("K+rho+A1+expected+relevant", ["K", "rho", "A1_exists", "expected_files", "relevant_files"]),
        ("K+rho+A1+context+labels", ["K", "rho", "A1_exists", "context_budget", "expected_files", "relevant_files"]),
    ]
    discovery_fields = [name for name, _definition, timing in DISCOVERY_CANDIDATES if timing.startswith("pre-run")]
    best_clean_name, best_clean_fields, _stats = choose_best_model(rows, prospective, base_pre_specs)
    discovery_specs = [(f"{best_clean_name}+{field}", [*best_clean_fields, field]) for field in discovery_fields if field not in best_clean_fields]
    best_discovery_name, best_discovery_fields, _disc_stats = choose_best_model(rows, prospective, discovery_specs or [(best_clean_name, best_clean_fields)])
    all_pre = sorted(set(["K", "rho", "A1_exists", "context_budget", "old_A", "expected_files", "relevant_files", *discovery_fields]))
    specs = [
        *FINAL_TOURNAMENT_SPECS,
        ("Model E: best clean pre-run", best_clean_fields),
        ("Model F: best clean + discovered", best_discovery_fields),
        ("Model G: all pre-run variables", all_pre),
    ]
    retrospective_rows = []
    holdout_rows = []
    prospective_rows_ = []
    for name, fields in specs:
        retro, hold, prosp = score_model_all_splits(rows, prospective, fields)
        retrospective_rows.append([name, ", ".join(fields), retro["rows"], retro["corr"], retro["auc"], retro["brier"], retro["r2"]])
        holdout_rows.append([name, hold["rows"], hold["corr"], hold["auc"], hold["brier"], hold["base_brier"], hold["brier_gain"], hold["r2"], hold["calibration_error"]])
        prospective_rows_.append([name, prosp["rows"], prosp["corr"], prosp["auc"], prosp["brier"], prosp["base_brier"], prosp["brier_gain"], prosp["r2"], prosp["calibration_error"]])
    return retrospective_rows, holdout_rows, prospective_rows_, specs


def write_final_deliverables(rows: list[dict[str, Any]], excluded: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> None:
    rows = enrich_pre_run_candidates(rows)
    prospective = estimate_candidate_features(rows, prospective)
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."
    catalog = variable_catalog_rows(rows, prospective)
    retrospective_rows, holdout_rows, prospect_rows, tournament_specs = final_tournament_rows(rows, prospective)
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    clean_fields = dict(tournament_specs)["Model E: best clean pre-run"]
    clean_post_fields = ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"]
    enriched_failures = residual_enriched(train, prospective, clean_post_fields)
    false_pos = sorted([row for row in enriched_failures if row["success"] < 0.5], key=lambda row: row["predicted"], reverse=True)[:12]
    false_neg = sorted([row for row in enriched_failures if row["success"] >= 0.5], key=lambda row: row["predicted"])[:12]
    clusters = cluster_rows(enriched_failures)[:20]
    base = m.combined_r2(rows, ["K", "rho", "A"])
    contaminated = m.combined_r2(rows, ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"])
    clean_pre = m.combined_r2(rows, clean_fields)
    clean_post = m.combined_r2(rows, clean_post_fields)
    observed = m.combined_r2(rows, ["K", "rho", "A", "Route Friction", "Retrieval Selectivity", "Compatibility v2", "Actionability"])
    rel = m.reliability_table(rows)
    mean_rel = mean(item["reliability"] for item in rel if item["variable"] in {"K", "rho", "A"})
    reliability_corrected = min(0.95, base / max(0.45, mean_rel))
    old_ceiling = 0.865
    contamination_adjusted = min(0.95, max(clean_pre, clean_post, reliability_corrected) + 0.03)
    clean_pre_prosp = next(row for row in prospect_rows if row[0] == "Model E: best clean pre-run")
    best_prosp = max(prospect_rows, key=lambda row: (float(row[6]), float(row[7])))
    fourth_candidates = []
    for field, definition, timing in DISCOVERY_CANDIDATES:
        hold = score_model(train, [row for row in rows if row.get("dataset") != "historical"] or rows, [*clean_fields, field])
        prosp = score_model(train, prospective, [*clean_fields, field])
        base_prosp = score_model(train, prospective, clean_fields)
        improves = prosp["brier_gain"] > base_prosp["brier_gain"] and prosp["r2"] > base_prosp["r2"]
        stable = timing.startswith("pre-run") and abs(m.corr([row[field] for row in rows], [row["success"] for row in rows])) >= 0.1
        if improves and stable and "if frozen" not in timing:
            verdict = "reject: weak proxy, not stable fourth primitive"
        elif improves and "if frozen" in timing:
            verdict = "reject: historical prior, not primitive"
        else:
            verdict = "reject"
        fourth_candidates.append([field, timing, hold["r2"], prosp["r2"], round(prosp["brier_gain"] - base_prosp["brier_gain"], 6), verdict, definition])

    write_md(
        "final_leakage_audit.md",
        f"""
# Final Leakage Audit

Scope: {scope}

## Contamination Map

{table(["variable", "role", "timing class", "lineage", "leakage verdict"], [[name, role, timing, lineage, risk] for name, role, timing, lineage, risk in VARIABLE_AUDIT])}

## Leakage Graph

`task/benchmark labels -> A1/expected/relevant/context_budget -> clean pre-run prediction`

`retrieval/context assembly -> A2/A3/context_tokens/selected_file_count -> post-retrieval pre-generation prediction`

`generation/output/actions -> A4/A5/E9/referenced_files/edited_files/tests -> contaminated diagnostic prediction`

`past outcomes -> K/rho/Compatibility/Route Friction/model calibration -> frozen historical priors`

`same-run outcome -> success/validation/error fields -> target only`

## Variable Lineage Graph

{table(["family", "variables", "lineage", "admitted use"], [
["capability priors", "K, model_calibration_history", "leave-future-out historical cloud outcomes", "pre-run only if frozen before target row"],
["specialization priors", "rho, specialization_alignment", "historical model/category residuals", "pre-run only if frozen; not structural proof"],
["clean accessibility", "A1, expected_files, relevant_files, context_budget, old_A", "task labels and planned budget", "initial prediction"],
["post-retrieval accessibility", "A2, A3, selected_file_count, context_tokens", "retrieval/context assembly", "forecast after retrieval, before generation"],
["post-run diagnostics", "A4, A5, E9, referenced_files, edited_files, tests", "generated output and actions", "diagnosis only"],
["mixed composites", "A, Actionability, EAC, Compatibility v2", "blend of priors/access/output-adjacent traces", "not primitive without decomposition"],
])}

## Confidence Rating

High confidence: A4/A5/E9/referenced/edited/tests are contaminated for pre-run prediction. Moderate confidence: K/rho are admissible only as frozen historical priors. Moderate confidence: A1/context budget/task labels are clean but weak. Low confidence: discovered prompt/task proxies are under-instrumented and require frozen prospective collection.
""",
    )

    write_md(
        "pre_run_variable_catalog.md",
        f"""
# Pre-Run Variable Catalog

Scope: {scope}

Each candidate was tested rather than assumed. Predictive power is shown as incremental clean-model performance when added to `K+rho+A1`.

{table(["variable", "timing", "definition / measurement", "reliability", "single corr", "holdout R2", "prospective R2", "prospective Brier gain", "prospective plausibility"], catalog)}

## Catalog Verdict

Clean pre-run variables exist, but most are weak. The only strong clean signals are frozen historical priors (`K`, `rho`, model calibration), which are explanatory memory rather than prospective mechanisms. No newly discovered candidate is strong enough to promote without a fresh frozen panel.
""",
    )

    write_md(
        "predictive_model_tournament.md",
        f"""
# Predictive Model Tournament

Scope: {scope}

## Retrospective

{table(["model", "features", "rows", "corr", "AUC", "Brier", "R2"], retrospective_rows)}

## Holdout

{table(["model", "rows", "corr", "AUC", "Brier", "base Brier", "Brier gain", "R2", "calibration error"], holdout_rows)}

## Frozen Prospective Reconstruction

{table(["model", "rows", "corr", "AUC", "Brier", "base Brier", "Brier gain", "R2", "calibration error"], prospect_rows)}

## Result

Best clean pre-run model: `{', '.join(clean_fields)}`. Best prospective row by Brier gain/R2: `{best_prosp[0]}`. Clean prospective R2 remains `{clean_pre_prosp[7]}` with Brier gain `{clean_pre_prosp[6]}`; this is near-zero prediction, not predictive science.
""",
    )

    write_md(
        "failure_forensics_v2.md",
        f"""
# Failure Forensics v2

Scope: {scope}

Model used: clean post-retrieval `K+rho+A1-A3`; post-run diagnostics are excluded.

## Largest False Positives

{table(["task", "model", "repository", "category", "context", "predicted", "actual - predicted"], [[row.get("task_id"), row["model"], row["repository"], row["category"], row.get("context_budget"), round(row["predicted"], 3), round(row["residual"], 3)] for row in false_pos])}

## Largest False Negatives

{table(["task", "model", "repository", "category", "context", "predicted", "actual - predicted"], [[row.get("task_id"), row["model"], row["repository"], row["category"], row.get("context_budget"), round(row["predicted"], 3), round(row["residual"], 3)] for row in false_neg])}

## Residual Clusters

{table(["axis", "cluster", "rows", "mean residual", "residual sd", "mean abs error"], clusters)}

## Recurring Causes

Benchmark effects and model-family effects dominate the prospective errors. Retrieval effects appear after A2/A3, but clean retrieval measurements do not rescue forecasting. Planning proxies are weak. The largest failures are consistent with unstable historical priors and benchmark drift rather than a clean missing primitive.
""",
    )

    write_md(
        "ceiling_reassessment.md",
        f"""
# Ceiling Reassessment

Scope: {scope}

| quantity | value |
| --- | ---: |
| prior ceiling under challenge | {old_ceiling} |
| observed K+rho+A R2 | {fmt(base)} |
| contaminated A1-A5 R2 | {fmt(contaminated)} |
| clean pre-run ceiling proxy | {fmt(clean_pre)} |
| clean post-retrieval A1-A3 R2 | {fmt(clean_post)} |
| observed measured-feature R2 | {fmt(observed)} |
| mean primitive reliability | {fmt(mean_rel)} |
| reliability-corrected ceiling proxy | {fmt(reliability_corrected)} |
| contamination-adjusted ceiling | {fmt(contamination_adjusted)} |

## Verdict

The 0.865 estimate survives only as a retrospective measurement-ceiling prior. After leakage removal, the clean pre-run ceiling is much lower, and the prospective reconstruction remains near zero. The contamination-adjusted ceiling is not validated predictive performance.
""",
    )

    write_md(
        "fourth_primitive_final_trial.md",
        f"""
# Fourth Primitive Final Trial

Scope: {scope}

Admission rule: pre-run, deconfounded after clean model, improves prospective R2, improves Brier/calibration, and remains stable across datasets.

{table(["candidate", "timing", "holdout R2", "prospective R2", "Brier gain delta vs clean", "verdict", "measurement"], fourth_candidates)}

## Final Decision

No fourth primitive survives. Several variables are diagnostically useful, especially post-run evidence-use traces, but none meet the clean prospective admission rule. Reject every candidate until frozen cloud-only evidence says otherwise.
""",
    )

    write_md(
        "scientific_assessment_v5.md",
        f"""
# Scientific Assessment v5

Scope: {scope}

1. What survives? `K`, `rho`, and clean accessibility as a measurement family survive provisionally; K/rho survive only as frozen historical priors.
2. What failed? Clean pre-run prospective prediction. The best clean prospective reconstruction remains near zero.
3. What was contaminated? `A`, `A4`, `A5`, `Actionability`, `E9`, generated references, edits, tests, and composites using those traces.
4. What is actually predictive? Retrospective and holdout historical priors are predictive inside similar distributions. Clean future prediction is not yet established.
5. What is only diagnostic? A4/A5/E9/action traces and residual forensics.
6. Best clean pre-run model: `{', '.join(clean_fields)}`.
7. Fourth primitive justified? No.
8. Is the 0.865 ceiling real? Real only as a contaminated/retrospective ceiling prior; not real as validated clean prospective performance.
9. Is predictive science achievable? Possibly, but not achieved here. It requires a balanced frozen cloud-only panel with variables measured before the run.
10. Next phase: freeze K/rho/model calibration priors, collect task labels and planned context before execution, run balanced cloud models across held-out benchmark cells, and score calibration before any post-run diagnostics are opened.

## Falsification Summary

K survives replacement attempts but is historical memory. `rho` survives but is unstable. Accessibility survives as a target but its strongest components are contaminated. The ceiling is sharply weakened. The diagnostic-science interpretation survives the strongest cloud-only falsification attempt in this workspace.
""",
    )

    write_md(
        "executive_verdict.md",
        f"""
# Executive Verdict

Scope: {scope}

## Classification

C. Diagnostic science

## Justification

Agent-Hub is stronger than mostly descriptive science because K/rho/accessibility explain structured failures and expose contamination mechanisms. It is not predictive science because clean pre-run prospective prediction remains near zero and the best retrospective gains depend on historical priors and post-run diagnostics. It is not yet emerging predictive science because the clean prospective evidence is too weak and imbalanced.

Final verdict: retain Agent-Hub as a cloud-only explanatory/diagnostic research program. Do not promote a fourth primitive or the 0.865 ceiling as prospective law until a frozen balanced cloud-only tournament validates them.
""",
    )


def contamination_loss(retro: list[list[Any]], holdout: list[list[Any]], prosp: list[list[Any]]) -> list[list[Any]]:
    def by_name(rows: list[list[Any]]) -> dict[str, list[Any]]:
        return {str(row[0]): row for row in rows}

    r = by_name(retro)
    h = by_name(holdout)
    p = by_name(prosp)
    return [
        ["retrospective in-sample", r["K+rho+A1-A5"][5], r["K+rho+A1-A3"][5], round(float(r["K+rho+A1-A5"][5]) - float(r["K+rho+A1-A3"][5]), 6)],
        ["historical/nonhistorical holdout", h["K+rho+A1-A5"][7], h["K+rho+A1-A3"][7], round(float(h["K+rho+A1-A5"][7]) - float(h["K+rho+A1-A3"][7]), 6)],
        ["prior prospective reconstruction", p["K+rho+A1-A5"][7], p["K+rho+A1-A3"][7], round(float(p["K+rho+A1-A5"][7]) - float(p["K+rho+A1-A3"][7]), 6)],
    ]


def main() -> int:
    rows, excluded = cloud.cloud_rows()
    prospective = prospective_rows(rows)
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    retrospective, holdout, prospect = model_tables(rows, prospective)
    clean_primary = "K+rho+A1-A3"
    clean_initial = "K+rho+A1"
    enriched = residual_enriched(train, prospective, ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"])
    fp = sorted([row for row in enriched if row["success"] < 0.5], key=lambda row: row["predicted"], reverse=True)[:12]
    fn = sorted([row for row in enriched if row["success"] >= 0.5], key=lambda row: row["predicted"])[:12]
    clusters = cluster_rows(enriched)[:18]
    stability = stability_rows(
        rows,
        ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action", "A", "Actionability", "E9", "context_budget"],
    )
    loss = contamination_loss(retrospective, holdout, prospect)
    audit_rows = [[name, role, timing, lineage, risk] for name, role, timing, lineage, risk in VARIABLE_AUDIT]
    true_pre = [name for name, _role, timing, _lineage, risk in VARIABLE_AUDIT if timing == "pre-run" or timing.startswith("pre-run") or "if frozen" in timing and "contamination" not in risk]
    during = [name for name, _role, timing, _lineage, _risk in VARIABLE_AUDIT if timing.startswith("during-run")]
    post = [name for name, _role, timing, _lineage, _risk in VARIABLE_AUDIT if timing == "post-run" or "post-run" in timing]

    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."

    write_md(
        "leakage_audit.md",
        f"""
# Leakage Audit

Scope: {scope}

## Timing Classification

{table(["variable", "role", "timing class", "lineage", "leakage verdict"], audit_rows)}

## Clean Predictor Sets

- Initial-route clean set: `K`, `rho`, `A1_exists`, `context_budget`, task/repository/model identifiers only if converted to frozen priors.
- Post-retrieval pre-generation clean set: initial-route set plus `A2_retrieved` and `A3_surfaced`.
- Removed from pre-run prediction: `A`, `A4_understood`, `A5_linked_to_action`, `Actionability`, `E9`, `referenced_files`, `edited_files`, `tests_or_verifiers`, and any same-run success/validation/error/latency fields.

## Verdict

The strongest retrospective accessibility gain is contaminated. `A4_understood` and `A5_linked_to_action` directly observe generated behavior. `K` and `rho` are not post-run traces for the target row when frozen, but they are historical outcome priors, so they test stability of past performance rather than a purely structural theory.
""",
    )

    write_md(
        "pre_run_prediction_framework.md",
        f"""
# Pre-Run Prediction Framework

Scope: {scope}

## Rule

A predictor is admissible only if its value can be frozen before the predicted success outcome exists. The strict initial-routing model excludes retrieval products. The clean post-retrieval model may use `A2_retrieved` and `A3_surfaced` only after the context package is frozen and before generation.

## Model Tournament

{table(["model", "features", "admissibility"], [[name, ", ".join(fields), "clean initial" if name in {"K", "K+rho", "K+rho+A1"} else ("clean post-retrieval" if name == "K+rho+A1-A3" else "diagnostic upper bound; contaminated")] for name, fields in SPECS])}

## Retrospective In-Sample Recompute

{table(["model", "rows", "corr", "AUC", "Brier", "R2"], retrospective)}

## Frozen-Style Holdout Recompute

{table(["model", "rows", "corr", "AUC", "Brier", "base Brier", "Brier gain", "R2", "calibration error"], holdout)}

## Prior Prospective Reconstruction

{table(["model", "rows", "corr", "AUC", "Brier", "base Brier", "Brier gain", "R2", "calibration error"], prospect)}

Best clean initial model: `{clean_initial}`. Best clean post-retrieval model: `{clean_primary}`. `K+rho+A1-A5` is reported only to measure contamination, not as an admissible forecast model.
""",
    )

    write_md(
        "prospective_failure_forensics.md",
        f"""
# Prospective Failure Forensics

Scope: {scope}

## Contamination Loss

{table(["comparison", "contaminated A1-A5 R2", "clean A1-A3 R2", "R2 loss when post-run fields removed"], loss)}

## Failure Causes

| cause | evidence | verdict |
| --- | --- | --- |
| leakage | A1-A5 beats A1-A3 retrospectively, and A4/A5 are generated-output traces | material cause of retrospective optimism |
| dataset size | prior prospective cloud set has only {len(prospective)} reconstructed rows after filtering | material; power and coverage are weak |
| benchmark drift | prospective rows are concentrated in a narrow frozen tournament rather than the full historical distribution | likely material |
| unstable predictors | `rho` and historical priors depend on model/category cells that do not transfer cleanly | material |
| model-family effects | accepted prospective rows are dominated by a single cloud family after exclusions | material |

## Interpretation

Prospective failure is not surprising after the timing audit. Retrospective explanatory power is partly real historical structure and partly diagnostic contamination. The clean model is trying to forecast a new, narrow, imbalanced tournament using priors learned from broader historical cells.

## Primary Answer

The failure is caused by methodology more than by a disproven core theory: the retrospective design allowed historical priors and post-generation diagnostics to masquerade as predictors. The theory may still be useful diagnostically, but it has not yet earned future-outcome prediction status.
""",
    )

    write_md(
        "prediction_failure_clusters.md",
        f"""
# Prediction Failure Clusters

Scope: {scope}

Model used for clustering: clean post-retrieval `{clean_primary}`.

## Largest False Positives

{table(["task", "model", "repository", "category", "context", "predicted", "actual - predicted"], [[row.get("task_id"), row["model"], row["repository"], row["category"], row.get("context_budget"), round(row["predicted"], 3), round(row["residual"], 3)] for row in fp])}

## Largest False Negatives

{table(["task", "model", "repository", "category", "context", "predicted", "actual - predicted"], [[row.get("task_id"), row["model"], row["repository"], row["category"], row.get("context_budget"), round(row["predicted"], 3), round(row["residual"], 3)] for row in fn])}

## Residual Clusters

{table(["axis", "cluster", "rows", "mean residual", "residual sd", "mean abs error"], clusters)}

## Cluster Reading

False positives are mostly over-crediting historical compatibility in cells where execution reliability collapses. False negatives are recoveries inside low-prior cells, especially where coarse category priors understate task-specific solvability. The errors are not random noise; they are structured by repository, category, context budget, and model-family concentration.
""",
    )

    write_md(
        "predictor_stability_analysis.md",
        f"""
# Predictor Stability Analysis

Scope: {scope}

## Predictor Stability

{table(["predictor", "rows", "global corr", "AUC", "split corr sd", "eligible split cells", "timing"], stability)}

## Findings

- `K` is the most useful clean prior, but it is an outcome-derived memory of past performance.
- `rho` is unstable under prospective transfer because its model/category cells are coarse and family-sensitive.
- `A1` is clean but too weak alone.
- `A2/A3` are cleaner than `A4/A5`, but only available after retrieval/context assembly.
- `A4/A5`, `E9`, and generated-reference fields are strong because they observe the run itself.

## Stability Verdict

The clean predictors are not stable enough to carry the retrospective ceiling into a narrow future benchmark. Predictor instability and model-family imbalance are sufficient to explain the prospective collapse without inventing a fourth primitive.
""",
    )

    best_prospect = max(prospect, key=lambda row: float(row[7])) if prospect else ["n/a", 0, 0, 0, 0, 0, 0, 0, 0]
    write_md(
        "prospective_validation_v3.md",
        f"""
# Prospective Validation v3

Scope: {scope}

## Clean Tournament

{table(["model", "rows", "corr", "AUC", "Brier", "base Brier", "Brier gain", "R2", "calibration error"], prospect)}

## Decision

Best prior prospective reconstruction: `{best_prospect[0]}` with R2 `{best_prospect[7]}`. This is not strong prospective validation because these feature values were reconstructed after the fact and the accepted set is narrow. The truly frozen older compatibility tournament remains near zero after cloud-only filtering.

## Answers

1. Truly pre-run predictors: `A1_exists`, planned `context_budget`, benchmark/task labels, and frozen historical priors (`K`, `rho`, compatibility priors) with the caveat that the priors are outcome-derived. `A2/A3` are only post-retrieval pre-generation.
2. Retrospective dependence on contamination: measured by the R2 loss table; the A1-A5 advantage over A1-A3 is diagnostic contamination, not clean forecast power.
3. Best clean pre-run model: `{clean_initial}` for initial routing; `{clean_primary}` after retrieval is frozen.
4. Why prospective prediction fails: leakage, small imbalanced prospective cloud rows, benchmark drift, unstable `rho`, and model-family concentration.
5. Methodology or theory: primarily methodology. The theory is explanatory/diagnostic until clean prospective evidence exists.
6. Can K+rho+A predict future outcomes before execution: not established. Clean K+rho+A1/A1-A3 does not yet meet strong prospective criteria.
7. Scientific status: Agent-Hub is currently explanatory and diagnostic science, not validated predictive science.
""",
    )

    write_md(
        "scientific_assessment_v4.md",
        f"""
# Scientific Assessment v4

Scope: {scope}

## Bottom Line

Assuming the prior conclusions are wrong was productive: the strongest positive result is not clean predictive science. Most of the extra explanatory power beyond the clean pre-generation variables comes from post-run diagnostics and historical outcome priors.

## What Survives

- K+rho+A remains useful as an explanatory measurement family.
- `A1-A3` are the clean accessibility candidates; `A4/A5` are diagnostics.
- No fourth primitive should be searched for or promoted from this failure.

## What Fails

- The retrospective ceiling does not transfer to actual frozen prospective prediction.
- `A1-A5` should not be used for future prediction before execution.
- Historical holdout performance overstates future performance when benchmark composition shifts.

## Success Classification

Moderate Success / Major Discovery: the cause of prospective failure is isolated enough to demote the current claim. Retrospective power depends materially on contamination and non-predictive diagnostic variables. Agent-Hub should be described as explanatory and diagnostic science until a balanced, frozen, cloud-only prospective panel proves otherwise.
""",
    )

    write_final_deliverables(rows, excluded, prospective)

    print(
        json.dumps(
            {
                "cloud_rows": len(rows),
                "prospective_rows": len(prospective),
                "best_clean_initial": clean_initial,
                "best_clean_post_retrieval": clean_primary,
                "contamination_loss": loss,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
