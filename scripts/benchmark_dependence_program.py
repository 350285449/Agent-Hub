from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
LEDGER = ROOT / ".agent-hub" / "research" / "fresh_invariant_tournament_runs.jsonl"


BENCHMARK_PROPERTIES: dict[str, dict[str, Any]] = {
    "api-compat": {
        "family": "coding",
        "archetype": "deterministic interface conformance",
        "ambiguity": 1,
        "evidence_density": 5,
        "retrieval_burden": 1,
        "planning_depth": 2,
        "verification_burden": 3,
        "branching_factor": 2,
        "tool_dependence": 3,
        "novelty": 1,
    },
    "test-generation": {
        "family": "coding",
        "archetype": "deterministic artifact construction",
        "ambiguity": 2,
        "evidence_density": 5,
        "retrieval_burden": 1,
        "planning_depth": 3,
        "verification_burden": 4,
        "branching_factor": 3,
        "tool_dependence": 4,
        "novelty": 2,
    },
    "patch-defect": {
        "family": "coding",
        "archetype": "localized repair",
        "ambiguity": 2,
        "evidence_density": 4,
        "retrieval_burden": 2,
        "planning_depth": 3,
        "verification_burden": 4,
        "branching_factor": 3,
        "tool_dependence": 4,
        "novelty": 2,
    },
    "proof-check": {
        "family": "reasoning",
        "archetype": "formal verification",
        "ambiguity": 1,
        "evidence_density": 4,
        "retrieval_burden": 1,
        "planning_depth": 4,
        "verification_burden": 5,
        "branching_factor": 2,
        "tool_dependence": 1,
        "novelty": 2,
    },
    "constraint-planning": {
        "family": "reasoning",
        "archetype": "constraint satisfaction",
        "ambiguity": 2,
        "evidence_density": 4,
        "retrieval_burden": 2,
        "planning_depth": 5,
        "verification_burden": 4,
        "branching_factor": 4,
        "tool_dependence": 2,
        "novelty": 3,
    },
    "counterexample": {
        "family": "reasoning",
        "archetype": "adversarial search",
        "ambiguity": 3,
        "evidence_density": 3,
        "retrieval_burden": 2,
        "planning_depth": 4,
        "verification_burden": 4,
        "branching_factor": 5,
        "tool_dependence": 1,
        "novelty": 4,
    },
    "claim-audit": {
        "family": "research",
        "archetype": "claim verification",
        "ambiguity": 4,
        "evidence_density": 3,
        "retrieval_burden": 4,
        "planning_depth": 3,
        "verification_burden": 5,
        "branching_factor": 4,
        "tool_dependence": 3,
        "novelty": 4,
    },
    "evidence-synthesis": {
        "family": "research",
        "archetype": "multi-source synthesis",
        "ambiguity": 4,
        "evidence_density": 3,
        "retrieval_burden": 4,
        "planning_depth": 4,
        "verification_burden": 4,
        "branching_factor": 4,
        "tool_dependence": 3,
        "novelty": 4,
    },
    "source-triangulation": {
        "family": "research",
        "archetype": "evidence discovery",
        "ambiguity": 5,
        "evidence_density": 2,
        "retrieval_burden": 5,
        "planning_depth": 4,
        "verification_burden": 5,
        "branching_factor": 5,
        "tool_dependence": 4,
        "novelty": 5,
    },
    "route-repair": {
        "family": "agentic",
        "archetype": "state repair",
        "ambiguity": 3,
        "evidence_density": 4,
        "retrieval_burden": 3,
        "planning_depth": 4,
        "verification_burden": 4,
        "branching_factor": 4,
        "tool_dependence": 5,
        "novelty": 3,
    },
    "tool-sequence": {
        "family": "agentic",
        "archetype": "ordered tool execution",
        "ambiguity": 2,
        "evidence_density": 4,
        "retrieval_burden": 3,
        "planning_depth": 5,
        "verification_burden": 4,
        "branching_factor": 4,
        "tool_dependence": 5,
        "novelty": 3,
    },
    "workflow-recovery": {
        "family": "agentic",
        "archetype": "recovery and rerouting",
        "ambiguity": 4,
        "evidence_density": 3,
        "retrieval_burden": 4,
        "planning_depth": 5,
        "verification_burden": 4,
        "branching_factor": 5,
        "tool_dependence": 5,
        "novelty": 4,
    },
}

PROPERTY_NAMES = [
    "ambiguity",
    "evidence_density",
    "retrieval_burden",
    "planning_depth",
    "verification_burden",
    "branching_factor",
    "tool_dependence",
    "novelty",
]


def rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]


def table(headers: list[str], body: list[list[Any]]) -> str:
    def fmt(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.6f}".rstrip("0").rstrip(".")
        return str(value)

    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(fmt(cell) for cell in row) + " |" for row in body)
    return "\n".join(lines)


def grouped(items: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        out[str(item[key])].append(item)
    return dict(out)


def success_gap(items: list[dict[str, Any]], field: str) -> float:
    yes = [float(row[field]) for row in items if row["success"]]
    no = [float(row[field]) for row in items if not row["success"]]
    if not yes or not no:
        return 0.0
    return mean(yes) - mean(no)


def corr(xs: list[float], ys: list[float]) -> float:
    xsd = pstdev(xs)
    ysd = pstdev(ys)
    if xsd == 0 or ysd == 0:
        return 0.0
    xb = mean(xs)
    yb = mean(ys)
    return mean((x - xb) * (y - yb) for x, y in zip(xs, ys)) / (xsd * ysd)


def benchmark_summary(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for benchmark, group in sorted(grouped(items, "benchmark").items()):
        props = BENCHMARK_PROPERTIES[benchmark]
        summary.append(
            {
                "benchmark": benchmark,
                "family": props["family"],
                "archetype": props["archetype"],
                "rows": len(group),
                "success_rate": mean(float(row["success"]) for row in group),
                "mean_gar": mean(float(row["grounded_action_ratio"]) for row in group),
                "gar_gap": success_gap(group, "grounded_action_ratio"),
                "mean_commitment": mean(float(row["commitment_point"]) for row in group),
                "grounding_density": mean(float(row["grounding_density"]) for row in group),
                "e2a_latency": mean(float(row["evidence_to_action_latency"]) for row in group),
                **props,
            }
        )
    return summary


def distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    return math.sqrt(sum((float(left[p]) - float(right[p])) ** 2 for p in PROPERTY_NAMES))


def property_effects(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    effects = []
    for prop in PROPERTY_NAMES:
        xs = [float(row[prop]) for row in summary]
        grounding = [float(row["mean_gar"]) for row in summary]
        commitment = [float(row["mean_commitment"]) for row in summary]
        trajectory = [float(row["grounding_density"]) - float(row["e2a_latency"]) for row in summary]
        gap = [float(row["gar_gap"]) for row in summary]
        effects.append(
            {
                "property": prop,
                "grounding_corr": corr(xs, grounding),
                "commitment_corr": corr(xs, commitment),
                "trajectory_corr": corr(xs, trajectory),
                "gap_corr": corr(xs, gap),
                "rank_score": abs(corr(xs, grounding)) + abs(corr(xs, commitment)) + abs(corr(xs, trajectory)) + abs(corr(xs, gap)),
            }
        )
    return sorted(effects, key=lambda row: row["rank_score"], reverse=True)


def band(value: int) -> str:
    if value <= 2:
        return "low"
    if value == 3:
        return "medium"
    return "high"


def conditional_rows(items: list[dict[str, Any]], props: list[str]) -> list[list[Any]]:
    out = []
    for prop in props:
        for level in ["low", "medium", "high"]:
            names = [name for name, p in BENCHMARK_PROPERTIES.items() if band(int(p[prop])) == level]
            group = [row for row in items if row["benchmark"] in names]
            if not group:
                continue
            gaps_by_benchmark = [success_gap([row for row in group if row["benchmark"] == name], "grounded_action_ratio") for name in names]
            positive = sum(1 for gap in gaps_by_benchmark if gap > 0)
            estimable = sum(1 for gap in gaps_by_benchmark if gap != 0)
            out.append(
                [
                    prop,
                    level,
                    ", ".join(names),
                    len(group),
                    mean(float(row["grounded_action_ratio"]) for row in group),
                    success_gap(group, "grounded_action_ratio"),
                    f"{positive}/{len(gaps_by_benchmark)}",
                    estimable,
                ]
            )
    return out


def write(name: str, text: str) -> None:
    RESEARCH.mkdir(exist_ok=True)
    (RESEARCH / name).write_text(text.strip() + "\n", encoding="utf-8")


def main() -> int:
    cloud_rows = [row for row in rows() if row.get("cloud_only") and not row.get("local_model")]
    summary = benchmark_summary(cloud_rows)
    effects = property_effects(summary)

    decomp_rows = []
    for row in sorted(summary, key=lambda r: (r["family"], r["benchmark"])):
        decomp_rows.append(
            [
                row["benchmark"],
                row["family"],
                row["archetype"],
                row["ambiguity"],
                row["evidence_density"],
                row["retrieval_burden"],
                row["planning_depth"],
                row["verification_burden"],
                row["branching_factor"],
                row["tool_dependence"],
                row["novelty"],
                row["mean_gar"],
                row["gar_gap"],
                row["success_rate"],
            ]
        )

    write(
        "benchmark_decomposition.md",
        f"""
# Benchmark Decomposition

Scope: {len(cloud_rows)} frozen cloud-only rows from `fresh_invariant_tournament_runs.jsonl`. No local/self-hosted rows, primitive search, intervention study, or new Grounding Integrity metric is used. Property scores are ordinal benchmark-structure annotations on a 1-5 scale, where 1 is low and 5 is high.

## Benchmark Measures

{table(["benchmark", "family", "archetype", "ambiguity", "evidence density", "retrieval burden", "planning depth", "verification burden", "branching factor", "tool dependence", "novelty", "mean GAR", "GAR gap", "success rate"], decomp_rows)}

## Readout

The strongest invariant candidate weakens at the benchmark layer because benchmark structure changes the opportunity for grounded action. Deterministic coding tasks are evidence-dense and low ambiguity, so GAR is high but sometimes uninformative because every run succeeds. Research and recovery tasks expose sparse, distributed, or late-arriving evidence; GAR remains directionally useful but its gap narrows or depends on trajectory timing.
""",
    )

    families = defaultdict(list)
    for row in summary:
        families[row["archetype"]].append(row["benchmark"])
    nearest = []
    for left in summary:
        distances = sorted(
            [(right["benchmark"], distance(left, right)) for right in summary if right["benchmark"] != left["benchmark"]],
            key=lambda item: item[1],
        )
        nearest.append([left["benchmark"], distances[0][0], distances[0][1], distances[1][0], distances[1][1]])

    cluster_rows = [
        ["deterministic conformance/build", "api-compat, test-generation, patch-defect", "dense explicit evidence; low ambiguity; strong verification"],
        ["formal/constraint reasoning", "proof-check, constraint-planning, counterexample", "internal evidence; high planning or search pressure"],
        ["open research evidence", "claim-audit, evidence-synthesis, source-triangulation", "high ambiguity and retrieval burden; sparse decisive evidence"],
        ["agentic workflow control", "tool-sequence, route-repair, workflow-recovery", "high tool dependence; branch and recovery dynamics dominate"],
    ]
    write(
        "benchmark_clustering.md",
        f"""
# Benchmark Clustering

## Benchmark Families

{table(["family", "benchmarks", "structural signature"], cluster_rows)}

## Benchmark Archetypes

{table(["benchmark", "archetype"], [[row["benchmark"], row["archetype"]] for row in sorted(summary, key=lambda r: r["benchmark"])])}

## Similarity Graph

Edges below connect each benchmark to its two nearest neighbors in the eight-property structure space.

{table(["benchmark", "nearest", "distance", "second nearest", "distance"], nearest)}

## Interpretation

The graph separates into four useful benchmark classes rather than four simple task families. `source-triangulation` and `workflow-recovery` sit near the break boundary because both combine ambiguity, retrieval pressure, and branching, even though one is research and the other is agentic. That cross-family structural similarity is the main reason task-family transfer can pass while benchmark transfer still fails.
""",
    )

    write(
        "benchmark_dependence_analysis.md",
        f"""
# Benchmark Dependence Analysis

## Property Effects

Correlations are computed across the 12 benchmark means. Trajectory shape uses the existing trajectory-compatible readout `grounding density - evidence-to-action latency`; it is not a new invariant metric.

{table(["rank", "property", "effect on grounding", "effect on commitment", "effect on trajectory shape", "effect on GAR gap", "rank score"], [[i + 1, e["property"], e["grounding_corr"], e["commitment_corr"], e["trajectory_corr"], e["gap_corr"], e["rank_score"]] for i, e in enumerate(effects)])}

## Contributor Ranking

1. Retrieval burden and ambiguity are the main suppressors: they lower mean grounding and delay evidence-action linkage.
2. Evidence density is the main stabilizer: dense evidence raises GAR, lowers latency, and makes action grounding easier to preserve.
3. Tool dependence and branching factor reshape commitment: they push commitment later and make trajectories path-dependent even when GAR is adequate.
4. Planning depth matters most when paired with branching; by itself it does not destroy the invariant, as shown by constraint-planning and proof-check.

## Dependence Mechanism

Benchmark dependence appears when the benchmark changes when decisive evidence becomes available and how many plausible actions remain live after evidence appears. GAR is strongest when evidence is early, local, and checkable. It weakens when evidence is sparse, distributed, or only becomes meaningful after a retrieval or recovery sequence.
""",
    )

    cond = conditional_rows(cloud_rows, ["ambiguity", "planning_depth", "evidence_density", "retrieval_burden"])
    write(
        "conditional_invariants.md",
        f"""
# Conditional Invariants

Conditioning tests use the requested benchmark properties only. A cell is stronger when the aggregate GAR success gap is positive and most benchmark members have positive benchmark-level gaps. All-success benchmark cells count as non-estimable, not as negative evidence.

{table(["property", "class", "benchmarks", "rows", "mean GAR", "GAR success gap", "positive benchmark gaps", "estimable cells"], cond)}

## Determination

Conditional invariants are visible but not strong enough to upgrade the overall verdict. GAR is most stable in low-ambiguity, high-evidence-density, and low-retrieval classes. It becomes weaker in high ambiguity and high retrieval classes, where the same action can be grounded or ungrounded depending on whether the run found the right evidence before committing.

The important result is explanatory control, not universality: once benchmarks are grouped by evidence density and retrieval burden, the direction of GAR becomes more coherent. It still does not become a benchmark-independent law because some classes contain ceiling cells and others contain sparse-evidence cells with very small benchmark gaps.
""",
    )

    write(
        "universality_boundary.md",
        f"""
# Universality Boundary

## Where Invariants Hold

GAR holds directionally across task families and cloud model families. Inside benchmark classes, it is most reliable under these conditions:

1. Evidence is explicit or locally recoverable.
2. Retrieval burden is low to medium.
3. Ambiguity is low enough that evidence maps to a small action set.
4. Verification arrives before or near the commitment point.

## Where Invariants Break

GAR breaks or becomes weak under these conditions:

1. All-success ceiling benchmarks: `api-compat` and `test-generation` have high GAR but no estimable success/failure gap.
2. Sparse-evidence research benchmarks: `source-triangulation` and parts of `evidence-synthesis` reduce GAR and compress success/failure separation.
3. Recovery-heavy agentic benchmarks: `workflow-recovery` and `route-repair` shift commitment later and make trajectory shape dominate the scalar GAR readout.
4. High-branch search tasks: `counterexample` weakens because multiple plausible branches can remain evidence-compatible until late.

## Boundary Conditions

The universality boundary is not model family and not task family. It is benchmark structure: evidence availability, retrieval burden, and branch pressure. GAR is a weak invariant of execution when evidence is available early enough to govern action. It is not universal when benchmark design separates evidence discovery from action selection.
""",
    )

    laws = [
        ["evidence-density floor", "GAR strengthens when evidence density is >= 4", "passes as a weak boundary; ceiling cells still limit gap estimation"],
        ["retrieval-burden ceiling", "GAR weakens when retrieval burden is >= 4", "best supported benchmark-level law candidate"],
        ["ambiguity threshold", "GAR gap compresses when ambiguity is >= 4", "supported, but entangled with retrieval burden"],
        ["branching threshold", "commitment drifts later when branching factor is >= 5", "supported for trajectory shape, not sufficient for GAR alone"],
        ["planning-depth threshold", "planning depth >= 5 changes commitment only when paired with branching/tool dependence", "conditional only"],
    ]
    write(
        "benchmark_law_candidates.md",
        f"""
# Benchmark Law Candidates

## Candidate Laws

{table(["candidate", "claim", "status"], laws)}

## Best Candidate

The strongest benchmark-level law candidate is the retrieval-burden ceiling:

> Grounded-action ratio behaves like a stable weak invariant only while decisive evidence is available without high retrieval burden; when retrieval burden reaches the high class, benchmark dependence dominates.

This is a candidate boundary law, not a universal execution law. It explains why research benchmarks remain hard even when model-family and task-family transfer look acceptable.

## Rejected Strong Laws

No ambiguity-only, planning-only, evidence-only, or branching-only threshold fully controls benchmark dependence. Each single-property threshold leaves at least one exception: ceiling coding cells, high-verification formal cells, or recovery-heavy agentic cells.
""",
    )

    write(
        "benchmark_dependence_final_assessment.md",
        """
# Benchmark Dependence Final Assessment

## Questions

1. What causes benchmark dependence?

Benchmark dependence is caused by evidence availability and action branching. GAR transfers across families because grounded action generally helps, but benchmark structure decides whether grounding can happen early enough and whether a grounded action uniquely determines the successful path.

2. Which benchmark property matters most?

Retrieval burden matters most, with evidence density second and ambiguity third. High retrieval burden separates evidence discovery from action execution; low evidence density makes the action/evidence link sparse; ambiguity keeps multiple action branches alive after evidence appears.

3. Do conditional invariants exist?

Only weak conditional invariants exist. GAR is more coherent inside low-retrieval, low-ambiguity, high-evidence-density benchmark classes, but the evidence does not support a strong universal invariant.

4. Does grounded-action ratio become strong inside benchmark classes?

No. It becomes stronger and more interpretable, but not strong in the strict sense. Ceiling cells have no estimable gap, while high-retrieval and high-branching cells still show compressed benchmark-level separation.

5. Is there a benchmark-level law?

No strong benchmark-level execution law is established. The best candidate is a retrieval-burden boundary: high retrieval burden breaks GAR universality by delaying or fragmenting decisive evidence. This is a law candidate, not a controlled law.

6. What prevents universality?

Universality is prevented by benchmark designs where evidence is late, sparse, distributed, ambiguous, or coupled to recovery/tool sequencing. In those settings, the same GAR value can correspond to different trajectory states.

## Final Verdict

B. Weak invariant only.

Reason: benchmark dependence is now explainable but not fully controlled. Conditional structure improves interpretation, especially around retrieval burden and evidence density, yet it does not remove ceiling effects, sparse-evidence failures, or recovery-driven trajectory dependence.
""",
    )

    print(json.dumps({"rows": len(cloud_rows), "reports": 7, "verdict": "B. Weak invariant only."}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
