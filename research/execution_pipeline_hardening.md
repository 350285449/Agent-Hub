# Execution Pipeline Hardening

Implemented recovery and acceptance gates:

| failure mode | recovery | acceptance rule |
| --- | --- | --- |
| malformed JSON | retry with repair prompt, then quarantine raw output | never accepted unless schema-valid |
| provider refusal/error | router failover plus executor retry | failed row retained as invalid |
| timeout/rate/quota | provider error classification and failover | not imputed |
| missing instrumentation | GAR/commitment/intervention validity gates | row invalid |
| logging failure | per-row raw trace, metrics files, event ledger | row invalid if artifacts missing |
| parser failure | strict JSON object extraction and schema validation | quarantined |
| intervention timing failure | pre-commit guard raises before event write | row invalid |

The executor now records failed rows explicitly instead of silently accepting partial outputs.
