# Handover: offboarding, a one-way door, and the worker structural floor

`feat/real-brand-mark`, 2026-08-18. Four commits on top of the per-user
credentials work: `56e78baa`, `f72b4375`, `9c68a556`, `e565e98e`. All pushed.

This is a per-topic handover in the usual convention, not a project status. For
the credentials feature itself and the branch merge, read
[`HANDOVER-2026-08-18-per-user-integration-credentials.md`](HANDOVER-2026-08-18-per-user-integration-credentials.md);
this one covers what happened after it was written.

## The finding worth carrying to other features

Per-user integration credentials shipped with a **one-way door**, and the shape
of it is not specific to credentials.

`control.integration.connect` is declared LOW consequence, so it skips
`_preauthorize_high_consequence` in `boltrig/config/control_approval.py`
entirely, and any member may seal a personal credential — measured, `role=member`
gets a 201. `control.integration.revoke` is HIGH consequence, and that same
function gates every high-consequence `control.integration.*` verb on
`can_author` through a prefix branch over whole namespaces. So the member who
connected got a 403 revoking the row they had just made, and was left holding a
live third-party token that nothing they could reach would destroy.

Neither half is wrong on its own. The consequence is declared per verb in the
spec tables; the role check lives in a namespace branch somewhere else. **The two
ends of a lifecycle are decided by different mechanisms that do not read each
other**, so any create/delete pair split across that line can come apart the same
way. When you add or open up a create verb, exercise its delete AS THE SAME
PRINCIPAL, not as an admin.

The fix is a targeted exemption, never a wider namespace branch: the
pre-authorisation now returns early for the caller's OWN user-scoped connection,
which is operating their own seat rather than administering the organisation.
Pinned by SEC-203.

A second defect fell out of the same test. `IntegrationConnection.__post_init__`
forbade a user-scoped row that did not own its credential, which also caught the
REVOKED row — revoke clears `credential_ref` and `credential_owned` together and
rebuilds the dataclass, so every personal disconnect returned 400. It went unseen
because every pre-existing revoke test revokes an ORG row. It now forbids what it
meant to: pointing at a credential you do not own.

## Offboarding

A departed member's sealed credential used to outlive them with nothing able to
reach it: `_revoke` refuses a row that is not the caller's, and the connection
routes hide a personal row from everyone but its owner.

| Piece | Where |
| --- | --- |
| Verb | `control.integration.revoke_member`, `boltrig/config/control_integrations.py` |
| Shared write | `_perform_revoke`, same file — both verbs make it, so they cannot drift |
| Spec | `boltrig/config/control_compat_specs.py` |
| Routes | `boltrig/kernel/platform_routes/integrations.py` (`_register_member_connections`) |
| SDK | `sdks/web/src/client.ts`, `sdks/web/src/types.ts` |
| UI | `apps/worker/src/components/integrations/MemberConnections.tsx`, mounted from `apps/worker/src/components/SettingsSurface.tsx` |
| Tests | `tests/security/test_integration_scope.py` |
| Invariants | SEC-202, SEC-203, FR-INTCRED-03 |

Three decisions in it that are worth not re-litigating:

- **Two verbs, not one with a role branch.** The kernel's `InvocationContext`
  carries GRANTS and no role, so reaching the verb IS the authority — the same
  mechanism every other `control.*` verb uses. And one verb could never tell an
  auditor whether a member disconnected their own credential or an administrator
  cleaned up after them.
- **The administrator sees LESS than the member does.** The projection omits
  `accounts` entirely. That field carries the member's identity at the provider,
  routinely an email address, and administering a row is not a reason to read it.
  Widening the fence to ADMINISTER these rows must not widen it to READ them.
- **The admin list excludes the caller's own rows.** So `revoke_member`'s refusal
  of your own connection stays a fail-closed guard rather than a dead end the
  console can walk someone into.

Revocation is high consequence, so every one of these is held for approval and
the tests go through `tests/approval.py::approved_request`. The transport
collapses every `ControlConflict` onto one reason string, so the two distinct
refusals are asserted at the verb rather than over HTTP.

## The worker structural floor

`make worker-structure` had been failing since the shader-body work. Seven files
were over the 400-line TypeScript floor with no debt entry, and `ChatView.tsx`
had grown past a ratchet.

**None of it could be pinned.** `evaluateTrustedBaseline` in
`apps/worker/scripts/check-structure.mjs` independently reloads the catalogue
from the trusted Git base and refuses any metric increase — and refuses a NEW
debt file outright. So a file that has drifted over the floor with no entry
cannot be given one; it has to come back under.

What moved, all verbatim, with the reasoning travelling with the code:

- `bodyPresets.ts` 485 → `jarvisPresets` + `ultronPresets`, barrel kept.
- `bodyTuning.ts` 466 → `bodyRamp.ts` (the shared vocabulary) + one file per body.
- `glslCommon.ts` 451 → `glslField.ts` holds `FIELD_GLSL`. **The re-export is load
  bearing**: `apps/worker/tests/ultronBundle.test.ts` globs that module eagerly
  and censuses its string exports for declared uniforms, so a uniform leaving the
  namespace would leave the census silently.
- Both `drawScene` methods (166 and 126 lines) → one method per pass, then out to
  `neuralScenePasses.ts` / `ultronScenePasses.ts` as free functions. They need
  nothing from the class but the GL context and the compiled programs. **Order is
  the design** — what draws over what — and is preserved exactly.
- The frame clock and the speech ring were duplicated in both renderers and had
  already drifted in their comments → `apps/worker/src/components/canvas/bodyClock.ts`.
  Each renderer's `drive` and `palette` → `jarvisDrive.ts` / `ultronDrive.ts`.
  What genuinely differs per body stayed with the body: energy floors, onset
  caps, colour.
- `ChatView.tsx` gave back the three lines commit `737f8f1f` took without moving
  the baseline, via `apps/worker/src/components/chat/stageTurnInput.ts`.

**Regenerate the catalogue, do not hand-edit it.** The exact ratchet is two-sided,
so a file that got SMALLER fails as `stale-high` until its pin comes down, and
function debt matches on `(name, line)` so a shifted start line is its own
failure:

```sh
node apps/worker/scripts/check-structure.mjs --candidate > docs/refactoring/worker-structural-debt.json
```

That mode re-measures everything and refuses to emit a catalogue that would
self-approve debt. Every entry shares one boilerplate reason, so nothing is lost.

**Prove a shader move by measurement.** `apps/worker/tests/visual/render-bodies.mjs`
renders all four bodies offscreen in about ten seconds and prints whether
anything failed to compile — a GLSL error is otherwise silent, because the
renderer removes its canvas and the stage looks like a CSS problem:

```sh
node apps/worker/tests/visual/render-bodies.mjs --playwright /home/jellytot/pw-node/node_modules/playwright/index.mjs
```

Every figure matched before and after. **Ultron's numbers move in the second
decimal between two runs of the SAME tree**, so that is the noise floor, not a
regression — measure it twice before reading a difference as one.

## Fixed on the way, and not looked for

`apps/worker/tests/voiceLoudness.test.ts` called `normalisationGain` once PER
SAMPLE inside a map over the whole buffer. Same answer — `map` does not mutate
the array it reads — at 48000× the cost. It fitted the 5s timeout on an idle
machine and blew it on a loaded one, which read as a flaky assertion and was a
quadratic test.

## Verification

Everything runs on the beelink in `~/boltrig-fixtree`.

```sh
make python-quality      # ~19 min
make worker-quality
make quality             # the complete local gate
node apps/worker/tests/visual/render-bodies.mjs --playwright <abs path>
```

Measured at `e565e98e`: `python-quality` 4184 passed, coverage 86.60% against an
82% floor. `worker-quality` exit 0, 981/981, build clean. Every remaining
component of `make quality` green individually — `python-audit`,
`public-product-validate`, `site-quality`, `compose-validate`, `doctor-fixture`,
`migration-parity`, and all five of `security-source`.

**One caveat on those numbers.** Another session merged the Opbox-blue brand mark
into this branch afterwards (`abbc8c6a`), touching `apps/worker/src` and
recapturing the evidence. `make worker-structure` and the VDS ledger check were
re-run at that HEAD and both pass; the longer suites were not.

Playwright is deliberately not a dependency of `apps/worker`, hence the explicit
`--playwright` path everywhere above.

## What is not done

- **The branch merge.** Diagnosed and answered in the credentials handover, not
  performed. The Alembic half is proven — a merge revision naming both heads
  yields a single head and rewrites nothing — but three of the fourteen conflicts
  are semantic and belong to whoever does the merge with both changes in their
  head.
- **`workspace` is still not a credential level**, deliberately. A workspace row
  needs a live membership re-check at resolve time and `Principal.context()` sets
  no `workspace_id` on the connect path.
- **`boltrig/kernel/credentials.py` is at 399 of its 400-line ceiling.** The next
  thing added there has to be an extraction.
- **Nothing enforces any of this.** No pre-push hook is installed in this
  worktree and GitHub Actions is billing-blocked, so green gates here are a
  discipline. The worker floor had been red for a day for exactly that reason.
