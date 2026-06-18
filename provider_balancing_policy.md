# Provider Balancing Policy

Policy version: `1`.

- Maximum accepted share per model family: `50%`.
- Minimum valid cloud model families for prospective execution: `3`.
- Replacement routes are limited to cloud agents that pass provider preflight/certification.
- The panel executor chooses the least-used eligible family first, then least-used agent.
- A route is temporarily backed off after provider failures, schema failures, timeouts, overload, quota, auth, or subscription errors.
- A capped family is removed from automatic replacement for the next row unless every other approved route is unavailable.
- Malformed outputs are quarantined before ingestion and do not count toward accepted diversity.
