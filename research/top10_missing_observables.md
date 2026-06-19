# Top 10 Missing Observables

Date: 2026-06-19

## 1. Viable Reachability Delta

Definition: change from step `t` to `t+1` in the set, probability mass, or minimum cost of reachable task-satisfying future states under remaining resources.

Instrumentation: after each action/observation, snapshot state, enumerate `k` plausible next routes or use a verifier to score whether success remains reachable; compute `VRD_t = viable_reachability(t+1) - viable_reachability(t)`.

Expected behavior: successful runs show early positive or preserved VRD, then valid compression; failures show negative VRD before terminal failure.

Falsification path: if VRD has no variance, cannot be measured reliably, or fails to predict/reconstruct success, repair, commitment, or grounding beyond simple step count and task family.

## 2. Transition Reversibility

Definition: estimated cost to undo or route around the current transition.

Instrumentation: label each state/action as reversible, costly-reversible, or irreversible; estimate required undo steps/tool calls/tests.

Expected behavior: irreversible wrong transitions create sharp failure risk; irreversible correct transitions look like productive commitment.

Falsification path: reversibility does not distinguish recoverable from unrecoverable failures.

## 3. Repair Efficiency

Definition: viability gained per feedback or repair action.

Instrumentation: inject or observe feedback, measure pre/post VRD, divide by repair resources.

Expected behavior: strong agents convert feedback into viability quickly; weak agents consume feedback without state improvement.

Falsification path: repair actions do not change viability or outcome after controlling for baseline ability.

## 4. Feedback Assimilation Rate

Definition: fraction of feedback constraints correctly reflected in subsequent actions within `n` steps.

Instrumentation: mark feedback facts/constraints, then score whether next actions obey or use them.

Expected behavior: high assimilation predicts recovery and fewer repeated failures.

Falsification path: assimilated feedback is indistinguishable from ignored feedback.

## 5. State-Space Compression

Definition: valid reduction of hypotheses/branches while preserving at least one viable solution route.

Instrumentation: track branch/hypothesis count, evidence support, and remaining viability before and after compression.

Expected behavior: success compresses after evidence; failure compresses before evidence or collapses viable routes.

Falsification path: compression cannot be separated from confidence wording or outcome labels.

## 6. Dead-End Entry Rate

Definition: frequency of transitions into states from which task completion is impossible or too costly.

Instrumentation: verifier labels first state where required constraints cannot be satisfied under remaining resources.

Expected behavior: failures have earlier and more frequent dead-end entries.

Falsification path: dead-end labels only appear after terminal failure and add no prospective signal.

## 7. Exploration Yield

Definition: number of viable new routes discovered per unit of exploration budget.

Instrumentation: count unique viable branches introduced by searches, tool calls, samples, or candidate generations.

Expected behavior: useful search has high yield; decorative search has breadth without viability gain.

Falsification path: branch count predicts as well as viable-branch count.

## 8. Trajectory Curvature

Definition: direction change in action/hypothesis space after evidence, contradiction, or feedback.

Instrumentation: embed or classify state/action descriptions and compute course-change after new information.

Expected behavior: adaptive agents bend after valid evidence; stuck agents remain straight; thrashing agents overbend.

Falsification path: curvature is mostly formatting variation and not tied to evidence or outcome.

## 9. Resource Burn Rate

Definition: resources spent per unit of viable progress.

Instrumentation: tokens, tool calls, wall time, retries, and actions divided by positive VRD or verified progress.

Expected behavior: strong agents have lower burn per viable gain, except on inherently hard tasks.

Falsification path: raw resource use explains as much as progress-normalized burn.

## 10. Branch Topology

Definition: graph shape of alternatives: branch count, depth, merge rate, dominance, dead-end density.

Instrumentation: require explicit branch IDs or reconstruct alternatives from sampled thoughts/actions.

Expected behavior: successful planning maintains several viable branches early and collapses after evidence.

Falsification path: topology without viability labels cannot predict commitment, repair, or success.
