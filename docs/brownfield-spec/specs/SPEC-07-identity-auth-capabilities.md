---
area: 07 Identity, authentication, seats and capabilities
id-block: BT-REQ-0700..0799
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: brownfield-spec area 07
date: 2026-08-24
---

# SPEC-07 Identity, authentication, seats and capabilities

## Bound of this reading

Read exhaustively, line by line: `boltrig/identity/*.py` (20 modules, 3535 lines),
`boltrig/capabilities/*` (2 files), `boltrig/kernel/access_routes.py`,
`account_profile_routes.py`, `ai_key_routes.py`, `ai_key_proposal_routes.py`,
`bearer_principal.py`, `device_crypto.py`, `device_routes.py`,
`boltrig/device_leases.py`, `boltrig/api/auth_routes.py`,
`auth_password_routes.py`, `auth_recovery_routes.py`, `auth_selection.py`,
`desktop_session_auth.py`, `mint_token.py`, `password_reset_composition.py`,
`host_boundary.py`, `boltrig/api/initiate.py`.

Read in full because the area's contracts are unreadable without them:
`boltrig/config/dev_posture.py`, `boltrig/kernel/hitl_response_auth.py`,
`boltrig/models/access.py`, `boltrig/models/identity.py`,
`boltrig/models/tenancy.py`, `boltrig/models/grants.py`,
`boltrig/kernel/org_discovery_routes.py`, `boltrig/kernel/integration_scope.py`,
`boltrig/config/author_ratchet.py`, `boltrig/store/password_resets.py`.

Sampled at top-level-definition depth, then read in depth only where a claim in
this spec rests on them: `boltrig/kernel/app.py` (Principal, resolver wiring,
`/v1/mcp`, `/v1/hitl/{id}/respond`), `boltrig/kernel/mcp.py` (run-token seam),
`boltrig/identity/bifrost_user_admin.py` (constants and method list only, not the
HTTP bodies), `boltrig/identity/mailersend_password_reset.py` (config validation
and the send path, not the JSON body shaping), `boltrig/kernel/device_agent_routes.py`
and `device_route_support.py` (the authentication path only),
`boltrig/store/postgres.py` (PAT and org rows only), `boltrig/config/manifest.py`
(`_parse_identity` only), `boltrig/config/settings.py` (auth fields only).

NOT read: the whole of `boltrig/store/postgres.py`, `boltrig/kernel/dispatch.py`
(only the author-crossing block), the channel adapters, the Worker/Familiar
frontends, `apps/`, `ios/`. Claims that would need those are marked UNCERTAIN.

## 2. Purpose

This subsystem answers three questions before any verb runs: who is calling, what
authority do they hold, and whose credential does the platform spend on their
behalf. It turns a bearer, a cookie, or an edge assertion into a `Principal`
carrying a `GrantSet`, narrows that set by org, workspace and role, and holds the
first-party credential lifecycle (invite, password, second factor, recovery,
session, personal access token). It also owns the per-scope AI-provider and
per-user integration credentials, which are the only places a user's own secret
is sealed and later spent by the kernel.

## 3. Boundaries

**Owns.** Verifiers and principal resolvers (`boltrig/identity/auth.py`), the
IdP-group to role/scope map and every grant-narrowing rule
(`boltrig/identity/rbac.py`), just-in-time provisioning
(`boltrig/identity/provisioning.py`), first-party sessions
(`boltrig/identity/sessions.py`), passwords, invites, TOTP, recovery tokens,
personal access tokens, per-scope AI-key resolution, the account and access
management HTTP surface (`boltrig/kernel/access_routes.py` and its registered
children), and the host-boundary attribution constant
(`boltrig/api/host_boundary.py`).

**Does not own.** The grant CHECK itself is the kernel chokepoint
(`GrantChecker`, invoked from `boltrig/kernel/dispatch.py`); this subsystem only
computes the set it checks. The approval independence rule lives in
`boltrig/kernel/hitl_response_auth.py` and reads `Principal.credential_kind` and
`identity.rbac.AUTHOR_ROLES` from here; that file is area 08's, but the two
constants it reads are this area's contract, so both are specified here.
Credential SEALING is `boltrig/store/sealing.py` (area 05); this area only writes
and reads references through `set_credential_ref` / `get_credential_ref`.

**Forbidden imports.** `boltrig/identity/auth.py` imports `authlib` lazily and
only inside `_load_authlib_jwt`, so the package stays import-safe and offline-safe
without it: [`boltrig/identity/auth.py:31`](../../../boltrig/identity/auth.py)
`"def _load_authlib_jwt(algorithms: list[str] | None = None)"`. A missing authlib
raises a RuntimeError naming SEC-01 rather than degrading to no verification
[`boltrig/identity/auth.py:46`](../../../boltrig/identity/auth.py)
`"OIDC token verification requires the 'authlib' package"`.

`boltrig/identity/user_view.py` exists because the projection was written twice
and two copies of a projection is one copy and a future disagreement
[`boltrig/identity/user_view.py:5`](../../../boltrig/identity/user_view.py)
`"Two copies of a projection is one copy"`. It deliberately carries no password
hash, session token, or TOTP secret
[`boltrig/identity/user_view.py:14`](../../../boltrig/identity/user_view.py)
`"NOTE WHAT IS ABSENT. No password hash"`.

## 4. Objects and contracts

### 4.1 `Principal` (the authenticated caller)

Built by exactly one resolver per request and never from a request body.

| field | default | meaning |
| --- | --- | --- |
| `tenant_id` | required | the ONE active org this request is bound to |
| `subject` | required | user id (the normalised email on the first-party path) |
| `grants` | `GrantSet.of([])` | effective verb authority for this request |
| `role` | `"agent"` | platform role |
| `actor_tier` | `"ephemeral"` | the authority tier acted with |
| `on_behalf_of` | `None` | delegated-actor subject |
| `scope` | `{}` | visibility scope (departments / nouns / verbs) |
| `active_workspace_id` | `None` | re-authorised every request, never body-supplied |
| `ip_address`, `user_agent` | `None` | stamped at the door |
| `credential_kind` | `"machine"` | HOW the caller authenticated |

Cited at [`boltrig/kernel/app.py:40`](../../../boltrig/kernel/app.py)
`"class Principal:"` through
[`boltrig/kernel/app.py:66`](../../../boltrig/kernel/app.py)
`"credential_kind: str = \"machine\""`.

`credential_kind` is deliberately a SEPARATE axis from `actor_tier`, and the code
says why: conflating them "let a machine bearer clear a control approval"
[`boltrig/kernel/app.py:63`](../../../boltrig/kernel/app.py)
`"them is what let a machine bearer clear a control approval"`. It defaults to
`"machine"` so an unlabelled resolver is refused rather than admitted.

`Principal.context()` drops caller-supplied values for `RESERVED_CONTEXT_KEYS`
(`principal_role`, `principal_scope`, `approved_by`, `approval_request_id`,
`approval_request_fingerprint`, `approval_resource_context`, `knowledge_scopes`,
`memory_scopes`) so a request body can never seed kernel-trusted authority
[`boltrig/kernel/app.py:113`](../../../boltrig/kernel/app.py)
`"RESERVED_CONTEXT_KEYS = frozenset("`.

### 4.2 The complete principal-type inventory

Every construction site of `Principal` in the tree (bounded:
`rg -n "Principal\(" --include=*.py boltrig/`, 2026-08-24, pinned tree; eight
sites, two of which are Protocol declarations in `run_access.py`):

| # | principal type | resolver | `actor_tier` | `credential_kind` | citation |
| --- | --- | --- | --- | --- | --- |
| 1 | Federated OIDC user (JIT-provisioned) | `build_principal_resolver` with a store | `human` | `federated` | [`boltrig/identity/auth.py:285`](../../../boltrig/identity/auth.py) `"return Principal("` |
| 2 | Federated OIDC user (no store, mapping only) | `build_principal_resolver` without a store | `human` | `federated` | [`boltrig/identity/auth.py:299`](../../../boltrig/identity/auth.py) `"grants=grants_for_scope(scope),"` |
| 3 | Cloudflare Access edge identity | `build_cf_access_resolver` | `human` | `federated` | [`boltrig/identity/auth.py:373`](../../../boltrig/identity/auth.py) `"return Principal("` |
| 4 | Dev header identity (two variants) | `dev_principal_resolver`, `_dev_principal` | header-supplied, default `human` | `dev-header` | [`boltrig/identity/auth.py:404`](../../../boltrig/identity/auth.py) `"credential_kind=\"dev-header\","`, [`boltrig/kernel/app.py:197`](../../../boltrig/kernel/app.py) `"stands in for an interactive session"` |
| 5 | First-party browser session | `build_session_resolver` | `human` | `session` | [`boltrig/identity/sessions.py:377`](../../../boltrig/identity/sessions.py) `"a person, at the door, with a password"` |
| 6 | Personal access token | `resolve_pat_principal` via `resolve_principal` | `human` | `pat` | [`boltrig/identity/tokens.py:201`](../../../boltrig/identity/tokens.py) `"credential_kind=\"pat\","` |
| 7 | Channel-bound external sender | `channel_principal` | `human` | UNSET, so `machine` | [`boltrig/kernel/channel_principal.py:95`](../../../boltrig/kernel/channel_principal.py) `"return Principal("` |
| 8 | Workflow webhook trigger owner | `webhook_principal` | `human` | UNSET, so `machine` | [`boltrig/kernel/workflow_trigger_delivery.py:84`](../../../boltrig/kernel/workflow_trigger_delivery.py) `"return Principal("` |

Two further caller shapes are NOT `Principal`s and never become one:

* **MCP run token.** A per-run bearer registered in an in-process, sha256-keyed,
  TTL-bounded registry, carrying a `GrantSet` directly rather than an identity
  [`boltrig/kernel/mcp.py:47`](../../../boltrig/kernel/mcp.py)
  `"A run-scoped MCP connection record (least privilege, SEC-23)"`. TTL is
  clamped to `1 <= ttl_seconds <= 3600`
  [`boltrig/kernel/mcp.py:116`](../../../boltrig/kernel/mcp.py)
  `"not 1 <= ttl_seconds <= self.MAX_RUN_TOKEN_TTL_SECONDS"`.
* **Device session.** A desktop device authenticates with its own opaque scoped
  token at the device-agent routes and yields an `EnrolledDevice`, not a
  `Principal` [`boltrig/kernel/device_route_support.py:38`](../../../boltrig/kernel/device_route_support.py)
  `"async def authenticate_device(request: Request, kernel, device_id: str)"`.

### 4.3 `GrantSet` (the capability primitive)

Immutable `(allow, deny)` tuples of verb ids or terminal-wildcard patterns.
Doctrine is baked in: deny dominates and short-circuits (K-5), nothing-matched is
deny (K-13), and only a TERMINAL wildcard matches, so `jira.*` covers `jira.read`
but not `jirax.read` (K-9)
[`boltrig/models/grants.py:104`](../../../boltrig/models/grants.py)
`"if any(_matches(p, verb_id) for p in self.deny):"` and
[`boltrig/models/grants.py:87`](../../../boltrig/models/grants.py)
`"return verb_id == prefix or verb_id.startswith(prefix + \".\")"`.

A verb id that is not a SAFE identifier after NFKC never matches any pattern, so
a Unicode confusable cannot impersonate an ASCII verb
[`boltrig/models/grants.py:76`](../../../boltrig/models/grants.py)
`"if not is_safe_identifier(verb_id):"`.

`intersect` is NOT symmetric set intersection: it keeps SELF's patterns that
OTHER fully permits, and expands a `*` or `noun.*` on the self side into the
other side's covered concrete entries
[`boltrig/models/grants.py:124`](../../../boltrig/models/grants.py)
`"elif pattern == \"*\":"`. Denies are unioned
[`boltrig/models/grants.py:142`](../../../boltrig/models/grants.py)
`"deny = tuple(set(self.deny) | set(other.deny))"`.

### 4.4 Role vocabularies (three sets, and they do not agree)

| set | members | citation |
| --- | --- | --- |
| `ROLE_PRECEDENCE` (most privileged first) | superadmin, admin, org-admin, department-head, manager, engineer, member, agent, viewer | [`boltrig/identity/rbac.py:22`](../../../boltrig/identity/rbac.py) `"ROLE_PRECEDENCE: tuple[str, ...] = ("` |
| `AUTHOR_ROLES` (may author + counts for four-eyes) | superadmin, admin, org-admin, department-head, manager, lead, integrator | [`boltrig/identity/rbac.py:163`](../../../boltrig/identity/rbac.py) `"AUTHOR_ROLES: frozenset[str] = frozenset("` |
| `CF_ACCESS_TIERS` (console product tiers) | superadmin, admin, member | [`boltrig/identity/auth.py:328`](../../../boltrig/identity/auth.py) `"CF_ACCESS_TIERS: tuple[str, ...] = (\"superadmin\", \"admin\", \"member\")"` |
| `_ADMIN_ROLES` (org administration on the roster routes) | org-admin, superadmin, admin | [`boltrig/kernel/access_routes.py:44`](../../../boltrig/kernel/access_routes.py) `"_ADMIN_ROLES = frozenset({\"org-admin\", \"superadmin\", \"admin\"})"` |
| `WORKSPACE_ROLES` | owner, admin, member, viewer, agent | [`boltrig/models/tenancy.py:29`](../../../boltrig/models/tenancy.py) `"WORKSPACE_ROLES: frozenset[str] = frozenset("` |
| `_WORKSPACE_ADMIN_ROLES` | owner, admin | [`boltrig/kernel/access_routes.py:40`](../../../boltrig/kernel/access_routes.py) `"_WORKSPACE_ADMIN_ROLES = frozenset({\"owner\", \"admin\"})"` |

`lead` and `integrator` are AUTHOR_ROLES that appear in NO precedence table, so
`_role_rank` sorts them last, below `viewer`
[`boltrig/identity/rbac.py:44`](../../../boltrig/identity/rbac.py)
`"return len(ROLE_PRECEDENCE)"`. `engineer` is in the precedence table and is NOT
an author role. See RISK-07-08.

### 4.5 Records

| record | table | key | secret at rest | citation |
| --- | --- | --- | --- | --- |
| `User` | `users` | (tenant_id, id) | none (credential is a separate table) | [`boltrig/models/identity.py:13`](../../../boltrig/models/identity.py) `"class User:"` |
| `RoleMapping` | manifest-only | (tenant, idp_group) | none | [`boltrig/models/identity.py:41`](../../../boltrig/models/identity.py) `"class RoleMapping:"` |
| password credential | `user_credentials` | (tenant_id, user_id) | argon2id PHC string | [`migrations/versions/0010_first_party_login.py:43`](../../../migrations/versions/0010_first_party_login.py) `"CREATE TABLE IF NOT EXISTS user_credentials ("` |
| `UserSession` | `user_sessions` | id, unique `token_hash` | sha256 of the cookie secret | [`boltrig/models/access.py:89`](../../../boltrig/models/access.py) `"class UserSession:"` |
| `PersonalAccessToken` | `personal_access_tokens` | id; resolved by `token_hash` | sha256 of the secret | [`boltrig/models/access.py:33`](../../../boltrig/models/access.py) `"class PersonalAccessToken:"` |
| `UserInvitation` | `user_invitations` | id, unique partial `token_hash` | sha256 of the invite secret | [`boltrig/models/access.py:48`](../../../boltrig/models/access.py) `"class UserInvitation:"` |
| `UserTotp` | `user_totp` | (tenant_id, user_id) | `secret_ref` only; base32 lives sealed | [`boltrig/models/access.py:127`](../../../boltrig/models/access.py) `"class UserTotp:"` |
| recovery codes | `user_recovery_codes` | (tenant, user, code_hash) | sha256 only | [`migrations/versions/0018_totp_two_factor.py:48`](../../../migrations/versions/0018_totp_two_factor.py) `"CREATE TABLE IF NOT EXISTS user_recovery_codes ("` |
| `TwoFactorChallenge` | `two_factor_challenges` | (tenant_id, token_hash) | sha256 only | [`boltrig/models/access.py:147`](../../../boltrig/models/access.py) `"class TwoFactorChallenge:"` |
| `PasswordResetToken` | `password_reset_tokens` | (tenant_id, user_id) | sha256 only, CHECK-constrained | [`migrations/versions/0045_password_reset.py:26`](../../../migrations/versions/0045_password_reset.py) `"CHECK (token_hash ~ '^[0-9a-f]{64}$')"` |
| `Organisation` | `organisations` | id == tenant_id | none | [`boltrig/models/tenancy.py:44`](../../../boltrig/models/tenancy.py) `"An organisation - the tenant boundary (D1)"` |
| `OrgMember` / `WorkspaceMember` | `org_members`, `workspace_members` | (tenant,user) / (workspace,user) | none | [`boltrig/models/tenancy.py:95`](../../../boltrig/models/tenancy.py) `"class OrgMember:"` |
| email to orgs index | `identity_orgs` | (email, tenant_id) | none | [`migrations/versions/0019_cross_tenant_identity.py:41`](../../../migrations/versions/0019_cross_tenant_identity.py) `"CREATE TABLE IF NOT EXISTS identity_orgs ("` |
| `AiConfig` | `ai_configs` | (tenant,level,scope_id,modality) | `credential_ref` only | [`boltrig/models/tenancy.py:129`](../../../boltrig/models/tenancy.py) `"class AiConfig:"` |
| `AiKeySecretProposal` | `ai_key_secret_proposals` | id `akp_*` | sealed staging + sha256 digest | [`boltrig/store/ai_key_proposal_contract.py:21`](../../../boltrig/store/ai_key_proposal_contract.py) `"def validate_proposal(proposal: AiKeySecretProposal, secret: str)"` |

### 4.6 Lifecycles

**User.** Created by exactly three routes: `boltrig initiate` (the founding
owner), accept-invite, and JIT provisioning on a federated login. A previously
provisioned user's stored role/scope/status is authoritative on every later
login, so an admin adjustment sticks and a deactivated user cannot self-revive by
re-logging-in [`boltrig/identity/provisioning.py:182`](../../../boltrig/identity/provisioning.py)
`"existing = await store.get_user(tenant_id, subject)"`.

**Session.** `new_session` mints a 12-hour bounded session with a fresh CSRF
token; `rotate_session` re-mints the secret in place, preserving the id, and
REFUSES past the 7-day creation-anchored cap
[`boltrig/identity/sessions.py:125`](../../../boltrig/identity/sessions.py)
`"raise ValueError(\"session past absolute lifetime cap\")"`.

**PAT.** Minted once, secret shown once, hash stored, expiry clamped to at most
365 days with a 90-day default
[`boltrig/identity/tokens.py:27`](../../../boltrig/identity/tokens.py)
`"MAX_TTL_DAYS = 365"`. Revocation is a flag; there is no re-mint in place.

**Provider seat (the Bifrost binding).** RE-MINTABLE IN PLACE and idempotent:
the credential ref is a deterministic sha256 of `(tenant, level, scope_id,
modality)` [`boltrig/identity/bifrost_user_binding.py:70`](../../../boltrig/identity/bifrost_user_binding.py)
`"digest = hashlib.sha256("`, and `ensure` returns the existing binding when it
is still usable, else re-provisions onto the SAME ref
[`boltrig/identity/bifrost_user_binding.py:190`](../../../boltrig/identity/bifrost_user_binding.py)
`"if existing is not None and await self.is_usable(existing):"`. A provider
change revokes the previous gateway objects before rewriting
[`boltrig/identity/bifrost_user_binding.py:226`](../../../boltrig/identity/bifrost_user_binding.py)
`"and previous.get(\"provider\") != provider"`. `POST /v1/ai-keys/activate` is
the explicit re-mint entry point and needs NO fresh approval and NO fresh secret
[`boltrig/kernel/ai_key_routes.py:320`](../../../boltrig/kernel/ai_key_routes.py)
`"@app.post(\"/v1/ai-keys/activate\")"`.

## 5. Control flow

### 5.1 Resolver selection at boot (one posture, fail-closed)

1. `select_principal_resolver` refuses a default/placeholder audit key under a
   production signal, then loads settings and the manifest
   [`boltrig/api/bootstrap.py:510`](../../../boltrig/api/bootstrap.py)
   `"refuse_default_audit_key_in_prod()  # K-19"`.
2. `select_auth_resolver` picks in strict order:
   `session` if `BOLTRIG_AUTH_MODE=session`
   [`boltrig/api/auth_selection.py:104`](../../../boltrig/api/auth_selection.py)
   `"if settings.session_auth_configured:"`; else Cloudflare Access if team domain
   and AUD are set; else generic OIDC; else dev auth; else deny-all.
3. **OIDC trust reconciliation.** A PARTIAL manifest OIDC trio refuses boot
   [`boltrig/api/auth_selection.py:71`](../../../boltrig/api/auth_selection.py)
   `"manifest identity OIDC trust is partial; issuer, audience and"`, and a
   manifest trio that DIFFERS from a simultaneously configured process trio also
   refuses [`boltrig/api/auth_selection.py:75`](../../../boltrig/api/auth_selection.py)
   `"manifest identity OIDC trust differs from process OIDC trust"`.
4. **Dev-auth failure branch.** `BOLTRIG_DEV_AUTH=1` under any production signal
   raises a FATAL RuntimeError rather than warning
   [`boltrig/api/boot_guards.py:33`](../../../boltrig/api/boot_guards.py)
   `"FATAL: BOLTRIG_DEV_AUTH is set with a production signal"`.
5. **Nothing configured.** Every request is refused 401
   [`boltrig/api/bootstrap.py:496`](../../../boltrig/api/bootstrap.py)
   `"detail=\"authentication is not configured\""`.
6. **No resolver passed to `create_app`.** Under a production signal this is
   FATAL; otherwise the header resolver is the fallback
   [`boltrig/kernel/app.py:257`](../../../boltrig/kernel/app.py)
   `"FATAL: create_app() received no principal_resolver with a production"`.
7. A `CF_ACCESS_ROLE_MAP` that is not valid JSON is logged and treated as EMPTY,
   which is deny-by-default, not open
   [`boltrig/api/auth_selection.py:35`](../../../boltrig/api/auth_selection.py)
   `"treating as empty (deny-by-default)"`.

### 5.2 Per-request principal resolution

1. `principal(request)` calls `resolve_principal`
   [`boltrig/kernel/app.py:321`](../../../boltrig/kernel/app.py)
   `"p = await resolve_principal(request, resolver, _get_kernel)"`.
2. `resolve_principal` reads the `Authorization: Bearer` value and short-circuits
   to the PAT path ONLY on the `boltrig_pat_` prefix
   [`boltrig/kernel/bearer_principal.py:54`](../../../boltrig/kernel/bearer_principal.py)
   `"if not (token and looks_like_pat(token)):"`.
   Failure branches: `WorkspaceNotPermitted` becomes 403, deliberately not 404,
   so the reply does not disclose which workspace ids exist
   [`boltrig/kernel/bearer_principal.py:67`](../../../boltrig/kernel/bearer_principal.py)
   `"raise HTTPException(status_code=403, detail=\"not a member of that workspace\")"`;
   an unresolvable PAT is 401
   [`boltrig/kernel/bearer_principal.py:69`](../../../boltrig/kernel/bearer_principal.py)
   `"detail=\"invalid or expired access token\""`.
3. Otherwise the configured resolver runs.
4. `ip_address` and `user_agent` are stamped from the request, never a body field
   [`boltrig/kernel/app.py:328`](../../../boltrig/kernel/app.py)
   `"p.ip_address = _client_ip(request)"`.
5. `set_current_tenant(p.tenant_id)` binds the RLS GUC for the rest of the request
   [`boltrig/kernel/app.py:332`](../../../boltrig/kernel/app.py)
   `"set_current_tenant(p.tenant_id)"`.

### 5.3 OIDC verification (`OidcVerifier.verify`)

1. Load the authlib JWT codec PINNED to the asymmetric allowlist
   (`RS256/384/512`, `ES256/384/512`), so `alg=none` and every HS* confusion is
   rejected by construction
   [`boltrig/identity/auth.py:74`](../../../boltrig/identity/auth.py)
   `"_ALLOWED_ALGS = (\"RS256\", \"RS384\", \"RS512\""`.
2. Read the `kid` from the header without verifying anything
   [`boltrig/identity/auth.py:122`](../../../boltrig/identity/auth.py)
   `"def _kid(self, token: str) -> str | None:"`. A malformed header yields
   `None`, and a `None` kid is treated as present so a single-key JWKS resolves
   [`boltrig/identity/auth.py:131`](../../../boltrig/identity/auth.py)
   `"return True  # let the verifier resolve a single-key JWKS"`.
3. Load the JWKS from cache (600s TTL default). On a kid MISS, force one refetch,
   but only if at least 30s have passed since the last fetch, so a bogus-kid
   storm cannot amplify into one outbound IdP request per inbound request
   [`boltrig/identity/auth.py:142`](../../../boltrig/identity/auth.py)
   `"if time.monotonic() - self._jwks_at >= self._FORCE_REFETCH_MIN_INTERVAL:"`.
   Failure branch: still missing after the refetch is 401 `unknown signing key`.
4. Decode with `iss`, `aud` and `exp` all essential, then `claims.validate` with a
   leeway clamped to at most 120 seconds
   [`boltrig/identity/auth.py:98`](../../../boltrig/identity/auth.py)
   `"self._leeway = max(0, min(int(leeway), 120))"`. Any exception becomes 401
   `invalid token`.
5. Reject an ID token presented as an access token when `token_use`/`typ` says so
   [`boltrig/identity/auth.py:163`](../../../boltrig/identity/auth.py)
   `"detail=\"id token is not an access token\""`. If neither claim is present the
   check is skipped, which is the documented shape.
6. Cap absolute lifetime twice: `exp - iat > 24h`, and independently
   `exp - now > 24h`, so a missing or non-numeric `iat` cannot let a far-future
   `exp` through [`boltrig/identity/auth.py:171`](../../../boltrig/identity/auth.py)
   `"if isinstance(exp, (int, float)) and exp - time.time() > self._MAX_LIFETIME:"`.

### 5.4 Federated principal build (`build_principal_resolver`)

1. Extract the bearer; a missing or non-`Bearer` header is 401
   [`boltrig/identity/auth.py:212`](../../../boltrig/identity/auth.py)
   `"detail=\"missing or malformed bearer token\""`.
2. Verify. Any non-HTTPException failure becomes 401 `token verification failed`
   [`boltrig/identity/auth.py:264`](../../../boltrig/identity/auth.py)
   `"detail=\"token verification failed\""`.
3. A token with no `sub`/`subject` is 401
   [`boltrig/identity/auth.py:268`](../../../boltrig/identity/auth.py)
   `"detail=\"token has no subject claim\""`.
4. Groups are pulled from `groups`, `roles`, or `cognito:groups`, in that order
   [`boltrig/identity/auth.py:218`](../../../boltrig/identity/auth.py)
   `"for key in (\"groups\", \"roles\", \"cognito:groups\"):"`.
5. With a store: `provision_user` runs; a `None` or non-active user is 403
   [`boltrig/identity/auth.py:284`](../../../boltrig/identity/auth.py)
   `"detail=\"no access for this identity\""`. The principal's grants are the
   user's CURRENT scope, so an admin adjustment or deactivation applies at once.
6. Without a store: role and scope come from the mappings alone, and a caller in
   no mapped group gets `(none, {})` which is `EMPTY_GRANTS`
   [`boltrig/identity/rbac.py:63`](../../../boltrig/identity/rbac.py)
   `"return (DEFAULT_ROLE, {})"`.
7. `on_behalf_of` is read from `act.sub` or `on_behalf_of`
   [`boltrig/identity/auth.py:229`](../../../boltrig/identity/auth.py)
   `"act = claims.get(\"act\")"`.

### 5.5 Cloudflare Access principal build

1. The assertion is the `Cf-Access-Jwt-Assertion` header, falling back to the
   `CF_Authorization` cookie; neither present is 401
   [`boltrig/identity/auth.py:320`](../../../boltrig/identity/auth.py)
   `"detail=\"missing Cloudflare Access assertion\""`.
2. Verify against the team JWKS at `<team>/cdn-cgi/access/certs`
   [`boltrig/api/auth_selection.py:41`](../../../boltrig/api/auth_selection.py)
   `"jwks_uri=f\"{team}/cdn-cgi/access/certs\","`.
3. An assertion with no `email` claim is 401; a mapped role outside
   `CF_ACCESS_TIERS` is 403 fail-closed even though Access already gated the
   origin [`boltrig/identity/auth.py:370`](../../../boltrig/identity/auth.py)
   `"detail=f\"{email} is not authorized\""`.
4. Every admitted tier gets `scope = {"all": True}`, so all three see the whole
   tenant and are differentiated only by `can_author` and by the HITL gate
   [`boltrig/identity/auth.py:372`](../../../boltrig/identity/auth.py)
   `"scope = {\"all\": True}  # tenant-wide"`.
5. The role map is lower-cased on both sides at build time
   [`boltrig/identity/auth.py:350`](../../../boltrig/identity/auth.py)
   `"role_map = {k.strip().lower(): v for k, v in (role_map or {}).items()}"`.

### 5.6 Session principal build (the ordered clamp chain)

1. No `boltrig_session` cookie is 401 `no session`
   [`boltrig/identity/sessions.py:273`](../../../boltrig/identity/sessions.py)
   `"raise HTTPException(status_code=401, detail=\"no session\")"`.
2. Bind the identity realm, then resolve the session by sha256 of the cookie.
   Unknown, revoked or expired is `None`, which becomes 401
   [`boltrig/identity/sessions.py:248`](../../../boltrig/identity/sessions.py)
   `"if session is None or session.revoked:"`.
3. **Active org.** `resolve_active_org` enumerates candidate orgs from the global
   `identity_orgs` index, then RE-AUTHORISES each against the RLS-fenced
   `org_members` row after binding that tenant
   [`boltrig/identity/sessions.py:204`](../../../boltrig/identity/sessions.py)
   `"set_current_tenant(tid)"`. A legacy identity with no index rows AND no
   seeded `active_org_id` falls back to the session's own realm; a
   membership-model session whose memberships were all revoked returns `None`
   [`boltrig/identity/sessions.py:199`](../../../boltrig/identity/sessions.py)
   `"return realm_tenant_id if session.active_org_id is None else None"`. `None`
   is 401.
4. Bind the ACTIVE org and read the PER-ORG `User` row. Missing or non-active is
   401 [`boltrig/identity/sessions.py:301`](../../../boltrig/identity/sessions.py)
   `"raise HTTPException(status_code=401, detail=\"invalid or expired session\")"`.
5. **CSRF.** On POST/PUT/PATCH/DELETE the `x-boltrig-csrf` header must match the
   session-bound token under `hmac.compare_digest`; failure is 403
   [`boltrig/identity/sessions.py:312`](../../../boltrig/identity/sessions.py)
   `"detail=\"csrf token missing or invalid\""`. Bearer and PAT callers never
   reach this code, so they are not CSRF-gated by design.
6. **Forced-rotation clamp.** `user.must_change_password` limits the session to
   `/v1/auth/csrf`, `/v1/auth/change-password`, `/v1/auth/logout`; anything else
   is 403 `password_change_required`
   [`boltrig/identity/sessions.py:322`](../../../boltrig/identity/sessions.py)
   `"raise HTTPException(status_code=403, detail=\"password_change_required\")"`.
7. **2FA enrollment clamp.** Only when the ACTIVE org sets `require_two_factor`,
   the TOTP row is read at the identity REALM (rebinding around that one read)
   and an unenrolled caller is limited to the enroll surface plus logout; 403
   `two_factor_enrollment_required`
   [`boltrig/identity/sessions.py:343`](../../../boltrig/identity/sessions.py)
   `"status_code=403, detail=\"two_factor_enrollment_required\""`.
8. **Active workspace.** Re-authorised against current membership on every
   request, by listing the caller's workspaces afresh
   [`boltrig/identity/sessions.py:231`](../../../boltrig/identity/sessions.py)
   `"workspaces = await store.list_workspaces_for_user(tenant_id, user_id)"`;
   a persisted workspace whose membership no longer holds drops to `None`
   rather than to the stale value
   [`boltrig/identity/sessions.py:232`](../../../boltrig/identity/sessions.py)
   `"if any(w.id == active_workspace_id for w in workspaces):"`.
9. Grants are computed ONCE here by `effective_grants_for_request` and the
   chokepoint then enforces them unchanged
   [`boltrig/identity/sessions.py:361`](../../../boltrig/identity/sessions.py)
   `"grants = await effective_grants_for_request(store, user, active_workspace_id)"`.
10. The RLS tenant is left bound to the ACTIVE org, and the `Principal.tenant_id`
    IS that org, so a cross-org read is structurally impossible for the rest of
    the request [`boltrig/identity/sessions.py:367`](../../../boltrig/identity/sessions.py)
    `"set_current_tenant(active_org_id)"`.

### 5.7 Grant derivation (scope to GrantSet to workspace ceiling)

1. `resolve_role(groups, mappings)` takes the HIGHEST-privilege matched role and
   the UNION of matched scopes; `org-admin` or any `{all: true}` collapses the
   merged scope to `{all: true}`
   [`boltrig/identity/rbac.py:67`](../../../boltrig/identity/rbac.py)
   `"if role == \"org-admin\" or any(_scope_is_all(m.scope) for m in matched):"`.
2. `grants_for_scope(scope)`: `{all: true}` becomes `["*"]`; otherwise the union
   of listed `verbs` plus one `<noun>.*` per listed noun, carrying any `deny`
   through; empty or missing scope becomes `EMPTY_GRANTS`
   [`boltrig/identity/rbac.py:107`](../../../boltrig/identity/rbac.py)
   `"return EMPTY_GRANTS"`. Departments are visibility metadata and do NOT widen
   the grant set [`boltrig/identity/rbac.py:103`](../../../boltrig/identity/rbac.py)
   `"Departments are visibility metadata, not verb authority"`.
3. `current_grants_for_user` returns `EMPTY_GRANTS` for a non-active user
   [`boltrig/identity/provisioning.py:31`](../../../boltrig/identity/provisioning.py)
   `"if user.status != \"active\":"`.
4. `effective_grants_for_request` narrows by the ACTIVE workspace role only.
   No active workspace returns today's grants unchanged; a MISSING membership row
   also returns today's grants, applying no narrowing rather than escalating
   [`boltrig/identity/provisioning.py:61`](../../../boltrig/identity/provisioning.py)
   `"return base  # not a member -> no workspace narrowing (never widen)"`.
5. `narrow_grants_to_workspace`: `viewer` keeps only concrete read-action
   patterns and collapses every wildcard; `owner/admin/member/agent` intersect
   with their `control.*` ceilings; an UNKNOWN workspace role becomes
   `EMPTY_GRANTS` [`boltrig/identity/rbac.py:259`](../../../boltrig/identity/rbac.py)
   `"return EMPTY_GRANTS  # unknown workspace role -> no authority (fail-closed)"`.

### 5.8 PAT resolution (`resolve_pat_principal`)

1. Look the token up by sha256; unknown or revoked returns `None`
   [`boltrig/identity/tokens.py:151`](../../../boltrig/identity/tokens.py)
   `"if pat is None or pat.revoked:"`.
2. Expired returns `None`.
3. **Bind the tenant BEFORE the owner read.** This is the one legitimate
   cross-tenant lookup; without the bind the RLS pool would see a null GUC and a
   valid token would 401 as de-provisioned
   [`boltrig/identity/tokens.py:162`](../../../boltrig/identity/tokens.py)
   `"set_current_tenant(pat.tenant_id)"`.
4. Missing or non-active owner returns `None`
   [`boltrig/identity/tokens.py:165`](../../../boltrig/identity/tokens.py)
   `"return None  # de-provisioned / deactivated -> token stops working"`.
5. **Workspace binding.** A REQUESTED workspace goes through the same
   `resolve_active_workspace` re-check as the session path and RAISES rather than
   falling back, because `None` means no active workspace which yields the
   owner's org grants UN-narrowed
   [`boltrig/identity/tokens.py:121`](../../../boltrig/identity/tokens.py)
   `"raise WorkspaceNotPermitted(requested_workspace_id)"`. With no request,
   exactly one membership binds; zero or many stay `None`
   [`boltrig/identity/tokens.py:124`](../../../boltrig/identity/tokens.py)
   `"return workspaces[0].id if len(workspaces) == 1 else None"`.
6. Effective grants are the PAT scope intersected with the owner's grants
   NARROWED by the workspace ceiling. The code records the historical hole this
   closes: until 2026-07-26 this line read the ORG grants, so a workspace VIEWER
   was refused a write through the browser and granted it through a PAT on the
   same account [`boltrig/identity/tokens.py:178`](../../../boltrig/identity/tokens.py)
   `"granted it through a PAT, in the same workspace, on the same account"`.
7. `last_used_at` is stamped and persisted on every successful resolve.

### 5.9 Invite-only account creation (`POST /v1/auth/accept-invite`, public)

1. Bind the console tenant, then apply a per-IP throttle (10/min) BEFORE the
   argon2 spend, because this is the only public endpoint that pays 64 MiB of
   argon2 before a single-use bearer is claimed
   [`boltrig/api/auth_routes.py:73`](../../../boltrig/api/auth_routes.py)
   `"_ACCEPT_RL_IP = RateLimit(per=\"minute\", max=10, scope=\"verb\")"`.
   A trip records a `RATE_LIMIT_TRIP` security event and returns 429.
2. Validate the password strength (>= 12 chars, <= 1024)
   [`boltrig/identity/passwords.py:28`](../../../boltrig/identity/passwords.py)
   `"MIN_PASSWORD_LENGTH = 12"`.
3. Hash the password BEFORE claiming the token, so pure work may fail only before
   the one-time bearer is spent
   [`boltrig/api/auth_routes.py:368`](../../../boltrig/api/auth_routes.py)
   `"Argon2 work is pure and may fail only before the one-time bearer is"`.
4. `claim_invitation_by_token_hash` atomically claims. Unknown, expired and
   already-used share ONE generic 400 so a probe cannot distinguish them
   [`boltrig/api/auth_routes.py:378`](../../../boltrig/api/auth_routes.py)
   `"{\"status\": \"error\", \"reason\": \"invalid or expired invite\"}"`.
5. Upsert the `User` with the invitation's intended role and scope, seed
   onboarding for a brand-new identity, then write the argon2id hash ONCE at the
   identity realm keyed by the normalised email, never duplicated per org
   [`boltrig/api/auth_routes.py:411`](../../../boltrig/api/auth_routes.py)
   `"await k.store.set_password_credential("`.
6. `_seat_invitee` materialises whichever of the three provisioning intents the
   invitation carries. Authority was bounded at invite CREATION, so nothing here
   is a fresh grant decision. A workspace seat coerces the invited platform role
   into `WORKSPACE_ROLES`, defaulting to `member`
   [`boltrig/api/auth_routes.py:173`](../../../boltrig/api/auth_routes.py)
   `"role = inv.intended_role if inv.intended_role in WORKSPACE_ROLES else \"member\""`.
   A provisioned org gets a fresh tenant_id, an `Organisation`, a per-org `User`
   at `superadmin` with `{all: true}`, onboarding, and the `OrgMember` index
   pointer [`boltrig/api/auth_routes.py:208`](../../../boltrig/api/auth_routes.py)
   `"id=email, tenant_id=new_tid, email=email, role=\"superadmin\","`.
7. Audit is keys-only: invitation id and email, never the password.

### 5.10 Login (`POST /v1/auth/login`, public)

1. Bind the console tenant, compute the client IP through `web_security.client_ip`
   which honours `CF-Connecting-IP` ONLY behind `BOLTRIG_TRUST_CF_CONNECTING_IP`
   and never trusts `X-Forwarded-For`
   [`boltrig/api/auth_routes.py:442`](../../../boltrig/api/auth_routes.py)
   `"X-Forwarded-For is deliberately NOT trusted"`.
2. Enforce BOTH rate limits (30/min per IP, 5/min per identity) before touching
   the credential store; a trip records `RATE_LIMIT_TRIP` and returns a generic
   429 [`boltrig/api/auth_routes.py:448`](../../../boltrig/api/auth_routes.py)
   `"await k.rate_limiter.enforce(tenant, f\"auth.login.ip:{client_ip}\", _LOGIN_RL_IP)"`.
3. Always spend an argon2 verify: the real one for an active user with a
   credential, the fixed decoy otherwise
   [`boltrig/api/auth_routes.py:471`](../../../boltrig/api/auth_routes.py)
   `"verify_dummy(password)"`.
4. Failure: keys-only audit plus a `LOGIN_FAILURE` security event, then the ONE
   byte-identical generic 401
   [`boltrig/api/auth_routes.py:78`](../../../boltrig/api/auth_routes.py)
   `"_GENERIC_LOGIN_FAILURE = {\"status\": \"error\", \"reason\": \"invalid email or password\"}"`.
5. **Second-factor fork.** `_two_factor_state` returns `(due, enrolled)`.
   * `enrolled` -> mint a 5-minute single-use challenge, issue NO session, return
     `2fa_required` [`boltrig/api/auth_routes.py:502`](../../../boltrig/api/auth_routes.py)
     `"return JSONResponse({\"status\": \"2fa_required\", \"challenge_token\": challenge})"`.
   * `due` but not enrolled -> issue an ENROLLMENT-ONLY session that the resolver
     clamps [`boltrig/api/auth_routes.py:511`](../../../boltrig/api/auth_routes.py)
     `"status=\"2fa_enrollment_required\")"`.
   * neither -> a plain session, with the response status set to
     `password_change_required` when the clamp applies so the console can route
     straight to rotation [`boltrig/api/auth_routes.py:521`](../../../boltrig/api/auth_routes.py)
     `"clamped = \"password_change_required\" if user.must_change_password else \"ok\""`.
6. `_mint_web_session` seeds the deterministic default active org from the global
   index and the default active workspace from membership WITHIN that org,
   rebinding the tenant around the workspace read so a cross-org login does not
   intersect to zero rows under live RLS
   [`boltrig/api/auth_routes.py:270`](../../../boltrig/api/auth_routes.py)
   `"if ws_tenant != tenant:"`.

### 5.11 Second factor

* **Enroll begin** (`POST /v1/auth/2fa/enroll`, session-authenticated, reachable
  from an enrollment-only session). Rate-limited per identity and per IP, because
  each call mints a fresh sealed secret and ROTATES the recovery codes
  [`boltrig/api/auth_routes.py:606`](../../../boltrig/api/auth_routes.py)
  `"Rate-limit the begin (like verify-enroll/challenge/disable)"`. Re-enrolling
  an already-enabled factor is refused 400, so the secret is never re-revealed
  [`boltrig/api/auth_routes.py:627`](../../../boltrig/api/auth_routes.py)
  `"\"reason\": \"two-factor is already enabled\""`. All 2FA state is written at
  the identity REALM, never the active org.
* **Verify enroll.** Only a TOTP code activates; a recovery code cannot bootstrap
  the factor [`boltrig/api/auth_routes.py:691`](../../../boltrig/api/auth_routes.py)
  `"Only a TOTP code activates enrollment (a recovery code cannot bootstrap it)"`.
  Nothing pending still spends a decoy verify.
* **Challenge** (public). Per-IP bound first, before any store or crypto work;
  the per-identity bound only after the challenge names the user. Unknown or
  expired spends a decoy verify and returns the one generic 401. The challenge is
  NOT consumed on a wrong code, so a retry within the TTL and the rate budget is
  allowed [`boltrig/api/auth_routes.py:775`](../../../boltrig/api/auth_routes.py)
  `"DO NOT consume the challenge on a miss"`. On a pass, the consume is atomic
  and a lost race fails
  [`boltrig/api/auth_routes.py:787`](../../../boltrig/api/auth_routes.py)
  `"if not await k.store.consume_two_factor_challenge(tenant, challenge.token_hash):"`.
* **Verify order.** `_verify_second_factor` ALWAYS spends a TOTP verify before
  trying the recovery fallback, so timing carries no oracle about which arm
  matched [`boltrig/api/auth_routes.py:319`](../../../boltrig/api/auth_routes.py)
  `"if verify_totp(secret, code):"`.
* **Disable.** Requires a FRESH factor (a current TOTP or a recovery code); it is
  never a bypass. Teardown drops the enrolment, clears the codes, and OVERWRITES
  the sealed secret with `{}`
  [`boltrig/api/auth_routes.py:852`](../../../boltrig/api/auth_routes.py)
  `"await k.store.set_credential_ref(tenant, totp.secret_ref, {})"`.

### 5.12 Password rotation and recovery

* **`POST /v1/auth/change-password`.** Proves the CURRENT password before
  rotating, because a session is a bearer of identity and not proof of the
  credential [`boltrig/api/auth_password_routes.py:37`](../../../boltrig/api/auth_password_routes.py)
  `"A session is a bearer of identity, not proof of the credential"`. Per-identity
  rate limit only (5/min). Re-setting the SAME password is refused, since that
  would clear the forced-rotation clamp while retiring nothing
  [`boltrig/api/auth_password_routes.py:86`](../../../boltrig/api/auth_password_routes.py)
  `"\"reason\": \"the new password must differ\""`. Every OTHER session of that
  identity is revoked, keeping the caller's own
  [`boltrig/api/auth_password_routes.py:97`](../../../boltrig/api/auth_password_routes.py)
  `"await k.store.revoke_user_sessions("`. Operates at the identity REALM.
* **`POST /v1/auth/password-reset/request`** (public). Rate-limited 3/hour per
  identity and 10/hour per IP, both consumed BEFORE any identity lookup, then
  always returns the same 202 envelope
  [`boltrig/api/auth_recovery_routes.py:39`](../../../boltrig/api/auth_recovery_routes.py)
  `"\"message\": \"If the account can be recovered, reset instructions have been sent.\""`.
  With NO notifier configured, nothing is minted at all: there is no console or
  log fallback [`boltrig/api/auth_recovery_routes.py:157`](../../../boltrig/api/auth_recovery_routes.py)
  `"No console/log fallback: absent explicit delivery means no minted bearer"`.
  Issuance happens in a background task; the store refuses to issue for an
  inactive or credential-less identity
  [`boltrig/store/password_resets.py:115`](../../../boltrig/store/password_resets.py)
  `"WHERE EXISTS ("`. A notifier exception is neither logged nor audited, because
  the adapter is outside the trust boundary and its text may carry provider
  payloads [`boltrig/api/auth_recovery_routes.py:95`](../../../boltrig/api/auth_recovery_routes.py)
  `"The delivery adapter is outside the trust boundary"`. A failed delivery
  invalidates that exact digest.
* **`POST /v1/auth/password-reset/confirm`** (public). Rate-limited per IP and
  per TOKEN HASH. Redemption is ONE data-modifying CTE: claim, rotate credential,
  clear the forced-rotation flag, revoke every session, delete every pending 2FA
  challenge [`boltrig/store/password_resets.py:171`](../../../boltrig/store/password_resets.py)
  `"WITH claimed AS ("`. No replacement session is issued; the response deletes
  both cookies.
* **Delivery evidence.** `password_reset_delivery_evidence` projects no
  recipient, provider, address, exception or message content, and reports a
  notifier acceptance as `accepted_by_notifier`, never as inbox delivery
  [`boltrig/identity/password_reset_evidence.py:29`](../../../boltrig/identity/password_reset_evidence.py)
  `"Project no recipient, provider, address, exception, or message content"`. An
  absent row inside the bounded 500-row tail reports
  `not_observed_in_bounded_tail`, never "never attempted".

### 5.13 Personal access token mint (two doors)

* **`POST /v1/me/tokens`.** Any authenticated principal; `ensure_user_record`
  first so a later resolve matches; the cap is `p.grants`
  [`boltrig/kernel/access_routes.py:303`](../../../boltrig/kernel/access_routes.py)
  `"user_grants=p.grants,"`. The secret is returned once inside the envelope
  [`boltrig/kernel/access_routes.py:308`](../../../boltrig/kernel/access_routes.py)
  `"view[\"secret\"] = secret  # shown ONCE, never stored in the clear"`.
* **`boltrig mint-token` (host shell).** Caps at `current_grants_for_user`, which
  is the ORG cap, and the module says so explicitly rather than claiming parity
  with the route [`boltrig/api/mint_token.py:12`](../../../boltrig/api/mint_token.py)
  `"The mint cap is deliberately stated as the ORG cap"`. A token minted here can
  be broader on paper than in effect because `resolve_pat_principal` applies the
  workspace ceiling at USE time. The audit actor is the HOST BOUNDARY, never the
  target [`boltrig/api/mint_token.py:87`](../../../boltrig/api/mint_token.py)
  `"actor=HOST_BOUNDARY_ACTOR, actor_tier=\"host\","`, plus a best-effort
  `HOST_BOUNDARY_CREDENTIAL` security event.

### 5.14 Scoped AI provider credential (the provider seat)

1. `PUT /v1/ai-keys` parses the intake and REJECTS any caller-supplied
   `approval_id`, `proposal_id` or `secret_digest`: that evidence is server-owned
   [`boltrig/kernel/ai_key_routes.py:74`](../../../boltrig/kernel/ai_key_routes.py)
   `"return None, _invalid(\"approval and proposal evidence is server-owned\")"`.
   The api key is `pop`ped off the body so it cannot survive into logging.
2. `_authorize_ai_key`: `org` level requires an admin role; workspace and user
   levels require the org's `allow_own_ai_keys` flag; workspace requires
   owner/admin membership unless org-admin; user level requires `scope_id ==
   principal.subject` unless org-admin
   [`boltrig/kernel/ai_key_routes.py:52`](../../../boltrig/kernel/ai_key_routes.py)
   `"elif level == \"user\" and not is_org_admin and scope_id != principal.subject:"`.
3. The secret is SEALED into a proposal BEFORE persistence, with a 15-minute
   maximum TTL and a sha256 digest, then `control.ai_key.set` is dispatched
   through the normal chokepoint
   [`boltrig/store/ai_key_proposal_contract.py:17`](../../../boltrig/store/ai_key_proposal_contract.py)
   `"AI_KEY_PROPOSAL_MAX_TTL = timedelta(minutes=15)"`.
4. If the dispatch pends for a human, the raised approval is bound to the sealed
   proposal. A failed bind expires the approval AND invalidates the proposal, and
   answers 503 rather than leaving orphaned staging
   [`boltrig/kernel/ai_key_routes.py:187`](../../../boltrig/kernel/ai_key_routes.py)
   `"await kernel.store.expire_hitl(principal.tenant_id, approval_id)"`.
5. **Self-approval fold.** For `level == "user"` and `scope_id == p.subject` ONLY,
   the route immediately answers the caller's own approval through
   `respond_to_hitl`, then finalises
   [`boltrig/kernel/ai_key_routes.py:299`](../../../boltrig/kernel/ai_key_routes.py)
   `"if attached is None or level != \"user\" or scope_id != p.subject:"`. The
   HITL layer decides whether that answer is lawful; a refusal returns the pending
   response unchanged [`boltrig/kernel/ai_key_proposal_routes.py:277`](../../../boltrig/kernel/ai_key_proposal_routes.py)
   `"The requester approving their own submission carries no oversight"`.
6. `proposal_state` invalidates on: a workspace mismatch, expiry, a missing
   approval id, a rejected or expired approval, and a CONSUMED approval whose
   proposal was not consumed, which is ambiguous and must never be claimed as
   applied [`boltrig/kernel/ai_key_proposal_routes.py:55`](../../../boltrig/kernel/ai_key_proposal_routes.py)
   `"Approval consumption without proposal consumption is ambiguous"`.
7. `_finalize_approved` RE-AUTHORISES before dispatching, and invalidates the
   staging if authority has changed since submission
   [`boltrig/kernel/ai_key_proposal_routes.py:86`](../../../boltrig/kernel/ai_key_proposal_routes.py)
   `"await _invalidate_state(kernel, principal, proposal, \"invalidated\")"`.
8. `activate_ai_key_config` loads the sealed material kernel-side and provisions
   the Bifrost provider key plus an exact-model virtual key, returning 503 with a
   sentence rather than a bare 500 for a legacy model id the current policy
   refuses [`boltrig/kernel/ai_key_proposal_routes.py:190`](../../../boltrig/kernel/ai_key_proposal_routes.py)
   `"except (BifrostUserBindingUnavailable, ValueError) as error:"`.

### 5.15 AI-key resolution at run time

`resolve_ai_key` precedence is user, workspace, org, then the manifest/env
default. When `allow_own_ai_keys` is False the user and workspace rows are SKIPPED
ENTIRELY, so revoking the policy is sufficient on its own with no row surgery
[`boltrig/identity/ai_keys.py:116`](../../../boltrig/identity/ai_keys.py)
`"if allow_own:"`. An absent org row is treated as `allow_own = False`
[`boltrig/identity/ai_keys.py:99`](../../../boltrig/identity/ai_keys.py)
`"allow_own = bool(org.allow_own_ai_keys) if org is not None else False"`. A
`vision` request falls back to the same scope's `text` row before descending a
level [`boltrig/identity/ai_keys.py:110`](../../../boltrig/identity/ai_keys.py)
`"if requested_modality == \"vision\":"`. `load_ai_key_material` accepts both the
self-service `secret` shape and the external-store `value` shape
[`boltrig/identity/ai_keys.py:156`](../../../boltrig/identity/ai_keys.py)
`"material = ref.get(\"value\")"`.

### 5.16 Per-user integration credentials

`pick_connection` prefers the caller's OWN connection over the org's, and reads
the policy flag ONLY once a personal connection actually exists, so a tenant that
does not use them pays exactly one query per dispatch
[`boltrig/kernel/integration_scope.py:39`](../../../boltrig/kernel/integration_scope.py)
`"org = await store.get_org(tenant_id)"`. Setup refuses BEFORE anything is
sealed when the org has not opted in, because an opted-out org would otherwise
hold a live credential nobody can use and nobody can find
[`boltrig/config/control_integrations.py:126`](../../../boltrig/config/control_integrations.py)
`"return \"own_integration_credentials_not_allowed\""`. A non-org level with no
personal scope (an agent or service token) is refused
`user_scope_requires_human_identity`
[`boltrig/config/control_integrations.py:119`](../../../boltrig/config/control_integrations.py)
`"return \"user_scope_requires_human_identity\""`. `acting_owner` reads
`on_behalf_of` else `actor`, and the module states that this MUST match what
dispatch passes as `owner` or the connection silently never resolves and the org
credential serves instead
[`boltrig/kernel/integration_scope.py:82`](../../../boltrig/kernel/integration_scope.py)
`"THIS MUST MATCH what dispatch hands to ``resolve_for_adapter`` as ``owner``"`.

### 5.17 Device enrollment and the device lease seat

1. `POST /v1/devices/enrollment/start` requires `actor_tier == "human"`, an
   available Ed25519 signer (else 503), and mints a scoped enrollment code whose
   sha256 alone is stored, expiring in 10 minutes
   [`boltrig/kernel/device_routes.py:71`](../../../boltrig/kernel/device_routes.py)
   `"if principal.actor_tier != \"human\":"` and
   [`boltrig/kernel/device_route_support.py:21`](../../../boltrig/kernel/device_route_support.py)
   `"ENROLLMENT_TTL = timedelta(minutes=10)"`.
2. `complete_enrollment` is UNAUTHENTICATED: the code IS the bearer. The store
   binds the device's `owner_id` and label from the consumed enrollment row, not
   from the request [`boltrig/store/device_memory.py:38`](../../../boltrig/store/device_memory.py)
   `"device, owner_id=enrollment.owner_id, label=enrollment.label"`.
3. A device session token is a base64url JSON envelope of
   `{version, kind, tenant_id, subject_id, secret}` with a >= 32-char secret,
   parsed strictly and matched against the path device id before the digest
   lookup [`boltrig/kernel/device_crypto.py:71`](../../../boltrig/kernel/device_crypto.py)
   `"or len(payload[\"secret\"]) < 32"`.
4. A device LEASE is the closest thing in this tree to a per-action capability
   seat: one signed Ed25519 grant, TTL 120 seconds, bound to an exact action
   digest, and issuable ONLY against a CONSUMED, INDEPENDENT approval
   [`boltrig/device_leases.py:126`](../../../boltrig/device_leases.py)
   `"or response.respondent in {"`. That independence check admits NO relief: it
   is a bare set-membership refusal with no sole-author and no development-posture
   arm. See RISK-07-01 for the contrast.

## 6. Data

Migrations owning this area, in order:

| revision | adds |
| --- | --- |
| `0002_round_four` | `personal_access_tokens`, `user_invitations`, `user_settings`, `user_sessions` |
| `0010_first_party_login` | `user_invitations.token_hash` (+ unique partial index), `user_credentials`, `user_sessions.token_hash/expires_at/csrf_token` (+ unique partial index) |
| `0011_org_workspace_tenancy` | `organisations`, `workspaces`, `org_members`, `workspace_members` |
| `0012_session_active_workspace` | `user_sessions.active_workspace_id` |
| `0013_ai_configs` | `ai_configs` |
| `0015_invitation_workspace_provision` | invitation workspace/provision columns |
| `0017_ai_config_base_url` | `ai_configs.base_url` |
| `0018_totp_two_factor` | `user_totp`, `user_recovery_codes`, `two_factor_challenges` + `tfa_challenges_user_idx` |
| `0019_cross_tenant_identity` | `user_sessions.active_org_id`, `identity_orgs` + `identity_orgs_email_idx` |
| `0038_workspace_members_tenant_key` | workspace-member tenant key |
| `0039_user_must_change_password` | `users.must_change_password` |
| `0042_desktop_devices` | device tables |
| `0045_password_reset` | `password_reset_tokens` with the sha256 CHECK, RLS enabled + forced, `tenant_isolation` policy |
| `0070_ai_config_modalities` | `ai_configs.modality` |
| `0078_scoped_integration_connections` | per-user integration connection scoping |

**Encryption and hashing.** Passwords are argon2id PHC strings with an embedded
per-user salt at argon2-cffi's OWASP-aligned defaults, kept as the library
default so an upgrade tracks upstream
[`boltrig/identity/passwords.py:23`](../../../boltrig/identity/passwords.py)
`"_PH = PasswordHasher()"`. Every OTHER bearer in this area is high-entropy and
stored as an UNSALTED sha256, which the code justifies explicitly: argon2 is
reserved for low-entropy passwords
[`boltrig/identity/totp.py:15`](../../../boltrig/identity/totp.py)
`"a high-entropy secret is fine to hash with sha256"`. Recovery codes were raised
to 26 base32 characters (130 bits) precisely because a 50-bit code was
GPU-crackable on a table leak
[`boltrig/identity/totp.py:51`](../../../boltrig/identity/totp.py)
`"(The old 10-char / 50-bit code was GPU-crackable on a"`.

**RLS.** Every identity table is fenced except three DOCUMENTED exclusions, all
resolved by an unguessable key BEFORE a tenant is bound:
`personal_access_tokens`, `identity_orgs`, `channels`
[`tests/security/test_rls_fence_coverage.py:52`](../../../tests/security/test_rls_fence_coverage.py)
`"DOCUMENTED_RLS_EXCLUSIONS = frozenset("`. `user_credentials`, `user_totp`,
`user_recovery_codes`, `two_factor_challenges`, `user_sessions`,
`user_invitations`, `password_reset_tokens`, `ai_configs`,
`ai_key_secret_proposals`, `org_members`, `workspace_members` are all in the
scoped array [`boltrig/store/rls.sql:100`](../../../boltrig/store/rls.sql)
`"'user_invitations','user_credentials','password_reset_tokens',"`.

**Retention.** No sweep deletes expired sessions, spent PATs, consumed reset
tokens, or expired two-factor challenges from this area. Bounded:
`rg -n "DELETE FROM (user_sessions|personal_access_tokens|password_reset_tokens)" boltrig/`
returns nothing; the only deletes are the CTE's
`DELETE FROM two_factor_challenges` on redemption
[`boltrig/store/password_resets.py:210`](../../../boltrig/store/password_resets.py)
`"DELETE FROM two_factor_challenges c"` and
`invalidate_password_reset_token`. Rows accumulate and are excluded by predicate
at read time. UNCERTAIN whether a janitor exists elsewhere; I did not read the
fleet janitors in full.

## 7. Configuration surface

| variable | default | effect | what breaks if wrong |
| --- | --- | --- | --- |
| `BOLTRIG_AUTH_MODE` | unset | `session` selects the first-party session resolver and wins over CF Access and OIDC | set by accident and OIDC is silently unused |
| `BOLTRIG_SESSION_TENANT` | `"default"` | the console's single identity realm; login, accept-invite, 2FA and recovery ALL operate in it | wrong value makes every credential land in a realm no session reads |
| `BOLTRIG_SESSION_COOKIE_SECURE` | `true` | drops `Secure` for a local http box | false in production leaks the cookie over http |
| `OIDC_ISSUER` / `OIDC_AUDIENCE` / `OIDC_JWKS_URI` | unset | the generic OIDC trio; all three or none | a partial manifest trio refuses boot; a partial env trio silently falls through to dev-auth or deny-all |
| `CF_ACCESS_TEAM_DOMAIN` / `CF_ACCESS_AUD` | unset | selects the Access resolver | both required; one alone is inert |
| `CF_ACCESS_ROLE_MAP` | unset | JSON `{email: role}` | invalid JSON logs an error and denies everyone by default |
| `CF_ACCESS_DEFAULT_ROLE` | `"none"` | role for an authenticated-but-unmapped email | anything outside `CF_ACCESS_TIERS` denies |
| `CF_ACCESS_TENANT` | unset | tenant Access users belong to | falls back to the process default tenant |
| `BOLTRIG_DEV_AUTH` | `0` | header-trusting resolver | FATAL under any production signal |
| `BOLTRIG_TRUST_CF_CONNECTING_IP` | unset | honours CF's client IP header for rate-limit keys | unset behind a tunnel collapses every per-IP bound into ONE global bucket |
| `BOLTRIG_TRUST_FORWARDED_PREFIX` | unset | honours `X-Forwarded-Prefix` to rescope session cookies to a mount | unset on a mounted console leaves `Path=/` and shares the cookie with everything on that host |
| `BOLTRIG_CORS_ORIGINS` | unset | an explicitly allowlisted Tauri origin gets `SameSite=None` cookies | a wrong entry weakens SameSite for a real browser origin |
| `BOLTRIG_INIT_PASSWORD` | unset | non-interactive password for `initiate` and `set-password` | lands in shell history, which is exactly why `must_change_password` exists |
| `BOLTRIG_PASSWORD_RESET_PROVIDER` | unset | `mailersend` or nothing | partial config raises at startup |
| `BOLTRIG_MAILERSEND_API_KEY`, `_FROM_EMAIL`, `_FROM_NAME`, `_PUBLIC_ORIGIN` | unset | MailerSend delivery | any missing REQUIRED one raises `password-reset delivery is missing required setting(s)` |
| `BOLTRIG_DEVICE_LEASE_SIGNING_KEY` | unset | base64url 32-byte Ed25519 seed | absent means every device route answers 503 `device_leases_unavailable` |
| `BOLTRIG_DEVICE_VERIFICATION_URI` | `/#/settings` | shown to the enrolling device | cosmetic |
| `BOLTRIG_MODEL_GATEWAY_URL` | unset | Bifrost admin base; must be http(s), an INTERNAL host, path exactly `/v1`, no credentials, no query | anything else raises `the model gateway configuration is invalid` |
| `BOLTRIG_BIFROST_MANAGEMENT_KEY` | unset | Bifrost admin bearer | absent means the admin calls go unauthenticated |
| `BOLTRIG_MODEL_GATEWAY_KEY` | unset | inference bearer; when absent the virtual key doubles as the OpenAI bearer | see [`boltrig/identity/bifrost_user_transport.py:106`](../../../boltrig/identity/bifrost_user_transport.py) `"ascii_secret(self._inference_key, \"gateway key\") if self._inference_key else virtual"` |

Manifest keys: `identity.provider` (`oidc` or `cf-access`; `saml` is REJECTED at
load), `identity.issuer`, `identity.audience`, `identity.jwks_uri`,
`identity.metadata_url` (parsed, unused), `identity.role_mappings[]`
(`idp_group`, `role`, `scope`)
[`boltrig/config/manifest.py:503`](../../../boltrig/config/manifest.py)
`"if provider == \"saml\":"`.

## 8. PROCESS

**Bring up a first-party console from nothing.**

1. Set `BOLTRIG_AUTH_MODE=session` and `BOLTRIG_SESSION_TENANT=<tenant>`.
2. `boltrig initiate --email E [--org-name N] [--workspace-name W]`. This seats
   ONE founding owner at `superadmin` with `{all: true}`, seeds the default org,
   a default workspace with a deterministic id `ws_<slug>`, and both memberships,
   and sets `must_change_password=True`
   [`boltrig/api/initiate.py:110`](../../../boltrig/api/initiate.py)
   `"must_change_password=True,"`. It REFUSES if any owner-tier user already
   exists (exit 3).
3. Log in. The response status is `password_change_required`; rotate through
   `POST /v1/auth/change-password`, which lifts the clamp and revokes every other
   session.
4. Create invitations from the console; the invite secret is shown once.

**Bridge an existing SSO identity to session login.**
`boltrig set-password --email E`. It refuses an unknown user (exit 3), rotates
idempotently, discharges `must_change_password`, and attributes the audit row to
`host-boundary` with `on_behalf_of` the target
[`boltrig/api/initiate.py:232`](../../../boltrig/api/initiate.py)
`"actor=HOST_BOUNDARY_ACTOR, actor_tier=\"host\","`.

**Mint a headless token.** `boltrig mint-token --email E --name N [--scope ...]
[--ttl-days N]`. The secret is printed alone on the last stdout line so it is
capturable with `| tail -1`
[`boltrig/api/mint_token.py:98`](../../../boltrig/api/mint_token.py)
`"trivially capturable (`... | tail -1`)"`. The identity command set is FIXED at
exactly `{initiate, set-password, mint-token}` and a static test pins the router's
literal [`tests/security/test_operator_seat_boundary.py:54`](../../../tests/security/test_operator_seat_boundary.py)
`"IDENTITY_COMMANDS = frozenset({\"initiate\", \"set-password\", \"mint-token\"})"`.

**Diagnose a user with no tools.** `DSN=... MANIFEST=... make user-authority`.
This exists because a live client's account read `role=admin` and held ZERO
authority, silently, because its invitation carried no scope
[`scripts/check_user_authority.py:8`](../../../scripts/check_user_authority.py)
`"its ``scope`` was ``{}``. Grants derive from SCOPE, not from role"`. It is NOT
a CI gate; it needs a tenant DSN
[`Makefile:161`](../../../Makefile)
`"user-authority: ## Does EVERY active user resolve to usable authority?"`.

**Recover a locked-out tenant.** The court refused a fourth host-boundary
command; the sanctioned path is `set-password` at the shell plus the existing
approval routes, because the respond route was open the whole time and had simply
never been used [`tests/security/test_operator_seat_boundary.py:9`](../../../tests/security/test_operator_seat_boundary.py)
`"The court walked the respond path and found no"`.

**Rotate a provider seat.** `POST /v1/ai-keys/activate` with the same level,
scope_id and modality re-provisions the Bifrost binding onto the STABLE
credential ref with no fresh secret and no fresh approval. To retire one, `DELETE
/v1/ai-keys/{level}/{scope_id}?modality=...`, which dispatches
`control.ai_key.delete` through the chokepoint.

**Change the approval regime deliberately.** Any control verb that would take a
tenant from two or more active authors down to exactly ONE is REFUSED before the
write, because at exactly one the sole-author exemption revives
[`boltrig/config/author_ratchet.py:43`](../../../boltrig/config/author_ratchet.py)
`"Refuse a crossing DOWN to exactly one active author."`. Crossings of the 1<->2
boundary are announced from the dispatch chokepoint
[`boltrig/kernel/dispatch.py:632`](../../../boltrig/kernel/dispatch.py)
`"Announce a crossing of the 1<->2 author boundary"`.

**Gates that bind this area.** `make invariants` cross-checks
`tests/invariants.yaml` against the `@pytest.mark.invariant` markers; `make
python-quality` is what the pre-push hook runs
[`Makefile:228`](../../../Makefile)
`"python-quality: invariants lint architecture structure"`.

## 9. Failure modes and fail-open/fail-closed posture

| guard | direction | proof |
| --- | --- | --- |
| No auth configured | CLOSED (401 every request) | [`boltrig/api/bootstrap.py:496`](../../../boltrig/api/bootstrap.py) `"detail=\"authentication is not configured\""` |
| Dev auth under production signal | CLOSED (FATAL at boot) | [`boltrig/api/boot_guards.py:33`](../../../boltrig/api/boot_guards.py) `"FATAL: BOLTRIG_DEV_AUTH is set with a production signal"` |
| Partial manifest OIDC trio | CLOSED (RuntimeError) | [`boltrig/api/auth_selection.py:71`](../../../boltrig/api/auth_selection.py) `"manifest identity OIDC trust is partial"` |
| Manifest `identity.provider: saml` | CLOSED (ValueError at load) | [`boltrig/config/manifest.py:505`](../../../boltrig/config/manifest.py) `"identity.provider 'saml' is not implemented"` |
| `SamlVerifier.verify` without a validator | CLOSED (NotImplementedError) | [`boltrig/identity/auth.py:201`](../../../boltrig/identity/auth.py) `"SAML verification is a seam"` |
| Malformed `CF_ACCESS_ROLE_MAP` | CLOSED (empty map, deny by default) | [`boltrig/api/auth_selection.py:35`](../../../boltrig/api/auth_selection.py) `"treating as empty (deny-by-default)"` |
| Unmapped IdP groups | CLOSED (`EMPTY_GRANTS`) | [`boltrig/identity/rbac.py:107`](../../../boltrig/identity/rbac.py) `"return EMPTY_GRANTS"` |
| Unknown workspace role | CLOSED (`EMPTY_GRANTS`) | [`boltrig/identity/rbac.py:259`](../../../boltrig/identity/rbac.py) `"unknown workspace role -> no authority"` |
| Caller NOT a member of the active workspace | OPEN-ish: no narrowing applied, falls back to the ORG ceiling | [`boltrig/identity/provisioning.py:61`](../../../boltrig/identity/provisioning.py) `"return base  # not a member -> no workspace narrowing"` |
| PAT names an out-of-reach workspace | CLOSED (403, never a silent fallback) | [`boltrig/identity/tokens.py:121`](../../../boltrig/identity/tokens.py) `"raise WorkspaceNotPermitted(requested_workspace_id)"` |
| Deactivated owner of a PAT | CLOSED (`None` -> 401) | [`boltrig/identity/tokens.py:165`](../../../boltrig/identity/tokens.py) `"de-provisioned / deactivated -> token stops working"` |
| Corrupt or foreign argon2 hash | CLOSED (treated as non-match, never distinguishable) | [`boltrig/identity/passwords.py:79`](../../../boltrig/identity/passwords.py) `"except Argon2Error:"` |
| Corrupt or foreign TOTP secret | CLOSED (non-match) | [`boltrig/identity/totp.py:96`](../../../boltrig/identity/totp.py) `"except Exception:"` |
| Every membership revoked mid-session | CLOSED (401 on the next request) | [`boltrig/identity/sessions.py:199`](../../../boltrig/identity/sessions.py) `"return realm_tenant_id if session.active_org_id is None else None"` |
| Session past the 7-day absolute cap on refresh | CLOSED (revoked, cookies deleted, 401) | [`boltrig/api/auth_routes.py:565`](../../../boltrig/api/auth_routes.py) `"session.revoked = True"` |
| No password-reset notifier | CLOSED (no bearer minted at all) | [`boltrig/api/auth_recovery_routes.py:157`](../../../boltrig/api/auth_recovery_routes.py) `"absent explicit delivery means no minted bearer"` |
| Password-reset notifier raises | CLOSED (digest invalidated, nothing logged) | [`boltrig/api/auth_recovery_routes.py:100`](../../../boltrig/api/auth_recovery_routes.py) `"await k.store.invalidate_password_reset_token(tenant, token_hash)"` |
| Device lease signer absent | CLOSED (503 on every device route) | [`boltrig/kernel/device_routes.py:75`](../../../boltrig/kernel/device_routes.py) `"return _error(\"device_leases_unavailable\", 503)"` |
| Bifrost gateway probe throws while listing AI keys | OPEN as `gateway_ready: False` (a bare `except Exception: pass` builds no gateway) | [`boltrig/kernel/ai_key_routes.py:253`](../../../boltrig/kernel/ai_key_routes.py) `"except Exception:"` |
| Host-boundary security-event write fails | OPEN by design (best-effort; the audit row is the business record) | [`boltrig/api/host_boundary.py:74`](../../../boltrig/api/host_boundary.py) `"except Exception:  # noqa: BLE001 - see the best-effort note above"` |
| Onboarding marker write fails | OPEN in this module, closed downstream (Worker refuses chat without the marker) | [`boltrig/identity/onboarding.py:34`](../../../boltrig/identity/onboarding.py) `"except Exception:"` |
| Approval independence, generic HITL path | RELIEVABLE (sole-author, development posture) | [`boltrig/kernel/hitl_response_auth.py:206`](../../../boltrig/kernel/hitl_response_auth.py) `"if await _sole_active_author(store, tenant_id, subject):"` |
| Approval independence, DEVICE LEASE path | CLOSED, no relief admitted | [`boltrig/device_leases.py:126`](../../../boltrig/device_leases.py) `"or response.respondent in {"` |

**Non-enumeration.** Login, invite acceptance, second-factor challenge and
password reset each collapse every distinguishable failure into ONE generic
response, and each spends the corresponding crypto work on the negative path so
timing carries no oracle
[`boltrig/api/auth_routes.py:88`](../../../boltrig/api/auth_routes.py)
`"_GENERIC_2FA_FAILURE = {\"status\": \"error\", \"reason\": \"invalid or expired code\"}"`.

**Rate-limit inventory for this area.**

| surface | per identity | per IP | other |
| --- | --- | --- | --- |
| login | 5/min | 30/min | - |
| accept-invite | none | 10/min | - |
| 2FA enroll-begin | 5/min | 30/min | - |
| 2FA verify-enroll | 5/min | 30/min | - |
| 2FA challenge | 5/min | 30/min | - |
| 2FA disable | 5/min | 30/min | - |
| change-password | 5/min | none | - |
| reset request | 3/hour | 10/hour | - |
| reset confirm | none | 30/min | 5/min per token hash |
| `POST /v1/me/tokens` (PAT mint) | NONE | NONE | NONE |

The PAT-mint row is bounded: `rg -n "rate_limiter|RateLimit"
boltrig/kernel/access_routes.py boltrig/identity/tokens.py
boltrig/api/mint_token.py` returns nothing, 2026-08-24, pinned tree.

## 10. What is proven

| invariant | what it binds | a test node |
| --- | --- | --- |
| SEC-01 | invalid or missing bearer 401, valid bearer scoped, CF Access tiers | `tests/security/test_auth.py::test_missing_bearer_rejected`, `tests/security/test_cf_access_auth.py::test_authenticated_but_unmapped_email_is_denied` |
| SEC-68 | a manifest advertising `saml` refuses to boot | `tests/security/test_auth.py::test_saml_provider_config_refuses_to_boot` |
| K-13 | empty grants deny everything | `tests/unit/test_grants_model.py::test_empty_grants_deny_everything` |
| SEC-34 | a PAT never escalates and dies with its user | `tests/security/test_round_four.py::test_pat_never_escalates_and_dies_with_user` |
| SEC-35 | invitations pre-stage only, consumed once | `tests/security/test_round_four.py::test_invitations_do_not_bypass_idp` |
| SEC-37 | headless REST/MCP runs the same chokepoint | `tests/security/test_round_four.py::test_headless_parity_no_weak_path` |
| SEC-38 | no unauthenticated access to tokens | `tests/security/test_round_four.py::test_no_unauthenticated_access_to_tokens` |
| SEC-65 | PAT resolution binds the tenant before the owner read; provisioning binds before the first read | `tests/security/test_rls_auth_binding.py::test_pat_resolution_binds_tenant_before_the_owner_read` |
| SEC-97 | invite-only, no self-signup, single-use, concurrent-safe | `tests/security/test_first_party_login.py::test_invite_only_no_self_signup_and_single_use` |
| SEC-98 | argon2id, non-reversible, never logged | `tests/security/test_first_party_login.py::test_password_is_hashed_non_reversible_and_never_logged` |
| SEC-99 | login rate-limited and non-enumerating | `tests/security/test_first_party_login.py::test_login_is_rate_limited_and_non_enumerating` |
| SEC-100 | cookie httpOnly + Secure + SameSite, bounded, revocable; accept-invite throttled before argon2 | `tests/security/test_first_party_login.py::test_session_cookie_is_httponly_secure_bounded_and_revocable` |
| SEC-101 | resolver fail-closed and CSRF-protected | `tests/security/test_first_party_login.py::test_resolver_fail_closed_and_csrf_protected` |
| SEC-102 | privilege ceiling on the roster routes | `tests/security/test_privilege_ceiling.py::test_admin_cannot_grant_a_role_above_its_own` |
| SEC-106 / SEC-107 / FR-ORG-03 | workspace switch re-authorised; revoked membership drops; deterministic default | `tests/security/test_active_context.py::test_switch_is_membership_reauthorized_and_fail_closed` |
| SEC-108 / SEC-109 / SEC-110 | workspace ceiling intersects down; a viewer's PAT cannot exceed their session; no active workspace keeps org grants | `tests/security/test_workspace_grants.py::test_a_viewers_pat_cannot_do_what_their_session_is_refused` |
| SEC-112 / SEC-113 / SEC-114 / SEC-115 | `allow_own_ai_keys` gate; the key is sealed, never returned or audited; tenant-scoped reads; role-scoped set route | `tests/security/test_ai_keys.py::test_ai_key_is_sealed_never_returned_or_audited` |
| SEC-118 | org/workspace-scoped invites seat within the SEC-102 ceiling | `tests/invariants.yaml` entry SEC-118 |
| SEC-126..SEC-130 | TOTP sealed; recovery codes hashed and single-use; challenge fail-closed between password and session; org-required enrollment clamp; fixed window | `tests/security/test_two_factor.py::test_challenge_is_fail_closed_between_password_and_session` |
| SEC-131..SEC-134 | one active org per request; org switch re-authorised; provisioned-org invitee has a usable login; shared credential and 2FA travel with the identity | `tests/security/test_cross_tenant_identity.py::test_resolver_binds_the_request_to_the_session_active_org` |
| SEC-182 | the sole-author bootstrap exemption and its audit flag | `tests/security/test_sole_author_exemption.py::test_sole_author_may_self_approve_with_an_audit_flag` |
| SEC-185 | the trusted-Codex wall's two postures | `tests/unit/test_codex_trusted_wall.py::test_per_cell_posture_admits_session_auth_without_dev_auth` |
| SEC-188 | every tenant table is fenced or documentedly excluded | `tests/security/test_rls_fence_coverage.py::test_every_tenant_table_is_rls_fenced_or_documented_excluded` |
| SEC-191 | login/2FA audit rows are keys-only, POSITIONALLY | `tests/security/test_auth_audit_is_keys_only.py::test_the_guarantee_is_positional_and_not_the_write_time_scrubber` |
| SEC-192 | every access-surface list view publishes exactly its declared keys | `tests/security/test_access_views_carry_no_secret.py::test_each_view_publishes_exactly_these_keys_and_no_others` |
| SEC-AIKEY-01 | the provider seat rotates in place on a stable scope and revoke cleans it | `tests/security/test_bifrost_user_binding.py::test_replacement_rotates_the_stable_scope_in_place_and_revoke_cleans_it` |
| SEC-AUTH-RECOVERY-01 | recovery is public, non-enumerating, one-use, revokes sessions, audits no secret | `tests/security/test_password_recovery.py::test_reset_is_one_use_revokes_sessions_and_never_audits_secrets` |
| SEC-WRK-07 | device enrollment/session single-use and digest-only; a lease needs a consumed exact-action approval | `tests/security/test_device_leases.py::test_signed_lease_requires_consumed_exact_action_and_is_single_use` |
| SEC-WRK-33 | AI-key secret sealed before approval and consumed exactly once | `tests/security/test_ai_key_secret_proposals.py::test_secret_is_sealed_before_approval_and_exactly_once_consumed` |
| FR-AIKEY-02/03/04 | precedence, one-press onboarding, keyless self-hosted providers | `tests/security/test_ai_keys.py::test_resolve_precedence_user_workspace_org_default` |

**Reachable but UNBOUND to any declared invariant** (each is a finding in its own
right, recorded in RISKS): the forced-rotation clamp
(`tests/security/test_forced_password_rotation.py`, 9 tests, zero
`@pytest.mark.invariant` markers, bounded: `grep -c "pytest.mark.invariant"` on
that file returns 0); PAT workspace selection
(`tests/security/test_pat_workspace_selection.py`, 7 tests, zero markers);
`boltrig set-password` (`tests/security/test_set_password.py`, 3 tests, zero
markers).

## 11. RISKS

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

RISK-07-02 (HIGH): **The device-lease path proves the stricter rule is
expressible, and the generic path does not use it.** `DeviceLeaseIssuer.materialize`
refuses outright when `response.respondent` is in the requester set, with no
relief arm at all [`boltrig/device_leases.py:126`](../../../boltrig/device_leases.py)
`"or response.respondent in {"`. Two independence rules now exist for the same
concept, and only one of them is reachable from `respond_to_hitl`.

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

RISK-07-05 (MEDIUM): **No credential rotation revokes the user's PATs.** Neither
`change-password`, nor the reset CTE, nor `set-password` touches
`personal_access_tokens`. A password rotation is normally performed BECAUSE the
credential is believed compromised, and a PAT minted before that moment keeps
working until its own expiry (up to 365 days). Cited:
[`boltrig/store/password_resets.py:171`](../../../boltrig/store/password_resets.py)
`"WITH claimed AS ("` (five CTE arms, none touching PATs). Bounded: `rg -n "pat"
boltrig/store/password_resets.py boltrig/api/auth_password_routes.py` returns
nothing.

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

RISK-07-07 (MEDIUM): **A non-member active workspace applies NO narrowing rather
than failing closed.** `effective_grants_for_request` returns the ORG grants when
the membership row is missing. The comment argues this "never widens", and
relative to the org ceiling that is true; but the SESSION resolver has already
dropped a non-member workspace to `None` before this is called, so the surviving
reachable caller is the PAT path, where a race between the membership check and
this read yields org authority under a workspace the caller is not in. Cited:
[`boltrig/identity/provisioning.py:61`](../../../boltrig/identity/provisioning.py)
`"return base  # not a member -> no workspace narrowing (never widen)"`.

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

RISK-07-09 (LOW, revised 2026-08-24): **The SEC-102 privilege ceiling is
implemented TWICE, and only the kernel copy is bound by a test.** The earlier
form of this risk, that the control verb is unguarded, is WITHDRAWN: the
control-plane handlers do re-check, through a second `_reject_escalation` that
lives in the config layer and carries the same two rules with a different
signature and a different exception
[`boltrig/config/control_operations.py:271`](../../../boltrig/config/control_operations.py)
`"def _reject_escalation(role: str, target_role: Any, scope: Any) -> None:"`,
raising `PermissionError` where the kernel copy raises `GrantMissing`
[`boltrig/kernel/access_routes.py:52`](../../../boltrig/kernel/access_routes.py)
`"def _reject_escalation(p, role, scope) -> None:"`. The SEC-102 test imports
only the kernel copy
[`tests/security/test_privilege_ceiling.py:13`](../../../tests/security/test_privilege_ceiling.py)
`"from boltrig.kernel.access_routes import _reject_escalation"`, so the config
copy can drift from the tested one unobserved. No test exercises the config copy
(bounded: `rg -n "control_operations" tests/`, 2026-08-24, pinned tree, returns a
single import, in `test_operator_seat_ratchet.py`, which exercises the author
ratchet and not the ceiling).

RISK-07-10 (MEDIUM): **Behind a Cloudflare tunnel without
`BOLTRIG_TRUST_CF_CONNECTING_IP`, every per-IP bound collapses to one global
bucket.** The code names this as a login-DoS lever and a useless anti-spray, and
the opt-in is unset by default. Cited:
[`boltrig/api/auth_routes.py:438`](../../../boltrig/api/auth_routes.py)
`"per-IP bound keyed on it collapses to ONE global bucket (a login-DoS"`.

RISK-07-11 (MEDIUM): **A session cookie is `Path=/` unless
`BOLTRIG_TRUST_FORWARDED_PREFIX` is set.** On a tenant box the console shares an
origin with the Opbox app, so an unset opt-in hands the console's session secret
to an application that took no part in issuing it. The refusal is correct (the
header is client-settable) but the safe posture requires an explicit opt-in.
Cited: [`boltrig/kernel/web_security.py:116`](../../../boltrig/kernel/web_security.py)
`"if not is_truthy(e.get(\"BOLTRIG_TRUST_FORWARDED_PREFIX\")):"`.

RISK-07-12 (LOW): **Three reachable security behaviours are bound to no declared
invariant.** The forced-rotation clamp, PAT workspace selection, and
`set-password` all have test files with zero `@pytest.mark.invariant` markers, so
`scripts/check_invariants.py` cannot notice if they regress out of the catalogue.
Bounded: `grep -c "pytest.mark.invariant"` on
`tests/security/test_forced_password_rotation.py`,
`tests/security/test_pat_workspace_selection.py` and
`tests/security/test_set_password.py` returns 0 for each.

RISK-07-13 (LOW): **`boltrig initiate`'s run-once guard is a read-then-write with
no transaction and no uniqueness constraint.** Two concurrent runs with DIFFERENT
emails both read an empty list and both seat a superadmin. The module records this
as accepted rather than closed. Cited:
[`boltrig/api/initiate.py:13`](../../../boltrig/api/initiate.py)
`"KNOWN LIMIT - the \"refusing to run twice\" guard is a read-then-write."`.

RISK-07-14 (LOW): **The keyless-provider placeholder is a public constant.** A
provider in `_KEYLESS_PROVIDERS` gets the literal string `"keyless"` sealed as its
credential and digested, so `secret_digest` for every ollama seat is a known
value. Harmless while the server ignores authorization, but the digest is no
longer a secret-bearing discriminator. Cited:
[`boltrig/kernel/ai_key_routes.py:65`](../../../boltrig/kernel/ai_key_routes.py)
`"_KEYLESS_PLACEHOLDER = \"keyless\""`.

RISK-07-15 (LOW): **No retention sweep for expired identity rows.** Sessions,
PATs, invitations, consumed reset tokens and expired two-factor challenges are
excluded by predicate at read time and never deleted (except challenges, deleted
inside the reset CTE). Bounded: `rg -n "DELETE FROM (user_sessions|personal_access_tokens|user_invitations)" boltrig/`
returns nothing, 2026-08-24, pinned tree.

RISK-07-16 (LOW): **The README's OIDC claim is true only in third place.** It says
bootstrap selects real OIDC verification "when `OIDC_*` is set", but
`select_auth_resolver` checks session mode and Cloudflare Access FIRST, so a box
with both `BOLTRIG_AUTH_MODE=session` and a full OIDC trio runs session auth and
never touches the trio. Cited:
[`README.md:222`](../../../README.md) `"Real OIDC token verification"`;
[`boltrig/api/auth_selection.py:104`](../../../boltrig/api/auth_selection.py)
`"if settings.session_auth_configured:"`.

## 12. OPEN QUESTIONS

OQ-07-01. SETTLED 2026-08-24, and the answer is yes: the control-plane handlers
re-apply the SEC-102 privilege ceiling themselves. `control.user.update`
dispatches into `update_user_record`
[`boltrig/config/control_plane.py:277`](../../../boltrig/config/control_plane.py)
`"user = await update_user_record(self._store, tenant, params, context=context)"`,
which rejects escalation before it reads or writes the user row
[`boltrig/config/control_operations.py:284`](../../../boltrig/config/control_operations.py)
`"_reject_escalation(role, params.get(\"role\"), params.get(\"scope\"))"`, and
`control.invitation.create` applies the same guard on entry
[`boltrig/config/control_operations.py:324`](../../../boltrig/config/control_operations.py)
`"_reject_escalation(role, params.get(\"role\"), params.get(\"scope\"))"`. The
author-ratchet call I had cited as a bare filename sits in the same handler
[`boltrig/config/control_operations.py:298`](../../../boltrig/config/control_operations.py)
`"store, tenant_id, user_id=updated.id, stays_author=is_active_author(updated)"`.
What remains is not an open question but a drift risk, recorded as RISK-07-09. I
still did not read `boltrig/config/control_compat.py`.

OQ-07-02. Is there a janitor that expires or deletes stale `user_sessions`,
`personal_access_tokens` or `two_factor_challenges` rows? Settled by reading
`boltrig/fleet/` janitors and `boltrig/kernel/hitl_expiry.py` for a sweep over
those tables. My bounded `rg` for `DELETE FROM` found none, but a sweep could be
expressed as an `UPDATE ... SET revoked`.

OQ-07-03. Does the channel principal path (`channel_principal`, `credential_kind`
unset and therefore `"machine"`) reach `respond_to_hitl`? If it does, the
sole-author relief admits it exactly as it admits a PAT, since only `actor_tier`
is checked there. Settled by tracing the channel intake reply path in
`boltrig/kernel/channel_*` (area 09).

OQ-07-04. Is `SamlVerifier` used by any deployment overlay or manifest outside the
pinned tree? Inside the tree it is exported and referenced only by the manifest
rejection and one test (bounded: `rg -n "SamlVerifier" boltrig/ tests/`, five
hits, none constructing it with a validator). Settled by a deployment inventory.

OQ-07-05. What enforces the invitation `expires_at` at CREATION time? `provision_user`
and accept-invite both refuse an expired invitation, but I did not read the
control-plane handler that sets `expires_at`, so whether an invitation can be
created with no expiry at all is unsettled. Settled by reading
`control.invitation.create` in `boltrig/config/`.

OQ-07-06. Does the Bifrost virtual key carry a TTL or rotation schedule of its
own, or does it live until the seat is re-minted or revoked? `ensure` and
`revoke` are the only lifecycle entry points I read; the Bifrost-side object
semantics live in `bifrost_user_admin.ensure_virtual_key`, whose HTTP bodies I
sampled but did not read line by line.

OQ-07-07. The capability MAPPING PACK layer (`boltrig/capabilities/`) lands every
pack binding as `proposed` and requires a human approval before any route uses it
[`boltrig/capabilities/mapping_packs.py:11`](../../../boltrig/capabilities/mapping_packs.py)
`"a pack binding always lands ``proposed``"`. WHERE that `proposed` state is set
and which route approves it is outside the files I read; `load_packs` itself only
parses and validates. Settled by finding the caller of `load_packs` (bounded:
not searched, so this is a stated gap rather than an absence claim).

## 13. Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-0700 | The system recognises exactly six Principal-producing resolvers: federated OIDC, Cloudflare Access, first-party session, personal access token, dev header, and the two internal builders (channel-bound sender, workflow webhook owner). | IMPLEMENTED | `boltrig/kernel/app.py:40` `"class Principal:"` and the eight construction sites listed in section 4.2 | SEC-01 |
| BT-REQ-0701 | A Principal carries `credential_kind` as a separate axis from `actor_tier`, defaulting to `machine` so an unlabelled resolver is refused rather than admitted. | IMPLEMENTED | `boltrig/kernel/app.py:66` `"credential_kind: str = \"machine\""` | SEC-185 |
| BT-REQ-0702 | Exactly one authentication posture is selected at boot, in the order session, Cloudflare Access, generic OIDC, dev auth, deny-all. | IMPLEMENTED | `boltrig/api/auth_selection.py:104` `"if settings.session_auth_configured:"` | SEC-01 |
| BT-REQ-0703 | With no authentication configured every request is refused 401. | IMPLEMENTED | `boltrig/api/bootstrap.py:496` `"detail=\"authentication is not configured\""` | SEC-01 |
| BT-REQ-0704 | `BOLTRIG_DEV_AUTH=1` under any production signal aborts boot with a FATAL RuntimeError. | IMPLEMENTED | `boltrig/api/boot_guards.py:33` `"FATAL: BOLTRIG_DEV_AUTH is set with a production signal"` | SEC-01 |
| BT-REQ-0705 | `create_app` called with no principal resolver under a production signal raises rather than defaulting to the header resolver. | IMPLEMENTED-UNTESTED | `boltrig/kernel/app.py:257` `"FATAL: create_app() received no principal_resolver"` (no test found; searched `tests/security/test_auth.py`, `tests/unit/`) | - |
| BT-REQ-0706 | A partial manifest OIDC trio refuses boot and a manifest trio differing from the process trio refuses boot. | IMPLEMENTED-UNTESTED | `boltrig/api/auth_selection.py:75` `"manifest identity OIDC trust differs from process OIDC trust"` (no test found in `tests/security/test_auth.py`) | - |
| BT-REQ-0707 | OIDC verification pins an asymmetric algorithm allowlist so `alg=none` and HS* confusion are rejected by construction. | IMPLEMENTED | `boltrig/identity/auth.py:74` `"_ALLOWED_ALGS = (\"RS256\", \"RS384\", \"RS512\""` | SEC-01 |
| BT-REQ-0708 | A verified token must carry `iss`, `aud` and `exp`, and clock leeway is clamped to at most 120 seconds. | IMPLEMENTED | `boltrig/identity/auth.py:98` `"self._leeway = max(0, min(int(leeway), 120))"` | SEC-01 |
| BT-REQ-0709 | A token's absolute lifetime is capped at 24 hours by two independent checks, so a missing `iat` cannot let a far-future `exp` through. | IMPLEMENTED | `boltrig/identity/auth.py:171` `"exp - time.time() > self._MAX_LIFETIME"` | SEC-01 |
| BT-REQ-0710 | A kid miss forces at most one JWKS refetch per 30 seconds, then fails closed with 401. | IMPLEMENTED | `boltrig/identity/auth.py:142` `"if time.monotonic() - self._jwks_at >= self._FORCE_REFETCH_MIN_INTERVAL:"` | SEC-01 |
| BT-REQ-0711 | An ID token presented as an access token is rejected 401 when the token says so via `token_use` or `typ`. | IMPLEMENTED-UNTESTED | `boltrig/identity/auth.py:163` `"detail=\"id token is not an access token\""` (no test found in `tests/security/test_auth.py`) | - |
| BT-REQ-0712 | SAML verification is a seam: `verify` raises without an injected validator, and a manifest declaring `identity.provider: saml` is rejected at load. | SEAM | `boltrig/identity/auth.py:201` `"SAML verification is a seam"`; `boltrig/config/manifest.py:505` `"identity.provider 'saml' is not implemented"` | SEC-68 |
| BT-REQ-0713 | OIDC and Cloudflare Access are SEAMS whose live legs are an external IdP: the verifier is real, the issuer is not in this tree. | SEAM | `boltrig/api/auth_selection.py:41` `"jwks_uri=f\"{team}/cdn-cgi/access/certs\","` | SEC-01 |
| BT-REQ-0714 | Identity comes only from the verified assertion: tenant and subject are never read from the request body or an untrusted header on any production resolver. | IMPLEMENTED | `boltrig/identity/auth.py:266` `"subject = claims.get(\"sub\") or claims.get(\"subject\")"` | SEC-01 |
| BT-REQ-0715 | Cloudflare Access admits only the tiers superadmin, admin and member; any other mapped role is denied 403 fail-closed. | IMPLEMENTED | `boltrig/identity/auth.py:370` `"detail=f\"{email} is not authorized\""` | SEC-01 |
| BT-REQ-0716 | Every admitted Cloudflare Access tier receives tenant-wide `{all: true}` scope and is differentiated only by authoring rights and the HITL gate. | IMPLEMENTED | `boltrig/identity/auth.py:372` `"scope = {\"all\": True}"` | SEC-01 |
| BT-REQ-0717 | An email is normalised to lower case on both sides of the Cloudflare Access role map. | IMPLEMENTED | `boltrig/identity/auth.py:350` `"role_map = {k.strip().lower(): v"` | SEC-01 |
| BT-REQ-0718 | The dev header resolver is reachable only in local development and stamps `credential_kind="dev-header"`. | IMPLEMENTED | `boltrig/identity/auth.py:404` `"credential_kind=\"dev-header\","` | SEC-01 |
| BT-REQ-0719 | A caller in several mapped IdP groups receives the highest-privilege matched role and the union of matched scopes. | IMPLEMENTED-UNTESTED | `boltrig/identity/rbac.py:65` `"role = min((m.role for m in matched), key=_role_rank)"` (searched `tests/security/test_auth.py`; only the single-mapping case is exercised) | - |
| BT-REQ-0720 | A caller matching no mapping receives role `none` and an empty scope. | IMPLEMENTED | `boltrig/identity/rbac.py:63` `"return (DEFAULT_ROLE, {})"` | K-13 |
| BT-REQ-0721 | An empty or missing scope yields `EMPTY_GRANTS`, so authority derives from scope and never from role. | IMPLEMENTED | `boltrig/identity/rbac.py:107` `"return EMPTY_GRANTS"` | K-13 |
| BT-REQ-0722 | Departments are visibility metadata and never widen the verb GrantSet. | IMPLEMENTED | `boltrig/identity/rbac.py:103` `"Departments are visibility metadata, not verb authority"` | SEC-07 |
| BT-REQ-0723 | A GrantSet is deny-dominant, fail-closed, and matches only terminal wildcards. | IMPLEMENTED | `boltrig/models/grants.py:87` `"return verb_id == prefix or verb_id.startswith(prefix + \".\")"` | K-13 |
| BT-REQ-0724 | A verb id that is not a safe identifier after NFKC never matches any grant pattern. | IMPLEMENTED-UNTESTED | `boltrig/models/grants.py:76` `"if not is_safe_identifier(verb_id):"` (searched `tests/unit/test_grants_model.py` by name only) | - |
| BT-REQ-0725 | A role stated with no scope at all is filled from `ORG_ROLE_DEFAULT_SCOPE` for superadmin, admin and org-admin only, and a stated-but-narrow scope is never widened. | IMPLEMENTED | `boltrig/identity/provisioning.py:130` `"if scope or not role:"` | - |
| BT-REQ-0726 | Provisioning a role with no scope and no canonical default logs a warning naming the consequence rather than failing silently. | IMPLEMENTED | `boltrig/identity/provisioning.py:134` `"logger.warning("` | - |
| BT-REQ-0727 | A workspace membership can only intersect authority DOWN; the result is always a subset of the org grants. | IMPLEMENTED | `boltrig/identity/rbac.py:241` `"def narrow_grants_to_workspace(base: GrantSet, workspace_role: str)"` | SEC-108 |
| BT-REQ-0728 | A workspace viewer keeps only concrete read-action grants; every wildcard collapses. | IMPLEMENTED | `boltrig/identity/rbac.py:255` `"allow = tuple(p for p in base.allow if _is_read_only_pattern(p))"` | SEC-109 |
| BT-REQ-0729 | An unknown workspace role yields `EMPTY_GRANTS`. | IMPLEMENTED | `boltrig/identity/rbac.py:259` `"return EMPTY_GRANTS  # unknown workspace role"` | SEC-109 |
| BT-REQ-0730 | A caller with no active workspace keeps their full org grants unchanged. | IMPLEMENTED | `boltrig/identity/provisioning.py:56` `"return base  # no active workspace -> today's grants"` | SEC-110 |
| BT-REQ-0731 | A deactivated user's current grants are `EMPTY_GRANTS`. | IMPLEMENTED | `boltrig/identity/provisioning.py:31` `"if user.status != \"active\":"` | SEC-34 |
| BT-REQ-0732 | A previously provisioned user's stored role, scope and status are authoritative on every later login, so re-login cannot self-revive a deactivated account. | IMPLEMENTED | `boltrig/identity/provisioning.py:182` `"existing = await store.get_user(tenant_id, subject)"` | SEC-34 |
| BT-REQ-0733 | An unmapped, un-invited federated identity is denied 403. | IMPLEMENTED | `boltrig/identity/auth.py:284` `"detail=\"no access for this identity\""` | SEC-35 |
| BT-REQ-0734 | An expired invitation confers nothing and a lost consume race confers nothing. | IMPLEMENTED | `boltrig/identity/provisioning.py:203` `"if not await store.consume_invitation(tenant_id, inv.id):"` | SEC-97 |
| BT-REQ-0735 | The session cookie is httpOnly, Secure and SameSite=strict, with a 12-hour bounded lifetime and a JS-readable CSRF mirror. | IMPLEMENTED | `boltrig/api/desktop_session_auth.py:44` `"response.set_cookie("` | SEC-100 |
| BT-REQ-0736 | An explicitly CORS-allowlisted packaged Tauri origin receives `SameSite=None` cookies; CSRF stays mandatory. | IMPLEMENTED-UNTESTED | `boltrig/api/desktop_session_auth.py:42` `"same_site = \"none\" if secure and _desktop_session_request(request) else \"strict\""` (searched `tests/security/test_first_party_login.py` and `test_mount_path_cookie_scope.py`) | - |
| BT-REQ-0737 | Only the sha256 of a session secret is persisted; the secret leaves in the Set-Cookie header and is never stored or logged. | IMPLEMENTED | `boltrig/identity/sessions.py:77` `"The at-rest representation of a session: its sha256"` | SEC-100 |
| BT-REQ-0738 | A session refresh rotates the secret and CSRF token in place and refuses past a 7-day creation-anchored absolute cap. | IMPLEMENTED | `boltrig/identity/sessions.py:125` `"raise ValueError(\"session past absolute lifetime cap\")"` | SEC-100 |
| BT-REQ-0739 | Every mutating cookie request must echo the session-bound CSRF token in `x-boltrig-csrf`, compared in constant time; bearer callers are exempt because they never reach this code. | IMPLEMENTED | `boltrig/identity/sessions.py:309` `"if not session.csrf_token or not hmac.compare_digest("` | SEC-101 |
| BT-REQ-0740 | Each request is bound to exactly ONE active org, re-authorised against `org_members` after binding that tenant, never trusting the client hint. | IMPLEMENTED | `boltrig/identity/sessions.py:204` `"set_current_tenant(tid)"` | SEC-131 |
| BT-REQ-0741 | A membership-model session whose every org membership was revoked fails closed rather than inheriting realm access. | IMPLEMENTED | `boltrig/identity/sessions.py:199` `"return realm_tenant_id if session.active_org_id is None else None"` | SEC-131 |
| BT-REQ-0742 | An org switch is the only place the active org changes and is membership-re-authorised with no write on refusal. | IMPLEMENTED | `boltrig/kernel/access_routes.py:483` `"member = await k.store.get_org_member(org_id, p.subject)"` | SEC-132 |
| BT-REQ-0743 | A workspace switch refuses an unknown workspace 404 and a non-member workspace 403, both with no write and no audit. | IMPLEMENTED | `boltrig/kernel/access_routes.py:432` `"{\"status\": \"denied\", \"reason\": \"not a member of that workspace\"}"` | SEC-106 |
| BT-REQ-0744 | An account still holding its provisioning credential reaches only the CSRF, change-password and logout routes, checked on every request rather than only at login. | IMPLEMENTED-UNTESTED | `boltrig/identity/sessions.py:322` `"detail=\"password_change_required\""` (nine tests in `tests/security/test_forced_password_rotation.py`, none carrying an invariant marker) | - |
| BT-REQ-0745 | When the active org requires two-factor and the caller has no activated factor, only the enrollment surface and logout are reachable. | IMPLEMENTED | `boltrig/identity/sessions.py:343` `"detail=\"two_factor_enrollment_required\""` | SEC-129 |
| BT-REQ-0746 | An account exists only by consuming a single-use, hashed, expiring invitation; there is no self-signup route. | IMPLEMENTED | `boltrig/api/auth_routes.py:380` `"inv = await k.store.claim_invitation_by_token_hash("` | SEC-97 |
| BT-REQ-0747 | Accept-invite is throttled per IP before the argon2 spend, because it is the only public endpoint paying 64 MiB before a bearer is claimed. | IMPLEMENTED | `boltrig/api/auth_routes.py:73` `"_ACCEPT_RL_IP = RateLimit(per=\"minute\", max=10, scope=\"verb\")"` | SEC-100 |
| BT-REQ-0748 | Unknown, expired and already-used invitations share one generic 400 so a probe cannot distinguish them. | IMPLEMENTED | `boltrig/api/auth_routes.py:378` `"\"reason\": \"invalid or expired invite\""` | SEC-97 |
| BT-REQ-0749 | Passwords are argon2id PHC strings with a per-user embedded salt, at least 12 and at most 1024 characters. | IMPLEMENTED | `boltrig/identity/passwords.py:28` `"MIN_PASSWORD_LENGTH = 12"` | SEC-98 |
| BT-REQ-0750 | The absent-user login path always spends a full argon2 verify against a fixed decoy hash. | IMPLEMENTED | `boltrig/identity/passwords.py:93` `"_PH.verify(_DUMMY_HASH, password)"` | SEC-99 |
| BT-REQ-0751 | Login enforces both a per-IP and a per-identity rate limit before touching the credential store and returns one byte-identical generic failure. | IMPLEMENTED | `boltrig/api/auth_routes.py:78` `"_GENERIC_LOGIN_FAILURE"` | SEC-99 |
| BT-REQ-0752 | Every login, logout, invite acceptance and 2FA event is audited keys-only, positionally, so the secret is absent from the dict the call site passes. | IMPLEMENTED | `boltrig/api/auth_routes.py:515` `"Keys-only via `_audit`: the session id, never the secret"` | SEC-191 |
| BT-REQ-0753 | The shared password credential is held ONCE at the identity realm keyed by the normalised email and is never duplicated per org. | IMPLEMENTED | `boltrig/api/auth_routes.py:405` `"Store ONLY the argon2id hash, apart from the identity row"` | SEC-134 |
| BT-REQ-0754 | The TOTP shared secret is sealed in `credential_refs` and returned to the client exactly once at enroll-begin. | IMPLEMENTED | `boltrig/api/auth_routes.py:634` `"await k.store.set_credential_ref(tenant, secret_ref, {\"secret\": secret})"` | SEC-126 |
| BT-REQ-0755 | Re-enrolling an already-enabled factor is refused 400, so the secret is never re-revealed. | IMPLEMENTED | `boltrig/api/auth_routes.py:627` `"\"reason\": \"two-factor is already enabled\""` | SEC-126 |
| BT-REQ-0756 | Recovery codes are ten 130-bit codes shown once, stored only as sha256, and consumed atomically. | IMPLEMENTED | `boltrig/identity/totp.py:54` `"_RECOVERY_CODE_LEN = 26"` | SEC-127 |
| BT-REQ-0757 | An enrolled user's correct-password login issues NO session and returns a single-use five-minute challenge instead. | IMPLEMENTED | `boltrig/api/auth_routes.py:502` `"return JSONResponse({\"status\": \"2fa_required\", \"challenge_token\": challenge})"` | SEC-128 |
| BT-REQ-0758 | Only a TOTP code activates enrollment; a recovery code cannot bootstrap the factor. | IMPLEMENTED | `boltrig/api/auth_routes.py:691` `"Only a TOTP code activates enrollment"` | SEC-126 |
| BT-REQ-0759 | A wrong second factor does not consume the challenge; a correct one consumes it atomically and a lost race fails. | IMPLEMENTED | `boltrig/api/auth_routes.py:775` `"DO NOT consume the challenge on a miss"` | SEC-128 |
| BT-REQ-0760 | Self-disabling two-factor requires a fresh TOTP or recovery code and overwrites the sealed secret material. | IMPLEMENTED-UNTESTED | `boltrig/api/auth_routes.py:852` `"await k.store.set_credential_ref(tenant, totp.secret_ref, {})"` (searched `tests/security/test_two_factor.py`; the six marked tests cover enroll, recovery, challenge, org-required, rate limit and window) | - |
| BT-REQ-0761 | Two-factor state travels with the identity realm and is never written under the active org. | IMPLEMENTED | `boltrig/api/auth_routes.py:604` `"tenant = _console_tenant()"` | SEC-134 |
| BT-REQ-0762 | A PAT is recognised by the `boltrig_pat_` prefix, stored only as sha256, and bounded by an expiry clamped to at most 365 days. | IMPLEMENTED | `boltrig/identity/tokens.py:27` `"MAX_TTL_DAYS = 365"` | SEC-34 |
| BT-REQ-0763 | A PAT's stored scope is the requested patterns the owner's grants actually permit, so it can never be minted above the user. | IMPLEMENTED | `boltrig/identity/tokens.py:70` `"effective_scope = [p for p in requested if user_grants.permits_pattern(p)]"` | SEC-34 |
| BT-REQ-0764 | A PAT's effective authority is re-computed on every call as its scope intersected with the owner's current grants narrowed by the active workspace ceiling. | IMPLEMENTED | `boltrig/identity/tokens.py:187` `"effective = GrantSet.of(allow=list(pat.scope)).intersect(user_grants)"` | SEC-109 |
| BT-REQ-0765 | PAT resolution binds the tenant before the RLS-scoped owner read, because the token table is the one legitimate cross-tenant lookup. | IMPLEMENTED | `boltrig/identity/tokens.py:162` `"set_current_tenant(pat.tenant_id)"` | SEC-65 |
| BT-REQ-0766 | A PAT naming a workspace its owner cannot reach is refused 403 and never falls back to unscoped org authority. | IMPLEMENTED-UNTESTED | `boltrig/identity/tokens.py:121` `"raise WorkspaceNotPermitted(requested_workspace_id)"` (seven tests in `tests/security/test_pat_workspace_selection.py`, none carrying an invariant marker) | - |
| BT-REQ-0767 | With no requested workspace, a PAT binds a single membership unambiguously and stays unscoped at zero or many. | IMPLEMENTED-UNTESTED | `boltrig/identity/tokens.py:124` `"return workspaces[0].id if len(workspaces) == 1 else None"` (bound only by unmarked tests, as above) | - |
| BT-REQ-0768 | The PAT list view carries neither the secret nor its hash. | IMPLEMENTED | `boltrig/kernel/access_routes.py:79` `"A PAT for listing: never the secret or the hash (PAT-02)"` | SEC-192 |
| BT-REQ-0769 | `POST /v1/me/tokens` accepts any authenticated principal, including a PAT, with no interactive-credential check and no rate limit. | IMPLEMENTED | `boltrig/kernel/access_routes.py:287` `"async def mint_my_token(body: dict, k=K, p=P)"` | - |
| BT-REQ-0770 | The host-boundary mint caps at the target's ORG grants and attributes the audit row to `host-boundary`, never the target. | IMPLEMENTED-UNTESTED | `boltrig/api/mint_token.py:87` `"actor=HOST_BOUNDARY_ACTOR, actor_tier=\"host\","` (searched `tests/security/test_operator_seat_boundary.py`, which pins the command SET, not the attribution) | - |
| BT-REQ-0771 | The identity command set at the host boundary is exactly `initiate`, `set-password`, `mint-token`, pinned by a static read of the router's literal. | IMPLEMENTED | `tests/security/test_operator_seat_boundary.py:54` `"IDENTITY_COMMANDS = frozenset({\"initiate\", \"set-password\", \"mint-token\"})"` | - |
| BT-REQ-0772 | `boltrig initiate` seats exactly one founding owner, flags the account for forced rotation, and refuses to run twice. | IMPLEMENTED-UNTESTED | `boltrig/api/initiate.py:110` `"must_change_password=True,"` (bound by `tests/security/test_first_party_login.py::test_initiate_is_idempotent_and_refuses_twice`, which carries no invariant marker) | - |
| BT-REQ-0773 | `boltrig set-password` operates only on an existing identity, never creating one, and discharges the forced-rotation flag. | IMPLEMENTED-UNTESTED | `boltrig/api/initiate.py:222` `"if user.must_change_password:"` (three unmarked tests in `tests/security/test_set_password.py`) | - |
| BT-REQ-0774 | `boltrig set-password` does NOT revoke any existing session for the rotated identity. | IMPLEMENTED | `boltrig/api/initiate.py:219` `"await store.set_password_credential(tenant, email, hash_password(password))"` (bounded: `rg -n "revoke_user_sessions" boltrig/api/initiate.py` returns nothing) | - |
| BT-REQ-0775 | Self-service password rotation proves the current password before setting a new one and refuses an unchanged password. | IMPLEMENTED-UNTESTED | `boltrig/api/auth_password_routes.py:86` `"\"reason\": \"the new password must differ\""` (unmarked tests only) | - |
| BT-REQ-0776 | Self-service rotation revokes every other session of the identity while keeping the caller's own. | IMPLEMENTED-UNTESTED | `boltrig/api/auth_password_routes.py:100` `"keep_token_hash=getattr(session, \"token_hash\", None),"` (unmarked tests only) | - |
| BT-REQ-0777 | Password-reset requests are non-enumerating, rate-limited per identity and per IP, and mint nothing at all when no delivery notifier is configured. | IMPLEMENTED | `boltrig/api/auth_recovery_routes.py:157` `"absent explicit delivery means no minted bearer"` | SEC-AUTH-RECOVERY-01 |
| BT-REQ-0778 | Reset redemption is one atomic transaction that claims the token, rotates the credential, clears the forced-rotation flag, revokes every session and deletes every pending 2FA challenge. | IMPLEMENTED | `boltrig/store/password_resets.py:171` `"WITH claimed AS ("` | SEC-AUTH-RECOVERY-01 |
| BT-REQ-0779 | Reset redemption issues no replacement session and deletes both cookies. | IMPLEMENTED | `boltrig/api/auth_recovery_routes.py:224` `"response.delete_cookie(SESSION_COOKIE, path=\"/\")"` | SEC-AUTH-RECOVERY-01 |
| BT-REQ-0780 | Reset delivery evidence discloses no recipient, provider, address, exception or message content and never represents notifier acceptance as inbox delivery. | IMPLEMENTED | `boltrig/identity/password_reset_evidence.py:29` `"Project no recipient, provider, address, exception, or message content"` | SEC-AUTH-RECOVERY-01 |
| BT-REQ-0781 | Password-reset delivery is a SEAM: the notifier is composed from deployment env and MailerSend is the only supported provider; partial configuration raises at startup. | SEAM | `boltrig/api/password_reset_composition.py:38` `"raise RuntimeError(\"unsupported password-reset delivery provider\")"` | SEC-AUTH-RECOVERY-01 |
| BT-REQ-0782 | An AI key is accepted once, sealed before persistence under an opaque proposal with a 15-minute maximum TTL, and never echoed in any response or audit row. | IMPLEMENTED | `boltrig/store/ai_key_proposal_contract.py:17` `"AI_KEY_PROPOSAL_MAX_TTL = timedelta(minutes=15)"` | SEC-113 |
| BT-REQ-0783 | Caller-supplied `approval_id`, `proposal_id` or `secret_digest` on the AI-key intake is refused as server-owned evidence. | IMPLEMENTED-UNTESTED | `boltrig/kernel/ai_key_routes.py:74` `"approval and proposal evidence is server-owned"` (searched `tests/security/test_ai_key_secret_proposals.py`, whose five marked tests cover sealing, expiry, requester-only status, drift and worker retention) | - |
| BT-REQ-0784 | An org-level AI key requires an admin role; a workspace or user key additionally requires the org's `allow_own_ai_keys` flag. | IMPLEMENTED | `boltrig/kernel/ai_key_routes.py:41` `"if org is None or not org.allow_own_ai_keys:"` | SEC-115 |
| BT-REQ-0785 | Connecting your OWN user-level key folds the approval answer into the same press, and a refusal from the HITL layer leaves the pending response standing. | IMPLEMENTED | `boltrig/kernel/ai_key_routes.py:299` `"if attached is None or level != \"user\" or scope_id != p.subject:"` | FR-AIKEY-03 |
| BT-REQ-0786 | AI-key resolution precedence is user, workspace, org, then the manifest default, and the user and workspace levels are skipped entirely when the org has not opted in. | IMPLEMENTED | `boltrig/identity/ai_keys.py:116` `"if allow_own:"` | SEC-112 |
| BT-REQ-0787 | An absent organisation row is treated as `allow_own_ai_keys = False`. | IMPLEMENTED | `boltrig/identity/ai_keys.py:99` `"allow_own = bool(org.allow_own_ai_keys) if org is not None else False"` | SEC-112 |
| BT-REQ-0788 | A vision request falls back to the same scope's text key before descending a level. | IMPLEMENTED | `boltrig/identity/ai_keys.py:110` `"if requested_modality == \"vision\":"` | FR-AIKEY-VISION-01 |
| BT-REQ-0789 | A provider seat is re-mintable in place: its credential ref is a deterministic digest of tenant, level, scope and modality, and `ensure` re-provisions onto the same ref when the binding is not usable. | IMPLEMENTED | `boltrig/identity/bifrost_user_binding.py:70` `"digest = hashlib.sha256("` | SEC-AIKEY-01 |
| BT-REQ-0790 | `POST /v1/ai-keys/activate` re-mints a provider seat with no fresh secret and no fresh approval, gated only by the same authorisation as the set route. | IMPLEMENTED-UNTESTED | `boltrig/kernel/ai_key_routes.py:320` `"@app.post(\"/v1/ai-keys/activate\")"` (searched `tests/security/test_ai_keys.py`; `test_existing_approved_key_can_be_reconciled_without_resubmitting_secret` covers the reconcile path but is marked SEC-113/FR-AIKEY-03, not an activate-specific invariant) | - |
| BT-REQ-0791 | The Bifrost model gateway is a SEAM: the admin base must be an internal host with an exact `/v1` path, and the binding refuses fail-closed when it cannot be proven usable. | SEAM | `boltrig/identity/bifrost_user_transport.py:45` `"raise BifrostUserBindingUnavailable(\"the model gateway configuration is invalid\")"` | SEC-AIKEY-01 |
| BT-REQ-0792 | A personal integration credential is preferred over the org's only when the org sets `allow_own_integration_credentials`; otherwise the user row is skipped entirely. | IMPLEMENTED-UNTESTED | `boltrig/kernel/integration_scope.py:40` `"if org is not None and org.allow_own_integration_credentials:"` (`tests/security/test_integration_scope.py` is named in the source comment; I did not read it) | - |
| BT-REQ-0793 | Personal integration setup is refused BEFORE anything is sealed when the org has not opted in, and refused when the caller has no personal scope. | IMPLEMENTED-UNTESTED | `boltrig/config/control_integrations.py:126` `"return \"own_integration_credentials_not_allowed\""` (test file not read) | - |
| BT-REQ-0794 | The roster routes reject granting a role ranked above the caller's own and restrict all-authority scope to the owner tier. | IMPLEMENTED | `boltrig/kernel/access_routes.py:56` `"if role is not None and _role_rank(str(role)) < _role_rank(p.role):"` | SEC-102 |
| BT-REQ-0795 | Provisioning a brand-new org from an invitation is superadmin-only at invite creation, refused 403 with no invitation written. | IMPLEMENTED | `boltrig/kernel/access_routes.py:584` `"\"reason\": \"org provisioning is owner-only\""` | SEC-118 |
| BT-REQ-0796 | Device enrollment requires a human actor tier and an available Ed25519 signer, and stores only the sha256 of a ten-minute authorisation code. | IMPLEMENTED | `boltrig/kernel/device_routes.py:88` `"authorization_code_hash=token_digest(code),"` | SEC-WRK-07 |
| BT-REQ-0797 | A device lease is issued only against a CONSUMED approval whose respondent is not in the requester set, with no relief admitted. | IMPLEMENTED | `boltrig/device_leases.py:126` `"or response.respondent in {"` | SEC-WRK-07 |
| BT-REQ-0798 | The sole-author approval relief lifts independence without consulting `credential_kind`, so a PAT principal in the sole author's name can answer its own approval. | IMPLEMENTED | `boltrig/kernel/hitl_response_auth.py:206` `"if await _sole_active_author(store, tenant_id, subject):"` | SEC-182 |
| BT-REQ-0799 | The on-behalf-of delegation mechanism is present but unreachable: `OnBehalfOf` is never constructed and `identity_mode` is read only by a view renderer. | DEAD | `boltrig/identity/delegation.py:28` `"class OnBehalfOf:"` (bounded: `rg -n "OnBehalfOf\(" --include=*.py .` returns nothing; `rg -n "identity_mode" boltrig/kernel/ boltrig/fleet/ boltrig/adapters/` returns one view-render hit, 2026-08-24, pinned tree) | - |
