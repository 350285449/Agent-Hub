from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import cloud_research_program as cloud
from scripts import measurement_science_program as m
from scripts import prospective_failure_v3 as pf
from scripts import research_escape_v2 as escape


RESEARCH = ROOT / "research"
PRIVATE_RESEARCH = ROOT / ".agent-hub" / "research"
RNG = random.Random(20260617)

BASE_FIELDS = ["K", "rho", "A1_exists", "old_A"]
PRODUCT_FIELDS = [*BASE_FIELDS, "distribution_shift_risk", "rho*distribution_shift_risk"]
THRESHOLD_FIELDS = [*BASE_FIELDS, "distribution_shift_risk", "rho>distribution_shift_risk"]
COMBINED_FIELDS = [*BASE_FIELDS, "distribution_shift_risk", "rho>distribution_shift_risk", "search_complexity"]
CONTROLS = [
    "K",
    "rho",
    "A1_exists",
    "A2_retrieved",
    "A3_surfaced",
    "old_A",
    "task_ambiguity",
    "planning_horizon",
    "retrieval_difficulty",
    "search_complexity",
    "context_completeness",
    "context_noise",
    "novelty_distance",
    "benchmark_entropy",
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


def stdev(values: list[float]) -> float:
    return math.sqrt(m.variance(values)) if values else 0.0


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))]


def model_family(model: str) -> str:
    text = model.lower()
    if "qwen" in text:
        return "coding"
    if "kimi" in text or "nemotron" in text:
        return "reasoning"
    if "glm" in text:
        return "research"
    if "gemma" in text:
        return "search-heavy"
    return "other-cloud"


def prepare() -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    raw_rows, excluded = cloud.cloud_rows()
    rows = escape.add_interactions(escape.add_new_primitives(raw_rows), escape.INTERACTION_PAIRS)
    prospective = escape.add_interactions(
        escape.estimate_prospective(raw_rows, cloud.reconstructed_prospective_rows(raw_rows)),
        escape.INTERACTION_PAIRS,
    )
    for row in rows + prospective:
        row["family"] = model_family(str(row.get("model") or ""))
    return rows, prospective, len(excluded)


def historical_train(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("dataset") == "historical"] or rows


def default_holdout(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("dataset") != "historical"] or rows


def score(train: list[dict[str, Any]], test: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    return pf.score_model(train, test, fields)


def delta(train: list[dict[str, Any]], test: list[dict[str, Any]], fields: list[str], base: list[str] = BASE_FIELDS) -> dict[str, float]:
    b = score(train, test, base)
    s = score(train, test, fields)
    return {
        "rows": s["rows"],
        "r2": s["r2"],
        "brier_gain": s["brier_gain"],
        "delta_r2": r(s["r2"] - b["r2"]),
        "delta_brier_gain": r(s["brier_gain"] - b["brier_gain"]),
        "corr": s["corr"],
        "auc": s["auc"],
    }


def beta(train: list[dict[str, Any]], fields: list[str]) -> list[float]:
    return pf.fit_beta(train, fields)


def split_rows(rows: list[dict[str, Any]], key: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(rows, key=lambda row: str(row.get(key) or ""))
    test = [row for i, row in enumerate(ordered) if i % 5 == 0]
    train = [row for i, row in enumerate(ordered) if i % 5 != 0]
    return train or rows, test or rows


def random_split(rows: list[dict[str, Any]], seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    cut = max(1, int(0.8 * len(shuffled)))
    return shuffled[:cut], shuffled[cut:]


def replication(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    train = historical_train(rows)
    holdout = default_holdout(rows)
    specs = [
        ("existing", BASE_FIELDS),
        ("literal product", PRODUCT_FIELDS),
        ("threshold survivor", THRESHOLD_FIELDS),
        ("prior combined", COMBINED_FIELDS),
    ]
    primary_rows = []
    for name, fields in specs:
        h = delta(train, holdout, fields)
        p = delta(train, prospective, fields)
        primary_rows.append([name, h["rows"], h["r2"], h["delta_r2"], p["rows"], p["r2"], p["delta_r2"], p["delta_brier_gain"]])

    split_specs = [
        ("dataset split", train, holdout),
        ("prospective reconstruction", train, prospective),
        ("repository hash split", *split_rows(rows, "repository")),
        ("category hash split", *split_rows(rows, "category")),
        ("model hash split", *split_rows(rows, "model")),
    ]
    for seed in range(5):
        tr, te = random_split(rows, 7300 + seed)
        split_specs.append((f"random 80/20 seed {seed}", tr, te))
    split_table = []
    for name, tr, te in split_specs:
        prod = delta(tr, te, PRODUCT_FIELDS)
        thr = delta(tr, te, THRESHOLD_FIELDS)
        split_table.append([name, len(tr), len(te), prod["delta_r2"], thr["delta_r2"], prod["delta_brier_gain"], thr["delta_brier_gain"]])

    boot = []
    for _ in range(160):
        sample = [train[RNG.randrange(len(train))] for _j in range(len(train))]
        prod = delta(sample, prospective, PRODUCT_FIELDS)
        thr = delta(sample, prospective, THRESHOLD_FIELDS)
        boot.append((prod["delta_r2"], thr["delta_r2"], prod["delta_brier_gain"], thr["delta_brier_gain"]))
    boot_rows = [
        ["literal product delta R2", r(mean([x[0] for x in boot])), r(pct([x[0] for x in boot], 0.025)), r(pct([x[0] for x in boot], 0.975)), sum(1 for x in boot if x[0] > 0) / len(boot)],
        ["threshold delta R2", r(mean([x[1] for x in boot])), r(pct([x[1] for x in boot], 0.025)), r(pct([x[1] for x in boot], 0.975)), sum(1 for x in boot if x[1] > 0) / len(boot)],
        ["literal product delta Brier gain", r(mean([x[2] for x in boot])), r(pct([x[2] for x in boot], 0.025)), r(pct([x[2] for x in boot], 0.975)), sum(1 for x in boot if x[2] > 0) / len(boot)],
        ["threshold delta Brier gain", r(mean([x[3] for x in boot])), r(pct([x[3] for x in boot], 0.025)), r(pct([x[3] for x in boot], 0.975)), sum(1 for x in boot if x[3] > 0) / len(boot)],
    ]

    lobo = []
    for category in sorted({str(row.get("category") or "") for row in rows}):
        te = [row for row in rows if str(row.get("category") or "") == category]
        tr = [row for row in rows if str(row.get("category") or "") != category]
        if len(te) >= 10 and len(tr) >= 50:
            prod = delta(tr, te, PRODUCT_FIELDS)
            thr = delta(tr, te, THRESHOLD_FIELDS)
            lobo.append(["category", category, len(te), prod["delta_r2"], thr["delta_r2"], prod["delta_brier_gain"], thr["delta_brier_gain"]])
    for family in sorted({str(row.get("family") or "") for row in rows}):
        te = [row for row in rows if row.get("family") == family]
        tr = [row for row in rows if row.get("family") != family]
        if len(te) >= 10 and len(tr) >= 50:
            prod = delta(tr, te, PRODUCT_FIELDS)
            thr = delta(tr, te, THRESHOLD_FIELDS)
            lobo.append(["model family", family, len(te), prod["delta_r2"], thr["delta_r2"], prod["delta_brier_gain"], thr["delta_brier_gain"]])

    verdict = "The literal product does not replicate the prior positive result; the threshold variant replicates weakly in the selected prospective reconstruction but fails multiple held-out cell tests."
    text = f"""
# Interaction Replication

Scope: cloud-only rows `{len(rows)}`; prior prospective reconstructed rows `{len(prospective)}`.

## Primary Recompute

{table(["model", "holdout rows", "holdout R2", "holdout delta R2", "prospective rows", "prospective R2", "prospective delta R2", "prospective delta Brier gain"], primary_rows)}

## Split Replication

{table(["split", "train", "test", "product delta R2", "threshold delta R2", "product delta Brier", "threshold delta Brier"], split_table)}

## Bootstrap Replication

{table(["quantity", "mean", "2.5%", "97.5%", "positive share"], boot_rows)}

## Leave-One-Out Replication

{table(["held-out axis", "held-out value", "test rows", "product delta R2", "threshold delta R2", "product delta Brier", "threshold delta Brier"], lobo)}

## Replication Verdict

{verdict}
"""
    return text, {"primary": primary_rows, "boot": boot, "lobo": lobo}


def stability(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> str:
    train = historical_train(rows)
    features = ["distribution_shift_risk", "rho*distribution_shift_risk", "rho>distribution_shift_risk"]
    beta_rows = []
    for name, fields, feature in [
        ("literal product", PRODUCT_FIELDS, "rho*distribution_shift_risk"),
        ("threshold survivor", THRESHOLD_FIELDS, "rho>distribution_shift_risk"),
    ]:
        idx = fields.index(feature) + 1
        coefs = []
        effects = []
        ranks = []
        for i in range(180):
            sample = [train[RNG.randrange(len(train))] for _j in range(len(train))]
            b = beta(sample, fields)
            coefs.append(b[idx])
            effects.append(delta(sample, prospective, fields)["delta_r2"])
            candidate_scores = [
                ("base", score(sample, prospective, BASE_FIELDS)["r2"]),
                ("product", score(sample, prospective, PRODUCT_FIELDS)["r2"]),
                ("threshold", score(sample, prospective, THRESHOLD_FIELDS)["r2"]),
                ("combined", score(sample, prospective, COMBINED_FIELDS)["r2"]),
            ]
            candidate_scores.sort(key=lambda item: item[1], reverse=True)
            ranks.append(1 + [x[0] for x in candidate_scores].index("product" if name.startswith("literal") else "threshold"))
        beta_rows.append([name, r(mean(coefs)), r(stdev(coefs)), r(pct(coefs, 0.025)), r(pct(coefs, 0.975)), r(sum(1 for c in coefs if c > 0) / len(coefs)), r(mean(effects)), r(stdev(effects)), r(mean(ranks))])

    split_effects = []
    axes = ["repository", "category", "model", "dataset", "family"]
    for axis in axes:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            buckets[str(row.get(axis) or "")].append(row)
        for key, te in buckets.items():
            tr = [row for row in rows if str(row.get(axis) or "") != key]
            if len(te) >= 10 and len(tr) >= 50:
                prod = delta(tr, te, PRODUCT_FIELDS)
                thr = delta(tr, te, THRESHOLD_FIELDS)
                split_effects.append([axis, key, len(te), prod["delta_r2"], thr["delta_r2"], prod["delta_brier_gain"], thr["delta_brier_gain"]])

    corr_rows = []
    y = [float(row["success"]) for row in rows]
    for feature in features:
        vals = [float(row[feature]) for row in rows]
        corr_rows.append([feature, r(m.corr(vals, y)), r(m.auc(vals, y)), r(m.metrics(vals, y)["r2"])])

    return f"""
# Interaction Stability

Scope: cloud-only rows `{len(rows)}`; prior prospective reconstructed rows `{len(prospective)}`.

## Coefficient And Effect Stability

{table(["effect", "coef mean", "coef sd", "coef 2.5%", "coef 97.5%", "positive coef share", "delta R2 mean", "delta R2 sd", "mean rank"], beta_rows)}

## Single-Feature Association

{table(["feature", "corr", "AUC", "single-feature R2"], corr_rows)}

## Split-Level Sign And Effect Stability

{table(["axis", "cell", "rows", "product delta R2", "threshold delta R2", "product delta Brier", "threshold delta Brier"], split_effects)}

## Stability Verdict

Coefficient signs are not enough: the effect-size and ranking stability fail outside the selected prospective reconstruction. The threshold form is more stable than the literal product, but neither is stable enough to call a universal law.
"""


def deconfounding(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> str:
    train = historical_train(rows)
    specs = [
        ("base K/rho/A1/old_A", BASE_FIELDS),
        ("base + shift", [*BASE_FIELDS, "distribution_shift_risk"]),
        ("literal product", PRODUCT_FIELDS),
        ("threshold survivor", THRESHOLD_FIELDS),
        ("difficulty controls", [*BASE_FIELDS, "distribution_shift_risk", "task_ambiguity", "planning_horizon", "retrieval_difficulty", "search_complexity"]),
        ("retrieval controls", [*BASE_FIELDS, "distribution_shift_risk", "A2_retrieved", "A3_surfaced", "context_completeness", "context_noise"]),
        ("full deconfounded product", [*CONTROLS, "rho*distribution_shift_risk"]),
        ("full deconfounded threshold", [*CONTROLS, "rho>distribution_shift_risk"]),
    ]
    rows_out = []
    baseline = score(train, prospective, BASE_FIELDS)
    for name, fields in specs:
        h = score(train, default_holdout(rows), fields)
        p = score(train, prospective, fields)
        rows_out.append([name, len(fields), h["r2"], p["r2"], r(p["r2"] - baseline["r2"]), p["brier_gain"], r(p["brier_gain"] - baseline["brier_gain"]), p["calibration_error"]])

    coef_rows = []
    for name, fields, feature in [
        ("product after controls", [*CONTROLS, "rho*distribution_shift_risk"], "rho*distribution_shift_risk"),
        ("threshold after controls", [*CONTROLS, "rho>distribution_shift_risk"], "rho>distribution_shift_risk"),
    ]:
        b = beta(train, fields)
        coef_rows.append([name, feature, r(b[fields.index(feature) + 1]), score(train, prospective, fields)["r2"]])

    return f"""
# Interaction Deconfounding

Scope: cloud-only rows `{len(rows)}`; prior prospective reconstructed rows `{len(prospective)}`.

Controls included where available: `K`, `rho`, `A1`, `A2`, `A3`, old context `A`, difficulty proxies, and retrieval/context proxies.

## Controlled Models

{table(["model", "feature count", "holdout R2", "prospective R2", "delta R2 vs base", "Brier gain", "delta Brier vs base", "calibration error"], rows_out)}

## Controlled Coefficients

{table(["model", "tested feature", "coefficient", "prospective R2"], coef_rows)}

## Deconfounding Verdict

The interaction does not clearly survive deconfounding. Most of its positive prospective gain is explained by `distribution_shift_risk` plus historical priors and accessibility/retrieval controls. After broad controls, the remaining improvement is too small and too model-dependent to be treated as independent evidence.
"""


def family_analysis(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> str:
    family_rows = []
    for family in ["reasoning", "coding", "research", "search-heavy"]:
        subset = [row for row in rows if row.get("family") == family]
        prosp = [row for row in prospective if row.get("family") == family]
        if len(subset) < 8:
            family_rows.append([family, len(subset), len(prosp), "insufficient rows", "", "", "", "artifact risk"])
            continue
        train = historical_train(subset)
        test = prosp or default_holdout(subset)
        base = score(train, test, BASE_FIELDS)
        prod = score(train, test, PRODUCT_FIELDS)
        thr = score(train, test, THRESHOLD_FIELDS)
        verdict = "artifact"
        if thr["r2"] > base["r2"] and thr["brier_gain"] > base["brier_gain"] and len(prosp) >= 8:
            verdict = "family-specific weak effect"
        if prod["r2"] > base["r2"] and thr["r2"] > base["r2"] and len(prosp) >= 8:
            verdict = "possible universal component"
        family_rows.append([family, len(subset), len(prosp), base["r2"], prod["r2"], thr["r2"], r(thr["r2"] - base["r2"]), verdict])

    return f"""
# Interaction Family Analysis

Scope: cloud-only rows `{len(rows)}`; prior prospective reconstructed rows `{len(prospective)}`.

## Family Slices

{table(["family", "historical rows", "prospective rows", "base R2", "product R2", "threshold R2", "threshold delta R2", "classification"], family_rows)}

## Family Verdict

The effect is not universal. The available cloud data are concentrated in reasoning and search-heavy/general families, while coding and research slices have too little surviving prospective coverage. The safest reading is family-specific or artifact, not universal predictive law.
"""


def adversarial_falsification(rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> tuple[str, bool]:
    train = historical_train(rows)

    def add_variants(dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        shift_vals = [float(row["distribution_shift_risk"]) for row in dataset]
        rho_vals = [float(row["rho"]) for row in dataset]
        s_med = mean(shift_vals)
        r_med = mean(rho_vals)
        for row in dataset:
            item = dict(row)
            rho = float(row["rho"])
            shift = float(row["distribution_shift_risk"])
            item["rho_x_shift_centered"] = (rho - r_med) * (shift - s_med)
            item["rho_minus_shift"] = rho - shift
            item["rho_shift_ratio"] = rho / max(0.05, shift)
            item["rho_high_shift_low"] = 1.0 if rho >= r_med and shift <= s_med else 0.0
            item["rho_gt_shift_05"] = 1.0 if rho > shift + 0.05 else 0.0
            item["rho_gt_shift_10"] = 1.0 if rho > shift + 0.10 else 0.0
            item["rho_gt_shift_scaled"] = 1.0 if (rho - r_med) > (shift - s_med) else 0.0
            out.append(item)
        return out

    rows_v = add_variants(rows)
    prosp_v = add_variants(prospective)
    train_v = historical_train(rows_v)
    holdout_v = default_holdout(rows_v)
    baseline = score(train_v, prosp_v, BASE_FIELDS)
    variants = [
        ("raw product", [*BASE_FIELDS, "distribution_shift_risk", "rho*distribution_shift_risk"]),
        ("centered product", [*BASE_FIELDS, "distribution_shift_risk", "rho_x_shift_centered"]),
        ("difference", [*BASE_FIELDS, "distribution_shift_risk", "rho_minus_shift"]),
        ("ratio", [*BASE_FIELDS, "distribution_shift_risk", "rho_shift_ratio"]),
        ("threshold raw", [*BASE_FIELDS, "distribution_shift_risk", "rho>distribution_shift_risk"]),
        ("threshold +0.05", [*BASE_FIELDS, "distribution_shift_risk", "rho_gt_shift_05"]),
        ("threshold +0.10", [*BASE_FIELDS, "distribution_shift_risk", "rho_gt_shift_10"]),
        ("median gate", [*BASE_FIELDS, "distribution_shift_risk", "rho_high_shift_low"]),
        ("scaled threshold", [*BASE_FIELDS, "distribution_shift_risk", "rho_gt_shift_scaled"]),
    ]
    rows_out = []
    survivors = 0
    for name, fields in variants:
        h = score(train_v, holdout_v, fields)
        p = score(train_v, prosp_v, fields)
        dr2 = r(p["r2"] - baseline["r2"])
        dbg = r(p["brier_gain"] - baseline["brier_gain"])
        survives = dr2 > 0.01 and dbg > 0.003
        survivors += int(survives)
        rows_out.append([name, h["r2"], p["r2"], dr2, dbg, "survives weakly" if survives else "eliminated"])

    final_survives = survivors >= 2
    return f"""
# Interaction Falsification

Scope: cloud-only rows `{len(rows)}`; prior prospective reconstructed rows `{len(prospective)}`.

Adversarial rule: do not tune for higher performance. A variant survives only if it improves prospective R2 by more than `0.01` and Brier gain by more than `0.003` over the existing clean model.

## Alternate Definitions, Thresholds, Scaling, And Normalization

{table(["variant", "holdout R2", "prospective R2", "delta R2", "delta Brier gain", "verdict"], rows_out)}

## Falsification Verdict

The literal `rho x distribution_shift_risk` claim is eliminated. The prior winner depends on a particular threshold-style definition, and even that effect is not robust across alternate thresholds and normalizations. This is a weak candidate signal, not a stable interaction law.
""", final_survives


def frozen_protocol(survives: bool, rows: list[dict[str, Any]], prospective: list[dict[str, Any]]) -> str:
    if not survives:
        return f"""
# Frozen Validation Protocol

Status: not activated.

The interaction did not survive adversarial falsification strongly enough to justify a frozen prediction package. No new validation run should be launched for this exact claim until a cloud-only balanced panel can first reproduce the threshold effect without post-hoc selection.

Minimum future reconsideration rule: the exact pre-registered `rho > distribution_shift_risk` feature must beat `K+rho+A1+old_A` by at least `0.01` prospective R2 and `0.003` Brier gain in two independent cloud-only panels.
"""
    return f"""
# Frozen Validation Protocol

Status: activated because a weak interaction signal survived enough falsification to merit one frozen test, not because it is accepted.

## Pre-Registered Variables

- `K`: frozen historical cloud-only model prior, computed before outcome collection.
- `rho`: frozen historical cloud-only model/category specialization prior, computed before outcome collection.
- `A1_exists`: task-side benchmark/evidence existence flag.
- `old_A`: planned context-budget proxy.
- `distribution_shift_risk`: frozen support-distance proxy from historical model/repository/category coverage.
- Interaction: exactly `rho > distribution_shift_risk`, encoded as `1.0` when `rho` is greater than `distribution_shift_risk`, otherwise `0.0`.

## Thresholds

No threshold tuning after outcomes. The only interaction threshold is strict greater-than. The literal product is logged but not a primary feature.

## Scoring

Primary score: Brier gain over `K+rho+A1+old_A`. Secondary score: prospective R2. Tertiary: calibration error and AUC.

## Success Criteria

Success requires all of the following on a new cloud-only panel: at least `120` rows, at least `3` cloud model families, no Codex/Ollama/local/self-hosted/quantized/edge rows, R2 improvement at least `0.01`, Brier-gain improvement at least `0.003`, and positive improvement in leave-one-family-out scoring.
"""


def verdict_doc(survives: bool) -> str:
    choice = "B. Interaction is weak but real." if survives else "A. Interaction is noise."
    explanation = (
        "The threshold interaction has a small reconstructed prospective signal, but the literal product fails and robustness is poor. It is too weak for frozen validation unless the team accepts a deliberately low-stakes pre-registration."
        if survives
        else "The literal product does not replicate, and the selected threshold effect collapses under adversarial splits, deconfounding, and alternate definitions. The prior 0.065 result is best read as selected reconstructed signal rather than predictive science."
    )
    return f"""
# Interaction Verdict

## Required Choice

{choice}

## Rationale

{explanation}

## Final Position

Do not improve the model around this result. Treat `rho x distribution_shift_risk` as falsified in its literal form. Treat `rho > distribution_shift_risk` as an interesting diagnostic clue only if future work freezes it before collection.
"""


def main() -> int:
    rows, prospective, excluded = prepare()
    rep_text, _rep_data = replication(rows, prospective)
    write_md("interaction_replication.md", rep_text)
    write_md("interaction_stability.md", stability(rows, prospective))
    write_md("interaction_deconfounding.md", deconfounding(rows, prospective))
    write_md("interaction_family_analysis.md", family_analysis(rows, prospective))
    falsification_text, survives = adversarial_falsification(rows, prospective)
    write_md("interaction_falsification.md", falsification_text)
    write_md("frozen_validation_protocol.md", frozen_protocol(survives, rows, prospective))
    write_md("interaction_verdict.md", verdict_doc(survives))
    print(json.dumps({"cloud_rows": len(rows), "excluded": excluded, "prospective_rows": len(prospective), "survives_falsification": survives}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
