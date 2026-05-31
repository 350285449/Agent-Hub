# Agent-Hub Architecture Modernization Phase 4

Phase 4 consolidates provider routing permissions behind the security layer.
The router still exposes the same compatibility methods and failover behavior,
but the decision mechanics for provider approval, enterprise policy checks,
permission audit events, and security audit records now live in
`agent_hub.security.provider_permissions`.

## Summary of Changes

- Added `ProviderPermissionPolicy` as the provider permission security boundary.
- Moved provider approval decisions out of `AgentRouter`.
- Moved trusted-cloud auto/compatibility bypass handling into the security layer.
- Moved enterprise-sensitive provider checks behind the same policy object.
- Moved provider permission event and security audit recording out of the router.
- Kept `AgentRouter._provider_permission_decision()` as a compatibility delegate.
- Kept `AgentRouter._enterprise_permission_decision()` as a compatibility delegate.

## Files Modified

- `agent_hub/security/provider_permissions.py`
- `agent_hub/core/router.py`
- `tests/test_provider_permission_policy.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase4.md`

## Architecture Boundary

The router now depends on one provider-permission boundary:

```text
AgentRouter
  -> ProviderPermissionPolicy
       -> PermissionManager
       -> EnterprisePolicy
       -> provider permission request builders
       -> provider permission observability
       -> provider routing security audit
```

This removes direct router dependencies on:

- `agent_hub.permissions`
- `agent_hub.enterprise`
- `agent_hub.security.audit`

## Compatibility Contract

Existing behavior remains stable:

- local/private providers return no blocking permission decision
- trusted cloud providers can be allowed without interactive approval in
  `approval_mode=auto` or IDE compatibility mode
- trusted cloud provider calls still honor enterprise policy before the bypass
- untrusted external providers still require explicit provider approval
- explicit provider approval still allows approved external provider calls
- permission audit and provider routing security audit events keep their stream
  names and event shapes
- router failover metadata still includes the provider trust level

## Risks Introduced

- **Permission regression risk: medium.** Provider approval is a routing gate, so
  behavior drift could block valid calls or allow calls unexpectedly. Direct
  policy tests cover trusted cloud, untrusted external, explicit approval, and
  enterprise-deny behavior.
- **Audit drift risk: medium.** Security and permission event writing moved to a
  new module. Tests assert both permission and security audit streams still
  receive provider events.
- **Private extension risk: low.** The router's private permission methods remain
  as delegates for compatibility with any internal callers.
- **Import-boundary risk: low.** Architecture guardrails assert the router no
  longer imports provider permission implementation modules directly.

## Tests Added Or Updated

- Added direct `ProviderPermissionPolicy` coverage for trusted cloud auto allow.
- Added direct coverage for untrusted external provider approval requirements.
- Added direct coverage that enterprise policy is checked before trusted auto
  bypass.
- Added router compatibility delegate coverage.
- Added architecture guardrail coverage for the security permission boundary.

## Validation Run

- `python -m unittest tests.test_provider_permission_policy`
- `python -m unittest tests.test_architecture_guardrails tests.test_permissions tests.test_server`
- `python -m unittest`
- `npm run check:version`
- `npm run package`
- `python scripts/validate_release.py --require-vsix`

## Remaining Work

- Move tool permission event recording out of `agent_hub.agent_tools`.
- Align provider security audit exports with a dedicated observability facade.
- Consolidate server-side explicit approval request shaping with the security
  policy so compatibility endpoints do not duplicate permission semantics.

## Rollback Strategy

Move the body of `ProviderPermissionPolicy.check()` back into
`AgentRouter._provider_permission_decision()`, restore the router imports from
`agent_hub.permissions`, `agent_hub.enterprise`, and `agent_hub.security.audit`,
and remove `tests/test_provider_permission_policy.py`.
