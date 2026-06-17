# Live Grounding Integrity Intervention Trial Design

Trial id: `grounding-integrity-live-rct-2026-06-17-v1`. Frozen date: 2026-06-17. Assignment seed: `20260617`.

## Frozen Live Batch

Machine-readable batch: `research/live_frozen_intervention_batch.jsonl`.

| field | value |
| --- | --- |
| frozen tasks | 20 |
| cloud rule | enabled agents with provider_type=ollama-cloud and model suffix :cloud |
| control | normal Agent-Hub execution |
| treatment | Agent-Hub execution plus delivered Grounding Integrity intervention when triggered |
| threshold | 0.42 |

## Trigger Rules

| trigger | rule |
| --- | --- |
| contradictory grounding | draft contains explicit inconsistency markers |
| evidence-action mismatch | draft misses at least half of frozen evidence keywords or omits a test action |
| grounding collapse | draft expresses inability/unknown while evidence keywords remain missing |
| grounded-action ratio below threshold | keyword-grounded action ratio < 0.42 |

## Delivered Interventions

Treatment-only triggered rows receive a second cloud call with evidence recheck, evidence verification, action consistency check, and grounding confirmation. Control rows receive no intervention.
