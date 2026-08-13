# Proposal: policy-gated auto-approval + dry-run preview

Status: DESIGN / the per-verb policy and dry-run described here are not
implemented. Boltrig does now have the narrower SEC-197 caller posture
(`always_ask`, `risk_based`, `full_access`): it changes only the extra consent
prompt for a caller's delegated adapter calls and cannot widen grants, match on
inputs, approve control-plane changes, or bypass deployment blocks. It is not
the rule engine proposed below and does not emit a policy-authored HITL decision.
This document remains the reviewed spec for the two broader features that change
the kernel chokepoint's behaviour. `AGENTS.md` forbids casually touching the
dispatch sequence, and a change to when the human-in-the-loop gate fires is
security-load-bearing.

## Why these two are sensitive

Both touch the one audited path every agent action goes through:

- **Approval policies** narrow *when* a high-consequence action pauses for a
  human. Done wrong, a policy is an approval-bypass backdoor.
- **Dry-run** adds a path that resolves and previews an action without executing
  it. Done wrong, it either leaks (returns data a denied caller shouldn't see) or
  diverges from the real decision (a misleading preview).

Neither may reorder the 10-step dispatch sequence. Both must be *additive* and
fully audited.

## A. Dry-run preview

### Behaviour
`POST /v1/invoke` (and the MCP `tools/call`) accept `dry_run: true`. The kernel
runs the chokepoint exactly as far as the decision is known - identity + grant
check + consequence determination + would-this-pause-for-approval - then
**short-circuits before `adapter.execute` and before raising HITL**, returning a
plan:

```json
{ "status": "plan", "verb": "payment.refund", "consequence": "high",
  "binding": "stripe-v1", "would_pause_for_approval": true,
  "grant_ok": true, "params_echo": { "...": "..." } }
```

### Invariant analysis
- A denied caller's dry-run MUST still be denied (the grant check runs first and
  unchanged) - so dry-run cannot be a discovery oracle for verbs you can't call.
- Dry-run MUST NOT execute: a side-effecting verb's effect does not happen. This
  needs a binding test (`a dry-run of a state-changing verb leaves state
  unchanged`).
- Dry-run MUST NOT widen scope: it returns only what the caller could already
  learn by being denied/allowed.
- The short-circuit is a single early-return *after* the grant/consequence steps
  and *before* execute - it does not reorder the sequence, but it is a new exit,
  so the dispatch invariants (`grant-checked before any effect`,
  `credentials resolved only inside the kernel`) must be re-asserted to still hold
  on the dry-run path.

### Open question for review
Is an early-return inside dispatch acceptable, or must dry-run be a separate
read-only `/v1/plan` route that re-derives the decision from the same primitives
(risking drift)? Recommendation: the in-dispatch early-return, because it reuses
the real decision and cannot drift; gated behind an explicit `dry_run` flag and
covered by the no-execute test.

## B. Policy-gated auto-approval

### Behaviour
Policy-as-data in the manifest `hitl` section:

```yaml
hitl:
  auto_approve:
    - verb: payment.refund
      when: { max_amount_micros: 250000000 }   # refunds under $250
      within_role: [support, lead]              # only for these roles
```

At the HITL-gate step, when `consequence == high` and an action would pause, the
kernel first evaluates the policy. If a rule matches, it **records an approval
automatically** (a real `HITLResponse` with `decided_by: "policy:<rule-id>"`,
fully audited) and proceeds; otherwise it raises HITL as today.

### Invariant analysis (the hard part)
- A policy may only ever **narrow toward auto-approve within a bounded
  allowlist**. It can never widen a caller's grants (SEC-29 / no-escalation still
  binds) and never auto-approve a verb the caller lacks.
- Every auto-approval is audited with the exact rule that matched and the inputs
  it matched on - so the audit log answers "why did this not pause?" as faithfully
  as it answers "who approved this?".
- Conditions are evaluated on the *resolved* inputs, in the kernel, not on
  caller-supplied claims.
- A policy is config, change-controlled like the rest of the manifest (revisioned,
  rollback-able) so a bad policy is traceable and reversible.
- The HITL-gate invariant changes from "high-consequence always pauses" to
  "high-consequence pauses unless a recorded, audited, bounded policy decided it" -
  this is the load-bearing change and the reason it needs review, not a quick PR.

### Open question for review
Is bounded, audited, config-revisioned auto-approval permissible at all - and if
so, what guard rails make it impossible to use as a blanket approval bypass
(e.g. a hard rule that `auto_approve` can never match `*`, must name a verb, must
carry at least one condition, and is itself a high-consequence config change that
pauses for approval to enable)?

## Build plan (only after review)
1. Dry-run: the early-return + the no-execute binding test + the denied-still-
   denied test. Smallest, least risky - ship first.
2. Approval policy: the policy schema + evaluator (pure, unit-tested against the
   allowlist/narrowing invariants) + the audited auto-approval record + the
   "enabling a policy is itself high-consequence" rule. Each new guarantee bound
   to a `@pytest.mark.invariant` at debt 0.

Until reviewed, neither is implemented. The rest of the "do all" backlog (RLS
live retrofit, Hatchet durable resume, the remaining frontend ideas) does not
touch the chokepoint and proceeds independently.
