# Permissions

Agent Hub routes all risky actions through the central permission manager.

Protected action classes:

- shell commands and process spawning
- package manager commands
- file writes, config edits, and deletion
- external downloads
- cloud provider calls with workspace content
- workspace uploads
- secret-bearing content

Recommended production modes:

- `ask`: prompt before privileged actions.
- `safe`: require approval for risky operations and block critical commands.
- `readonly`: allow inspection and provider routing while blocking workspace
  changes.

Dangerous commands such as `rm -rf`, `git reset --hard`, sudo/admin escalation,
downloaded install scripts, and credential exposure are blocked or require
explicit approval.

See `docs/security-boundaries.md` for the provider, workflow, filesystem,
shell, and API boundary model.
