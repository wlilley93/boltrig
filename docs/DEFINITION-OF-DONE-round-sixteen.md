# Definition of Done - Round Sixteen (security hardening, the buildable controls)

Specs: `requirements-security-batch1.md` (zero-trust, ~107 controls) +
`requirements-security-batch2.md` (Azure/cloud/host/runtime, ~76 controls). Both
were recovered verbatim from the transcript and ported to `docs/` (they had never
been ported - this is now the authoritative copy).

Per `AGENTS.md`: the code was triaged against the actual codebase first (every
control classified BUILT / GAP / SEAM with cites), then the genuinely-missing,
highest-severity, pure-code controls were built and bound. The cloud/host/CI/ops
controls are NOT claimed as built - they are seams, tracked honestly in
`docs/security-conformance.md`.

## What shipped (the real code gaps, all bound at binding-debt 0)

- **SEC-58 - edge/web hardening (WEB-02/03/05/06, RES-01).** The kernel app
  installed zero middleware. `boltrig/kernel/web_security.py` adds security headers
  (HSTS/nosniff/frame-deny/referrer/permissions/CSP), a CORS allowlist (never `*`
  with credentials), TrustedHost Host-validation, and a request-body cap (413).
- **SEC-59 - JWT verification hardening (IAM-02/03/04/05).** `identity/auth.py`:
  an explicit RS/ES algorithm allowlist (alg=none and HS confusion rejected, via
  `JsonWebToken(algs)`), `exp` required + absolute-lifetime cap + leeway clamped
  <=120s, access-token-only (ID token rejected), JWKS cache TTL + kid-miss
  refetch-then-fail-closed + explicit fetch timeout.
- **SEC-60 - dev auth impossible in prod (IAM-09).** `bootstrap.refuse_dev_auth_in_prod`
  hard-aborts startup when `BOLTRIG_DEV_AUTH` coincides with a production signal
  (ENV/BOLTRIG_ENV/APP_ENV=prod|staging or BOLTRIG_PRODUCTION=1) - not a warning.
- **SEC-61 - shared egress/SSRF guard (INJ-02 / CLOUD-03).** `boltrig/adapters/egress.py`
  consolidates the SSRF/policy logic (web.fetch now re-exports it - one source of
  truth) and adds `assert_no_metadata_egress`, applied in `http_base.request` so
  EVERY HTTP adapter refuses a cloud-metadata / link-local target - closing the
  SSRF -> IMDS managed-identity-token-theft path.
- **SEC-62 - identifier normalization (UPLOAD-05 / AZ-02).** `models/grants.py`
  NFKC-normalises and charset-restricts ids at the grant-match boundary, so a
  Unicode homoglyph / zero-width / non-canonical verb id can never match a grant.
- **SEC-63 - webhook replay window (ADP-08).** `inbound_webhook` now rejects a
  signed request whose timestamp is outside the replay window. Plus constant-time
  PAT hash compare (CRYPTO-04).

## Gate (green)

- `pytest`: **147 passed, 14 skipped** (+6); no regressions to the prior 141.
- `check_invariants.py`: **declared=93, bound_tests=121, binding_debt=0, PASS**.
- `ruff`: clean.

## Honest residue (NOT built - seams, tracked in security-conformance.md)

The Azure/cloud (managed identity, Key Vault, private endpoints, NSG, WAF), Linux
host (CIS, rootless, bastion), CI/CD (SCA, signing, required gates - the GitHub
Actions billing block is the live blocker), TLS/at-rest/RLS deploy controls, and
the Pi-runtime native-tool-disable + micro-VM isolation (lands with the real Pi
loop) are environment/ops/Principal-owned. Container hardening in the Dockerfiles
(INF-01) and a least-privilege DB role + RLS policies are buildable follow-ons for
a next code round. `docs/security-conformance.md` is the per-family source of truth
for what is BUILT vs SEAM; keep it accurate.

This is the first security-hardening round: the highest-severity code controls of
both batches, built and bound. The remaining work is either ops (Principal) or a
documented next code round, all tracked in the conformance ledger.
