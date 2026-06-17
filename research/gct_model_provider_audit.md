# GCT Model and Provider Validity Audit

Dataset: `research/gct_prospective_dataset.jsonl`.

## Observed Model Coverage

| field | observed |
| --- | --- |
| final agent diversity | 1 agent: `ollama-nemotron-cloud` in 16/16 rows |
| final model diversity | `nemotron-3-super` in 15/16 rows; `nemotron-3-super:cloud` in 1/16 rows |
| final provider field | `null` in 16/16 rows |
| cloud-only row flag | `cloud_only=true` in 16/16 rows |
| cloud agent selected | `cloud_agent_selected=true` in 16/16 rows |

The panel overfits to one agent/model route. It is not a multi-model or multi-provider falsification.

## Should `ollama-nemotron-cloud` Count?

It can count as cloud-only evidence only in the narrow sense that the selected agent name ends in `-cloud` and the runner restricted configuration to provider type `ollama-cloud`. However, row-level evidence is incomplete:

| check | status |
| --- | --- |
| agent suffix indicates cloud | pass |
| runner enforces `provider_type == ollama-cloud` | pass by script logic |
| final model carries `:cloud` suffix | pass in only 1/16 rows |
| row records concrete provider | fail; provider is null |
| independent provider verification | absent |

So `ollama-nemotron-cloud` is admissible as a cloud-only row for this internal program, but weak as externally auditable cloud-only evidence.

## Provider Diversity

Provider diversity is effectively zero. The null provider field prevents independent validation that multiple hosted backends were used. Even if `ollama-nemotron-cloud` is accepted, it supplies one provider family and one model family.

## Determination

Model/provider validity fails for broad falsification. The 16-row result may be a single-cloud-route result, but it should not be accepted as evidence that GCT fails across cloud models or providers.
