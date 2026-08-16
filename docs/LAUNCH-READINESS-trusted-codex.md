# Launch readiness: the trusted Codex lane, 2026-07-20

A single honest statement of where the line is, so "is it ready?" has one answer and does not keep
being re-asked. Written against the code on `main`, not from memory.

## What is DONE and proven

- Codex 0.144.3 is the agent runtime, governed by the kernel, reachable from the console behind
  `BOLTRIG_CODEX_TRUSTED`.
- The tool ceiling holds on the model-proxy wire, request and response, proved live on the pinned
  binary (VJS-CC-VJS 4, all four limbs).
- Bearer delivery is attested and nothing is at rest (VJS-CC-VJS 1/3); the ingress socket is
  abstract and uid-bound (VJS-CC-VJS 7 J8).
- **Two mutually distrusting cells run concurrently under kernel-enforced per-cell uids**
  (VJS-CC-VJS 7, enacted AND wired into the product). The adversarial gate passes as a recorded
  test: hostile cell A, with full write access to everything its uid can reach, cannot reach cell
  B's `config.toml` by any of nine routes, and the API itself is never privileged.

  A correctness bug was found and fixed after the first enactment, and it is worth recording because
  it was another overclaim: the J9 gate proved the mechanism in a harness that stayed uid 0, but the
  PRODUCT decides per-cell mode inside the API, which the entrypoint deliberately DROPS to uid 10001.
  So `per_cell_uid_mode_available()` read False in the running API, `config_toml_protected` stayed
  False, the provider kept refusing the second cell, and nothing built a `CellLane` - the feature was
  enacted in compose but OFF in the product. The dropped API cannot answer "are per-cell uids on?"
  from its own uid; the honest signal is the live spawner socket the entrypoint hands it. That is now
  the signal, the composition root builds the `CellLane` from it, and the dropped API reads True (
  proven in-container). Without the capability the socket is absent and the API is unchanged.

Gate green: 1926 passed. `tests/integration/test_per_cell_uid_gates.py` arms the J7/J9 live gates.

## The three remaining lines, and who owns each

### 1. `production_ready` = True — BLOCKED BY THE CODEX VERSION, not by unfinished work

This flag is False, and the receipt contract (`codex_runtime_config.py:251`) *asserts* it False. It
cannot be flipped on Codex 0.144.3, for a runtime reason that no amount of our work changes:

`QUARANTINED_PREFLIGHT_BLOCKERS` lists seven preflight items. Some are now dischargeable by the work
done (`effective_tools` is DETERMINED at the proxy, its four proofs passed; `effective_config`,
`effective_apps`, `effective_plugins`, `effective_external_agents` have a returned discharge design).
But **`effective_provider` and `full_generated_schema_contract` have no method in the 0.144.3
protocol** to enumerate them. They cannot be self-attested by this Codex version, so a truthful
`production_ready` cannot be True while pinned to it.

Flipping it also requires a fresh court application under [2026] VJS-CC-VJS 4 F9 — the grant in force
is expressly not that permission. But the court cannot grant what the runtime forbids, so the
honest position is: **this line moves when Codex gains those methods (a version bump), not before,
and the application waits for that.** Keeping it False needs no court and is correct.

This is not a gap in the security work. The security goal — safe concurrency for distrusting cells —
does not depend on this flag.

### 2. PR8 — the write/effects phase — a NEW goal, court-gated, deliberately not opened

Codex today only reasons. Letting it act (edit files, run effectful tools) is a separate,
court-gated phase and should not open before the read-only lane has real use. This is the next goal,
not the tail of this one. Opening it now would be scope inflation against a standing judgment.

### 3. The prod cutover — APPROVED, and now BLOCKED ON A SCHEMA-RECONCILIATION PLAN

The Principal's go is banked. The read-only first steps of the runbook were taken this session and
they surfaced a hard precondition that must be resolved before the irreversible step, so the cutover
is not a blind `alembic upgrade head`:

**Observed on a production host, read-only (2026-07-20):** the `boltrig` database has 57 tables, one
real user, `organisations`, `workspaces` and `audit_log` — and **NO `alembic_version` table**. It
was created directly from `schema.sql` (the first-boot load) and has NEVER been migrated through
alembic. `boltrig-kernel-1` still runs `boltrig/kernel:0.1.0`.

So "deploy the new image and run `alembic upgrade head`" is not routine. Applying a 33-step chain to
a schema.sql-created database with no baseline is the exact destructive bug-class already on record
(a stale-schema migration dropping or recreating live tables). The cutover therefore needs a
decision made deliberately, with a verified off-box snapshot in hand, BEFORE any migration runs:

- stamp an alembic baseline matching the current schema.sql state, then upgrade forward; or
- dump the one user's data, migrate a fresh database, and reload; or
- reconcile schema.sql against the migration chain and pick the safe entry point.

`0022` (a type conversion and column removal with no automated downgrade) sits inside that chain, so
whichever route is chosen is irreversible on the real user's data and is done first, with full
context and a rehearsal on a disposable copy, not as an exhausted final step. Deferring it was the
right call; the read-only inspection turned "probably risky" into "concretely blocked until the
reconciliation route is chosen."

## The one-line answer

The thing you asked to be made safe — two tenants at once — is safe, proven, and on `main`. Of what
remains, one line is blocked by the Codex version (`production_ready`), one is the next goal (PR8),
and one is an irreversible deploy that is yours to time (prod). None of them is "is it safe for two
tenants," and that one is answered yes, with evidence.
