# Mechanism Directionality

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Attack: reverse the compressed mechanism and ask whether `Outcome -> Commitment` or `Outcome -> Grounding` is a better directional account than `Evidence -> Grounding -> Branch Commitment -> Outcome`.

## Direction Tests

| direction tested | primary value | comparison value | delta / contribution | determination |
| --- | --- | --- | --- | --- |
| Grounding -> Commitment | 1.0 | 0.144538 | -0.003139 | favored |
| Commitment -> Grounding | 0.0 | -0.003139 | 0.144538 | not favored |
| Outcome -> Grounding | 0.414634 | 0.072727 | 0.341907 | retrospective association only |
| Outcome -> Commitment | 0.138837 | 0.023377 | 0.11546 | retrospective association only |

## Interpretation

Outcome predicts both grounding and commitment retrospectively, but that is terminal-label leakage rather than process direction. The temporal test is harsher: among runs with both grounding and convergence/commitment, grounding occurs no later than convergence at rate 1. First grounding also has stronger event contribution than first branch collapse in the existing event ranking.

## Determination

The reversal fails. Commitment is best treated as the downstream lock-in point; grounding is the upstream condition that makes commitment useful rather than merely irreversible.
