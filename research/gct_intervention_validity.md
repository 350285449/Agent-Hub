# GCT Intervention Validity Audit

Dataset: `research/gct_prospective_dataset.jsonl`; runner: `scripts/gct_prospective_program.py`.

## Intervention Definition

Treatment rows first receive a control-style draft. Then the same selected cloud agent receives the draft plus an instruction to apply pre-commit evidence verification and branch comparison.

Control system prompt: "Answer directly in under 160 words. Include evidence, branch choice, outcome/verifier."

Treatment system prompt: verify evidence, justify accepted evidence, compare at least two branches, then give final action/outcome in under 180 words.

## Timing

| check | result |
| --- | --- |
| delivered before initial model answer | no |
| delivered before final treatment answer | yes |
| same agent retained for treatment final | yes |
| draft included in treatment context | yes |
| intervention delivered in treatment rows | 8/8 |

The intervention is not cleanly pre-commitment if the first draft already contains a branch choice and outcome. It is better described as a post-draft repair or revision intervention.

## Mechanism Change

| measure | control | treatment | direction |
| --- | ---: | ---: | --- |
| success | 100.0% | 62.5% | worse |
| grounding quality | 0.815625 | 0.696875 | worse |
| commitment quality | 0.49375 | 0.6625 | better |

The intervention appears to increase measured commitment language while decreasing grounding and success. That is consistent with added verbosity or branch-comparison overhead rather than a clean test of GCT's causal claim.

## Distraction and Overhead

Treatment answers had a longer and more complex prompt, included the initial draft, and required extra rhetorical structure. Failures occurred only in treatment rows. One treatment failure was `[Provider returned malformed response]`, which is an instrumentation/provider failure as much as a theory outcome.

## Determination

The intervention was delivered, but it did not test GCT cleanly. It mixed mechanism prompting, draft anchoring, extra output constraints, and overhead. It is evidence that this intervention did not improve this panel, not decisive evidence that correct pre-commit grounding/commitment interventions cannot work.
