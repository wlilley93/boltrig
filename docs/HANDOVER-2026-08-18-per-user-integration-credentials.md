# Handover — per-user integration credentials

Date: 2026-08-18

## Outcome

- An organisation has one shared connection per integration and any member may
  connect their own; a personal credential wins for that person's calls and the
  org's serves everyone else.
- Resolution is own -> org -> the env/manifest binding, gated by a new org flag
  `allow_own_integration_credentials`. With the flag off a user row is skipped
  ENTIRELY, so revoking the policy is sufficient on its own and turning it back
  on restores the personal credential with no row surgery.
- The scope is sealed into the credential and compared on read, so a connection
  pointing at another scope's sealed row fails closed.
- The connection list, the health route and the revoke route are fenced on
  ownership. A row the caller may not see answers `not_found`, never `forbidden`.
- The Plugins page offers the scope choice and says whose credential each
  connection is.
- Four commits on `feat/real-brand-mark`, pushed, ending at `2a72358a`.
- `make python-quality` passes: 4179 tests, 0 failures, coverage 86.59% against
  the 82% floor. `make worker-quality`'s test leg is 981/981.

This is a working feature behind an org policy that defaults to off. It is NOT
reachable by the `member` role yet (see "What is not done").

## READ THIS FIRST: the branch collides with `capability-doctrine-001`

Both branches added a migration `0077` and a `0078` from the same parent, so
merging them produces **two Alembic heads** and `alembic upgrade head` will
refuse.

```text
merge-base e79e64b7, both at 0076_typed_memory_ledger

feat/real-brand-mark      0076 -> 0077_trajectory
                                  -> 0078_scoped_integration_connections
capability-doctrine-001   0076 -> 0077_audit_outbox
                                  -> 0078_capability_presentation_fields
                                  -> 0079_capability_routing_shard
```

Both first migrations carry `down_revision = "0076_typed_memory_ledger"`.

**`capability-doctrine-001` is the side that should re-parent**, because this
branch is already on origin and that one is local and unpushed. Concretely: set
`0077_audit_outbox`'s `down_revision` to `0078_scoped_integration_connections`,
renumber its three files, and set `EXPECTED_ALEMBIC_HEAD` in
`boltrig/api/readiness.py` to the new head. That constant is a strict equality
check, so a merge that leaves it naming the wrong revision makes readiness
report unhealthy rather than failing loudly.

`boltrig/store/schema.sql` was edited on both sides and will conflict textually.
`make migration-parity` is the check that the merged result is coherent; it
compares the Alembic head against `schema.sql` on a disposable Postgres and runs
in a few seconds.

## Where it lives

| Piece | Where |
| --- | --- |
| Migration | `migrations/versions/0078_scoped_integration_connections.py` |
| Scope on the row | `boltrig/models/integrations.py` (`INTEGRATION_SCOPE_LEVELS`) |
| Precedence | `boltrig/kernel/integration_scope.py` |
| Resolution | `boltrig/kernel/credentials.py` (`resolve_for_adapter`) |
| Sealed-scope fence | `boltrig/kernel/integration_credentials.py` |
| Store, both twins | `boltrig/store/integration_atomic.py`, `boltrig/store/integrations.py` |
| Governed connect/revoke | `boltrig/config/control_integrations.py` |
| HTTP routes | `boltrig/kernel/platform_routes/integration_setup.py`, `boltrig/kernel/platform_routes/integrations.py` |
| UI | `apps/worker/src/components/integrations/ManualSecretSetup.tsx` |
| Tests | `tests/security/test_integration_scope.py` (13) |
| Invariants | SEC-200, SEC-201, FR-INTCRED-01, FR-INTCRED-02 |

An org row's `scope_id` IS the tenant id, derived in `__post_init__` rather than
demanded, which is why every caller that predates scoping still constructs a
valid connection untouched.

## Three traps, each of which cost real time

**`on_behalf_of` is None for a person logged in directly.** It names the human an
AGENT is acting for; `boltrig/identity/sessions.py` builds the Principal without
it. The first commit resolved credentials by that field alone, so a personal
credential was sealed under the user id and looked up under nothing — resolution
fell through to the org credential with no error anywhere, and the feature would
have looked correct while doing nothing. Both sides now derive
`on_behalf_of or actor`; `acting_owner` is its single definition and
`tests/security/test_integration_scope.py` pins it to dispatch so they cannot
drift apart.

**A backfill against a FORCE-RLS table silently updates zero rows.** During a
migration `app.tenant_id` is unset, the policy predicate is NULL, and a
non-bypassing role matches nothing. It works today only because the compose
default connects as a superuser. `SET LOCAL row_security = off` is the first
statement of the upgrade. A `SELECT count(*)` self-check cannot detect this — it
reads 0 for the same reason.

**The sealed-scope check tolerates a missing level, deliberately.** Every
credential already in production was sealed before the field existed, the value
sits inside a Fernet envelope so no migration can reach it, and a strict
comparison would raise on every dispatch for every existing tenant — an outage,
not a fence. Absent level means legacy means org, following the precedent in
`boltrig/store/sealing.py`. Do not copy `owner_matches` from
`boltrig/kernel/run_scoped_credentials.py`, which refuses on absence; it can
afford to because run-scoped rows are swept at run terminal.

## Verifying it

Everything runs on the beelink in `~/boltrig-fixtree`, which is a git worktree of
`~/Projects/boltrig` and shares its object store.

```sh
make migration-parity     # Alembic head vs schema.sql, seconds
make python-quality       # the whole Python gate, ~16 min
cd apps/worker && pnpm run test
```

The visual capture binds a digest over `apps/worker/src` read from the git
INDEX, so any change there must be staged and then recaptured, or
`make visual-evidence` fails:

```sh
git add apps/worker/src
node apps/worker/tests/visual/capture-current.mjs --additive-evidence \
  --timeout-ms 45000 --playwright /home/jellytot/pw-node/node_modules/playwright/index.mjs
node apps/worker/tests/visual/capture-current.mjs --evidence \
  --timeout-ms 45000 --playwright /home/jellytot/pw-node/node_modules/playwright/index.mjs
.venv/bin/python apps/worker/tests/visual/compare-current.py
.venv/bin/python scripts/regen_vds_route_manifest.py
vds ledger screens
vds ledger routes --from docs/design/evidence/2026-08-11-console-parity/current/vds-route-manifest.json
```

Playwright is deliberately not a dependency of `apps/worker`, hence the explicit
path.

## Done since, in commit 56e78baa

Three things this document listed as open, and one it got wrong.

- **A member could connect a credential they could never destroy.** Worse than
  "cannot reach the feature", which is what the first draft of this section said:
  `control.integration.connect` is LOW consequence, so any member may connect at
  `level=user` -- measured, `role=member` gets a 201 -- while
  `control.integration.revoke` is high consequence and
  `_preauthorize_high_consequence` gates every high-consequence
  `control.integration.*` verb on `can_author`. So the same member got a 403
  revoking the row they had just made. The pre-authorisation now exempts exactly
  one case, the caller's OWN user-scoped connection, which is operating their own
  seat rather than administering the organisation (SEC-203).
- **Org-admin offboarding exists.** `control.integration.revoke_member`, with
  `GET`/`DELETE /v1/integrations/member-connections` and a panel in
  Settings > Organisation. Two verbs rather than a role branch inside one,
  because the kernel context carries GRANTS and not a role, and because one verb
  could not tell an auditor which of the two things happened. The administrator's
  projection omits `accounts` (SEC-202, FR-INTCRED-03).
- **The borrowing guard 400'd every personal disconnect.** `__post_init__` said a
  user-scoped row "must own its credential", which also caught the REVOKED row --
  revoke clears `credential_ref` and `credential_owned` together and rebuilds the
  dataclass. Every existing revoke test revoked an ORG row, so nothing saw it.

## What is not done

- **Health is per-adapter, and that is correct.** An earlier draft of this
  section called it a gap. It is not: `HttpAdapter.health` is documented "Best-
  effort reachability probe. Never raises; needs no credential", so the column
  has always meant "is the provider reachable" and never "is this credential
  good". Two rows for one adapter therefore show the same health, which is
  honest but easy to misread as a claim about the credential. Making it a claim
  about the credential needs a credentialed probe protocol that no adapter has.
- **`workspace` is not a level.** `ai_configs` has one; this does not, because a
  workspace row needs a live membership re-check at resolve time and
  `Principal.context()` sets no `workspace_id` on the connect path. The
  `CHECK (level IN ('org','user'))` constraint means adding it later costs a
  migration — a deliberate choice, since the table already constrains `health`
  the same way.

## Debt found on the way, and not in the way

`boltrig/kernel/credentials.py` sits at 399 of its 400-line ceiling. The next
thing added there has to be an extraction.

The worker structure gate was red from the earlier shader work in this same
session, and is green again as of f72b4375: the seven canvas and shader files
were split rather than pinned, and `ChatView.tsx` gave back the three lines
commit 737f8f1f took without moving the baseline. Nothing there could be waived —
`evaluateTrustedBaseline` in `apps/worker/scripts/check-structure.mjs` reloads
the catalogue from Git and refuses a new debt file outright — so every one of
them had to come under the limits. The moves are verbatim and
`tests/visual/render-bodies.mjs` measured all four bodies before and after.

No pre-push hook is installed in this worktree (`core.hooksPath` is unset and the
shared git dir carries none), so none of that blocks a push. Combined with
GitHub Actions being billing-blocked, green gates here are a discipline rather
than something enforced.

## The beat after this one, probably superseded

The agreed next step was to pass the provider as a variable in the call input and
let the model see which adapters are loaded under a verb. Scouting turned up the
obstacle: `KernelRegistry._register_spec` in `boltrig/kernel/registry.py` is
last-write-wins for adapter-over-adapter and silently discards the losers, so
nothing records that several adapters claimed one verb.

`capability-doctrine-001` appears to solve the same problem from the other end,
with a second binding table and a router consulted when the invoked name is not a
stored verb. **Read that branch before starting any provider-selection work
here** — the two designs overlap and the plan in this repository predates it.
