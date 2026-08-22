# 0041 - Self-service account deletion is a direct route, not a control verb

- Status: proposed (design only, 2026-08-22; nothing built)
- Date: 2026-08-22
- Blocks: the iPhone app's `DELETE /v1/me` entry
  (`BoltrigEnvironment.accountDeletionAvailable = false`),
  `docs/HANDOVER-2026-08-22-ios-app.md` Part 4 "Blocked" item 4
- Relates to: SEC-202, SEC-203 and
  `docs/HANDOVER-2026-08-18-offboarding-and-the-worker-floor.md`

## Context

`DELETE /v1/me` does not exist. App Store review requires an in-app deletion
path for an app that creates accounts, so the phone ships with the entry behind
a flag. This record exists so the next implementer does not begin by making the
obvious wrong choice, which is expensive to discover and cheap to avoid.

## The finding that shapes it: do NOT make this a `control.*` verb

Every other administrative operation in this codebase is a `control.*` verb, so
that is the natural instinct. Three independent mechanisms make a `control.*`
account-deletion verb unusable by the very person it is for:

1. **The grant lattice denies it before any gate runs.**
   `boltrig/identity/rbac.py` sets `WORKSPACE_ROLE_CEILINGS["member"]` to
   `GrantSet.of(allow=["*"], deny=["control.*"])`, and `"agent"` the same. A
   caller acting inside a workspace as `member` has `control.*` denied at the
   chokepoint, before `_preauthorize_high_consequence` is ever consulted. That
   is a hard 403 the targeted-exemption idiom cannot reach.
2. **Consequence.** `boltrig/kernel/approval_posture.py` returns
   `verb_def.consequence == Consequence.HIGH` for a direct human call, and
   `_spec` defaults new verbs to `high`. A HIGH verb yields `PendingHuman` and a
   202, not a deletion.
3. **Anti-self-approval.** `boltrig/kernel/hitl_response_auth.py` refuses
   `initiators & respondents` unless the tenant has exactly one active
   author-tier user. So a member deleting their own account would need a
   different human to approve it. That is not self-service, and it is precisely
   the blocker the phone is waiting on.

Dropping the verb to LOW consequence dodges (2) and (3) and **not** (1).

**This is the SEC-203 one-way door, one layer lower.**
`control.integration.connect` was LOW so any member could seal a credential;
`control.integration.revoke` was HIGH and gated on `can_author`, so the member
who connected got a 403 revoking their own row and was left holding a live
third-party token nothing they could reach would destroy. The lesson recorded
there applies verbatim: **exercise the delete AS THE SAME PRINCIPAL, not as an
admin.**

The codebase already settles this by precedent. Every self-service destructive
`/v1/me/*` route writes through the store directly and audits; **none**
dispatches a control verb: `DELETE /v1/me/conversations/{id}`,
`DELETE /v1/me/tokens/{id}`, `DELETE /v1/me/sessions/{id}`,
`POST /v1/auth/change-password`. The contrast is `PATCH /v1/admin/users/{id}`,
which *does* dispatch `control.user.deactivate` — and is admin-only.

## Decision (proposed)

`DELETE /v1/me` is a direct route in the `register_*_routes` idiom, modelled on
`boltrig/kernel/auth_password_routes.py` (proof-of-credential, then fan-out
revocation) rather than on the control-verb idiom. It should live in a new
module rather than `boltrig/kernel/access_routes.py`, which sits on an exact
structural ratchet — the same reasoning `auth_password_routes.py` records for
its own existence.

Order of operations inside the handler, which mirrors
`boltrig/config/control_compat.py`'s rule that external authority dies first so
a failure can be retried rather than orphaning live credentials:

1. Bind the session realm (`session.tenant_id`), not the active org — sessions
   live at the identity realm for a multi-org identity.
2. Rate-limit per identity.
3. Re-prove the credential. A session is a bearer of identity, not proof of the
   credential; `auth_password_routes.py` rejects the weaker reading explicitly.
4. Refuse the sole-active-author lockout (409) rather than orphan the org.
5. Deactivate the user, revoke every session and every PAT, clear TOTP and
   recovery codes, close conversations, and revoke every user-scoped
   integration connection — that last one is SEC-202: a departing member's
   sealed credential must not outlive them.
6. Audit keys-only. Never the email or display name.

**Do not attempt to erase the audit trail.** `boltrig/store/rls.sql` strips
`UPDATE` and `DELETE` from `audit_log`, `security_log`, `config_revisions`,
`trajectory_events` and `execution_ledger` for the app role. A deletion design
that tries will be refused by the database, and should be.

## What the implementer must know before starting

- **There are no foreign keys to `users`.** Not one, in the schema or in any
  migration; there is no `ondelete` anywhere. **Nothing cascades.** Every
  dependent table must be handled explicitly, and there are roughly two dozen.
- **`GET /v1/me/export` is not a sufficient inventory.** It gathers
  conversations, work items and settings. It omits PATs, sessions, TOTP,
  recovery codes, credentials, artifacts, devices, personal agents, memory,
  integration connections, AI configs, notification prefs, channel bindings and
  org/workspace memberships. An export narrower than a deletion is itself a gap
  worth fixing in the same pass.
- **`tests/worker_surface_ledger.py` carries an exact route census**, not a
  ratchet. `DELETE /v1/me` needs a row and the count needs incrementing, or the
  ledger test fails first and loudest.
- **`tests/approval.py::approved_request` calls `kernel.hitl.answer` directly**,
  so a passing test using it does NOT prove a real user could approve. Do not
  read a green there as evidence the flow works for a member.
- **Do not test with `x-boltrig-grants: "*"`.** That header is exactly what
  would mask finding (1). Seat the user as a real `member` in a workspace.

## Open forks — for the court, not for the implementer to settle silently

1. **Proof for an SSO user.** An IdP-provisioned user has no `user_credentials`
   row, so there is no password to verify. Options: require a password and 409
   for SSO (honest, blocks SSO deletion); fall back to TOTP where enrolled;
   accept the session alone (weakest, and `auth_password_routes.py` already
   rejects that reasoning); or type-the-email as a second factor of intent.
2. **Deactivate-then-purge, or erase synchronously.** Nothing in the codebase
   hard-deletes a `users` row today; `control.user.deactivate` only flips a
   status, and `boltrig/fleet/retention.py` is where hard purging happens. The
   existing shape argues for deactivate-now, purge-later — but App Store review
   reads "delete" literally, so the window must be short and stated.
3. **The last org admin.** Refuse (fail-closed, matching the codebase's
   temperament) or transfer ownership. Not settled anywhere.
4. **Whether an admin `control.user.erase` should exist too.** Separate verb if
   so — "two verbs, not one with a role branch", so the audit trail can say
   which of the two happened.

Until 1 and 2 are settled, the route should not be called "delete" in its own
docstring if it only deactivates. That overclaim is the kind the prose gates and
claim inventory exist to catch.
