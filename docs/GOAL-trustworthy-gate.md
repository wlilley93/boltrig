# Goal: make the gate tell the truth again

## The goal statement

**Restore boltrig's verification apparatus to the point where a green result is
evidence, so that "the gates pass" means the code is actually checked rather than
that the checks did not run.**

Done means, precisely:

1. Every job in `ci.yml` and `security.yml` is green on a pushed commit:
   `test-and-gate`, `ui-build`, `ui-e2e`, `site-build-test-lint`,
   `compose-validate`, `quality`, and the container + source security jobs.
2. The `channel_deliveries_channel_id_fkey` violation in
   `tests/store/test_channel_durability.py` is fixed **at its root**, in the
   store's delivery path or in a genuinely wrong fixture, never by relaxing the
   constraint or skipping the parametrisation.
3. The Postgres surface is runnable locally against a dedicated throwaway
   database, so the ~20 tests that today skip without
   `BOLTRIG_TEST_DATABASE_URL` (RLS fence drift, migration parity, tenancy,
   store parity) execute on a developer box. The invocation is documented in
   Makefile help and `.env.example`.
4. Every service-gated invariant that CAN now run has been run: FR-WFL-17 (live
   Hatchet, newly possible), the docker-gated per-cell-uid and backup/restore
   suites. Any that genuinely need a credential the Principal must supply is
   recorded as blocked on that credential, by name, rather than left ambiguous.
5. The five HIGH findings in `docs/security/audit-2026-07-02.md` (H1 HITL
   null-verb approval bypass, H2 SSRF DNS-rebind TOCTOU, H3 audit HMAC key
   defaulting on the worker, H4 budget hard-stop lost under concurrency, H5
   invariant gate red in CI) each have a written closure record pointing at the
   code and the test that closes them, or are fixed.
6. `docs/security-conformance.md` no longer claims GitHub Actions is
   billing-blocked. Runs execute today, so that line is false and it is currently
   excusing the whole SUP-01..06 + PIPE family.

**Not in this goal**, deliberately: the UI SDK build-out to the 17-domain
contract, the PR8 write/effects phase, the builtin-rehydration fork, the
structural-exemption cliff, and prod cutover Path C. Each is real work and each
is better done on top of a gate that can be believed, not underneath one.

## Why this is the goal

Boltrig currently reports two contradictory things about itself, and the
comforting one is louder.

Locally, `make check` passes: invariants, lint, architecture, structure,
codex-protocol, typecheck, 2354 tests. Remotely, **every** `ci.yml` job has been
failing, including on commits that touched nothing but Markdown. The two are not
in conflict because one is wrong; they are measuring different things. The
~20 Postgres tests only ever run in CI, because only CI sets
`BOLTRIG_TEST_DATABASE_URL`. So the surface that carries RLS fence drift,
migration parity and tenancy isolation has been checked in exactly one place, and
that place has been dark.

This is not hypothetical. It was already hiding a defect: among 2508 passing
tests, CI shows a single real failure, a foreign-key violation in the channel
durability path that the in-memory store cannot detect and no local run will ever
surface.

A red CI that everyone has stopped reading is worse than no CI, because it
converts every future real failure into noise. And the local green is worse still,
because it is actively reassuring. The programme that just finished, the
kernel-tools lane, was ultimately won by insisting on the audit row rather than
the plausible reply. This goal applies the same standard one level up: to the
apparatus that is supposed to be doing the insisting.

Fixing it is also cheap. Six red jobs reduce to five root causes, only one of
which is a genuine code defect. That asymmetry, high value and low cost, is why
this comes before anything else in the backlog.

## The one rule that governs how it is built

**Green must mean green.** No result counts unless you can name where it ran.

Concretely, for this goal:

- A fix is not verified by a local run when the failure only reproduces in CI.
  Push it and read the job.
- A test that passes because it skipped has not passed. Watch the skip count, not
  just the pass count.
- Do not silence a check to make a board green. If a check is wrong, say so and
  change it deliberately, in a commit that explains why. If a check is right,
  fix the code.
- A closure claim needs a pointer to the code and the test that closes it. The
  2026-07-02 audit is in this goal precisely because "later rounds imply it was
  handled" is not a closure record.
