from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / ".agent-hub" / "research"


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def corr(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = mean(xs)
    my = mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return 0.0 if dx == 0.0 or dy == 0.0 else num / (dx * dy)


def auc(scores: list[float], labels: list[float]) -> float:
    pairs = sorted(zip(scores, labels), key=lambda item: item[0])
    pos = sum(1 for _score, label in pairs if label >= 0.5)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rank_sum = 0.0
    index = 0
    while index < len(pairs):
        end = index + 1
        while end < len(pairs) and pairs[end][0] == pairs[index][0]:
            end += 1
        avg_rank = (index + 1 + end) / 2.0
        rank_sum += avg_rank * sum(1 for _score, label in pairs[index:end] if label >= 0.5)
        index = end
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def brier(scores: list[float], labels: list[float]) -> float:
    return mean((clamp01(score) - label) ** 2 for score, label in zip(scores, labels)) if scores else 0.0


def linear_fit_predict(features: list[list[float]], targets: list[float]) -> list[float]:
    if not features:
        return []
    x = [[1.0, *row] for row in features]
    xtx = [[sum(row[i] * row[j] for row in x) for j in range(len(x[0]))] for i in range(len(x[0]))]
    xty = [sum(row[i] * target for row, target in zip(x, targets)) for i in range(len(x[0]))]
    beta = solve(xtx, xty)
    return [sum(coef * value for coef, value in zip(beta, row)) for row in x]


def solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    aug = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) < 1e-12:
            aug[col][col] += 1e-6
            pivot = col
        aug[col], aug[pivot] = aug[pivot], aug[col]
        div = aug[col][col]
        aug[col] = [value / div for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [value - factor * base for value, base in zip(aug[row], aug[col])]
    return [aug[row][-1] for row in range(n)]


def r2(actual: list[float], predicted: list[float]) -> float:
    if not actual:
        return 0.0
    baseline = mean(actual)
    total = sum((value - baseline) ** 2 for value in actual)
    residual = sum((value - pred) ** 2 for value, pred in zip(actual, predicted))
    return 0.0 if total == 0.0 else 1.0 - residual / total


def metrics(values: list[float], labels: list[float]) -> dict[str, float]:
    preds = linear_fit_predict([[value] for value in values], labels)
    return {
        "rows": len(values),
        "corr": round(corr(values, labels), 6),
        "auc": round(auc(values, labels), 6),
        "brier_as_probability": round(brier(values, labels), 6),
        "linear_r2": round(r2(labels, preds), 6),
    }


def load_json(name: str) -> Any:
    return json.loads((RESEARCH / name).read_text(encoding="utf-8"))


def evidence_rows() -> list[dict[str, Any]]:
    return load_json("evidence_access_dataset.json")["rows"]


def action_rows() -> list[dict[str, Any]]:
    return load_json("actionability_dataset.json")["rows"]


def row_pairs() -> list[dict[str, Any]]:
    evidence = evidence_rows()
    actions = action_rows()
    rows = []
    for index, action in enumerate(actions):
        if index >= len(evidence):
            continue
        ev = evidence[index]
        action_id = str(action.get("row_id") or "")
        evidence_id = str(ev.get("row_id") or "")
        if action_id and evidence_id and action_id != evidence_id:
            raise ValueError(f"row alignment mismatch at {index}: {action_id} != {evidence_id}")
        row = {**action, "_evidence": ev}
        rows.append(row)
    return rows


def value(row: dict[str, Any], field: str, default: float = 0.0) -> float:
    raw = row.get(field)
    return default if raw in (None, "") else float(raw)


def component_values(rows: list[dict[str, Any]], name: str) -> tuple[list[float], list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    action: list[float] = []
    for row in rows:
        component = row["_evidence"]["components"].get(name)
        if component is None:
            continue
        xs.append(float(component))
        ys.append(value(row, "outcome"))
        action.append(value(row, "actionability_score"))
    return xs, ys, action


def infer_e9_parts(row: dict[str, Any]) -> dict[str, float | None]:
    components = row["_evidence"]["components"]
    e6 = components.get("E6")
    e7 = components.get("E7")
    e8 = components.get("E8")
    e9 = components.get("E9")
    if e9 is None:
        action_cues = None
    elif e6 is None and e7 is None and e8 is None:
        action_cues = float(e9)
    else:
        known = [float(part) for part in (e6, e7, e8) if part is not None]
        action_cues = clamp01(float(e9) * (len(known) + 1) - sum(known))
    return {
        "E6_noticed_decisive": None if e6 is None else float(e6),
        "E7_edit_distance": None if e7 is None else float(e7),
        "E8_verifier_distance": None if e8 is None else float(e8),
        "output_action_cues": action_cues,
    }


def pre_run_features(row: dict[str, Any]) -> list[float]:
    ev = row["_evidence"]
    components = ev["components"]
    selected = float(ev.get("selected_file_count") or 0.0)
    expected = float(row.get("trace_counts", {}).get("expected_files") or len(ev.get("benchmark_expected_files") or []))
    relevant = float(row.get("trace_counts", {}).get("relevant_files") or len(ev.get("benchmark_relevant_files") or []))
    return [
        float(components.get("E1") or 0.0),
        float(components.get("E2") or 0.0),
        float(components.get("E3") or 0.0),
        float(components.get("E4") or 0.0),
        float(components.get("E5") or 0.0),
        0.0 if components.get("E10") is None else 1.0 - float(components.get("E10")),
        clamp01(value(row, "context_budget") / 100.0),
        math.log1p(selected) / math.log1p(60.0),
        math.log1p(expected) / math.log1p(10.0),
        math.log1p(relevant) / math.log1p(10.0),
    ]


def pre_run_e9(rows: list[dict[str, Any]]) -> list[float]:
    targets = [value(row, "E9_evidence_actionability") for row in rows]
    features = [pre_run_features(row) for row in rows]
    return [clamp01(pred) for pred in linear_fit_predict(features, targets)]


def residuals(rows: list[dict[str, Any]], fields: list[str]) -> list[float]:
    filtered = [row for row in rows if all(row.get(field) is not None for field in fields)]
    features = [[value(row, field) for field in fields] for row in filtered]
    labels = [value(row, "outcome") for row in filtered]
    preds = linear_fit_predict(features, labels)
    by_id = {row["row_id"]: label - pred for row, label, pred in zip(filtered, labels, preds)}
    return [by_id.get(row["row_id"], 0.0) for row in rows]


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def write(name: str, text: str) -> None:
    (RESEARCH / name).write_text(text.strip() + "\n", encoding="utf-8")


def main() -> int:
    rows = row_pairs()
    labels = [value(row, "outcome") for row in rows]
    clean_action = [value(row, "actionability_score") for row in rows]
    e9 = [value(row, "E9_evidence_actionability") for row in rows]
    pre_e9 = pre_run_e9(rows)
    access_a = [value(row, "Accessibility") for row in rows]

    component_rows = []
    for name in [f"E{i}" for i in range(1, 11)]:
        if name == "E9":
            xs = [value(row, "E9_evidence_actionability") for row in rows]
            ys = [value(row, "outcome") for row in rows]
            action = [value(row, "actionability_score") for row in rows]
        else:
            xs, ys, action = component_values(rows, name)
        timing = {
            "E1": "pre-run after retrieval",
            "E2": "pre-run after retrieval",
            "E3": "pre-run after retrieval",
            "E4": "pre-run after retrieval",
            "E5": "pre-run benchmark/retrieval",
            "E6": "post-generation output reference",
            "E7": "post-run edit trace",
            "E8": "post-run verifier trace",
            "E9": "post-generation diagnostic",
            "E10": "pre-run after retrieval",
        }[name]
        risk = {
            "E1": "low",
            "E2": "low",
            "E3": "low",
            "E4": "low",
            "E5": "low",
            "E6": "high",
            "E7": "high",
            "E8": "high",
            "E9": "high",
            "E10": "low",
        }[name]
        component_rows.append([name, len(xs), round(corr(xs, ys), 6), round(corr(xs, action), 6), timing, risk])

    sub_rows = []
    for name in ["E6_noticed_decisive", "E7_edit_distance", "E8_verifier_distance", "output_action_cues"]:
        xs = []
        ys = []
        action = []
        for row in rows:
            part = infer_e9_parts(row)[name]
            if part is None:
                continue
            xs.append(float(part))
            ys.append(value(row, "outcome"))
            action.append(value(row, "actionability_score"))
        sub_rows.append([name, len(xs), round(mean(xs), 6) if xs else 0.0, round(corr(xs, ys), 6), round(corr(xs, action), 6)])

    trust_rows = []
    for label, values in [
        ("E9 original", e9),
        ("E9 pre-run approximation", pre_e9),
        ("clean A1-A10 Actionability", clean_action),
        ("Evidence Access A", access_a),
    ]:
        m = metrics(values, labels)
        high = [out for val, out in zip(values, labels) if val >= 0.5]
        low = [out for val, out in zip(values, labels) if val < 0.5]
        trust_rows.append(
            [
                label,
                m["corr"],
                m["auc"],
                m["brier_as_probability"],
                m["linear_r2"],
                round(mean(high), 6) if high else "n/a",
                round(mean(low), 6) if low else "n/a",
            ]
        )

    residual_specs = [
        ("K+rho+A", ["K", "rho", "Accessibility"]),
        ("Compatibility v2", ["compatibility_v2"]),
        ("Evidence Access A", ["Accessibility"]),
        ("clean Actionability", ["actionability_score"]),
    ]
    residual_rows = []
    for label, fields in residual_specs:
        res = residuals(rows, fields)
        residual_rows.append([label, round(corr(e9, res), 6), round(corr(pre_e9, res), 6), round(corr(clean_action, res), 6)])

    source_counts: dict[str, int] = {}
    no_label_e9s = []
    for row in rows:
        source_counts[row.get("dataset", "")] = source_counts.get(row.get("dataset", ""), 0) + 1
        ev = row["_evidence"]
        if ev.get("label_source") == "unavailable":
            no_label_e9s.append(value(row, "E9_evidence_actionability"))

    write(
        "e9_definition_audit.md",
        f"""
# E9 Definition Audit

Exact formula from `agent_hub/research/evidence_access_measurement.py`:

`E9 = mean(available_action_parts)`, where `available_action_parts = [E6, E7, E8, action_cues]` after dropping `None` values.

Subformulas:

- `E6 = noticed_decisive / decisive_hits`, where `noticed_decisive = selected decisive files referenced in model output`.
- `E7 = distance_score(selected files, decisive hits, edited files)`.
- `E8 = distance_score(selected files, decisive hits, verifier files/commands)`.
- `action_cues = clamp01((count(action words in output_preview) + verifier_bonus) / 6)`.

Source fields used:

- Retrieval/context fields: `selected_files`, `context_files`, `context_token_counts`, and selected-file ordering.
- Benchmark/task labels: `benchmark_expected_files`, `expected_files`, `focus_files`, `benchmark_relevant_files`, `relevant_files`, `gold_patch_files`, and benchmark `tests`.
- Model-output fields: `output_preview`, `files_referenced_in_output`, `referenced_files`, `output_referenced_files`.
- Post-run action fields: `files_actually_edited`, `edited_files`, `files_edited`, `modified_files`, `patch_files`, `tests_or_verifiers_triggered`, `tests_triggered`, `verifiers_triggered`, `commands_run`.

Audit answers:

- Uses model output: yes. `output_preview` is parsed for paths and action words.
- Uses edited files: yes by definition through E7, although this corpus has zero available E7 rows.
- Uses success-adjacent fields: yes. Output references, edited files, and verifier commands are behavioral traces produced by the same run whose success is being predicted.
- Uses post-run information: yes for output, edit, and verifier traces.
- Computable before the run: no. Only E1-E5/E10 are pre-run or retrieval-time; E9 itself requires at least generated output.

Corpus detail: E9 is available for {len(e9)} rows. E7 and E8 are available for zero rows, so the observed E9 signal is E6 plus inferred output action cues, not edit/test execution distance.
""",
    )

    write(
        "e9_leakage_timing_audit.md",
        f"""
# E9 Leakage And Timing Audit

Classification:

| class | verdict |
| --- | --- |
| pre-run clean | no |
| during-run trace | yes, if output text is treated as the run trace |
| post-run diagnostic | yes |
| outcome-adjacent | yes |
| leaky | yes for primitive-variable or pre-run causal claims |

Reason: E9 reads the model's generated answer, inferred referenced files, and optionally edited files or verifier commands. These are not task-side observables available before answer generation. They are part of the behavioral pathway from model attempt to success.

Measured correlations in the current cloud corpus:

- Corr(E9, success): {round(corr(e9, labels), 6)}
- Corr(clean A1-A10 Actionability, success): {round(corr(clean_action, labels), 6)}
- Corr(E9, clean Actionability): {round(corr(e9, clean_action), 6)}
- Mean E9 on rows without benchmark labels: {round(mean(no_label_e9s), 6) if no_label_e9s else "n/a"}

Verdict: E9 is a strong post-generation trace diagnostic, not a clean pre-run task variable.
""",
    )

    write(
        "e9_component_decomposition.md",
        "# E9 Component Decomposition\n\n"
        + "## Evidence Components\n\n"
        + md_table(["component", "rows", "corr with success", "corr with clean Actionability", "timing status", "leakage risk"], component_rows)
        + "\n\n## E9 Subcomponents Actually Used\n\n"
        + md_table(["subcomponent", "rows", "mean", "corr with success", "corr with clean Actionability"], sub_rows)
        + "\n\nE7 and E8 have no available rows in this corpus. Therefore, original E9's strength comes from `E6_noticed_decisive` and `output_action_cues`, both of which require generated output.",
    )

    write(
        "e9_prerun_approximation.md",
        "# E9 Pre-run Approximation\n\n"
        + "A clean approximation was fit to original E9 using only pre-generation fields: E1-E5, usable context efficiency from E10, context budget, selected-file count, expected-file count, and relevant-file count. It was fit to E9 itself, not to success, so this is an approximation audit rather than a new success theory.\n\n"
        + f"- Corr(pre-run approximation, original E9): {round(corr(pre_e9, e9), 6)}\n"
        + f"- Corr(pre-run approximation, clean Actionability): {round(corr(pre_e9, clean_action), 6)}\n\n"
        + md_table(["score", "corr with success", "AUC", "Brier if used as probability", "linear R2", "success rate score>=0.5", "success rate score<0.5"], trust_rows)
        + "\n\nThe pre-run approximation recovers only a minority of E9's success signal. That gap is the behavioral/output part of E9, not clean task-side actionability.",
    )

    write(
        "e9_diagnostic_value.md",
        "# E9 Post-run Diagnostic Value\n\n"
        + md_table(["score", "corr with success", "AUC", "Brier if used as probability", "linear R2", "success rate score>=0.5", "success rate score<0.5"], trust_rows)
        + "\n\nDiagnostic interpretation:\n\n"
        + "- Trust scoring: yes, E9 is strong as an after-generation trust signal because high E9 means the answer referred to decisive evidence and used action/verification language.\n"
        + "- Failure detection: yes, low E9 is a useful warning that the answer did not visibly connect decisive evidence to an action.\n"
        + "- Rerouting/retry: yes after a first draft/run. It can support retry decisions, but cannot choose the initial route cleanly.\n"
        + "- Causal primitive use: no. The diagnostic value depends on seeing the model's behavior, so it should not be interpreted as pre-run causal structure.",
    )

    write(
        "e9_residual_test.md",
        "# E9 Residual Test\n\n"
        + "Residual is `Outcome - linear_prediction(baseline)` within the matched cloud rows. The pre-run column uses the clean E9 approximation; the post-run column uses original E9.\n\n"
        + md_table(["baseline", "post-run E9 residual corr", "pre-run E9 approximation residual corr", "clean Actionability residual corr"], residual_rows)
        + "\n\nSeparation:\n\n"
        + "- Pre-run explanatory value: limited. The clean approximation is consistently weaker than original E9 against residuals.\n"
        + "- Post-run diagnostic value: strong. Original E9 explains residual behavior left by several pre-run or fixed theory scores because it observes the generated answer.",
    )

    write(
        "e9_forensic_verdict.md",
        f"""
# E9 Forensic Verdict

1. Is E9 clean? No. It uses generated output and optionally post-run edit/verifier traces.
2. Is E9 leaky? Yes for primitive-variable, routing, and pre-run causal claims. It is not leaky if explicitly framed as a post-generation diagnostic.
3. Is E9 pre-run causal or post-run diagnostic? Post-run diagnostic. In this corpus, its active pieces are mostly output reference behavior and action-language cues.
4. Why did clean Actionability fail while E9 succeeded? Clean Actionability measures task-side conversion affordance with fixed pre-run components. E9 succeeds because it measures whether the model actually converted evidence into an answer-like action after generation. That is closer to realized competence/answer quality than to task-side actionability.
5. Can E9 be converted into a clean pre-run variable? Only partially. The clean approximation has corr={round(corr(pre_e9, e9), 6)} with original E9 and corr={metrics(pre_e9, labels)['corr']} with success, below original E9's corr={round(corr(e9, labels), 6)}.
6. Is E9 useful for routing, retry, or answer trust scoring? Useful for answer trust scoring and retry/reroute after a draft is generated. Not valid for initial routing unless replaced by a much weaker clean proxy.
7. Should E9 be excluded from primitive-variable claims? Yes. It should be excluded from primitive-variable claims and retained only as a diagnostic trace variable.

Scientific bottom line: the strongest E9 signal is measurement contamination for causal/pre-run purposes, but it is real behavioral information for post-generation diagnostics.
""",
    )
    print(json.dumps({"rows": len(rows), "corr_e9_success": round(corr(e9, labels), 6), "corr_pre_e9_success": round(corr(pre_e9, labels), 6)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
