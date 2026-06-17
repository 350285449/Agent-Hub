# Commitment Instrumentation Validation

Commitment is measured from ledger events:

- branch creation: direct `branch_creation`
- branch selection: direct `branch_selection`
- branch switching: direct `branch_switching`
- commitment onset: first `commitment_event`
- lock-in: explicit lock flag or strength threshold with no later reversal

200-row dry-run instrumentation failures: 0.
