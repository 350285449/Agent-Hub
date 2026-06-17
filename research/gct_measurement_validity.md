# GCT Measurement Validity Audit

Dataset: `research/gct_prospective_dataset.jsonl`; runner: `scripts/gct_prospective_program.py`.

## GAR / Grounding Measurement

The requested GAR audit cannot validate a true Grounded Action Ratio because the GCT dataset does not contain a `grounded_action_ratio` field. It contains `grounding_quality`, computed from final text using keyword ratio and the presence of generic terms such as action, patch, verifier, test, outcome, and runs first.

| measurement | status |
| --- | --- |
| true action trace denominator | absent |
| true evidence-to-action numerator | absent |
| grounding based on final text | present |
| grounding judged before outcome | no |

This is not a valid GAR measurement. It is a post hoc text heuristic.

## Commitment Score

Commitment quality is computed from the final answer text using generic markers such as choose, commit, branch, final, next action, runs first, patch, alternative, compare, verifier, test, and measure. `branch_commitment` is then thresholded at commitment quality >= 0.55.

| issue | effect |
| --- | --- |
| commitment judged from final answer | post hoc measurement |
| no temporal commitment point logged | cannot test before/after commitment cleanly |
| terse correct answers can score poor commitment | creates false negatives |
| treatment explicitly asks for branch comparison | inflates commitment marker score |

The four poor-commitment successes are real under this scoring rule, but they may reflect a weak commitment metric rather than true absence of commitment.

## Success Labels

Success is assigned when keyword ratio is at least 0.75, grounding quality is at least 0.45, and no contradiction marker appears. This means success is partly mechanically tied to the same text features used for grounding.

Examples:

| row | issue |
| --- | --- |
| `gct-reasoning-001` | provider returned malformed response but row has `ok=true`; success failure is valid operationally but not task-competence evidence |
| `gct-research-001` | long plausible answer fails because only 1/4 keywords are hit |
| `gct-reasoning-003` | correct terse answer succeeds despite very low commitment score |
| `gct-research-002` | correct answer succeeds with commitment quality 0.0 |

Success labels are usable as an internal keyword rubric, but too weak for theory-level falsification.

## Poor Commitment Labels

The poor-commitment labels are reproducible from the code, but not independently validated. They are especially vulnerable to prompt style: treatment asks for branch comparison, while control asks for a direct answer under 160 words. That creates asymmetric commitment-language incentives.

## Determination

Measurement validity is the largest data-quality problem. GAR is not measured, commitment is post hoc, success is keyword-coupled to grounding, and poor-commitment labels are not temporally grounded. This prevents accepting the 16-row result as a real falsification.
