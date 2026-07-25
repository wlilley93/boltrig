# Closure record: the five HIGH findings of `audit-2026-07-02.md`

Verified 2026-07-25 against the working tree, by reading the code and running the
bound tests. Written because no closure record existed: later rounds used a
different SEC-nnn numbering and `security-conformance.md` claimed several of these
families hardened, which is not the same thing as evidence. "Later work probably
covered it" is not a closure record, which is why this file exists.

**Result: 3 of 5 closed with evidence (H1, H2, H4). 2 partially closed (H3, H5),
with the exact remainder named below.**

Both partial findings were put to the VJS court rather than decided unilaterally
or routed to the Principal by default, and BOTH judgments held the acts were
Lexby's to take: [2026] VJS-CC-BOLTRIG-BRANCH-PROTECTION-001 and
[2026] VJS-CC-BOLTRIG-AUDIT-KEY-PROVISIONING-001. The first corrected an error of
law in an earlier revision of this very file. The second found the H3 hole to be
materially worse than this record first described. Both are recorded below at the
control's true scope, because a ledger entry claiming more than the control
delivers is the failure mode this whole exercise exists to remove.

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

**The hole was WORSE than this record first stated.** My own first pass said the
guard was correct but "never armed by default". Putting the question to the court
([2026] VJS-CC-BOLTRIG-AUDIT-KEY-PROVISIONING-001) established that the guard did
not even recognise the value the project SHIPS. It compared against the in-source
default (`dev-insecure-audit-key`) and blank only, while `.env.example` carried
`change-me-to-a-long-random-secret`. A deployment following the documented
`cp .env.example .env` therefore tripped NEITHER the fatal NOR the warning. A
guard that misses the value its own project ships is worse than no guard, because
it reassures. Two further defects fell out of the same root:

- `boltrig/api/doctor.py` already KNEW that string was a placeholder, so two
  predicates disagreed and the gap between them was the hole (O2).
- `boltrig/fleet/stack_tool_receipts.py::receipt_signing_key` rejected only blank,
  so a placeholder key produced a well-formed signing key and readiness receipts
  were signed with a public constant - forgeable by anyone with this repository,
  which is worth no more than no receipt (O3).

**Source default CORRECTED** (O1, O2, O3, O6): `.env.example` now ships the key
BLANK, so it cannot be copied verbatim into a real deployment; all three
consumers ask one shared predicate (`boltrig/config/weak_secrets.py`) that knows
every placeholder this repo has ever shipped; and
`tests/security/test_audit_key_provisioning.py` pins the property at each site,
including a test that fails if `.env.example` ever ships a value again.

**ESTATE REMEDIATION OPEN, and it is live.** Both prod deployments were checked
and BOTH carry a placeholder audit key - `boltrig-tenants/cv/boltrig.env` (a real
client tenant) and `boltrig-tenants/boltrig-io.env`. Their audit chains are
forgeable today, while `security-conformance.md` records DATA-05 "tamper-evident
hash-chained audit" as BUILT. The dev box has a real 64-character key.

Rotation on a running deployment is **RESERVED TO THE PRINCIPAL** (O9): rotating
breaks continuity with rows already signed under the old key, and CV holds live
client rows. So the source is fixed and the estate is not; do not record H3 as
closed until the estate is remediated.

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

**PARTIALLY CLOSED**, at the control's true scope, stated verbatim so the ledger
claims no more than the control delivers:

Branch protection is now enabled on `main`
([2026] VJS-CC-BOLTRIG-BRANCH-PROTECTION-001, Order 2). Contexts `quality` and
`Security gate` are required; `allow_force_pushes` and `allow_deletions` are
false. It binds pull requests and every NON-ADMIN actor, including `release.yml`'s
`GITHUB_TOKEN` and Dependabot. `enforce_admins` is FALSE, so the sole admin
retains a bypass, and `strict` is false. That is why this is PARTIALLY closed and
must not be recorded as closed.

The strong form was refused on the evidence, not for want of authority:
`security.yml` sets `cancel-in-progress`, so at the current push cadence a run on
`main` is frequently cancelled rather than failed, and admin enforcement would
create a gate with no lawful path through it. Conditions for renewing that
application are in Order 4 of the same judgment.

**Correction of an error of law in an earlier revision of this file.** This
section previously said making the checks required "belongs to the Principal
rather than to a passing commit". That was wrong, and the court corrected it
(Order 7). Enabling branch protection here is not reserved to the Principal: it
needs no credential Lexby lacks, it is undone by a single reversing API call that
destroys no data, and it is neither a release nor a destructive act. It is
governed work, and routing it to the Principal would itself have been a breach.
Permission to appeal the jurisdictional limb was granted on the court's own
motion.

## What this record does not cover

The ~14 MEDIUM and ~15 LOW/INFO findings of the same audit were not re-verified
here. Three of its project-scoped items (M10 automated off-box backup, M11
conversation purge worker, M14 cost reconciliation) still appear as open work
elsewhere in `docs/`, so treat the MEDIUM set as unverified rather than closed.
