# Missing Observables

Date: 2026-06-19

Purpose: candidate measurements modern agent research is largely blind to.

## Candidate Observables

| Observable | Definition | Why it is missing |
| --- | --- | --- |
| Viable Reachability Delta (VRD) | Per-step change in reachable task-completing states under remaining resources. | Benchmarks score terminal success but rarely measure whether each step opens or closes future completion paths. |
| Transition Reversibility | Cost or probability of returning from current state to a previous viable state. | Agents can make mistakes that are cheap, expensive, or impossible to undo; most leaderboards flatten this into success/failure. |
| Repair Efficiency | Improvement in task viability per unit of feedback, retry, or debugging action. | Reflexion-style work measures improvement over trials, not the conversion rate from feedback to recovered state. |
| Feedback Assimilation Rate | Fraction of feedback constraints that alter subsequent actions correctly and promptly. | Feedback presence is logged more often than feedback uptake. |
| Branch Topology | Shape of the live option graph: branch count, depth, merge rate, dead-end rate, dominance. | ToT/LATS expose trees, but benchmarks usually score the final path, not the structure of alternatives. |
| State-Transition Graph Structure | Nodes are execution states; edges are actions/observations; graph metrics include bottlenecks and dead ends. | Most traces are linear logs even when the agent internally searches or revises. |
| Transition Velocity | Rate at which an agent moves toward or away from viable terminal states. | Step count is measured; progress per step is not. |
| State-Space Compression | Reduction in live hypotheses/options after evidence assimilation, without premature loss of viable paths. | Research measures confidence or success, not whether compression is valid. |
| Trajectory Curvature | Degree to which a trajectory bends after evidence, feedback, or contradiction. | Agents that "change their mind" are not distinguished from agents that merely continue with different words. |
| Resource Burn Rate | Resource consumed per unit of viable progress. | Tokens/tool calls are measured, but not normalized by progress in the task state-space. |
| Coupling Validity | Whether an action is constrained by a valid observation/environment reference. | GAR-like metrics approximate this, but most benchmarks do not align each action to a validated observation. |
| Irreversible Commitment Point | First point after which reversal cost crosses a threshold while branch entropy is low. | Commitment is often inferred after success/failure rather than measured prospectively. |
| Dead-End Entry Rate | Frequency with which the agent enters states from which success is impossible or too expensive. | Failures are counted, but the entry point into failure is usually unmeasured. |
| Recovery Horizon | Number of steps/resources required to restore viability after a bad transition. | Repair is often evaluated as another trial, not as a local state-space property. |
| Exploration Yield | Viable new branches discovered per search/tool/action budget. | Breadth is sometimes measured; useful breadth is not. |

## Strongest Pattern

Many candidates reduce to one deeper observable:

```text
How each transition changes viable reachability.
```

Branch topology, reversibility, repair, feedback assimilation, trajectory curvature, and resource burn are all projections of this transition-level viability change.

## Non-Candidates

These are useful but not the missing measurement target:

- raw success rate;
- raw step count;
- raw token count;
- self-reported confidence alone;
- benchmark category;
- final judge score;
- ungrounded reasoning trace length.

They are already measured or too downstream.
