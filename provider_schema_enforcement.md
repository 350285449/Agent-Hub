# Provider-Neutral Schema Enforcement

Schema version: `1`.

Contract applies to every configured provider through the frozen panel executor. Provider responses are parsed as JSON, validated against one event schema, and accepted only when strict phase gates pass.

- Required root key: `events`.
- Required event keys: `event_type`, `payload`, `phase`.
- Repair policy: one malformed JSON repair candidate and one provider re-prompt are allowed.
- Quarantine policy: malformed outputs are written under `_quarantine` with row, phase, attempt, errors, and raw provider call.
- Ingestion policy: invalid payloads are never passed to the event ledger.

```json
{
  "commitment_event_types": [
    "branch_selection",
    "branch_switching",
    "commitment_event",
    "justification_event"
  ],
  "event_optional_keys": [
    "branch_id",
    "commitment_strength",
    "event_id",
    "evidence_refs",
    "evidence_unit",
    "id",
    "local_grounding",
    "lock_in",
    "previous_branch_id",
    "selected_branch_id",
    "uncertainty"
  ],
  "event_required_keys": [
    "event_type",
    "payload",
    "phase"
  ],
  "optional_root_keys": [
    "final_answer"
  ],
  "pre_commit_event_types": [
    "branch_creation",
    "evidence_discovery",
    "evidence_interpretation",
    "evidence_recognition",
    "uncertainty_estimate"
  ],
  "repair_attempts_allowed": 1,
  "required_root_keys": [
    "events"
  ],
  "root_type": "object",
  "schema_version": 1
}
```
