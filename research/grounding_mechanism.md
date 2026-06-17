# Grounding Mechanism

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Direct Tests

| question | result |
| --- | --- |
| Does grounding precede convergence? | 1 of runs with both grounding and convergence have grounding no later than convergence. |
| Does convergence precede success? | 0.891566 of converged runs that succeed have convergence before the final success outcome. |
| Can success be predicted after grounded state? | success after grounding is 0.88755 versus 0.466368 without grounding. |
| Does grounding explain Dynamic Assimilation? | Dynamic Assimilation holdout/prospective R2 is 0.611615/0.117627; grounding alone is 0.612539/0.101662; dynamic without grounding is 0.592129/0.092633. |

## Interpretation

Grounding is the mechanism that turns retrieval into convergence. Dynamic Assimilation is broader because it also includes later tool, verification, branch-collapse, and recovery evidence; however, the largest early jump is grounding-related rather than generic tool use.
