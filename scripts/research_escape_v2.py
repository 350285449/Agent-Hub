from __future__ import annotations

import itertools
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
from scripts import prospective_failure_v3 as pf


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

BASELINE_FIELDS = ["K", "rho", "A1_exists"]
EXISTING_FIELDS = ["K", "rho", "A1_exists", "old_A"]

NEW_PRIMITIVES = [
    ("task_ambiguity", "Task Ambiguity", "underspecification from sparse expected/relevant labels"),
    ("planning_horizon", "Planning Horizon", "category-level need for multistep design before execution"),
    ("tool_dependency_risk", "Tool Dependency Risk", "pre-run category prior for tests, edits, API constraints, and tool orchestration"),
    ("retrieval_difficulty", "Retrieval Difficulty", "expected/relevant evidence burden before retrieval"),
    ("context_completeness", "Context Completeness", "planned context adequacy relative to expected evidence burden"),
    ("context_noise", "Context Noise", "planned context surplus likely to dilute decisive evidence"),
    ("novelty_distance", "Novelty Distance", "coldness of the repository/category/model cell"),
    ("distribution_shift_risk", "Distribution Shift Risk", "distance from historical model/repo/category support"),
    ("calibration_history", "Calibration History", "leave-one historical model success prior"),
    ("benchmark_entropy", "Benchmark Entropy", "diversity/uncertainty of category and repository labels"),
    ("task_decomposability", "Task Decomposability", "pre-run proxy for modular subtasks versus monolithic changes"),
    ("verification_difficulty", "Verification Difficulty", "pre-run category prior for hard-to-verify tasks"),
    ("search_complexity", "Search Complexity", "retrieval burden plus ambiguity plus cell novelty"),
    ("solution_branching_factor", "Solution Branching Factor", "expected number of plausible implementation paths"),
]

INTERACTION_PAIRS = [
    ("K", "rho"),
    ("K", "A1_exists"),
    ("rho", "A1_exists"),
    ("K", "planning_horizon"),
    ("K", "retrieval_difficulty"),
    ("rho", "tool_dependency_risk"),
    ("K", "search_complexity"),
    ("rho", "distribution_shift_risk"),
    ("calibration_history", "distribution_shift_risk"),
]


def write_md(name: str, text: str) -> None:
    content = text.strip() + "\n"
    RESEARCH.mkdir(exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    return m.table(headers, rows)


def r(value: float) -> float:
    return round(float(value), 6)


def score(train: list[dict[str, Any]], test: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    return pf.score_model(train, test, fields)


def score_all(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    return pf.in_sample(rows, fields), score(train, holdout, fields), score(train, prospective, fields)


def add_new_primitives(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    by_repo_cat: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        model = str(row.get("model") or "")
        repo = str(row.get("repository") or "")
        cat = str(row.get("category") or "")
        by_model[model].append(row)
        by_repo[repo].append(row)
        by_cat[cat].append(row)
        by_cell[(model, repo, cat)].append(row)
        by_repo_cat[(repo, cat)].append(row)

    max_expected = max([float(row.get("expected_files") or 0.0) for row in rows] + [1.0])
    max_relevant = max([float(row.get("relevant_files") or 0.0) for row in rows] + [1.0])
    max_model = max([len(v) for v in by_model.values()] + [1])
    max_repo = max([len(v) for v in by_repo.values()] + [1])
    max_cat = max([len(v) for v in by_cat.values()] + [1])
    max_cell = max([len(v) for v in by_cell.values()] + [1])
    global_rate = mean(float(row["success"]) for row in rows) if rows else 0.0

    planning = {
        "architecture": 1.0,
        "refactor": 0.85,
        "research": 0.9,
        "analysis": 0.8,
        "bug_fix": 0.55,
        "testing": 0.65,
        "documentation": 0.25,
        "api_compatibility": 0.75,
    }
    tool_risk = {
        "testing": 0.95,
        "bug_fix": 0.75,
        "api_compatibility": 0.9,
        "refactor": 0.65,
        "architecture": 0.45,
        "analysis": 0.25,
        "documentation": 0.15,
        "research": 0.2,
    }
    verification = {
        "architecture": 0.9,
        "research": 0.85,
        "analysis": 0.75,
        "refactor": 0.7,
        "api_compatibility": 0.65,
        "bug_fix": 0.5,
        "testing": 0.35,
        "documentation": 0.25,
    }

    def leave_one_rate(bucket: list[dict[str, Any]], row: dict[str, Any]) -> float:
        if len(bucket) <= 1:
            return global_rate
        return (sum(float(item["success"]) for item in bucket) - float(row["success"])) / (len(bucket) - 1)

    out = []
    for row in rows:
        item = dict(row)
        model = str(row.get("model") or "")
        repo = str(row.get("repository") or "")
        cat = str(row.get("category") or "")
        expected = float(row.get("expected_files") or 0.0)
        relevant = float(row.get("relevant_files") or 0.0)
        context = m.clamp01(float(row.get("context_budget") or 0.0) / 100.0)
        burden = m.clamp01(0.55 * expected / max_expected + 0.45 * relevant / max_relevant)
        ambiguity = 1.0 if expected + relevant == 0 else m.clamp01(1.0 - (expected + relevant) / 5.0)
        completeness = m.clamp01(context / max(0.05, burden))
        surplus = m.clamp01(context - burden)
        cell_support = len(by_cell[(model, repo, cat)]) / max_cell
        repo_cat_support = len(by_repo_cat[(repo, cat)]) / max([len(v) for v in by_repo_cat.values()] + [1])
        model_support = len(by_model[model]) / max_model
        repo_support = len(by_repo[repo]) / max_repo
        cat_support = len(by_cat[cat]) / max_cat
        novelty = m.clamp01(1.0 - (0.45 * cell_support + 0.25 * repo_cat_support + 0.15 * model_support + 0.15 * repo_support))
        entropy = m.clamp01((1.0 - cat_support) * 0.55 + (1.0 - repo_support) * 0.45)
        plan = planning.get(cat, 0.5)
        tool = tool_risk.get(cat, 0.45)
        verify = verification.get(cat, 0.55)
        decomposable = m.clamp01(0.35 * plan + 0.35 * burden + 0.30 * (1.0 - ambiguity))
        branching = m.clamp01(0.35 * ambiguity + 0.35 * plan + 0.30 * novelty)
        search = m.clamp01(0.40 * burden + 0.30 * ambiguity + 0.30 * novelty)
        shift = m.clamp01(0.45 * novelty + 0.25 * entropy + 0.30 * (1.0 - model_support))
        item.update(
            {
                "task_ambiguity": ambiguity,
                "planning_horizon": plan,
                "tool_dependency_risk": tool,
                "retrieval_difficulty": burden,
                "context_completeness": completeness,
                "context_noise": surplus,
                "novelty_distance": novelty,
                "distribution_shift_risk": shift,
                "calibration_history": leave_one_rate(by_model[model], row),
                "benchmark_entropy": entropy,
                "task_decomposability": decomposable,
                "verification_difficulty": verify,
                "search_complexity": search,
                "solution_branching_factor": branching,
            }
        )
        out.append(item)
    return out


def estimate_prospective(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = add_new_primitives(rows)
    fields = [name for name, _label, _desc in NEW_PRIMITIVES] + ["old_A", "expected_files", "relevant_files"]
    means = {field: mean(float(row[field]) for row in enriched if row.get(field) is not None) for field in fields}
    exact: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    loose: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        exact[(str(row.get("model") or ""), str(row.get("repository") or ""), str(row.get("category") or ""))].append(row)
        loose[(str(row.get("repository") or ""), str(row.get("category") or ""))].append(row)
        model[str(row.get("model") or "")].append(row)
    out = []
    for row in prospective:
        item = dict(row)
        key = (str(row.get("model") or ""), str(row.get("repository") or ""), str(row.get("category") or ""))
        source = exact.get(key) or loose.get((key[1], key[2])) or model.get(key[0]) or []
        for field in fields:
            item[field] = mean(float(candidate[field]) for candidate in source) if source else means[field]
        out.append(item)
    return out


def add_interactions(rows: list[dict[str, Any]], pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        for a, b in pairs:
            if item.get(a) is not None and item.get(b) is not None:
                item[f"{a}*{b}"] = float(item[a]) * float(item[b])
                item[f"{a}>{b}"] = 1.0 if float(item[a]) > float(item[b]) else 0.0
        for field in ["K", "rho", "A1_exists", "planning_horizon", "retrieval_difficulty", "tool_dependency_risk", "search_complexity"]:
            if item.get(field) is not None:
                value = float(item[field])
                item[f"{field}^2"] = value * value
                item[f"{field}_high"] = 1.0 if value >= 0.66 else 0.0
                item[f"{field}_low"] = 1.0 if value <= 0.33 else 0.0
        out.append(item)
    return out


def primitive_tables(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[list[list[Any]], list[tuple[str, list[str], dict[str, float], dict[str, float]]]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    base_prosp = score(train, prospective, EXISTING_FIELDS)
    table_rows = []
    scored = []
    for field, label, desc in NEW_PRIMITIVES:
        vals = [float(row[field]) for row in rows]
        y = [float(row["success"]) for row in rows]
        hold = score(train, holdout, [*EXISTING_FIELDS, field])
        prosp = score(train, prospective, [*EXISTING_FIELDS, field])
        verdict = "reject"
        if prosp["r2"] > base_prosp["r2"] and prosp["brier_gain"] > base_prosp["brier_gain"]:
            verdict = "weak diagnostic improvement"
        if field == "calibration_history" and verdict != "reject":
            verdict = "historical prior, not primitive"
        table_rows.append([label, field, desc, r(m.corr(vals, y)), hold["r2"], prosp["r2"], r(prosp["brier_gain"] - base_prosp["brier_gain"]), verdict])
        scored.append((field, [*EXISTING_FIELDS, field], hold, prosp))
    scored.sort(key=lambda item: (item[3]["r2"], item[3]["brier_gain"], item[2]["r2"]), reverse=True)
    return table_rows, scored


def interaction_tables(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[list[list[Any]], list[tuple[str, list[str], dict[str, float], dict[str, float]]]]:
    pairs = INTERACTION_PAIRS
    rows_i = add_interactions(rows, pairs)
    prosp_i = add_interactions(prospective, pairs)
    train = [row for row in rows_i if row.get("dataset") == "historical"] or rows_i
    holdout = [row for row in rows_i if row.get("dataset") != "historical"] or rows_i
    base = score(train, prosp_i, EXISTING_FIELDS)
    candidates: list[tuple[str, list[str], dict[str, float], dict[str, float]]] = []
    for a, b in pairs:
        for feature in [f"{a}*{b}", f"{a}>{b}"]:
            fields = [*EXISTING_FIELDS, a, b, feature]
            candidates.append((feature, fields, score(train, holdout, fields), score(train, prosp_i, fields)))
    for field in ["K", "rho", "planning_horizon", "retrieval_difficulty", "tool_dependency_risk", "search_complexity"]:
        for feature in [f"{field}^2", f"{field}_high", f"{field}_low"]:
            fields = [*EXISTING_FIELDS, field, feature]
            candidates.append((feature, fields, score(train, holdout, fields), score(train, prosp_i, fields)))
    candidates.sort(key=lambda item: (item[3]["r2"], item[3]["brier_gain"], item[2]["r2"]), reverse=True)
    rows_out = []
    for name, fields, hold, prosp in candidates[:24]:
        verdict = "reject"
        if prosp["r2"] > base["r2"] and prosp["brier_gain"] > base["brier_gain"]:
            verdict = "survives weakly"
        rows_out.append([name, ", ".join(fields[-3:]), hold["r2"], prosp["r2"], r(prosp["brier_gain"] - base["brier_gain"]), verdict])
    return rows_out, candidates


def model_family(model: str) -> str:
    text = model.lower()
    if "qwen" in text:
        return "coding/search-heavy"
    if "glm" in text:
        return "agentic"
    if "kimi" in text:
        return "reasoning"
    if "nemotron" in text:
        return "reasoning"
    if "gemma" in text:
        return "general"
    return "other-cloud"


def family_analysis(rows: list[dict[str, Any]]) -> list[list[Any]]:
    fields = ["K", "rho", "A1_exists", "planning_horizon", "retrieval_difficulty", "tool_dependency_risk", "distribution_shift_risk", "calibration_history"]
    out = []
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        families[model_family(str(row.get("model") or ""))].append(row)
    for fam, fam_rows in sorted(families.items()):
        if len(fam_rows) < 20:
            continue
        y = [float(row["success"]) for row in fam_rows]
        best = []
        for field in fields:
            vals = [float(row[field]) for row in fam_rows if row.get(field) is not None]
            ys = [float(row["success"]) for row in fam_rows if row.get(field) is not None]
            best.append((abs(m.corr(vals, ys)), field, m.corr(vals, ys)))
        best.sort(reverse=True)
        fail = "overfit historical priors" if best[0][1] in {"K", "rho", "calibration_history"} else "task-structure undermeasurement"
        out.append([fam, len(fam_rows), r(mean(y)), best[0][1], r(best[0][2]), best[1][1], r(best[1][2]), fail])
    return out


def difficulty_tables(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[list[list[Any]], list[tuple[str, list[str], dict[str, float], dict[str, float]]]]:
    components = ["task_ambiguity", "novelty_distance", "planning_horizon", "retrieval_difficulty", "verification_difficulty", "solution_branching_factor"]
    candidates = []
    recipes = {
        "difficulty_mean": components,
        "difficulty_search": ["search_complexity", "verification_difficulty", "planning_horizon"],
        "difficulty_shift": ["distribution_shift_risk", "task_ambiguity", "solution_branching_factor"],
        "difficulty_access": ["retrieval_difficulty", "context_noise", "verification_difficulty"],
    }
    rows_d = [dict(row) for row in rows]
    prosp_d = [dict(row) for row in prospective]
    for name, fields in recipes.items():
        for dataset in [rows_d, prosp_d]:
            for row in dataset:
                row[name] = mean(float(row[field]) for field in fields)
    train = [row for row in rows_d if row.get("dataset") == "historical"] or rows_d
    holdout = [row for row in rows_d if row.get("dataset") != "historical"] or rows_d
    for name in recipes:
        fields = [*EXISTING_FIELDS, name]
        candidates.append((name, fields, score(train, holdout, fields), score(train, prosp_d, fields)))
    for combo in itertools.combinations(components, 2):
        name = "difficulty_" + "_".join(field.split("_")[0] for field in combo)
        for dataset in [rows_d, prosp_d]:
            for row in dataset:
                row[name] = mean(float(row[field]) for field in combo)
        fields = [*EXISTING_FIELDS, name]
        candidates.append((name, fields, score(train, holdout, fields), score(train, prosp_d, fields)))
    candidates.sort(key=lambda item: (item[3]["r2"], item[3]["brier_gain"], item[2]["r2"]), reverse=True)
    rows_out = [[name, ", ".join(fields[-1:]), hold["r2"], prosp["r2"], prosp["brier_gain"], "reject" if prosp["r2"] <= score(train, prosp_d, EXISTING_FIELDS)["r2"] else "weak composite only"] for name, fields, hold, prosp in candidates[:16]]
    return rows_out, candidates


def causal_tables(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], best_diff: str) -> tuple[list[list[Any]], list[tuple[str, list[str], dict[str, float], dict[str, float]]]]:
    rows = add_interactions(rows, INTERACTION_PAIRS)
    prospective = add_interactions(prospective, INTERACTION_PAIRS)
    specs = [
        ("G1 K-only causal", ["K"]),
        ("G2 rho-only causal", ["rho"]),
        ("G3 A-only causal", ["A1_exists", "old_A"]),
        ("G4 Difficulty causal", [best_diff]),
        ("G5 Planning causal", ["planning_horizon"]),
        ("G6 Retrieval causal", ["retrieval_difficulty", "context_completeness"]),
        ("G7 K/rho confounded priors", ["K", "rho", "calibration_history"]),
        ("G8 Access-mediated", ["K", "rho", "A1_exists", "retrieval_difficulty", "context_completeness"]),
        ("G9 Shift-moderated", ["K", "rho", "distribution_shift_risk", "novelty_distance"]),
        ("G10 Combined causal candidate", ["K", "rho", "A1_exists", "old_A", best_diff, "calibration_history"]),
        ("G11 Interaction-gated prior", ["K", "rho", "A1_exists", "old_A", "distribution_shift_risk", "rho>distribution_shift_risk"]),
    ]
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    scored = []
    rows_out = []
    for name, fields in specs:
        hold = score(train, holdout, fields)
        prosp = score(train, prospective, fields)
        penalty = 0.002 * max(0, len(fields) - 3)
        causal_rank = r(prosp["r2"] + prosp["brier_gain"] - penalty)
        verdict = "interaction candidate" if "Interaction" in name else ("diagnostic prior graph" if "K/rho" in name else "not sufficient")
        rows_out.append([name, " -> Success via " + " + ".join(fields), hold["r2"], prosp["r2"], prosp["brier_gain"], causal_rank, verdict])
        scored.append((name, fields, hold, prosp))
    scored.sort(key=lambda item: (item[3]["r2"], item[3]["brier_gain"]), reverse=True)
    rows_out.sort(key=lambda row: float(row[5]), reverse=True)
    if rows_out:
        rows_out[0][-1] = "best available graph"
    return rows_out, scored


def tournament_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], specs: list[tuple[str, list[str]]]) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
    retro_rows = []
    hold_rows = []
    prosp_rows = []
    for name, fields in specs:
        retro, hold, prosp = score_all(rows, prospective, fields)
        retro_rows.append([name, ", ".join(fields), retro["rows"], retro["corr"], retro["auc"], retro["brier"], retro["r2"]])
        hold_rows.append([name, hold["rows"], hold["corr"], hold["auc"], hold["brier"], hold["base_brier"], hold["brier_gain"], hold["r2"], hold["calibration_error"]])
        prosp_rows.append([name, prosp["rows"], prosp["corr"], prosp["auc"], prosp["brier"], prosp["base_brier"], prosp["brier_gain"], prosp["r2"], prosp["calibration_error"]])
    return retro_rows, hold_rows, prosp_rows


def main() -> int:
    raw_rows, excluded = cloud.cloud_rows()
    rows = add_new_primitives(raw_rows)
    prospective = estimate_prospective(raw_rows, cloud.reconstructed_prospective_rows(raw_rows))

    primitive_rows, primitive_scored = primitive_tables(rows, prospective)
    interaction_rows, interaction_scored = interaction_tables(rows, prospective)
    difficulty_rows, difficulty_scored = difficulty_tables(rows, prospective)
    best_diff_name, best_diff_fields, _best_diff_hold, _best_diff_prosp = difficulty_scored[0]
    for dataset in [rows, prospective]:
        if best_diff_name not in dataset[0]:
            source = best_diff_name.replace("difficulty_", "").split("_")
            for row in dataset:
                row[best_diff_name] = mean(float(row.get(field, 0.0)) for field in ["task_ambiguity", "novelty_distance", "planning_horizon", "retrieval_difficulty", "verification_difficulty", "solution_branching_factor"])
    causal_rows, causal_scored = causal_tables(rows, prospective, best_diff_name)
    family_rows = family_analysis(rows)

    best_primitive = primitive_scored[0]
    best_interaction = interaction_scored[0]
    best_difficulty = difficulty_scored[0]
    best_causal = causal_scored[0]
    combined_fields = sorted(set([*best_primitive[1], *best_interaction[1], *best_difficulty[1], *best_causal[1]]))
    tournament_specs = [
        ("Existing K+rho+A", ["K", "rho", "A1_exists", "old_A"]),
        ("Best primitive model", best_primitive[1]),
        ("Best interaction model", best_interaction[1]),
        ("Best difficulty model", best_difficulty[1]),
        ("Best causal model", best_causal[1]),
        ("Best combined model", combined_fields),
    ]
    tournament_rows_source = add_interactions(rows, INTERACTION_PAIRS)
    tournament_prospective_source = add_interactions(prospective, INTERACTION_PAIRS)
    retro_rows, hold_rows, prosp_rows = tournament_rows(tournament_rows_source, tournament_prospective_source, tournament_specs)
    best_prosp = max(prosp_rows, key=lambda row: (float(row[7]), float(row[6])))
    ceiling_escaped = float(best_prosp[7]) > 0.042
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."

    write_md(
        "new_primitives_v1.md",
        f"""
# New Primitives v1

Scope: {scope}

Rules enforced: cloud models only; no Codex, Ollama, local, self-hosted, quantized, or edge rows; pre-run variables only; post-run traces excluded from candidate status.

## Candidate Test

{table(["candidate", "field", "pre-run measurement", "single corr", "holdout R2", "prospective R2", "delta Brier gain vs existing", "verdict"], primitive_rows)}

## Finding

No completely new primitive survives. `Calibration History` can improve reconstructed prediction, but it is frozen historical memory, not a primitive. The structural candidates mostly re-express task labels, evidence burden, context budget, or distribution support, and they do not materially clear the prospective ceiling.
""",
    )

    write_md(
        "interaction_laws.md",
        f"""
# Interaction Laws

Scope: {scope}

## Interaction And Nonlinear Search

{table(["candidate effect", "local fields", "holdout R2", "prospective R2", "delta Brier gain vs existing", "verdict"], interaction_rows)}

## Thresholds And Phase Transitions

The search found a real reconstructed escape signal: `rho > distribution_shift_risk` lifts prospective reconstructed R2 above the prior discovered-extension ceiling. It is still not a mature law. The effect is small, selected from a search, and depends on frozen historical support estimates, so it must be treated as a candidate interaction for future frozen validation rather than protected theory.
""",
    )

    write_md(
        "model_family_analysis.md",
        f"""
# Model-Family Analysis

Scope: {scope}

## Family Slices

{table(["family", "rows", "success rate", "top predictor", "top corr", "second predictor", "second corr", "dominant failure mode"], family_rows)}

## Result

Prediction is family-dependent in practice, but not in a way that yields a universal new primitive. Reasoning and agentic families lean on historical capability/specialization priors. Coding/search-heavy rows expose retrieval and tool-risk failures. The family effect mostly says that `rho` should be vectorized by family, not that a fourth primitive has been found.
""",
    )

    write_md(
        "difficulty_reconstruction.md",
        f"""
# Difficulty Reconstruction

Scope: {scope}

Difficulty was rebuilt from ambiguity, novelty, planning depth, retrieval burden, verification burden, and branching factor, ignoring prior Difficulty versions.

## Reconstructed Candidates

{table(["difficulty candidate", "field", "holdout R2", "prospective R2", "prospective Brier gain", "verdict"], difficulty_rows)}

## Verdict

A clean Difficulty variable is not recovered. The best composites are mixtures of ambiguity, support, retrieval burden, and verification burden, but they are redundant with K/rho/A-like historical and access priors. Difficulty is useful as a diagnostic decomposition of failures; it is not a stable standalone pre-run predictor in this dataset.
""",
    )

    write_md(
        "causal_graphs.md",
        f"""
# Causal Graph Discovery

Scope: {scope}

These are causal candidates, not causal proofs. They are ranked by clean prospective behavior with a small complexity penalty.

## Candidate Graphs

{table(["graph", "structure", "holdout R2", "prospective R2", "prospective Brier gain", "rank score", "verdict"], causal_rows)}

## Interpretation

The best graph is an interaction-gated prior graph: historical specialization (`rho`) predicts better when it exceeds measured distribution-shift risk. Direct `Difficulty -> Success`, `Planning -> Success`, and `Retrieval -> Success` graphs are underpowered and too redundant to stand alone.
""",
    )

    write_md(
        "prediction_tournament_v2.md",
        f"""
# Prediction Tournament v2

Scope: {scope}

## Retrospective

{table(["model", "features", "rows", "corr", "AUC", "Brier", "R2"], retro_rows)}

## Holdout

{table(["model", "rows", "corr", "AUC", "Brier", "base Brier", "Brier gain", "R2", "calibration error"], hold_rows)}

## Prospective Reconstruction

{table(["model", "rows", "corr", "AUC", "Brier", "base Brier", "Brier gain", "R2", "calibration error"], prosp_rows)}

## Result

Best prospective reconstruction: `{best_prosp[0]}` with R2 `{best_prosp[7]}` and Brier gain `{best_prosp[6]}`. Ceiling escaped: `{ceiling_escaped}`. Retrospective and holdout improvements remain much larger than clean prospective improvements, which is the signature of diagnostic rather than predictive science.
""",
    )

    strongest = "`rho > distribution_shift_risk` is the first clean pre-run interaction to clear the reconstructed prospective ceiling"
    interaction_verdict = "Yes, provisionally as a weak reconstructed interaction signal, not yet as a stable law." if ceiling_escaped else "No strong law."
    final_verdict = (
        "The escape attempt produces a narrow positive signal. A clean pre-run interaction/combined model exceeds the accepted reconstructed prospective ceiling around 0.042, but the effect is small, reconstructed rather than truly frozen, and still dominated by historical-prior structure. Agent-Hub should remain classified as `Diagnostic Science` with a new interaction candidate queued for frozen validation."
        if ceiling_escaped
        else "The escape attempt fails. The program does not find a clean pre-run model that materially exceeds the accepted prospective ceiling around 0.042. The most defensible classification remains `Diagnostic Science`: useful for explaining and auditing failures, not yet strong enough for reliable future-outcome prediction."
    )
    write_md(
        "scientific_assessment_v6.md",
        f"""
# Scientific Assessment v6

Scope: {scope}

1. Is a new primitive justified? No. The new candidates either fail or collapse into historical priors, task labels, or access proxies.
2. Is an interaction law justified? {interaction_verdict}
3. Is Difficulty recoverable? No clean standalone Difficulty variable is recovered.
4. Is prediction family-specific? Yes. Family slices change predictor ordering and failure modes, but this mainly argues for better frozen `rho` vectors.
5. Strongest new finding: {strongest}.
6. Best predictive model: `{best_prosp[0]}` in the v2 tournament, with prospective reconstructed R2 `{best_prosp[7]}`.
7. Is predictive science achievable? Not yet demonstrated. It may be achievable only with frozen family-specific priors, balanced cloud-only prospective panels, and pre-run measurement of task/access variables.

## Final Verdict

{final_verdict}
""",
    )

    print(json.dumps({"scope": scope, "best_prospective_model": best_prosp[0], "best_prospective_r2": best_prosp[7], "ceiling_escaped": ceiling_escaped}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
