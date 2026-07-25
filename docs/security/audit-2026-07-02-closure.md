# Closure record: the five HIGH findings of `audit-2026-07-02.md`

Verified 2026-07-25 against the working tree, by reading the code and running the
bound tests. Written because no closure record existed: later rounds used a
different SEC-nnn numbering and `security-conformance.md` claimed several of these
families hardened, which is not the same thing as evidence. "Later work probably
covered it" is not a closure record, which is why this file exists.

**Result: 3 of 5 closed with evidence (H1, H2, H4). 2 partially closed (H3, H5),
with the exact remainder named below.**

## H1 - HITL null-verb approval bypass: CLOSED

`consume_if_approved` no longer skips the verb match on a null verb or accepts a
non-APPROVAL type. The gate fails closed on both in `boltrig/kernel/hitl.py:356-363`
(`req.type != HITLType.APPROVAL or req.verb != verb`; a `None` verb can never equal
the passed `str`). The respond-route half is in
`boltrig/kernel/hitl_response_auth.py:181-204`: non-APPROVAL types require
`actor_tier == "human"`, are anti-self-approval checked, and are assignee-bound.

Bound by `tests/security/test_hitl_gate.py::test_escalation_answer_cannot_clear_high_consequence_gate`
(the name the audit prescribed), marked `SEC-14`, declared in `tests/invariants.yaml`.

## H2 - SSRF DNS-rebind TOCTOU: CLOSED, with two by-design residuals

The vetted IP is now pinned at connect time. `boltrig/adapters/egress.py` gained
`resolve_and_vet` (one audited resolution), `_pinned_backend` (an httpcore backend
that dials the pinned IP and ignores the hostname), and
`pinned_async_client{,_for_ip}`, all forcing `follow_redirects=False`. Adopted by
every client the finding named: `web_fetch`, `channel_send`, `mcp_transport`,
`mcp_consumer`, and `http_base` (so every HTTP adapter inherits it).

Bound by `tests/security/test_egress_pinning.py::test_egress_rejects_dns_rebind_between_check_and_connect`,
which flips `getaddrinfo` public -> metadata on the second lookup and asserts the
socket went to the public IP. Marked `SEC-61`.

Residuals, both commented as deliberate: `browser_cli.py:233` vets but cannot pin
(the URL is handed to a subprocess CLI), and `web_fetch.py`'s `https_proxy` branch
delegates resolution to the proxy. Neither is the agent-reachable rebind H2
described, but neither is IP-pinned.

## H3 - Audit HMAC key silently defaults on the worker: PARTIALLY CLOSED

Closed: `refuse_default_audit_key_in_prod()` is now the first statement of
`build_kernel_async` (`boltrig/api/bootstrap.py:364`), so the fleet and Hatchet
worker paths are guarded, not just `create_app`. Bound by
`tests/security/test_round_sixteen.py::test_worker_boot_refuses_default_audit_key_under_prod_signal`,
which really boots the worker path under `BOLTRIG_PRODUCTION=1` and asserts it
raises. Marked `K-19`.

**Still open, and it matters:** the guard only fires when a production signal is
set, and nothing sets one by default.

1. `boltrig/kernel/audit.py:25` still reads the key at import time with an
   in-source fallback: `os.environ.get("BOLTRIG_AUDIT_HMAC_KEY", "dev-insecure-audit-key")`.
   The audit asked for this to be settings-driven into `AuditWriter`;
   `AuditWriter.__init__` still takes only `store`.
2. `docker-compose.yml` emits `BOLTRIG_ENV: ${BOLTRIG_ENV:-}` and
   `BOLTRIG_PRODUCTION: ${BOLTRIG_PRODUCTION:-}` - empty by default.

Together these mean a real deployment that never sets the signal boots happily on
a hash-chain key that is a public constant in this repository, which makes the
audit log's tamper-evidence decorative rather than real. The guard is not wrong;
it is simply never armed by default. Closing this needs a decision on the shipped
posture (default the signal on, or make the key mandatory with an explicit
opt-out for offline dev), so it is recorded rather than changed unilaterally.

## H4 - Budget hard-stop lost under concurrency: CLOSED

Fixed more strongly than prescribed. The per-scope `consume_budget` loop whose
boolean return was ignored is gone; `boltrig/kernel/cost.py:154-161` now makes one
transactional multi-scope reserve and raises `BudgetExceeded` when it returns
False. `store/postgres.py:888-940` locks each scope `FOR UPDATE` in sorted order
(deadlock-safe), re-checks each hard stop under the lock, and returns before any
UPDATE so nothing partial commits.

Bound at two layers: `tests/security/test_budget_and_pii.py::test_reserve_honors_atomic_store_refusal`
(`FR-COST-02`) and `tests/store/test_budget_atomic_reserve.py::test_concurrent_multi_scope_reserves_cannot_partially_debit`
(`FR-COST-05`, whose declaration names "audit H4").

Caveat: the genuinely racing assertions are on the `[postgres]` leg, which skips
without `BOLTRIG_TEST_DATABASE_URL`. That is now runnable locally as well as in
CI (see the Makefile `test` target), so the race is no longer verified in only
one place.

## H5 - Invariant gate red in CI: PARTIALLY CLOSED

Closed: the root cause the audit identified (the CI Postgres service lacked the
`pgvector` extension) is fixed by the digest-pinned `pgvector/pgvector:pg16`
service in `.github/workflows/ci.yml`. As of 2026-07-25 `ci.yml` is green,
verified on consecutive pushed runs, and `make invariants` reports
`PASS - every declared invariant is bound and every marker is declared`.

The audit also recorded that CI is **not** billing-blocked "contrary to the repo
docs". That contradiction persisted for three more weeks;
`docs/security-conformance.md` has now been corrected.

**Still open:** `repos/:owner/:repo/branches/main/protection` returns
`404 Branch not protected`. Nothing requires the gate to be green before a commit
lands on main, which is the condition the finding described. Making these checks
required is the remaining half, and it changes how everyone pushes to this repo,
so it belongs to the Principal rather than to a passing commit.

## What this record does not cover

The ~14 MEDIUM and ~15 LOW/INFO findings of the same audit were not re-verified
here. Three of its project-scoped items (M10 automated off-box backup, M11
conversation purge worker, M14 cost reconciliation) still appear as open work
elsewhere in `docs/`, so treat the MEDIUM set as unverified rather than closed.
