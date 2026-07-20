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
  (VJS-CC-VJS 7, enacted). The adversarial gate passes as a recorded test: hostile cell A, with full
  write access to everything its uid can reach, cannot reach cell B's `config.toml` by any of nine
  routes, and the API itself is never privileged.

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

### 3. The prod cutover — APPROVED, deferred with cause

The Principal's go is banked. It is not started at a session's tail because it is a ~500-commit jump
whose Alembic chain includes `0022`, a type conversion and column removal with **no automated
downgrade**, on live customer data. The runbook (`PROD-CUTOVER-RUNBOOK.md`, Path A) mandates a
verified off-box snapshot and a restore rehearsal first. This is done first, with full context, not
as an exhausted final step. Deferring an irreversible migration is the right call, not reluctance.

## The one-line answer

The thing you asked to be made safe — two tenants at once — is safe, proven, and on `main`. Of what
remains, one line is blocked by the Codex version (`production_ready`), one is the next goal (PR8),
and one is an irreversible deploy that is yours to time (prod). None of them is "is it safe for two
tenants," and that one is answered yes, with evidence.
