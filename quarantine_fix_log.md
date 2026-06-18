# Quarantine Fix Log

| blocker | fix implemented | file | result |
| --- | --- | --- | --- |
| quarantined checkpoint rows were skipped on rerun | removed quarantine skip so failed rows are retried while accepted rows still resume | `scripts/frozen_panel_executor.py` | exact rerun command executed live rows again |
| commitment responses used pre_commit phases / event-level final_answer | added stricter structured-output prompts and executor-local provider response normalization | `scripts/frozen_panel_executor.py` | parser/schema quarantines dropped to 0 in final dashboard |
| repair retry lacked pre_commit context | passed pre_commit trace into commitment repair retry | `scripts/frozen_panel_executor.py` | commitment repair remained executable |
| provider-local ids such as ev5/br3 were lost after ledger ingestion | preserved declared ids in event payload and resolved them as aliases | `scripts/frozen_panel_executor.py` | 19/20 rows completed with valid instrumentation |
| unusable providers attempted before Gemma | evidence recorded; no config/GCT change made | run artifacts | qwen/kimi/glm returned subscription/auth errors; nemotron returned invalid response |
