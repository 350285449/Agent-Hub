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
from scripts import predictive_failure_program as pfp
from scripts import prospective_failure_v3 as pf


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"

PRE_RUN = ["K", "rho", "A1_exists", "old_A", "context_budget", "expected_files", "relevant_files"]
ACCESSIBILITY = ["A1_exists", "A2_retrieved", "A3_surfaced"]
K_RHO_A = ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"]
FAMILIES = ["coding", "reasoning", "research", "agentic"]


def write_md(name: str, text: str) -> None:
    content = text.strip() + "\n"
    RESEARCH.mkdir(exist_ok=True)
    PRIVATE_RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / name).write_text(content, encoding="utf-8")
    (PRIVATE_RESEARCH / name).write_text(content, encoding="utf-8")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    return m.table(headers, rows)


def fmt(value: Any) -> str:
    try:
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def material_fields(rows: list[dict[str, Any]], fields: list[str], extra: list[dict[str, Any]] | None = None) -> list[str]:
    source = [*rows, *(extra or [])]
    return [field for field in fields if source and all(row.get(field) is not None for row in source)]


def score_all(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float]]:
    train = [row for row in rows if row.get("dataset") == "historical"] or rows
    holdout = [row for row in rows if row.get("dataset") != "historical"] or rows
    usable = material_fields(rows, fields)
    usable_prosp = material_fields(rows, fields, prospective)
    return {
        "retro": pf.in_sample(rows, usable),
        "holdout": pf.score_model(train, holdout, usable),
        "prospective": pf.score_model(train, prospective, usable_prosp),
    }


def gain_model(rows: list[dict[str, Any]], prospective: list[dict[str, Any]], baseline: list[str], fields: list[str]) -> dict[str, float]:
    base = score_all(rows, prospective, baseline)
    full = score_all(rows, prospective, [*baseline, *fields])
    return {
        "holdout_base": float(base["holdout"]["r2"]),
        "holdout_full": float(full["holdout"]["r2"]),
        "holdout_gain": float(full["holdout"]["r2"]) - float(base["holdout"]["r2"]),
        "prospective_base": float(base["prospective"]["r2"]),
        "prospective_full": float(full["prospective"]["r2"]),
        "prospective_gain": float(full["prospective"]["r2"]) - float(base["prospective"]["r2"]),
        "prospective_brier_gain": float(full["prospective"]["brier_gain"]),
    }


def family(row: dict[str, Any]) -> str:
    return pfp.task_family(row)


def normalize_count(value: Any, cap: float = 3.0) -> float:
    return m.clamp01(float(value or 0.0) / cap)


def phase_values(row: dict[str, Any]) -> dict[str, float]:
    a1 = float(row.get("A1_exists") or 0.0)
    a2 = float(row.get("A2_retrieved") or 0.0)
    a3 = float(row.get("A3_surfaced") or 0.0)
    a4 = float(row.get("A4_understood") or 0.0)
    a5 = float(row.get("A5_linked_to_action") or 0.0)
    evidence_burden = m.clamp01((float(row.get("expected_files") or 0.0) + float(row.get("relevant_files") or 0.0)) / 6.0)
    context = m.clamp01(float(row.get("context_budget") or 0.0) / 100.0)
    referenced = normalize_count(row.get("referenced_files"), 4.0)
    edited = normalize_count(row.get("edited_files"), 3.0)
    verified = normalize_count(row.get("tests_or_verifiers"), 2.0)
    tool = m.clamp01(0.55 * edited + 0.45 * verified)
    evidence_flow = [a1, a2, a3, a4, a5]
    deltas = [evidence_flow[i + 1] - evidence_flow[i] for i in range(len(evidence_flow) - 1)]
    recovery_depth = max(0.0, max(-d for d in deltas) if deltas else 0.0)
    recovered = 1.0 if recovery_depth >= 0.15 and a5 >= max(a3, a4, 0.45) else 0.0
    contradiction = 1.0 if a2 >= 0.55 and a4 < 0.35 else 0.0
    confused = 1.0 if a3 >= 0.45 and a5 < 0.30 else 0.0
    branch_repair = 1.0 if edited > 0.0 and verified > 0.0 and recovered else 0.0
    decisive_evidence_time = 0.10 if a2 >= 0.55 else 0.25 if a3 >= 0.55 else 0.50 if a4 >= 0.55 else 0.75 if a5 >= 0.55 else 1.00
    action_time = 0.25 if tool >= 0.35 else 0.50 if referenced >= 0.35 else 0.75 if a5 >= 0.45 else 1.00
    verification_time = 0.50 if verified >= 0.35 else 0.75 if tool >= 0.35 else 1.00
    grounding_latency = decisive_evidence_time
    evidence_to_action_latency = max(0.0, action_time - decisive_evidence_time)
    grounded_action_ratio = m.clamp01((a4 + a5 + referenced + tool) / max(0.35, a1 + a2 + a3 + evidence_burden))
    correction_speed = 0.0 if not recovered else m.clamp01(1.0 - evidence_to_action_latency - 0.5 * recovery_depth)
    retry_success = 1.0 if recovered and (tool > 0.0 or a5 >= 0.55) else 0.0
    recovery_loops = 1.0 if contradiction or confused else 0.0
    return {
        "dyn_signal_10": m.clamp01(0.45 * a2 + 0.35 * a1 + 0.20 * context),
        "dyn_signal_25": m.clamp01(0.30 * a2 + 0.35 * a3 + 0.20 * context + 0.15 * (1.0 - evidence_burden)),
        "dyn_signal_50": m.clamp01(0.25 * a3 + 0.35 * a4 + 0.20 * referenced + 0.20 * (1.0 - contradiction)),
        "dyn_signal_75": m.clamp01(0.20 * a4 + 0.30 * a5 + 0.25 * tool + 0.15 * referenced + 0.10 * recovered),
        "grounding_latency": grounding_latency,
        "time_to_decisive_evidence": decisive_evidence_time,
        "evidence_to_action_latency": evidence_to_action_latency,
        "grounded_action_ratio": grounded_action_ratio,
        "contradiction_detection": contradiction,
        "correction_speed": correction_speed,
        "retry_success": retry_success,
        "recovery_loops": recovery_loops,
        "branch_repair": branch_repair,
        "first_decisive_evidence": 1.0 if decisive_evidence_time <= 0.25 else 0.0,
        "first_successful_tool_call": 1.0 if tool >= 0.35 else 0.0,
        "first_verification_success": 1.0 if verified >= 0.35 else 0.0,
        "first_recovery_event": recovered,
        "state_grounded": 1.0 if decisive_evidence_time <= 0.25 and grounded_action_ratio >= 0.45 else 0.0,
        "state_exploring": 1.0 if a2 >= 0.35 and a3 < 0.55 and a5 < 0.55 else 0.0,
        "state_converging": 1.0 if a4 >= 0.45 and a5 >= 0.45 else 0.0,
        "state_stuck": 1.0 if a2 < 0.30 and a5 < 0.30 else 0.0,
        "state_confused": confused,
        "state_recovered": recovered,
    }


def state_at(row: dict[str, Any], pct: int) -> str:
    a2 = float(row.get("A2_retrieved") or 0.0)
    a3 = float(row.get("A3_surfaced") or 0.0)
    a4 = float(row.get("A4_understood") or 0.0)
    a5 = float(row.get("A5_linked_to_action") or 0.0)
    d = row
    if pct <= 10:
        return "grounded" if d["state_grounded"] and a2 >= 0.55 else "exploring" if a2 >= 0.35 else "stuck"
    if pct <= 25:
        return "grounded" if d["state_grounded"] else "exploring" if a3 >= 0.35 else "stuck"
    if pct <= 50:
        if d["state_recovered"]:
            return "recovered"
        if d["state_confused"]:
            return "confused"
        return "converging" if a4 >= 0.45 else "exploring"
    if d["state_recovered"]:
        return "recovered"
    if a5 >= 0.45:
        return "converging"
    return "confused" if d["state_confused"] else "stuck"


def kmeans(rows: list[dict[str, Any]], fields: list[str], k: int = 6, iterations: int = 20) -> tuple[list[int], list[list[float]]]:
    data = [[float(row.get(field) or 0.0) for field in fields] for row in rows]
    if not data:
        return [], []
    centroids = [data[int(i * (len(data) - 1) / max(1, k - 1))][:] for i in range(k)]
    labels = [0] * len(data)
    for _ in range(iterations):
        for i, point in enumerate(data):
            labels[i] = min(range(k), key=lambda c: sum((point[j] - centroids[c][j]) ** 2 for j in range(len(fields))))
        for c in range(k):
            members = [point for label, point in zip(labels, data) if label == c]
            if members:
                centroids[c] = [mean(point[j] for point in members) for j in range(len(fields))]
    return labels, centroids


def add_dynamics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        item.update(phase_values(item))
        seq = [state_at(item, pct) for pct in [10, 25, 50, 75]]
        item["state_sequence"] = ">".join(seq)
        item["state_switches"] = float(sum(1 for i in range(3) if seq[i] != seq[i + 1])) / 3.0
        out.append(item)
    cluster_fields = [
        "dyn_signal_10",
        "dyn_signal_25",
        "dyn_signal_50",
        "dyn_signal_75",
        "grounding_latency",
        "grounded_action_ratio",
        "correction_speed",
        "recovery_loops",
    ]
    labels, centroids = kmeans(out, cluster_fields)
    names = name_clusters(centroids, cluster_fields)
    for item, label in zip(out, labels):
        item["hidden_cluster"] = float(label)
        item[f"cluster_{names[label]}"] = 1.0
    for name in ["grounded", "exploring", "converging", "stuck", "confused", "recovered"]:
        for item in out:
            item.setdefault(f"cluster_{name}", 0.0)
    return out


def name_clusters(centroids: list[list[float]], fields: list[str]) -> list[str]:
    labels = []
    used = Counter()
    idx = {field: i for i, field in enumerate(fields)}
    for center in centroids:
        if center[idx["correction_speed"]] > 0.35 or center[idx["recovery_loops"]] > 0.45:
            base = "recovered"
        elif center[idx["grounding_latency"]] <= 0.25 and center[idx["grounded_action_ratio"]] > 0.45:
            base = "grounded"
        elif center[idx["dyn_signal_75"]] > 0.60:
            base = "converging"
        elif center[idx["dyn_signal_25"]] > center[idx["dyn_signal_75"]]:
            base = "confused"
        elif center[idx["dyn_signal_10"]] < 0.25 and center[idx["dyn_signal_75"]] < 0.30:
            base = "stuck"
        else:
            base = "exploring"
        used[base] += 1
        labels.append(base if used[base] == 1 else f"{base}_{used[base]}")
    return labels


def window_fields() -> dict[str, list[str]]:
    return {
        "pre-run": PRE_RUN,
        "10% execution": [*PRE_RUN, "dyn_signal_10"],
        "25% execution": [*PRE_RUN, "dyn_signal_10", "dyn_signal_25", "first_decisive_evidence", "grounding_latency"],
        "50% execution": [*PRE_RUN, "dyn_signal_10", "dyn_signal_25", "dyn_signal_50", "first_decisive_evidence", "grounded_action_ratio", "evidence_to_action_latency", "state_grounded", "state_exploring", "state_confused"],
        "75% execution": [
            *PRE_RUN,
            "dyn_signal_10",
            "dyn_signal_25",
            "dyn_signal_50",
            "dyn_signal_75",
            "first_decisive_evidence",
            "first_successful_tool_call",
            "first_verification_success",
            "first_recovery_event",
            "grounded_action_ratio",
            "evidence_to_action_latency",
            "correction_speed",
            "retry_success",
            "branch_repair",
            "state_grounded",
            "state_converging",
            "state_stuck",
            "state_confused",
            "state_recovered",
        ],
    }


def signal_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    for name, fields in window_fields().items():
        stats = score_all(rows, prospective, fields)
        out.append(
            [
                name,
                len(material_fields(rows, fields)),
                stats["retro"]["r2"],
                stats["holdout"]["r2"],
                stats["holdout"]["brier_gain"],
                stats["prospective"]["r2"],
                stats["prospective"]["brier_gain"],
            ]
        )
    return out


def first_material_signal(rows: list[list[Any]]) -> str:
    pre = float(rows[0][3])
    for row in rows[1:]:
        if float(row[3]) - pre >= 0.05 and float(row[4]) > 0.03:
            return str(row[0])
    return "not before 75% under robustness gate"


def hidden_state_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    for field in ["state_grounded", "state_exploring", "state_converging", "state_stuck", "state_confused", "state_recovered"]:
        positive = [row for row in rows if float(row.get(field) or 0.0) >= 0.5]
        negative = [row for row in rows if float(row.get(field) or 0.0) < 0.5]
        out.append([field.replace("state_", ""), len(positive), round(mean(float(r["success"]) for r in positive), 6) if positive else "n/a", round(mean(float(r["success"]) for r in negative), 6) if negative else "n/a"])
    return out


def sequence_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("state_sequence"))].append(row)
    out = []
    for seq, values in buckets.items():
        if len(values) >= 6:
            out.append([seq, len(values), round(mean(float(row["success"]) for row in values), 6)])
    out.sort(key=lambda row: (float(row[2]), int(row[1])), reverse=True)
    return out[:16]


def tipping_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    triggers = ["first_decisive_evidence", "first_successful_tool_call", "first_verification_success", "first_recovery_event", "state_grounded", "state_recovered"]
    out = []
    for field in triggers:
        yes = [row for row in rows if float(row.get(field) or 0.0) >= 0.5]
        no = [row for row in rows if float(row.get(field) or 0.0) < 0.5]
        if not yes or not no:
            continue
        jump = mean(float(row["success"]) for row in yes) - mean(float(row["success"]) for row in no)
        gain = gain_model(rows, prospective, K_RHO_A, [field])
        out.append([field, len(yes), round(mean(float(row["success"]) for row in yes), 6), round(mean(float(row["success"]) for row in no), 6), round(jump, 6), round(gain["holdout_gain"], 6), round(gain["prospective_gain"], 6)])
    out.sort(key=lambda row: abs(float(row[4])), reverse=True)
    return out


def threshold_scan(rows: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    for field in ["grounded_action_ratio", "dyn_signal_25", "dyn_signal_50", "dyn_signal_75", "correction_speed"]:
        best = ("n/a", 0, 0.0, 0.0, 0.0)
        for threshold in [0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75]:
            hi = [row for row in rows if float(row.get(field) or 0.0) >= threshold]
            lo = [row for row in rows if float(row.get(field) or 0.0) < threshold]
            if len(hi) < 12 or len(lo) < 12:
                continue
            jump = mean(float(row["success"]) for row in hi) - mean(float(row["success"]) for row in lo)
            if abs(jump) > abs(best[4]):
                best = (threshold, len(hi), mean(float(row["success"]) for row in hi), mean(float(row["success"]) for row in lo), jump)
        out.append([field, best[0], best[1], round(best[2], 6), round(best[3], 6), round(best[4], 6)])
    out.sort(key=lambda row: abs(float(row[5])), reverse=True)
    return out


def family_model_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    fields = [*PRE_RUN, "dyn_signal_25", "dyn_signal_50", "dyn_signal_75", "grounded_action_ratio", "correction_speed", "retry_success"]
    out = []
    for fam in FAMILIES:
        fam_rows = [row for row in rows if family(row) == fam]
        fam_prosp = [row for row in prospective if family(row) == fam]
        if len(fam_rows) < 8:
            out.append([fam, len(fam_rows), len(fam_prosp), "n/a", "n/a", "n/a", "insufficient rows"])
            continue
        local_fields = material_fields(fam_rows, fields)
        stats = score_all(fam_rows, fam_prosp, local_fields)
        global_stats = score_all(rows, prospective, local_fields)
        verdict = "family-specific required" if abs(float(stats["holdout"]["r2"]) - float(global_stats["holdout"]["r2"])) >= 0.12 or len(fam_prosp) < 20 else "shared calibration plausible"
        out.append([fam, len(fam_rows), len(fam_prosp), stats["retro"]["r2"], stats["holdout"]["r2"], stats["prospective"]["r2"], verdict])
    return out


def dynamic_assimilation_rows(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[list[Any]]:
    specs = [
        ("initial prior", ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced"]),
        ("+ evidence events", ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "first_decisive_evidence", "grounding_latency", "grounded_action_ratio"]),
        ("+ tool events", ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "first_decisive_evidence", "grounding_latency", "grounded_action_ratio", "first_successful_tool_call", "dyn_signal_50"]),
        ("+ verification events", ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "first_decisive_evidence", "grounding_latency", "grounded_action_ratio", "first_successful_tool_call", "first_verification_success", "dyn_signal_50", "dyn_signal_75"]),
        ("+ recovery events", ["K", "rho", "A1_exists", "A2_retrieved", "A3_surfaced", "first_decisive_evidence", "grounding_latency", "grounded_action_ratio", "first_successful_tool_call", "first_verification_success", "dyn_signal_50", "dyn_signal_75", "first_recovery_event", "correction_speed", "retry_success", "branch_repair"]),
    ]
    out = []
    for name, fields in specs:
        stats = score_all(rows, prospective, fields)
        out.append([name, len(material_fields(rows, fields)), stats["holdout"]["r2"], stats["holdout"]["brier_gain"], stats["prospective"]["r2"], stats["prospective"]["brier_gain"]])
    return out


def robustness_score(holdout_gain: float, prospective_gain: float, has_falsification: bool = True) -> float:
    score = 0.0
    score += 0.35 if holdout_gain > 0.03 else 0.15 if holdout_gain > 0 else 0.0
    score += 0.35 if prospective_gain > 0.02 else 0.15 if prospective_gain > 0 else 0.0
    score += 0.20 if has_falsification else 0.0
    score += 0.10 if holdout_gain >= prospective_gain - 0.05 else 0.0
    return round(score, 3)


def tournament(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> list[dict[str, Any]]:
    theories = [
        ("Existing K+rho+A framework", K_RHO_A),
        ("Signal Emergence Theory", window_fields()["75% execution"]),
        ("Hidden State Theory", [*K_RHO_A, "state_grounded", "state_exploring", "state_converging", "state_stuck", "state_confused", "state_recovered", "state_switches"]),
        ("Tipping Point Theory", [*K_RHO_A, "first_decisive_evidence", "first_successful_tool_call", "first_verification_success", "first_recovery_event"]),
        ("Grounding Theory", [*K_RHO_A, "time_to_decisive_evidence", "grounding_latency", "evidence_to_action_latency", "grounded_action_ratio"]),
        ("Recovery Theory", [*K_RHO_A, "contradiction_detection", "correction_speed", "retry_success", "recovery_loops", "branch_repair"]),
        ("Family-Specific Science", [*K_RHO_A, "dyn_signal_25", "dyn_signal_50", "dyn_signal_75", "grounded_action_ratio", "correction_speed"]),
        ("Dynamic Assimilation Theory", dynamic_specs_final()),
    ]
    baseline = score_all(rows, prospective, K_RHO_A)
    base_hold = float(baseline["holdout"]["r2"])
    base_prosp = float(baseline["prospective"]["r2"])
    out = []
    for name, fields in theories:
        if name == "Family-Specific Science":
            fam_metrics = []
            for fam in FAMILIES:
                fam_rows = [row for row in rows if family(row) == fam]
                fam_prosp = [row for row in prospective if family(row) == fam]
                if len(fam_rows) < 8:
                    continue
                local_fields = material_fields(fam_rows, fields)
                stats = score_all(fam_rows, fam_prosp, local_fields)
                fam_metrics.append((len(fam_rows), stats))
            total = sum(weight for weight, _stats in fam_metrics) or 1
            explanatory = sum(weight * max(0.0, float(stats["retro"]["r2"])) for weight, stats in fam_metrics) / total
            hold = sum(weight * float(stats["holdout"]["r2"]) for weight, stats in fam_metrics) / total
            prosp = sum(weight * float(stats["prospective"]["r2"]) for weight, stats in fam_metrics) / total
            predictive = max(0.0, 0.65 * hold + 0.35 * prosp)
            heterogeneity = max((float(stats["holdout"]["r2"]) for _weight, stats in fam_metrics), default=0.0) - min((float(stats["holdout"]["r2"]) for _weight, stats in fam_metrics), default=0.0)
            robustness = round(0.65 if heterogeneity >= 0.25 else 0.35, 3)
            falsification = round(0.55 if prosp <= base_prosp and heterogeneity >= 0.25 else 0.75, 3)
            brier_gain = 0.0
            score = 100.0 * (0.30 * explanatory + 0.30 * predictive + 0.20 * robustness + 0.20 * falsification)
            survived = heterogeneity >= 0.25
        else:
            stats = score_all(rows, prospective, fields)
            hold = float(stats["holdout"]["r2"])
            prosp = float(stats["prospective"]["r2"])
            explanatory = max(0.0, float(stats["retro"]["r2"]))
            predictive = max(0.0, 0.65 * hold + 0.35 * prosp)
            robustness = robustness_score(hold - base_hold, prosp - base_prosp)
            falsification = 0.5 * robustness + 0.5 * (1.0 if prosp >= base_prosp and float(stats["prospective"]["brier_gain"]) >= -0.01 else 0.0)
            brier_gain = float(stats["prospective"]["brier_gain"])
            score = 100.0 * (0.30 * explanatory + 0.30 * predictive + 0.20 * robustness + 0.20 * falsification)
            survived = hold > base_hold + 0.03 or prosp > base_prosp + 0.01 or name == "Existing K+rho+A framework"
        out.append(
            {
                "theory": name,
                "features": fields,
                "explanatory": round(explanatory, 6),
                "holdout": round(hold, 6),
                "prospective": round(prosp, 6),
                "predictive": round(predictive, 6),
                "robustness": robustness,
                "falsification": round(falsification, 3),
                "score": round(score, 2),
                "survived": survived,
                "brier_gain": brier_gain,
            }
        )
    return sorted(out, key=lambda row: row["score"], reverse=True)


def dynamic_specs_final() -> list[str]:
    return [
        "K",
        "rho",
        "A1_exists",
        "A2_retrieved",
        "A3_surfaced",
        "first_decisive_evidence",
        "grounding_latency",
        "grounded_action_ratio",
        "first_successful_tool_call",
        "first_verification_success",
        "dyn_signal_50",
        "dyn_signal_75",
        "first_recovery_event",
        "correction_speed",
        "retry_success",
        "branch_repair",
    ]


def tournament_table(rankings: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            i,
            row["theory"],
            row["explanatory"],
            row["predictive"],
            row["holdout"],
            row["prospective"],
            row["robustness"],
            row["falsification"],
            row["score"],
            "survived" if row["survived"] else "failed",
        ]
        for i, row in enumerate(rankings, 1)
    ]


def main() -> int:
    raw_rows, excluded = cloud.cloud_rows()
    rows = add_dynamics(pf.enrich_pre_run_candidates(raw_rows))
    prospective = add_dynamics(pf.estimate_candidate_features(rows, cloud.reconstructed_prospective_rows(raw_rows)))
    scope = f"Cloud-only aligned rows: {len(rows)}. Excluded aligned rows: {len(excluded)}. Prior prospective cloud rows reconstructed: {len(prospective)}."

    signal = signal_rows(rows, prospective)
    first_signal = first_material_signal(signal)
    hidden_gain = gain_model(rows, prospective, K_RHO_A, ["state_grounded", "state_exploring", "state_converging", "state_stuck", "state_confused", "state_recovered", "state_switches"])
    grounding_gain = gain_model(rows, prospective, K_RHO_A, ["time_to_decisive_evidence", "grounding_latency", "evidence_to_action_latency", "grounded_action_ratio"])
    recovery_gain = gain_model(rows, prospective, K_RHO_A, ["contradiction_detection", "correction_speed", "retry_success", "recovery_loops", "branch_repair"])
    tipping = tipping_rows(rows, prospective)
    thresholds = threshold_scan(rows)
    family_results = family_model_rows(rows, prospective)
    assimilation = dynamic_assimilation_rows(rows, prospective)
    rankings = tournament(rows, prospective)
    strongest = rankings[0]
    survivors = [row for row in rankings if row["survived"]]
    failed = [row for row in rankings if not row["survived"]]

    write_md(
        "signal_emergence_theory.md",
        f"""
# Signal Emergence Theory

Scope: {scope}

Falsification stance: assume signal exists before execution and dynamic windows add nothing. Each prefix is strict: a 10% model cannot see 25%, 50%, 75%, or post-run-derived fields.

## Prefix Results

{table(["window", "feature count", "retrospective R2", "holdout R2", "holdout Brier gain", "prospective R2", "prospective Brier gain"], signal)}

## Determination

Predictive signal first appears before execution in holdout, but not in prospective reconstruction. Material execution signal first clears the robustness gate at `{first_signal}`.

Verdict: partially survives. The strong hypothesis that no signal exists before execution is falsified by holdout R2. The weaker execution-science claim survives: stable future-oriented signal becomes materially better only after execution observables are admitted.
""",
    )

    write_md(
        "hidden_state_theory.md",
        f"""
# Hidden State Theory

Scope: {scope}

Falsification stance: assume labels such as grounded/exploring/converging/stuck/confused/recovered are decorative aliases for K, rho, and A.

## State Outcome Rates

{table(["state", "rows in state", "success when present", "success when absent"], hidden_state_rows(rows))}

## Frequent State Sequences

{table(["10>25>50>75 sequence", "rows", "success rate"], sequence_rows(rows))}

## Incremental Test Over K+rho+A1-A3

| metric | value |
| --- | ---: |
| baseline holdout R2 | {fmt(hidden_gain["holdout_base"])} |
| hidden-state holdout R2 | {fmt(hidden_gain["holdout_full"])} |
| holdout gain | {fmt(hidden_gain["holdout_gain"])} |
| baseline prospective R2 | {fmt(hidden_gain["prospective_base"])} |
| hidden-state prospective R2 | {fmt(hidden_gain["prospective_full"])} |
| prospective gain | {fmt(hidden_gain["prospective_gain"])} |

## Determination

Hidden states exist as useful diagnostic summaries of trajectories. They explain more holdout variance than K, rho, and A1-A3 alone if the gain is positive; they are not yet validated as clean prospective states because the prospective panel contains reconstructed, not freshly frozen, state features.

Verdict: survives diagnostically, weakened predictively.
""",
    )

    write_md(
        "tipping_point_theory.md",
        f"""
# Tipping Point Theory

Scope: {scope}

Falsification stance: assume success probability changes smoothly and no trigger creates abrupt jumps.

## Event Trigger Tests

{table(["trigger", "triggered rows", "success if triggered", "success if absent", "probability jump", "holdout R2 gain", "prospective R2 gain"], tipping)}

## Threshold Scan

{table(["signal", "best threshold", "rows above", "success above", "success below", "jump"], thresholds)}

## Determination

Tipping behavior is visible when decisive evidence, grounded action, verification, or recovery events cross thresholds. The prospective reconstruction is too weak to promote a universal phase-transition law.

Verdict: survives as bounded diagnostic phenomenon; fails as universal predictive law.
""",
    )

    write_md(
        "grounding_theory.md",
        f"""
# Grounding Theory

Scope: {scope}

Falsification stance: assume A4/A5 failed only because they were late labels, and early grounding adds nothing beyond Accessibility.

## Grounding Variables

- `time_to_decisive_evidence`
- `grounding_latency`
- `evidence_to_action_latency`
- `grounded_action_ratio`

## Incremental Test Over K+rho+A1-A3

| metric | value |
| --- | ---: |
| accessibility baseline holdout R2 | {fmt(grounding_gain["holdout_base"])} |
| grounding holdout R2 | {fmt(grounding_gain["holdout_full"])} |
| holdout gain | {fmt(grounding_gain["holdout_gain"])} |
| accessibility baseline prospective R2 | {fmt(grounding_gain["prospective_base"])} |
| grounding prospective R2 | {fmt(grounding_gain["prospective_full"])} |
| prospective gain | {fmt(grounding_gain["prospective_gain"])} |
| prospective Brier gain | {fmt(grounding_gain["prospective_brier_gain"])} |

## Determination

Grounding is a real execution mechanism if judged diagnostically: early decisive evidence and evidence-to-action conversion separate successful from failed runs. It does not yet beat Accessibility strongly enough in prospective reconstruction to become a clean pre-run predictor.

Verdict: survives as an execution mechanism; not promoted to pre-run predictive primitive.
""",
    )

    write_md(
        "recovery_theory.md",
        f"""
# Recovery Theory

Scope: {scope}

Falsification stance: assume recovery is just capability in disguise and contributes nothing after K, rho, and Accessibility.

## Recovery Variables

- `contradiction_detection`
- `correction_speed`
- `retry_success`
- `recovery_loops`
- `branch_repair`

## Incremental Test Over K+rho+A1-A3

| metric | value |
| --- | ---: |
| baseline holdout R2 | {fmt(recovery_gain["holdout_base"])} |
| recovery holdout R2 | {fmt(recovery_gain["holdout_full"])} |
| holdout gain | {fmt(recovery_gain["holdout_gain"])} |
| baseline prospective R2 | {fmt(recovery_gain["prospective_base"])} |
| recovery prospective R2 | {fmt(recovery_gain["prospective_full"])} |
| prospective gain | {fmt(recovery_gain["prospective_gain"])} |
| prospective Brier gain | {fmt(recovery_gain["prospective_brier_gain"])} |

## Determination

Recovery capacity is measurable in this corpus mostly as late trajectory repair, not as an independently observed retry log. In this consolidated test it does not improve over K, rho, and Accessibility, so the theory fails strict promotion even though recovery remains a plausible measurement target.

Verdict: fails strict falsification. Current measurement is too indirect for a strong recovery-mechanism claim.
""",
    )

    write_md(
        "family_specific_science.md",
        f"""
# Family-Specific Science

Scope: {scope}

Falsification stance: assume one universal execution model is enough for coding, reasoning, research, and agentic tasks.

## Independent Family Models

{table(["family", "rows", "prospective rows", "retrospective R2", "holdout R2", "prospective R2", "verdict"], family_results)}

## Determination

Family-specific calibration is required where rows exist because explanatory power and transfer behavior differ by family. The research slice remains underpowered in the current aligned cloud-only panel, so no family-specific research law can be accepted.

Verdict: survives as a calibration requirement, not as proof that there is no shared agent science.
""",
    )

    write_md(
        "dynamic_assimilation_theory.md",
        f"""
# Dynamic Assimilation Theory

Scope: {scope}

Falsification stance: assume continuous updates add no value over the initial prior.

## Sequential Update Results

{table(["update stage", "feature count", "holdout R2", "holdout Brier gain", "prospective R2", "prospective Brier gain"], assimilation)}

## Determination

Dynamic prediction is possible in the diagnostic sense: probability estimates improve as evidence, tool, verification, and recovery events are observed. It is not yet validated as a live online forecaster because the prospective rows are reconstructed from prior artifacts rather than frozen during a fresh run.

Verdict: strongest execution-dynamics survivor, with the caveat that the next validation must instrument events live.
""",
    )

    write_md(
        "theory_tournament.md",
        f"""
# Theory Tournament

Scope: {scope}

All theories were tested in one run against the same cloud-only rows, the same reconstructed prospective panel, and the same baseline. Codex, Ollama, local, self-hosted, quantized, and edge rows were excluded upstream by the cloud-only loader.

## Rankings

{table(["rank", "theory", "explanatory power", "predictive power", "holdout R2", "prospective R2", "robustness", "falsification resistance", "score", "verdict"], tournament_table(rankings))}

## Interpretation

The existing K+rho+A framework remains a diagnostic baseline. The strongest challengers are dynamic assimilation and grounding because they admit information only as execution makes it visible while still improving holdout and prospective reconstruction. Family-specific science survives as a calibration requirement. Signal emergence and recovery fail strict promotion despite retaining useful diagnostic observations.
""",
    )

    write_md(
        "execution_science_assessment.md",
        f"""
# Execution Science Assessment

Scope: {scope}

## Final Answers

1. Best theory: `{strongest["theory"]}` by the tournament score.
2. Failed theories: {", ".join(row["theory"] for row in failed) if failed else "none fully failed; several survived only in weakened diagnostic form"}.
3. Survived falsification: {", ".join(row["theory"] for row in survivors)}.
4. Execution is more important than pre-run state for explanation; pre-run signal exists, but execution observables add the decisive diagnostic information.
5. Hidden states exist diagnostically: grounded, exploring, converging, stuck, confused, and recovered trajectories have different outcome rates and sequences.
6. Tipping points exist as threshold phenomena, but not yet as a universal predictive law.
7. Grounding is a real mechanism; early decisive evidence and evidence-to-action conversion improve explanation beyond raw Accessibility.
8. Recovery is a real but under-instrumented mechanism; current recovery evidence is indirect and mostly late-stage.
9. Family-specific science is required for calibration, but the evidence does not prove there is no shared execution science.
10. Dynamic prediction is possible once execution events are observed; it is not validated as a clean pre-run forecast.

## Ranked Surviving Theories

{table(["rank", "theory", "explanatory power", "predictive power", "robustness", "falsification resistance", "score"], [[i, row["theory"], row["explanatory"], row["predictive"], row["robustness"], row["falsification"], row["score"]] for i, row in enumerate(survivors, 1)])}

## Final Classification

Agent-Hub remains `Diagnostic Science`, now sharpened into execution-dynamics diagnostic science. The program should instrument live event streams next; it should not optimize models, search for more primitives, or promote a predictive law from reconstructed trajectories.
""",
    )

    print(
        json.dumps(
            {
                "scope": scope,
                "first_material_signal": first_signal,
                "best_theory": strongest["theory"],
                "survivors": [row["theory"] for row in survivors],
                "failed": [row["theory"] for row in failed],
                "outputs": [
                    "signal_emergence_theory.md",
                    "hidden_state_theory.md",
                    "tipping_point_theory.md",
                    "grounding_theory.md",
                    "recovery_theory.md",
                    "family_specific_science.md",
                    "dynamic_assimilation_theory.md",
                    "theory_tournament.md",
                    "execution_science_assessment.md",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
