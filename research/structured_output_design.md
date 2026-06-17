# Structured Output Design

Structured-output enforcement is implemented in `agent_hub.research.gct_readiness`.

Rules:

- Requests include `response_format={"type":"json_object"}` when supported.
- Responses must contain a JSON object with a non-empty `events` array.
- Pre-commit responses may not contain commitment events.
- Required event types are checked by phase.
- Numeric metrics must be in `[0, 1]`.
- Malformed outputs are retried, repaired only by JSON extraction/trailing-comma cleanup, then quarantined.
- Quarantined output is never ingested into GAR, commitment, intervention, or outcome metrics.
