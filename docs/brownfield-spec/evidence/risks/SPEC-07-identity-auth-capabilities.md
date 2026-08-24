# Risks harvested from SPEC-07-identity-auth-capabilities.md

RISK-07-01 (HIGH): **A PAT can answer the approval gate it itself raised on a
sole-author tenant.** `approval_response_block` refuses a non-`human`
`actor_tier`, then, when the responder is in the initiator set, tries the
sole-author relief FIRST and only reaches the credential-class check if that
relief does not apply. `credential_kind` is therefore never consulted on a
single-author tenant. `resolve_pat_principal` stamps `actor_tier="human"`. So a
PAT minted in the sole author's name can raise a gated `control.*` verb and then
clear its own approval through `POST /v1/hitl/{id}/respond`, with no person at any
keyboard. Cited: [`boltrig/kernel/hitl_response_auth.py:206`](../../../boltrig/kernel/hitl_response_auth.py)
`"if await _sole_active_author(store, tenant_id, subject):"`;
[`boltrig/identity/tokens.py:197`](../../../boltrig/identity/tokens.py)
`"actor_tier=\"human\","`. The development-posture arm explicitly closes this
same hole for its own relief and states the reasoning
([`boltrig/config/dev_posture.py:17`](../../../boltrig/config/dev_posture.py)
`"It does not admit a non-human approver. This is enforced on the CREDENTIAL"`),
which makes the asymmetry a gap rather than a design. No test in
`tests/security/test_sole_author_exemption.py` mentions `credential_kind` or a
PAT (bounded: `grep -n "credential_kind\|pat\|PAT"` on that file returns
nothing).

---

RISK-07-02 (HIGH): **The device-lease path proves the stricter rule is
expressible, and the generic path does not use it.** `DeviceLeaseIssuer.materialize`
refuses outright when `response.respondent` is in the requester set, with no
relief arm at all [`boltrig/device_leases.py:126`](../../../boltrig/device_leases.py)
`"or response.respondent in {"`. Two independence rules now exist for the same
concept, and only one of them is reachable from `respond_to_hitl`.

---

RISK-07-03 (HIGH): **`POST /v1/me/tokens` is reachable by a PAT, so a token can
mint further tokens.** The route takes only `Depends(principal_dep)`, which
admits a PAT principal, and its cap is `p.grants`. There is no
`is_interactive_credential` check and no rate limit. The same file's neighbours
show what such a check looks like
([`boltrig/kernel/approval_posture_routes.py:25`](../../../boltrig/kernel/approval_posture_routes.py)
`"if p.actor_tier != \"human\" or not is_interactive_credential(p.credential_kind):"`),
so its absence here is a choice nobody recorded. Cited:
[`boltrig/kernel/access_routes.py:287`](../../../boltrig/kernel/access_routes.py)
`"async def mint_my_token(body: dict, k=K, p=P) -> JSONResponse:"`. Bounded:
`rg -n "credential_kind|is_interactive_credential|rate_limiter"
boltrig/kernel/access_routes.py` returns nothing.

---

RISK-07-04 (HIGH): **`boltrig set-password` rotates a credential without revoking
any session.** The in-band rotation route and the reset CTE both revoke sessions;
the host-boundary command does not. An attacker's live session therefore survives
the very operator action taken to lock them out, for up to the 12-hour sliding
and 7-day absolute session lifetimes. Cited:
[`boltrig/api/initiate.py:219`](../../../boltrig/api/initiate.py)
`"await store.set_password_credential(tenant, email, hash_password(password))"`;
contrast [`boltrig/api/auth_password_routes.py:97`](../../../boltrig/api/auth_password_routes.py)
`"await k.store.revoke_user_sessions("`. Bounded: `rg -n "revoke_user_sessions"
boltrig/api/initiate.py` returns nothing.

---

RISK-07-05 (MEDIUM): **No credential rotation revokes the user's PATs.** Neither
`change-password`, nor the reset CTE, nor `set-password` touches
`personal_access_tokens`. A password rotation is normally performed BECAUSE the
credential is believed compromised, and a PAT minted before that moment keeps
working until its own expiry (up to 365 days). Cited:
[`boltrig/store/password_resets.py:171`](../../../boltrig/store/password_resets.py)
`"WITH claimed AS ("` (five CTE arms, none touching PATs). Bounded: `rg -n "pat"
boltrig/store/password_resets.py boltrig/api/auth_password_routes.py` returns
nothing.

---

RISK-07-06 (MEDIUM): **`OnBehalfOf` and `identity_mode` are a delegation
mechanism nothing reaches.** The module states that a delegated verb "must act as
the user and must not fall back to the service principal", yet `OnBehalfOf` is
never constructed anywhere in the tree and `identity_mode` is read only by a
view renderer. Every verb therefore runs as the service principal regardless of
what its registry row declares. Cited:
[`boltrig/identity/delegation.py:21`](../../../boltrig/identity/delegation.py)
`"SERVICE_PRINCIPAL = \"service-principal\""`;
[`boltrig/kernel/platform_routes/authored_registry_views.py:68`](../../../boltrig/kernel/platform_routes/authored_registry_views.py)
`"\"identity_mode\": verb.identity_mode,"`. Bounded: `rg -n "OnBehalfOf\("
--include=*.py .` returns nothing, and `rg -n "identity_mode" boltrig/kernel/
boltrig/fleet/ boltrig/adapters/` returns exactly the one view-render hit,
2026-08-24, pinned tree.

---

RISK-07-07 (MEDIUM): **A non-member active workspace applies NO narrowing rather
than failing closed.** `effective_grants_for_request` returns the ORG grants when
the membership row is missing. The comment argues this "never widens", and
relative to the org ceiling that is true; but the SESSION resolver has already
dropped a non-member workspace to `None` before this is called, so the surviving
reachable caller is the PAT path, where a race between the membership check and
this read yields org authority under a workspace the caller is not in. Cited:
[`boltrig/identity/provisioning.py:61`](../../../boltrig/identity/provisioning.py)
`"return base  # not a member -> no workspace narrowing (never widen)"`.

---

RISK-07-08 (MEDIUM): **`AUTHOR_ROLES` and `ROLE_PRECEDENCE` disagree on
membership, and the escalation guard reads only the precedence table.** `lead` and
`integrator` confer author tier (studios, admin console, four-eyes counting) but
are absent from `ROLE_PRECEDENCE`, so `_role_rank` ranks them BELOW `viewer` and
`_reject_escalation` lets any admin grant them. `engineer` is the inverse: ranked,
not an author. Cited:
[`boltrig/identity/rbac.py:164`](../../../boltrig/identity/rbac.py)
`"{\"superadmin\", \"admin\", \"org-admin\", \"department-head\", \"manager\", \"lead\", \"integrator\"}"`;
[`boltrig/kernel/access_routes.py:56`](../../../boltrig/kernel/access_routes.py)
`"if role is not None and _role_rank(str(role)) < _role_rank(p.role):"`. No test
compares the two sets (bounded: `rg -n "AUTHOR_ROLES" tests/` returns one prose
mention in `test_operator_seat_boundary.py`).

---

RISK-07-09 (MEDIUM): **`_reject_escalation` guards the roster routes but not the
control verb.** `PATCH /v1/admin/users/{id}` and `POST /v1/admin/invitations`
call it before dispatching, but the guard lives in the HTTP layer, so any other
caller of `control.user.update` or `control.invitation.create` is unguarded by it.
Cited: [`boltrig/kernel/access_routes.py:52`](../../../boltrig/kernel/access_routes.py)
`"def _reject_escalation(p, role, scope) -> None:"`. Whether the control-plane
handlers re-check is UNCERTAIN: I did not read `boltrig/config/control_operations.py`
in full.

---

RISK-07-10 (MEDIUM): **Behind a Cloudflare tunnel without
`BOLTRIG_TRUST_CF_CONNECTING_IP`, every per-IP bound collapses to one global
bucket.** The code names this as a login-DoS lever and a useless anti-spray, and
the opt-in is unset by default. Cited:
[`boltrig/api/auth_routes.py:438`](../../../boltrig/api/auth_routes.py)
`"per-IP bound keyed on it collapses to ONE global bucket (a login-DoS"`.

---

RISK-07-11 (MEDIUM): **A session cookie is `Path=/` unless
`BOLTRIG_TRUST_FORWARDED_PREFIX` is set.** On a tenant box the console shares an
origin with the Opbox app, so an unset opt-in hands the console's session secret
to an application that took no part in issuing it. The refusal is correct (the
header is client-settable) but the safe posture requires an explicit opt-in.
Cited: [`boltrig/kernel/web_security.py:116`](../../../boltrig/kernel/web_security.py)
`"if not is_truthy(e.get(\"BOLTRIG_TRUST_FORWARDED_PREFIX\")):"`.

---

RISK-07-12 (LOW): **Three reachable security behaviours are bound to no declared
invariant.** The forced-rotation clamp, PAT workspace selection, and
`set-password` all have test files with zero `@pytest.mark.invariant` markers, so
`scripts/check_invariants.py` cannot notice if they regress out of the catalogue.
Bounded: `grep -c "pytest.mark.invariant"` on
`tests/security/test_forced_password_rotation.py`,
`tests/security/test_pat_workspace_selection.py` and
`tests/security/test_set_password.py` returns 0 for each.

---

RISK-07-13 (LOW): **`boltrig initiate`'s run-once guard is a read-then-write with
no transaction and no uniqueness constraint.** Two concurrent runs with DIFFERENT
emails both read an empty list and both seat a superadmin. The module records this
as accepted rather than closed. Cited:
[`boltrig/api/initiate.py:13`](../../../boltrig/api/initiate.py)
`"KNOWN LIMIT - the \"refusing to run twice\" guard is a read-then-write."`.

---

RISK-07-14 (LOW): **The keyless-provider placeholder is a public constant.** A
provider in `_KEYLESS_PROVIDERS` gets the literal string `"keyless"` sealed as its
credential and digested, so `secret_digest` for every ollama seat is a known
value. Harmless while the server ignores authorization, but the digest is no
longer a secret-bearing discriminator. Cited:
[`boltrig/kernel/ai_key_routes.py:65`](../../../boltrig/kernel/ai_key_routes.py)
`"_KEYLESS_PLACEHOLDER = \"keyless\""`.

---

RISK-07-15 (LOW): **No retention sweep for expired identity rows.** Sessions,
PATs, invitations, consumed reset tokens and expired two-factor challenges are
excluded by predicate at read time and never deleted (except challenges, deleted
inside the reset CTE). Bounded: `rg -n "DELETE FROM (user_sessions|personal_access_tokens|user_invitations)" boltrig/`
returns nothing, 2026-08-24, pinned tree.

---

RISK-07-16 (LOW): **The README's OIDC claim is true only in third place.** It says
bootstrap selects real OIDC verification "when `OIDC_*` is set", but
`select_auth_resolver` checks session mode and Cloudflare Access FIRST, so a box
with both `BOLTRIG_AUTH_MODE=session` and a full OIDC trio runs session auth and
never touches the trio. Cited:
[`README.md:222`](../../../README.md) `"Real OIDC token verification"`;
[`boltrig/api/auth_selection.py:104`](../../../boltrig/api/auth_selection.py)
`"if settings.session_auth_configured:"`.
