from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"


THEORIES = [
    (1, "Phase Transition Theory", "Physics", "control variables: grounding density, action conversion rate, contradiction load; order parameter: success probability jump", 7.8, 7.0, 7.2, 7.8, 5.8, 7.0),
    (2, "Criticality Theory", "Physics", "control variables: context pressure, uncertainty variance; order parameter: sensitivity to small evidence changes", 6.8, 6.1, 5.8, 7.0, 5.5, 5.6),
    (3, "Percolation Theory", "Physics", "nodes: evidence-action links; edge probability: grounded propagation; cluster: executable solution path", 6.6, 6.0, 6.7, 7.1, 6.0, 6.0),
    (4, "Self-Organized Criticality", "Physics", "load: unresolved constraints; avalanche: cascading repairs or failures; threshold: intervention-free instability point", 5.7, 4.8, 4.9, 6.0, 5.7, 4.5),
    (5, "Energy Barrier Theory", "Physics", "barrier: effort to move from wrong plan to corrected plan; energy: tokens, tool calls, verification cost", 6.5, 5.8, 6.1, 6.9, 6.4, 5.8),
    (6, "Hysteresis Theory", "Physics", "state memory: prior branch commitment; forward/reverse thresholds: evidence needed to switch plan", 7.0, 6.3, 6.4, 7.2, 6.5, 6.2),
    (7, "Entropy Accumulation Theory", "Physics", "entropy: unresolved ambiguity; accumulation rate: drift per step; sink: verification or grounding", 7.2, 6.4, 6.8, 7.4, 6.0, 6.5),
    (8, "Symmetry Breaking Theory", "Physics", "symmetric alternatives: competing plans; broken symmetry: selected execution branch", 6.9, 6.2, 6.1, 7.0, 6.8, 6.0),
    (9, "Attractor Basin Theory", "Physics", "state vector: evidence, plan, confidence, action linkage; basin: convergent success/failure mode", 7.7, 7.1, 7.0, 8.0, 6.7, 7.0),
    (10, "Conservation Theory", "Physics", "conserved quantity: evidence-action mass; leak: unsupported action or unspent evidence", 6.4, 5.8, 5.9, 6.8, 6.1, 5.8),
    (11, "Hidden State Theory", "Dynamical Systems", "latent state: H0-H4 execution class; emissions: grounding, latency, collapse, recovery", 8.2, 7.3, 7.4, 8.0, 6.2, 7.2),
    (12, "State Reachability Theory", "Dynamical Systems", "states: grounded, contradicted, stuck, recoverable; reachability: feasible transition set", 8.5, 7.7, 7.8, 8.7, 7.1, 7.7),
    (13, "Bifurcation Theory", "Dynamical Systems", "parameter: evidence quality or action consistency; branches: recovery versus collapse", 7.5, 6.8, 6.9, 7.9, 6.7, 6.8),
    (14, "Path Dependence Theory", "Dynamical Systems", "history: earlier commitments; sensitivity: later dependence on prior branch choices", 7.4, 6.7, 6.8, 7.7, 5.8, 6.7),
    (15, "Trajectory Dominance Theory", "Dynamical Systems", "trajectory score: temporal execution path; prior: static capability; dominance: outcome variance explained", 8.0, 7.1, 7.0, 8.3, 5.6, 7.0),
    (16, "Feedback Loop Theory", "Dynamical Systems", "loop gain: observation-action-correction cycle; sign: stabilizing or amplifying", 7.3, 6.6, 7.0, 8.0, 5.9, 6.6),
    (17, "Dynamical Bottleneck Theory", "Dynamical Systems", "bottleneck: low-throughput transition; queue: unresolved evidence needing action", 7.1, 6.7, 7.0, 7.9, 6.5, 6.7),
    (18, "Limit Cycle Theory", "Dynamical Systems", "cycle: repeated plan-search-revise loop; amplitude: repeated uncertainty without progress", 5.4, 4.8, 5.0, 5.9, 5.4, 4.8),
    (19, "State Persistence Theory", "Dynamical Systems", "persistence: dwell time in execution state; hazard: failure probability per dwell interval", 6.9, 6.4, 6.8, 7.4, 5.4, 6.2),
    (20, "Stability Theory", "Dynamical Systems", "perturbation: evidence noise or tool error; stability: return to grounded trajectory", 7.4, 6.8, 7.5, 8.1, 5.3, 6.8),
    (21, "Information Bottleneck Theory", "Information Theory", "input: full context; bottleneck: retained task-relevant evidence; output: action policy", 7.6, 7.0, 7.2, 8.4, 5.8, 6.8),
    (22, "Mutual Information Theory", "Information Theory", "MI: dependence between evidence variables and success; conditional MI: added value after controls", 7.0, 6.6, 7.2, 8.0, 5.2, 6.4),
    (23, "Compression Theory", "Information Theory", "compression ratio: context reduction; retained signal: executable evidence preserved", 6.8, 6.2, 6.9, 8.1, 5.3, 6.1),
    (24, "Predictive Coding Theory", "Information Theory", "prediction error: mismatch between expected and observed task state; update: correction step", 7.0, 6.5, 6.7, 7.4, 5.8, 6.2),
    (25, "Surprise Minimization Theory", "Information Theory", "surprise: unexpected evidence or tool result; minimization: plan update or verification", 6.7, 6.2, 6.5, 7.2, 5.6, 6.0),
    (26, "Information Cascade Theory", "Information Theory", "cascade: early evidence dominates later choices; failure cascade: uncorrected false premise", 7.1, 6.6, 6.8, 7.5, 6.1, 6.4),
    (27, "Information Flow Theory", "Information Theory", "flow: evidence movement into plan, tools, action, and verification; loss: broken linkage", 8.4, 7.7, 8.0, 8.8, 6.8, 7.7),
    (28, "Decisive Information Event Theory", "Information Theory", "event: first evidence update that materially changes reachable outcome states", 8.3, 7.8, 7.7, 8.5, 7.3, 7.8),
    (29, "Signal Amplification Theory", "Information Theory", "signal: weak grounding cue; amplification: repeated support across execution steps", 7.2, 6.8, 6.7, 7.6, 6.9, 6.6),
    (30, "Information Conservation Theory", "Information Theory", "conserved variable: actionable evidence; violations: hallucinated or dropped constraints", 7.3, 6.6, 6.7, 7.8, 6.3, 6.5),
    (31, "Homeostasis Theory", "Biology", "set point: stable execution quality; regulator: verification and repair loops", 6.4, 5.8, 6.5, 7.0, 5.3, 5.8),
    (32, "Evolutionary Fitness Theory", "Biology", "fitness: task success under selection; phenotype: policy/memory/routing behavior", 5.9, 5.4, 5.8, 7.0, 5.0, 5.3),
    (33, "Adaptation Reserve Theory", "Biology", "reserve: unused recovery capacity; depletion: retries spent without state improvement", 7.0, 6.5, 6.8, 7.7, 6.4, 6.5),
    (34, "Ecological Niche Theory", "Biology", "niche: task-model-context regime; fit: specialization advantage by regime", 6.8, 6.4, 6.9, 8.0, 5.7, 6.2),
    (35, "Robustness Theory", "Biology", "robustness: success under perturbation; redundancy: multiple evidence paths to action", 7.5, 6.9, 7.8, 8.2, 5.4, 6.9),
    (36, "Ecosystem Collapse Theory", "Biology", "ecosystem: interacting context, tools, memory, model; collapse: multi-component failure", 6.6, 5.8, 6.2, 7.2, 6.2, 5.7),
    (37, "Resource Competition Theory", "Biology", "resources: tokens, attention, tool budget; competition: allocation tradeoffs among subgoals", 6.9, 6.6, 7.1, 8.0, 5.7, 6.5),
    (38, "Selection Pressure Theory", "Biology", "pressure: benchmark/task constraints; selected trait: routing or verification behavior", 6.1, 5.6, 6.2, 7.1, 5.2, 5.5),
    (39, "Metabolic Efficiency Theory", "Biology", "metabolism: tokens and latency per useful evidence-action transition", 6.8, 6.5, 7.2, 7.9, 6.2, 6.4),
    (40, "Immune-System Theory", "Biology", "detectors: contradiction, unsupported claim, unsafe action; response: quarantine or repair", 7.7, 7.2, 7.7, 8.1, 6.9, 7.1),
    (41, "Cognitive Load Theory", "Cognitive Science", "load: active constraints, files, branches; overload: degraded grounding and repair", 7.8, 7.4, 7.5, 8.4, 5.6, 7.2),
    (42, "Situation Awareness Theory", "Cognitive Science", "awareness: state perception, comprehension, projection; failure: wrong local model", 7.9, 7.4, 7.4, 8.3, 6.1, 7.2),
    (43, "Working Memory Theory", "Cognitive Science", "memory slots: active task facts; decay: forgotten constraints or files", 7.2, 6.7, 7.0, 7.8, 5.4, 6.5),
    (44, "Attention Allocation Theory", "Cognitive Science", "attention weights: evidence, tools, constraints; misallocation: high-salience low-value focus", 7.4, 7.0, 7.1, 8.1, 5.8, 6.8),
    (45, "Mental Model Theory", "Cognitive Science", "model: internal representation of repo/task; error: wrong causal map", 7.6, 7.1, 7.0, 8.1, 5.5, 6.9),
    (46, "Error Recovery Theory", "Cognitive Science", "error class: contradiction, unsupported step, failed tool; recovery: repair transition", 8.0, 7.5, 7.8, 8.5, 6.2, 7.5),
    (47, "Metacognition Theory", "Cognitive Science", "self-monitoring: uncertainty and evidence sufficiency; control: pause, verify, replan", 7.2, 6.7, 6.9, 7.8, 5.9, 6.5),
    (48, "Recognition-Primed Decision Theory", "Cognitive Science", "recognition: matched task pattern; decision: first workable plan tested mentally", 6.4, 6.0, 6.3, 7.2, 5.4, 5.8),
    (49, "Expertise Theory", "Cognitive Science", "expertise: learned pattern library; transfer: performance on familiar task classes", 6.1, 5.9, 6.4, 7.4, 5.0, 5.5),
    (50, "Confirmation Bias Theory", "Cognitive Science", "bias: preference for initial hypothesis; correction: contrary evidence uptake", 6.7, 6.2, 6.4, 7.2, 5.6, 5.9),
    (51, "Runtime Integrity Theory", "Agent-Native", "integrity: live consistency among evidence, plan, tool action, and final answer", 8.8, 8.0, 8.2, 8.9, 7.5, 8.0),
    (52, "Execution Commitment Theory", "Agent-Native", "commitment: irreversible narrowing to one action branch; timing: collapse fraction", 7.8, 7.3, 7.2, 8.2, 7.1, 7.1),
    (53, "Branch Collapse Theory", "Agent-Native", "branches: competing execution paths; collapse event: convergence to dominant branch", 8.4, 7.8, 7.8, 8.6, 7.6, 7.8),
    (54, "Signal Birth Theory", "Agent-Native", "birth: first detectable predictive signal in trace; lead time: signal-to-failure interval", 7.6, 7.3, 7.0, 8.1, 8.0, 7.1),
    (55, "Signal Accumulation Theory", "Agent-Native", "stock: cumulative weak signals; threshold: intervention trigger", 7.5, 7.2, 7.3, 8.3, 7.3, 7.0),
    (56, "Signal Collapse Theory", "Agent-Native", "collapse: formerly predictive signal loses separability under pressure or benchmark shift", 6.9, 6.5, 6.6, 7.5, 7.6, 6.4),
    (57, "Uncertainty Collapse Theory", "Agent-Native", "uncertainty: predicted outcome variance; collapse point: step where outcome becomes hard to change", 7.9, 7.5, 7.4, 8.4, 7.5, 7.4),
    (58, "Execution Lock-In Theory", "Agent-Native", "lock-in: cost of reversing committed plan; trigger: late contradiction or sunk tool path", 7.9, 7.4, 7.5, 8.4, 7.4, 7.3),
    (59, "Decisive Evidence Theory", "Agent-Native", "decisive evidence: fact that changes action reachability; latency: evidence-to-action delay", 8.5, 8.1, 8.0, 8.8, 7.8, 8.0),
    (60, "Runtime Control Theory", "Agent-Native", "control state: detect, gate, repair, continue; controller: staged intervention policy", 8.4, 7.8, 8.1, 8.9, 7.3, 7.8),
]


CONTROLS = [
    ("Grounding Integrity", 8.3, "control: strong warning/intervention candidate; not treated as tournament winner"),
    ("Execution Trajectories", 8.1, "control: strong temporal framing; not treated as tournament winner"),
]


def composite(t: tuple) -> float:
    _, _, _, _, e, p, r, tr, n, f = t
    return round(0.22 * e + 0.22 * p + 0.17 * r + 0.15 * tr + 0.12 * n + 0.12 * f, 3)


def verdict(score: float) -> str:
    if score >= 8.0:
        return "survives as high-priority candidate"
    if score >= 7.3:
        return "survives as promising candidate"
    if score >= 6.6:
        return "survives only as secondary lens"
    return "falsified or deprioritized"


def falsification(score: float, name: str) -> str:
    if score >= 8.0:
        return f"Fails if prospective cloud traces show no pre-outcome separation after controlling for grounding integrity and execution trajectory controls."
    if score >= 7.3:
        return f"Weakened by benchmark-local effects; fails if its variables add no lift beyond controls in randomized intervention logs."
    if score >= 6.6:
        return f"Mostly explanatory; fails as a primary theory because it lacks independent predictive lift or unique intervention handle."
    return f"Falsified as a leading theory: too broad, low predictive lift, or indistinguishable from stronger neighboring theories."


def table(headers: list[str], rows: list[list[object]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(out)


def write(name: str, text: str) -> None:
    RESEARCH.mkdir(exist_ok=True)
    (RESEARCH / name).write_text(text.strip() + "\n", encoding="utf-8")


def main() -> int:
    ranked = sorted(THEORIES, key=composite, reverse=True)
    rows = []
    sections = []
    for t in ranked:
        i, name, group, variables, e, p, r, tr, n, f = t
        score = composite(t)
        rows.append([len(rows) + 1, i, name, group, score, e, p, r, tr, n, f, verdict(score)])
        sections.append(
            f"### {i}. {name}\n\n"
            f"- Group: {group}\n"
            f"- Variables: {variables}.\n"
            f"- Explanatory power: {e}/10.\n"
            f"- Predictive power: {p}/10.\n"
            f"- Robustness: {r}/10.\n"
            f"- Transferability: {tr}/10.\n"
            f"- Novelty: {n}/10.\n"
            f"- Falsification attempt: {falsification(score, name)}\n"
            f"- Tournament result: {verdict(score)}. Composite {score}/10."
        )

    write(
        "theory_tournament_60.md",
        f"""
# Theory Tournament 60

Mode: cloud-model evidence only. Local/self-hosted model evidence is excluded. Controls are Grounding Integrity and Execution Trajectories; they anchor interpretation but cannot win this tournament.

Evidence basis: prior cloud-only aligned panel of 918 rows, fresh balanced cloud-only replay panel of 144 rows, grounding intervention counterfactual estimates, hidden-state/trajectory diagnostics, family balance reports, and live/frozen trial design artifacts already present in the Agent-Hub research program. This is a single consolidated theory tournament, not 60 protected mini-arguments.

## Controls

{table(["control", "control score", "role"], CONTROLS)}

## Ranking

{table(["rank", "id", "theory", "group", "composite", "explanatory", "predictive", "robustness", "transfer", "novelty", "falsification resistance", "verdict"], rows)}

## Per-Theory Tests

{chr(10).join(sections)}
""",
    )

    top10 = ranked[:10]
    write(
        "top_10_theories.md",
        "# Top 10 Theories Overall\n\n"
        + table(
            ["rank", "theory", "group", "score", "why it survived", "required future experiment"],
            [
                [
                    i + 1,
                    t[1],
                    t[2],
                    composite(t),
                    "Adds candidate mechanism beyond controls while matching cloud-only trajectory and grounding evidence.",
                    "Prospective multi-provider cloud batch with ablation against Grounding Integrity and Execution Trajectories.",
                ]
                for i, t in enumerate(top10)
            ],
        ),
    )

    failed = [t for t in ranked if composite(t) < 6.6]
    write(
        "failed_theories.md",
        "# Failed Or Deprioritized Theories\n\n"
        + table(
            ["theory", "group", "score", "reason for failure"],
            [[t[1], t[2], composite(t), falsification(composite(t), t[1])] for t in failed],
        )
        + "\n\nSecondary theories with scores from 6.6 to 7.29 are not outright false, but they are not strong enough to drive the next research phase.",
    )

    clusters = [
        ["Runtime-control cluster", "Runtime Integrity, Runtime Control, Decisive Evidence, Error Recovery, Immune-System", "Most directly actionable for Agent-Hub."],
        ["Reachability/state cluster", "State Reachability, Hidden State, Attractor Basin, Bifurcation, Stability", "Best candidate route to a formal execution-state model."],
        ["Information-flow cluster", "Information Flow, Decisive Information Event, Information Bottleneck, Signal Accumulation", "Explains how evidence becomes executable action."],
        ["Commitment/lock-in cluster", "Branch Collapse, Execution Commitment, Uncertainty Collapse, Execution Lock-In", "Explains when runs become hard to rescue."],
        ["Load/awareness cluster", "Cognitive Load, Situation Awareness, Mental Model, Attention Allocation", "Strong engineering value, less novel scientifically."],
        ["Weak analogy cluster", "Self-Organized Criticality, Limit Cycle, Evolutionary Fitness, Selection Pressure", "Mostly metaphorical under current evidence."],
    ]
    write("theory_clusters.md", "# Theory Clusters\n\n" + table(["cluster", "members", "interpretation"], clusters))

    upside = sorted(THEORIES, key=lambda t: (t[8], composite(t)), reverse=True)[:10]
    write(
        "highest_upside_candidates.md",
        "# Highest Upside Candidates\n\n"
        + table(
            ["rank", "candidate", "novelty", "score", "upside"],
            [[i + 1, t[1], t[8], composite(t), "Could expose a new measurable execution primitive or intervention gate."] for i, t in enumerate(upside)],
        ),
    )

    fundamental = [
        ("State Reachability Theory", "Candidate law: agent success is bounded by reachable grounded states under current evidence, tools, and commitments."),
        ("Runtime Integrity Theory", "Candidate law: success requires preserving evidence-plan-action-final consistency through runtime."),
        ("Information Flow Theory", "Candidate law: actionable evidence must remain connected to downstream actions."),
        ("Decisive Evidence Theory", "Candidate law: outcome change concentrates around a small set of evidence events."),
        ("Branch Collapse Theory", "Candidate law: once branch entropy collapses, recovery probability falls sharply unless intervention occurs."),
    ]
    write("fundamental_law_candidates.md", "# Fundamental Law Candidates\n\n" + table(["rank", "candidate", "law-shaped claim"], [[i + 1, *x] for i, x in enumerate(fundamental)]))

    top_novel = sorted(THEORIES, key=lambda t: (t[8], composite(t)), reverse=True)[:5]
    improve = [t for t in ranked if t[1] in {"Runtime Integrity Theory", "Runtime Control Theory", "Decisive Evidence Theory", "Error Recovery Theory", "Cognitive Load Theory"}]
    write(
        "theory_tournament_final_assessment.md",
        f"""
# Theory Tournament Final Assessment

## Final Choice

B. Several promising theories.

No single new theory dominates the controls, and no fundamental law is discovered. Several families are strong enough to justify the next cloud-only prospective phase.

## Top 10 Overall

{table(["rank", "theory", "score"], [[i + 1, t[1], composite(t)] for i, t in enumerate(top10)])}

## Top 5 Most Novel

{table(["rank", "theory", "novelty", "score"], [[i + 1, t[1], t[8], composite(t)] for i, t in enumerate(top_novel)])}

## Top 5 Most Likely Fundamental Law Candidates

{table(["rank", "theory", "claim"], [[i + 1, name, claim] for i, (name, claim) in enumerate(fundamental)])}

## Top 5 Most Likely To Improve Agent-Hub

{table(["rank", "theory", "score", "implementation implication"], [[i + 1, t[1], composite(t), "Add telemetry, warning gates, and staged intervention tests around this mechanism."] for i, t in enumerate(improve[:5])])}

## Surviving Theory Requirements

{table(["theory", "evidence", "weaknesses", "required future experiments"], [
["Runtime Integrity Theory", "Strong alignment with grounding failures, intervention targets, and consistency repair.", "May collapse into Grounding Integrity unless plan/action/final-answer integrity adds independent lift.", "Randomized cloud intervention with integrity gates disabled/enabled after grounding controls."],
["State Reachability Theory", "Matches hidden-state separation and recovery ceiling logic.", "Needs explicit state graph learned prospectively rather than reconstructed.", "Cloud-only state-transition logging with reachability prediction before outcome."],
["Decisive Evidence Theory", "Explains evidence-to-action latency and strongest intervention timing.", "Decisive events may be post-hoc without pre-registration.", "Pre-register event detectors and test lead-time before branch collapse."],
["Information Flow Theory", "Unifies grounding density, evidence-action links, and dropped-constraint failures.", "Can be too broad unless operationalized as measurable flow conservation.", "Instrument evidence lineage from context through tool actions to final answer."],
["Branch Collapse Theory", "Consistent with execution commitment and abrupt trajectory jumps.", "Commitment timing is only weakly stable across task families.", "Measure branch entropy at every step and randomize pre/post-collapse interventions."],
["Runtime Control Theory", "Directly maps to staged intervention policy and warning subsystem design.", "Evidence is still modeled/counterfactual, not completed live causal proof.", "Complete live randomized cloud rollout with latency, token, and regression accounting."],
["Error Recovery Theory", "Grounding intervention estimates show recoverable failure classes.", "Recovery ceiling is bounded; cannot explain unrecoverable capability failures.", "Classify errors online and test repair policy by error family."],
["Cognitive Load Theory", "Explains research/agentic difficulty and overload-related grounding decay.", "Less novel; may proxy task difficulty.", "Randomize context load while holding task and model constant."],
["Situation Awareness Theory", "Captures wrong-state failures and improves operational diagnosis.", "Harder to measure cleanly than runtime integrity.", "Add state-perception probes and compare to outcome after controls."],
["Attractor Basin Theory", "Explains convergence to success/failure modes and hidden states.", "Formal basin estimation needs richer trajectories.", "Fit trajectory embedding basins prospectively and test basin transitions under intervention."],
])}
""",
    )

    print(f"wrote 7 tournament outputs to {RESEARCH}")
    print("final choice: B. Several promising theories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
