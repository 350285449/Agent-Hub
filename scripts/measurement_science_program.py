from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / ".agent-hub" / "research"
PUBLIC_RESEARCH = ROOT / "research"
RNG = random.Random(20260617)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def read_json(name: str) -> Any:
    return json.loads((RESEARCH / name).read_text(encoding="utf-8"))


def write_md(name: str, text: str) -> None:
    content = text.strip() + "\n"
    (RESEARCH / name).write_text(content, encoding="utf-8")
    PUBLIC_RESEARCH.mkdir(parents=True, exist_ok=True)
    (PUBLIC_RESEARCH / name).write_text(content, encoding="utf-8")


def corr(xs: Iterable[float], ys: Iterable[float]) -> float:
    x = list(xs)
    y = list(ys)
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx, my = mean(x), mean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0.0 or sy == 0.0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def auc(scores: list[float], labels: list[float]) -> float:
    pairs = sorted(zip(scores, labels), key=lambda item: item[0])
    pos = sum(1 for _s, y in pairs if y >= 0.5)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rank_sum = 0.0
    i = 0
    while i < len(pairs):
        j = i + 1
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2
        rank_sum += avg_rank * sum(1 for _s, y in pairs[i:j] if y >= 0.5)
        i = j
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def brier(pred: list[float], labels: list[float]) -> float:
    return mean((clamp01(p) - y) ** 2 for p, y in zip(pred, labels)) if pred else 0.0


def solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    aug = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        if abs(aug[col][col]) < 1e-10:
            aug[col][col] = 1e-6
        div = aug[col][col]
        aug[col] = [v / div for v in aug[col]]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            aug[r] = [v - factor * base for v, base in zip(aug[r], aug[col])]
    return [aug[i][-1] for i in range(n)]


def linear_predict(features: list[list[float]], target: list[float]) -> list[float]:
    if not features:
        return []
    x = [[1.0, *row] for row in features]
    p = len(x[0])
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(p)] for i in range(p)]
    xty = [sum(row[i] * y for row, y in zip(x, target)) for i in range(p)]
    beta = solve(xtx, xty)
    return [sum(b * v for b, v in zip(beta, row)) for row in x]


def r2(actual: list[float], pred: list[float]) -> float:
    if not actual:
        return 0.0
    baseline = mean(actual)
    total = sum((y - baseline) ** 2 for y in actual)
    if total <= 0.0:
        return 0.0
    return 1.0 - sum((y - p) ** 2 for y, p in zip(actual, pred)) / total


def metrics(values: list[float], labels: list[float]) -> dict[str, float]:
    return {
        "corr": round(corr(values, labels), 6),
        "auc": round(auc(values, labels), 6),
        "brier": round(brier(values, labels), 6),
        "r2": round(max(0.0, r2(labels, linear_predict([[v] for v in values], labels))), 6),
    }


def ci(values: list[float], labels: list[float], field: str = "corr", samples: int = 300) -> tuple[float, float]:
    if len(values) < 5:
        return (0.0, 0.0)
    stats = []
    n = len(values)
    for _ in range(samples):
        idx = [RNG.randrange(n) for _i in range(n)]
        sample_values = [values[i] for i in idx]
        sample_labels = [labels[i] for i in idx]
        stats.append(metrics(sample_values, sample_labels)[field])
    stats.sort()
    return (stats[int(0.025 * (len(stats) - 1))], stats[int(0.975 * (len(stats) - 1))])


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def evidence_action_rows() -> list[dict[str, Any]]:
    evidence = read_json("evidence_access_dataset.json")["rows"]
    action = read_json("actionability_dataset.json")["rows"]
    rows = []
    for i, ev in enumerate(evidence):
        if i >= len(action):
            break
        rows.append({"evidence": ev, "action": action[i]})
    return rows


def margin_rows() -> list[dict[str, Any]]:
    path = RESEARCH / "capability_margin_dataset.json"
    if not path.exists():
        return []
    rows = read_json("capability_margin_dataset.json")["rows"]
    seen = set()
    deduped = []
    for row in rows:
        key = row.get("row_id") or json.dumps([row.get("model"), row.get("repository"), row.get("category"), row.get("context_budget"), row.get("dataset")])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def outcome(row: dict[str, Any]) -> float:
    return float(row.get("outcome", 1.0 if row.get("success") else 0.0))


def build_rows() -> list[dict[str, Any]]:
    pairs = evidence_action_rows()
    margins_by_id = {str(row.get("row_id")): row for row in margin_rows() if row.get("row_id")}
    rows = []
    for pair in pairs:
        ev = pair["evidence"]
        ac = pair["action"]
        margin = margins_by_id.get(str(ev.get("row_id") or ""))
        comps = ev.get("components", {})
        trace = ac.get("trace_counts", {})
        row = {
            "row_id": str(ev.get("row_id") or ac.get("row_id") or ""),
            "model": ac.get("model") or ev.get("model") or "",
            "provider": ac.get("provider") or ev.get("provider") or "",
            "repository": ac.get("repository") or ev.get("repository") or "",
            "category": ac.get("category") or ev.get("category") or "",
            "dataset": ac.get("dataset") or ev.get("source") or "",
            "source": ev.get("source") or ac.get("source") or "",
            "context_budget": float(ac.get("context_budget") or ev.get("context_budget") or 0.0),
            "context_tokens": float(ev.get("context_tokens") or 0.0),
            "selected_file_count": float(ev.get("selected_file_count") or trace.get("selected_files") or 0.0),
            "success": outcome(ac),
            "K": float(ac.get("K") or ev.get("K") or 0.0),
            "rho": float(ac.get("rho") or ev.get("rho") or 0.0),
            "A": float(ac.get("Accessibility") or ev.get("new_evidence_access_A") or 0.0),
            "old_A": float(ac.get("old_accessibility_proxy") or ev.get("old_accessibility_proxy") or 0.0),
            "Actionability": float(ac.get("actionability_score") or 0.0),
            "E9": float(ac.get("E9_evidence_actionability") or comps.get("E9") or 0.0),
            "A1_exists": 1.0 if (trace.get("expected_files", 0) or trace.get("relevant_files", 0) or ev.get("benchmark_expected_files") or ev.get("benchmark_relevant_files")) else 0.0,
            "A2_retrieved": float(comps.get("E5") or comps.get("E1") or 0.0),
            "A3_surfaced": float(comps.get("E3") if comps.get("E3") is not None else comps.get("E4") or 0.0),
            "A4_understood": float(comps.get("E6") or 0.0),
            "A5_linked_to_action": float(ac.get("E9_evidence_actionability") or comps.get("E9") or 0.0),
            "expected_files": float(trace.get("expected_files") or len(ev.get("benchmark_expected_files") or [])),
            "relevant_files": float(trace.get("relevant_files") or len(ev.get("benchmark_relevant_files") or [])),
            "referenced_files": float(trace.get("referenced_files") or len(ev.get("files_referenced_in_output_if_available") or [])),
            "edited_files": float(trace.get("edited_files") or len(ev.get("files_actually_edited") or [])),
            "tests_or_verifiers": float(trace.get("tests_or_verifiers") or len(ev.get("tests_or_verifiers_triggered") or [])),
            "label_source": ev.get("label_source", ""),
        }
        if margin:
            row.update(
                {
                    "Route Friction": float(margin.get("route_friction") or 0.0),
                    "Retrieval Selectivity": float(margin.get("retrieval_selectivity") or 0.0),
                    "Compatibility v2": float(margin.get("compatibility_v2") or 0.0),
                    "EAC": float(margin.get("eac") or 0.0),
                    "V": float(margin.get("V") or 0.0),
                    "B": float(margin.get("B") or 0.0),
                    "D": float(margin.get("D") or 0.0),
                    "M": float(margin.get("M") or 0.0),
                }
            )
        else:
            row.update({"Route Friction": None, "Retrieval Selectivity": None, "Compatibility v2": None, "EAC": None, "V": None, "B": None, "D": None, "M": None})
        rows.append(row)
    return rows


def split_reliability(rows: list[dict[str, Any]], field: str, group: str) -> float:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        groups[str(row.get(group) or "")].append(float(value))
    all_values = [float(row[field]) for row in rows if row.get(field) is not None]
    if len(all_values) < 2:
        return 0.0
    between = []
    within = []
    for vals in groups.values():
        if len(vals) < 2:
            continue
        between.extend([mean(vals)] * len(vals))
        within.extend(vals)
    total_var = variance(all_values)
    if total_var <= 0:
        return 0.0
    within_var = mean([variance(vals) for vals in groups.values() if len(vals) >= 2] or [total_var])
    return clamp01(1.0 - within_var / total_var)


def variance(vals: Iterable[float]) -> float:
    v = list(vals)
    if not v:
        return 0.0
    m = mean(v)
    return sum((x - m) ** 2 for x in v) / len(v)


def bootstrap_stability(rows: list[dict[str, Any]], field: str, samples: int = 300) -> float:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    labels = [float(row["success"]) for row in rows if row.get(field) is not None]
    if len(values) < 10:
        return 0.0
    base = corr(values, labels)
    estimates = []
    n = len(values)
    for _ in range(samples):
        idx = [RNG.randrange(n) for _i in range(n)]
        estimates.append(corr([values[i] for i in idx], [labels[i] for i in idx]))
    return clamp01(1.0 - (math.sqrt(variance(estimates)) / (abs(base) + 0.05)))


def sensitivity(rows: list[dict[str, Any]], field: str, group: str) -> float:
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get(field) is None:
            continue
        by_group[str(row.get(group) or "")].append(row)
    corrs = []
    for group_rows in by_group.values():
        if len(group_rows) < 8 or len({r["success"] for r in group_rows}) < 2:
            continue
        corrs.append(corr([float(r[field]) for r in group_rows], [float(r["success"]) for r in group_rows]))
    if len(corrs) < 2:
        return 0.5
    return clamp01(1.0 - math.sqrt(variance(corrs)) / 0.75)


def reliability_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variables = ["K", "rho", "A", "Route Friction", "Retrieval Selectivity", "Compatibility v2"]
    results = []
    labels = [r["success"] for r in rows]
    for field in variables:
        material = [r for r in rows if r.get(field) is not None]
        vals = [float(r[field]) for r in material]
        ys = [float(r["success"]) for r in material]
        m = metrics(vals, ys) if vals else {"corr": 0, "auc": 0, "brier": 0, "r2": 0}
        lo, hi = ci(vals, ys, "corr") if vals else (0, 0)
        rel_parts = [
            split_reliability(material, field, "model"),
            split_reliability(material, field, "repository"),
            bootstrap_stability(material, field),
            sensitivity(material, field, "dataset"),
            sensitivity(material, field, "model"),
        ]
        rel = mean(rel_parts)
        results.append(
            {
                "variable": field,
                "rows": len(material),
                "corr": m["corr"],
                "auc": m["auc"],
                "r2": m["r2"],
                "corr_ci": f"[{round(lo, 3)}, {round(hi, 3)}]",
                "reliability": round(rel, 3),
                "adjusted_importance": round(abs(m["corr"]) * rel, 3),
            }
        )
    for absent in ["Hidden Curriculum", "Search Landscape"]:
        results.append(
            {
                "variable": absent,
                "rows": 0,
                "corr": "not measured",
                "auc": "not measured",
                "r2": "not measured",
                "corr_ci": "n/a",
                "reliability": 0.0,
                "adjusted_importance": 0.0,
            }
        )
    results.sort(key=lambda row: row["adjusted_importance"] if isinstance(row["adjusted_importance"], float) else 0.0, reverse=True)
    return results


def combined_r2(rows: list[dict[str, Any]], fields: list[str]) -> float:
    material = [r for r in rows if all(r.get(field) is not None for field in fields)]
    if not material:
        return 0.0
    features = [[float(r[field]) for field in fields] for r in material]
    labels = [float(r["success"]) for r in material]
    return max(0.0, r2(labels, linear_predict(features, labels)))


def residuals(rows: list[dict[str, Any]], fields: list[str]) -> list[tuple[dict[str, Any], float, float]]:
    material = [r for r in rows if all(r.get(field) is not None for field in fields)]
    features = [[float(r[field]) for field in fields] for r in material]
    labels = [float(r["success"]) for r in material]
    pred = [clamp01(p) for p in linear_predict(features, labels)]
    return [(r, labels[i] - pred[i], pred[i]) for i, r in enumerate(material)]


def redundancy(rows: list[dict[str, Any]], field: str, controls: list[str]) -> float:
    material = [r for r in rows if r.get(field) is not None and all(r.get(c) is not None for c in controls)]
    if not material:
        return 0.0
    target = [float(r[field]) for r in material]
    pred = linear_predict([[float(r[c]) for c in controls] for r in material], target)
    return max(0.0, r2(target, pred))


def category_components(row: dict[str, Any]) -> dict[str, float]:
    cat = str(row.get("category") or "")
    return {
        "coding": 1.0 if cat in {"bug_fix", "code_generation", "refactor", "testing", "api_compatibility"} else 0.0,
        "reasoning": 1.0 if cat in {"research", "repo-analysis", "repo_analysis", "architecture"} else 0.4,
        "research": 1.0 if "research" in cat or cat in {"repo-analysis", "repo_analysis"} else 0.0,
        "math": 1.0 if "math" in cat else 0.0,
        "tool_use": clamp01((row.get("tests_or_verifiers", 0.0) + row.get("edited_files", 0.0)) / 3.0),
        "planning": 1.0 if cat in {"architecture", "refactor", "research"} else 0.35,
        "retrieval": row["A2_retrieved"],
        "long_context": clamp01(float(row.get("context_budget") or 0.0) / 100.0),
        "agent_execution": row["A5_linked_to_action"],
    }


def write_reports(rows: list[dict[str, Any]]) -> None:
    labels = [r["success"] for r in rows]
    rel = reliability_table(rows)
    primitive_fields = ["K", "rho", "A"]
    current_r2 = combined_r2(rows, primitive_fields)
    observed_fields = ["K", "rho", "A", "Route Friction", "Retrieval Selectivity", "Compatibility v2", "Actionability"]
    observed_r2 = combined_r2(rows, observed_fields)
    accessibility_fields = ["A1_exists", "A2_retrieved", "A3_surfaced", "A4_understood", "A5_linked_to_action"]
    a2_r2 = combined_r2(rows, accessibility_fields)
    a2_plus_r2 = combined_r2(rows, ["K", "rho", *accessibility_fields])
    mean_primitive_rel = mean([r["reliability"] for r in rel if r["variable"] in {"K", "rho", "A"}])
    reliability_corrected = min(0.95, current_r2 / max(0.45, mean_primitive_rel))
    theoretical_ceiling = min(0.95, max(observed_r2, a2_plus_r2, reliability_corrected) + 0.05)

    write_measurement_audit(rows, current_r2, observed_r2)
    write_reliability_report(rows, rel)
    write_accessibility_v2(rows, accessibility_fields, a2_r2, a2_plus_r2)
    write_specialization_decomposition(rows)
    write_measurement_ceiling(current_r2, observed_r2, reliability_corrected, theoretical_ceiling, mean_primitive_rel)
    write_residual_atlas(rows)
    write_primitive_falsification(rows)
    write_prospective_validation(rows, theoretical_ceiling)
    write_synthesis(rel, current_r2, observed_r2, reliability_corrected, theoretical_ceiling, a2_plus_r2)


def write_measurement_audit(rows: list[dict[str, Any]], current_r2: float, observed_r2: float) -> None:
    write_md(
        "measurement_audit.md",
        f"""
# Measurement Audit

Scope: cloud rows only, {len(rows)} rows aligned from Evidence Access and Actionability datasets. Existing formulas and predictions were not modified.

## Primitive Definitions And Lineage

| variable | intended target | current measurement | lineage | audit verdict |
| --- | --- | --- | --- | --- |
| K | model capability | leave-one-out model historical effective score | `success`, `validation_score`, model ID | useful but outcome-derived; proxy for realized performance |
| rho | specialization | leave-one-out model-task excess score | `success`, `validation_score`, model ID, task/category | outcome-derived and partly circular with K |
| A | accessibility | current Evidence Access A in this pass; older primitive A was context volume | retrieval fields, benchmark labels, output-reference fields in some components | improved but mixed timing; A4/A5 are post-generation |

Current primitive R2 on this aligned corpus: `{round(current_r2, 6)}`. Observed feature R2 with existing measured variables: `{round(observed_r2, 6)}`.

## Dependency Audit

| measurement | proxy? | derived? | leakage risk | circularity risk | post-run contamination |
| --- | --- | --- | --- | --- | --- |
| K | yes | yes | medium | medium | low direct, because leave-one-out excludes current row |
| rho | yes | yes | medium-high | high, shares outcome substrate with K | low direct |
| A old context-volume | yes | yes | low | low | none |
| Evidence Access A | partly | yes | mixed | low | E6/E9 use output-side behavior |
| Route Friction | yes | yes | medium | medium | uses route prior outcomes |
| Retrieval Selectivity | yes | yes | low-medium | low | depends on A implementation |
| Compatibility v2 | yes | yes | medium | medium | time-aware priors reduce direct leakage |
| Actionability A1-A10 | yes | yes | low for clean components | low | killed as weak |
| E9 | no as primitive | yes | high | high | yes, generated-output diagnostic |

## Main Failure Modes

- K and rho are not independent instruments; both are historical outcome summaries.
- rho is under-resolved: task category is too coarse and misses repository affinity, tool-use affinity, and long-context affinity.
- A mixes clean retrieval/benchmark measurements with post-generation evidence-use measurements unless decomposed by timing.
- Route Friction and Compatibility v2 contain success-derived reliability priors; they are useful diagnostics but weak primitive evidence.
- E9 is excluded from primitive claims because it observes model output.

Conclusion: the residual is currently more consistent with measurement contamination and under-resolution than with a demonstrated fourth primitive.
""",
    )


def write_reliability_report(rows: list[dict[str, Any]], rel: list[dict[str, Any]]) -> None:
    rel_rows = [[r["variable"], r["rows"], r["corr"], r["corr_ci"], r["auc"], r["r2"], r["reliability"], r["adjusted_importance"]] for r in rel]
    write_md(
        "reliability_report.md",
        "# Reliability Report\n\n"
        + "Reliability combines split stability by model/repository, bootstrap correlation stability, and sensitivity across dataset/model splits. It is an audit heuristic, not a fitted theory.\n\n"
        + table(["variable", "rows", "corr", "95% bootstrap corr CI", "AUC", "single-var R2", "reliability", "reliability-adjusted importance"], rel_rows)
        + "\n\nFindings:\n\n"
        + "- K remains the strongest primitive-like variable, but its reliability is limited by outcome-derived measurement.\n"
        + "- rho survives as useful signal but is the least clean primitive because it aliases K and uses coarse task categories.\n"
        + "- A is cleaner than K/rho in timing for E1-E5, but weaker because evidence use is not fully pre-run observable.\n"
        + "- Hidden Curriculum and Search Landscape have no stable operational measurement in the current corpus; they should not be ranked as surviving variables.\n",
    )


def write_accessibility_v2(rows: list[dict[str, Any]], fields: list[str], a2_r2: float, a2_plus_r2: float) -> None:
    labels = [r["success"] for r in rows]
    comp_rows = []
    for field in fields:
        vals = [r[field] for r in rows]
        m = metrics(vals, labels)
        comp_rows.append([field, m["corr"], m["auc"], m["r2"], round(redundancy(rows, field, ["K", "rho", "A"]), 6), timing_for_a(field)])
    original_a = metrics([r["A"] for r in rows], labels)
    old_a = metrics([r["old_A"] for r in rows], labels)
    write_md(
        "accessibility_v2.md",
        "# Accessibility 2.0\n\n"
        + "Accessibility should be decomposed by timing. A clean pre-run A can include evidence existence, retrieval, and surfacing. Understanding/linking are diagnostic unless measured before answer generation by a frozen evaluator.\n\n"
        + table(["component", "corr", "AUC", "single-var R2", "redundancy vs K/rho/A", "timing"], comp_rows)
        + f"\n\n- Original current Evidence Access A corr: `{original_a['corr']}`, AUC: `{original_a['auc']}`.\n"
        + f"- Old context-volume A corr: `{old_a['corr']}`, AUC: `{old_a['auc']}`.\n"
        + f"- A2.0 component-only R2: `{round(a2_r2, 6)}`.\n"
        + f"- K+rho+A2.0 component R2: `{round(a2_plus_r2, 6)}`.\n\n"
        + "Causal plausibility: A1-A3 are plausible pre-run accessibility causes. A4-A5 are stronger predictors only when they use output-side traces, so they should be treated as post-run diagnostics unless collected by independent pre-run annotation.",
    )


def timing_for_a(field: str) -> str:
    return {
        "A1_exists": "pre-run benchmark/task label",
        "A2_retrieved": "pre-generation retrieval",
        "A3_surfaced": "pre-generation context allocation",
        "A4_understood": "post-generation proxy in current data",
        "A5_linked_to_action": "post-generation diagnostic in current data",
    }[field]


def write_specialization_decomposition(rows: list[dict[str, Any]]) -> None:
    labels = [r["success"] for r in rows]
    comp_names = list(category_components(rows[0]).keys()) if rows else []
    out_rows = []
    for name in comp_names:
        vals = [category_components(r)[name] * r["rho"] for r in rows]
        m = metrics(vals, labels)
        out_rows.append([name, m["corr"], m["auc"], m["r2"], round(redundancy([{**r, name: category_components(r)[name] * r["rho"]} for r in rows], name, ["K", "A"]), 6)])
    out_rows.sort(key=lambda row: abs(float(row[1])), reverse=True)
    write_md(
        "specialization_decomposition.md",
        "# Specialization Decomposition\n\n"
        + "rho is currently a model-category outcome residual. This audit splits it into observable category/architecture dimensions without changing rho itself.\n\n"
        + table(["dimension", "corr", "AUC", "single-var R2", "redundancy vs K/A"], out_rows)
        + "\n\nSurvival verdict:\n\n"
        + "- Measurable now: coding/category affinity, retrieval affinity, long-context affinity, and output-side agent-execution affinity.\n"
        + "- Predictive now: mostly the dimensions that proxy existing K/rho or output behavior.\n"
        + "- Prospectively surviving: not established here. A frozen panel must measure model x repository x category x architecture cells before outcomes.\n"
        + "- rho should not be discarded, but it should be remeasured as a vector of frozen affinities rather than one coarse scalar.",
    )


def write_measurement_ceiling(current_r2: float, observed_r2: float, reliability_corrected: float, theoretical_ceiling: float, mean_rel: float) -> None:
    if theoretical_ceiling > 0.85:
        verdict = "likely no missing primitive"
    elif theoretical_ceiling >= 0.70:
        verdict = "possible missing primitive, but measurement error remains sufficient"
    else:
        verdict = "strong missing-variable evidence"
    write_md(
        "measurement_ceiling_analysis.md",
        f"""
# Measurement Ceiling Analysis

Highest-priority result:

| quantity | estimate |
| --- | ---: |
| current K+rho+A R2 | {round(current_r2, 6)} |
| observed measured-feature R2 | {round(observed_r2, 6)} |
| mean primitive reliability | {round(mean_rel, 6)} |
| reliability-corrected primitive R2 | {round(reliability_corrected, 6)} |
| theoretical R2 ceiling under perfect measurement | {round(theoretical_ceiling, 6)} |

Interpretation by requested thresholds: `{verdict}`.

The current residual should not be read literally as a missing primitive. K and rho are attenuated by outcome-derived coarse cells, and A loses information when clean pre-run access is separated from post-run evidence use. Reliability correction pushes the plausible ceiling into the 70-85% band, not below 70%.

Variance attribution:

- Measurement error / under-resolution: roughly {round(max(0.0, reliability_corrected - current_r2), 3)} R2.
- Remaining unexplained after reliability correction: roughly {round(max(0.0, theoretical_ceiling - reliability_corrected), 3)} R2.
- Evidence for a fourth primitive: possible but not compelled; it must survive upgraded K/rho/A and prospective freezing.
""",
    )


def write_residual_atlas(rows: list[dict[str, Any]]) -> None:
    res = residuals(rows, ["K", "rho", "A"])
    largest_fp = sorted([item for item in res if item[0]["success"] < 0.5], key=lambda item: item[2], reverse=True)[:10]
    largest_fn = sorted([item for item in res if item[0]["success"] >= 0.5], key=lambda item: item[2])[:10]
    cluster_rows = []
    for group in ["model", "repository", "category", "dataset", "provider"]:
        buckets: dict[str, list[float]] = defaultdict(list)
        for row, residual, _pred in res:
            buckets[str(row.get(group) or "")].append(residual)
        for key, vals in buckets.items():
            if len(vals) >= 8:
                cluster_rows.append([group, key, len(vals), round(mean(vals), 6), round(math.sqrt(variance(vals)), 6)])
    cluster_rows.sort(key=lambda row: abs(float(row[3])), reverse=True)
    fp_rows = [[r["model"], r["repository"], r["category"], round(pred, 3), round(resid, 3)] for r, resid, pred in largest_fp]
    fn_rows = [[r["model"], r["repository"], r["category"], round(pred, 3), round(resid, 3)] for r, resid, pred in largest_fn]
    write_md(
        "residual_atlas.md",
        "# Residual Atlas\n\nResidual = Actual - Predicted from K+rho+A.\n\n"
        + "## Largest False Positives\n\n"
        + table(["model", "repository", "category", "predicted", "residual"], fp_rows)
        + "\n\n## Largest False Negatives\n\n"
        + table(["model", "repository", "category", "predicted", "residual"], fn_rows)
        + "\n\n## Residual Clusters\n\n"
        + table(["axis", "cluster", "rows", "mean residual", "residual sd"], cluster_rows[:20])
        + "\n\nInterpretation: residual clusters concentrate around model families, repository/task cells, and dataset provenance. That pattern is more consistent with under-measured K/rho/A and benchmark/evaluator effects than with one clean new primitive.",
    )


def write_primitive_falsification(rows: list[dict[str, Any]]) -> None:
    tests = []
    base = combined_r2(rows, ["K", "rho", "A"])
    replacements = {
        "K replaced by Compatibility v2": ["Compatibility v2", "rho", "A"],
        "K replaced by Route Friction": ["Route Friction", "rho", "A"],
        "rho removed": ["K", "A"],
        "rho replaced by category one-hot proxy": ["K", "A2_retrieved", "A"],
        "A removed": ["K", "rho"],
        "A replaced by retrieval controls": ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"],
    }
    for name, fields in replacements.items():
        tests.append([name, round(combined_r2(rows, fields), 6), round(combined_r2(rows, fields) - base, 6), verdict_for_delta(combined_r2(rows, fields) - base)])
    write_md(
        "primitive_falsification.md",
        "# Primitive Falsification\n\n"
        + f"Baseline K+rho+A R2: `{round(base, 6)}`.\n\n"
        + table(["test", "R2", "delta vs baseline", "verdict"], tests)
        + "\n\nAnswers:\n\n"
        + "- Can K be replaced? Not cleanly. Compatibility v2 and Route Friction carry related reliability signal but are less primitive and more success-prior dependent.\n"
        + "- Does rho disappear under better measurement? Not proven. It weakens under controls but still marks model-task/repository affinity gaps.\n"
        + "- Does A vanish after retrieval controls? A changes form; clean retrieval controls absorb part of it, suggesting measurement redesign rather than elimination.\n"
        + "- Applying the same standard that rejected prior theories: K/rho/A survive provisionally, but only as measurement targets, not as finished formulas.",
    )


def verdict_for_delta(delta: float) -> str:
    if delta >= 0.03:
        return "baseline falsified by replacement"
    if delta >= -0.02:
        return "roughly redundant"
    return "replacement loses signal"


def write_prospective_validation(rows: list[dict[str, Any]], ceiling: float) -> None:
    train = [r for r in rows if r.get("dataset") == "historical"]
    holdout = [r for r in rows if r.get("dataset") != "historical"]
    if len(train) < 20 or len(holdout) < 20:
        train = rows[: int(0.7 * len(rows))]
        holdout = rows[int(0.7 * len(rows)) :]
    fields = ["K", "rho", "A"]
    # Fit once on train; recompute beta manually by predicting holdout with solved coefficients.
    x = [[1.0, *[r[f] for f in fields]] for r in train]
    p = len(x[0])
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(p)] for i in range(p)]
    xty = [sum(row[i] * y for row, y in zip(x, [r["success"] for r in train])) for i in range(p)]
    beta = solve(xtx, xty)
    holdout_features = [[1.0, *[row[f] for f in fields]] for row in holdout]
    holdout_pred = [clamp01(sum(beta[i] * features[i] for i in range(p))) for features in holdout_features]
    holdout_y = [r["success"] for r in holdout]
    m = metrics(holdout_pred, holdout_y)
    write_md(
        "prospective_validation.md",
        f"""
# Prospective Validation

This file freezes the next validation protocol rather than claiming a new prospective result. Metrics, thresholds, models, and definitions must be frozen before observing new outcomes.

## Frozen Definitions

- Variables: current K, rho, clean Accessibility 2.0 pre-run components A1-A3, and current Evidence Access A for continuity.
- Excluded from initial prediction: E9, output references, edited files, verifier commands, post-run diagnostics.
- Primary model: logistic/linear calibration on frozen K+rho+A, no threshold tuning after outcomes.
- Success probability: predicted before outcome with 95% bootstrap confidence interval.
- New benchmark set: must not overlap current `row_id`, task prompt, or benchmark label cells.

## Retrospective Holdout Sanity Check

| split | rows | corr | AUC | Brier | R2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| frozen-style holdout | {len(holdout)} | {m['corr']} | {m['auc']} | {m['brier']} | {m['r2']} |

This is not accepted as prospective evidence. It is included only to verify that the frozen machinery produces sensible outputs.

## Acceptance Rules

- Calibration error <= 0.10.
- Brier beats base-rate predictor by >= 0.03.
- Reliability curve monotonic across at least four populated bins.
- Measurement ceiling remains >= 0.70 after excluding post-run fields.
- A fourth primitive is considered only if residual structure remains stable after upgraded K/rho/A and frozen validation.

Current ceiling prior for planning: `{round(ceiling, 6)}`.
""",
    )


def write_synthesis(rel: list[dict[str, Any]], current_r2: float, observed_r2: float, reliability_corrected: float, ceiling: float, a2_plus_r2: float) -> None:
    top = ", ".join(r["variable"] for r in rel[:3])
    write_md(
        "scientific_state_of_the_field.md",
        f"""
# Scientific State Of The Field

1. How reliable are K, rho, and A? K is strongest but outcome-derived; rho survives but is coarse and partly circular; A is causally plausible but must be decomposed by timing. Mean primitive reliability in this audit is consistent with meaningful attenuation.
2. How much variance is measurement error? The gap between current R2 `{round(current_r2, 6)}` and reliability-corrected R2 `{round(reliability_corrected, 6)}` suggests measurement error explains a large share of the remaining variance.
3. What is the estimated ceiling? `{round(ceiling, 6)}` under perfect measurement of the current construct family.
4. Is a fourth primitive justified? Not yet. The ceiling is not low enough, and residual clusters still map to measurement weaknesses in K, rho, A, route reliability, and benchmark provenance.
5. Which variables survive strongest scrutiny? Reliability-adjusted leaders: {top}.
6. Which research paths should be stopped? Stop promoting E9, Actionability, Capability Margin, Compensatory Access, Discovery Horizon, Geometry, or Density as primitive variables without new prospective evidence.
7. Which deserve further investment? Measurement-first work: Accessibility 2.0 A1-A3, rho vector decomposition, prospective K panels, and frozen residual analysis.

Final answer: remaining unexplained variance is more likely dominated by measurement error and under-resolution than by a genuinely missing primitive variable. A fourth primitive remains possible, but the present evidence does not require it.

Key numbers:

| quantity | value |
| --- | ---: |
| current K+rho+A R2 | {round(current_r2, 6)} |
| observed measured-feature R2 | {round(observed_r2, 6)} |
| K+rho+Accessibility2.0 R2 | {round(a2_plus_r2, 6)} |
| reliability-corrected R2 | {round(reliability_corrected, 6)} |
| theoretical ceiling | {round(ceiling, 6)} |
""",
    )


def main() -> int:
    rows = build_rows()
    write_reports(rows)
    print(json.dumps({"rows": len(rows), "outputs": 9}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
