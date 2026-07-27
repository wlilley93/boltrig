# Security model (one page for a reviewer)

This is the trust model of a Boltrig box, for a security reviewer at a prospective tenant. It states what is enforced today, and marks honestly what is Principal-gated or not-yet-live.

## The dispatch chokepoint

Every external action - a tool call, a model call, an agent spawn, an MCP call - funnels through one function, `Dispatcher.invoke`. The order is fixed and the same for every caller, and an audit row is written at the end regardless of outcome:

```
resolve verb + binding    (fail-closed if unknown)
validate params           (schema validation)
grant check               (deny-by-default)
consequence / HITL gate   (cannot be bypassed)
rate limit
idempotency replay
resolve credential        (inside the kernel only)
execute adapter | agent   (degrade on unavailable)
validate output
audit (always)
```

There is one path in, so there is one place to reason about authorization, and no route can add its own dispatch policy.

## Deny-by-default grants

Authority is a `GrantSet` of allow/deny verb patterns (terminal-wildcard, deny-dominant). An unmapped caller resolves to role `none` and empty grants - it can do nothing. Grants come from the IdP-group-to-role/scope mapping (or the first-party user's role/scope), and are only ever intersected **down**:

- The active workspace role narrows grants to its ceiling (see `01-organisations-and-workspaces.md`); a workspace membership can only remove authority.
- A personal access token is minted as a **subset** of the caller's current grants and re-checked on every use, so it never escalates. Deactivating the user kills the token's authority (the token resolves against current role/scope/status).
- No principal may grant a role above its own; only the owner may grant all-authority scope (the escalation clamp on invite/update-user).

## Kernel-held sealed credentials

The database holds credential **references**, never plaintext (`SECRET_STORE` selects the backend: env / vault / kms / docker). Secret material - AI keys, adapter credentials, session/invite hashes - is resolved kernel-side at call time and handed straight to one adapter or runtime call. It is never returned to an agent, embedded in a result, or written to the audit log. AI keys additionally never come back on any read (only provider/model/`has_key`). See `03-ai-keys-and-models.md`.

## Sensitive data stays local (SEC-12)

Model endpoints are classified `standard` or `sensitive`. The router guard enforces that sensitive-classified data may only reach a local `sensitive` endpoint, otherwise it raises `SensitiveDataMisrouted` and audits the attempt. This overrides AI-key routing. `AIR_GAPPED=true` forbids all outbound network and forces on-box inference.

## The human-in-the-loop (HITL) gate

Consequential verbs pause at the HITL gate inside dispatch and cannot proceed without a human approval - the gate cannot be bypassed. Approvals are hardened (SEC-14):

- An approval is **single-use and verb-bound**: `consume_if_approved` atomically flips ANSWERED to CONSUMED, so the same approval can never authorise a second execution.
- Only a genuine `APPROVAL` (not a question or clarification) with a matching verb clears the gate; a null or mismatched verb fails closed. An escalation/question cannot be laundered into authorising a gated verb.
- The answer route for agent questions is a separate path that can never clear an approval; user-supplied answers are enveloped as untrusted data before being replayed into a run (so inbound text is never re-ingested as instructions).

## Session + CSRF (first-party login)

With `BOLTRIG_AUTH_MODE=session` (what genesis sets), login issues a Boltrig session: a high-entropy opaque secret whose sha256 alone is persisted. Properties:

- The session cookie is httpOnly, Secure (`session_cookie_secure`, default true), and SameSite=Strict - not readable by JS, not sent cross-site.
- A readable CSRF cookie (`boltrig_csrf`) must be echoed in the `x-boltrig-csrf` header on every mutating (POST/PUT/PATCH/DELETE) cookie request; the resolver constant-time-compares it. Safe methods are exempt. Bearer/PAT auth never reaches the CSRF check.
- Sessions are bounded (12h TTL), rotating (refresh mints a new secret and invalidates the old cookie), and revocable (logout, or the sessions panel). There is an absolute creation-anchored cap (7 days) past which refresh refuses and forces re-auth.
- Identity comes only from the verified session, never the request body. A deactivated user's session stops resolving on the next request (fail-closed).
- Login is non-enumerating: constant-time verify with a decoy hash on the absent/deactivated path, one generic failure body, and rate limits (5/min per identity, 30/min per IP) that also emit a security signal on trip.

### Alternative edge auth

Instead of first-party sessions a deployment can front the box with Cloudflare Access (verifies a per-request signed assertion, maps email to role) or OIDC (`OIDC_ISSUER` / `OIDC_AUDIENCE` / `OIDC_JWKS_URI`; the kernel verifies real bearer tokens). With no auth configured the kernel refuses all requests (fail-closed) unless `BOLTRIG_DEV_AUTH=1` - which trusts headers with no verification and must **never** be set in production. A production signal (`BOLTRIG_PRODUCTION=1`, or a prod/staging `ENV`) makes the kernel refuse to start if `BOLTRIG_DEV_AUTH=1` is also set.

## Tamper-evident audit

Every action is hash-chained per tenant and verifiable; security signals are on a separate chained stream; a rollup anchor covers segments. See `04-audit-and-compliance.md`. External anchoring (RFC3161 TSA + KMS signature) is a Principal-gated seam - not live until credentials are wired.

## Two-factor authentication - TOTP ([2026] VJS-COUNTY 10)

Boltrig enforces TOTP (authenticator-app) second-factor auth on the first-party
login, with hashed single-use recovery codes as the fallback. No external
dependency (TOTP verifies offline).

- **Enroll**: `POST /v1/auth/2fa/enroll` mints a secret (returned once for the
  authenticator, alongside the recovery codes) and `POST /v1/auth/2fa/verify-enroll`
  confirms a code to activate. The secret is stored SEALED in the credential store
  (never a plaintext column, never returned again, never audited); recovery codes
  are stored only as hashes (130-bit each, single-use).
- **Challenge**: after the password verifies, if the user has 2FA enabled the login
  returns `2fa_required` with a short-lived single-use challenge token and issues NO
  session; `POST /v1/auth/2fa/challenge` verifies the TOTP (or a recovery code) and
  only then issues the session. Fail-closed, rate-limited, constant-time,
  non-enumerating, audited keys-only.
- **Org enforcement**: when `require_two_factor` is set, a user who has not enrolled
  is clamped to the enrollment surface only (the resolver refuses every other route
  with `403 two_factor_enrollment_required`, including a mid-session flip of the
  flag), so the org policy is an enforced control, not just a record.
- **Recovery + disable**: recovery codes are a single-use fallback, never a bypass;
  `POST /v1/auth/2fa/disable` requires a fresh factor.

WebAuthn/passkeys are a permitted later add-on; email/SMS OTP was rejected (an
external dependency). Edge-IdP MFA (Cloudflare Access / OIDC) also remains an option
when fronting the box.

## Deployment hardening knobs (set for production)

- `POSTGRES_PASSWORD` (compose refuses to start without it) and a matching `DATABASE_URL` credential segment.
- `BOLTRIG_AUDIT_HMAC_KEY` - long random, per deployment.
- `BOLTRIG_ALLOWED_HOSTS` - the box's real hostnames (default `*` is dev-only).
- `BOLTRIG_CORS_ORIGINS` - the browser origin allowlist (never `*` with credentials).
- `BOLTRIG_MAX_BODY_BYTES` - request body cap (default 1 MiB).
- Off-box, optionally-encrypted backups via the `backup` compose profile (`BACKUP_REMOTE`, `BACKUP_PASSPHRASE`).
