# GCT 50-Row Quarantine Report

Quarantined rows: `2` of `50` (`4.00%`).
Malformed-ingestion count: `0`.

| row | provider | model | failure reason | raw response summary | retry count | recoverability |
| --- | --- | --- | --- | --- | --- | --- |
| gct-v2-coding-050 | ollama-nemotron-cloud | nemotron-3-super, nemotron-3-super:cloud | No valid structured output for pre_commit after 2 attempts: ["json_decode:Expecting ',' delimiter", "json_decode:Expecting ',' delimiter"] | [Provider returned malformed response]; {   "events": [     {       "id": "e1",       "event_type": "evidence_discovery",       "phase": "pre_commit",       "payload": {"explanatio | 1 | recoverable_with_schema_or_json_repair; not accepted in this run |
| gct-v2-coding-040 | ollama-nemotron-cloud | nemotron-3-super | Provider returned invalid response: missing_content_or_tool_calls | {   "events": [     {       "event_type": "evidence_discovery",       "phase": "pre_commit",       "payload": {"summary": "Observed CI-only  | 0 | recoverable_by_provider_reroute_or_availability_fix; not accepted in this run |
