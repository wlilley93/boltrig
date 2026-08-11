# Handover — the Jarvis Stage body, camera, and the ui retirement, 2026-08-11

One day's arc: the branch's outstanding work was committed in coherent pieces,
a second Stage body was built and wired, the character seam was reopened so
bodies can live in plugins, and four repo gates were brought back to green.

**State at handover**: `feat/console-target` is **40 commits ahead of
`origin/main` and NOT pushed**. Nine of those commits are this session's,
`76f5157`..`9a63d58`. Worker suite 656/656. `structure`, `reachability`,
`order-directives`, `claims`, `prose-references` and `unwired-claims` all pass.
Nine files are uncommitted and belong to other sessions — leave them.

**The one remaining action**: push. It is blocked by one thing, and that thing
is not in the repository. See below.

## The blocker

`git push` runs `.githooks/pre-push`, which runs `make quality-gate`. On macOS
that dispatches into the OrbStack machine `boltrig-vm` via
`scripts/quality-gate.sh`, because seventeen of these tests assert Linux kernel
controls the host does not implement. The VM run is **3726 passed, 1 failed**.

That one failure is local state:

- the active manifest declares `module_ref: companion_plugin.adapters.companion:build`
- no such module is installed, in the VM or on the host
- `boltrig/config/manifest_apply.py` imports it while
  `boltrig/api/bootstrap.py` builds the kernel
- so the production-boot guard in `tests/security/test_round_sixteen.py` dies on
  `ModuleNotFoundError` before it can assert anything

The manifest is gitignored, so CI never sees it and this failure cannot happen
there. It is the companion/Maya work in flight.

To finish: install that module or drop its `module_ref`, then push clean. The
hook's own documented escape is `SKIP_QUALITY_GATE=1`, which leaves a trace in
the command that was typed.

**This Mac cannot push directly** — the `gh` token is invalid and the SSH key is
not registered, which is the same constraint the 2026-08-10 handovers describe.
A bare relay is already cloned on the beelink at `~/boltrig-relay.git` and the
beelink is authenticated. Push M4 → relay (that is where the hook runs), then
push relay → origin from there.

## Shipped on this branch

| commit | what |
| --- | --- |
| `76f5157` | `ui/` retired: 510 files, its harness, deploy overlay and deploy tests |
| `23238fa` | camera: UVC discovery, leases, per-model modalities, migrations 0068-0070 |
| `354acaa` | console redesign, appearance settings, the character store |
| `15baaed` | **Jarvis**: a HUD instrument body for the Stage |
| `f3d019e` | claim inventory refreshed, ratchet re-pinned |
| `709115a` | structure, reachability, order-directives and claims brought green |
| `d27a6a5` | ledgers and invariants reconciled with what landed |
| `e50bcd2` | the Stage character became a registry |
| `9a63d58` | Linux-only legs report as unverified off Linux; a real schema drift fixed |

### Jarvis

A sibling of the Familiar, not a replacement: the Familiar is a creature with a
private inner life, Jarvis is an instrument that reads the machine's measured
state. He reads three real sources — the nine-scalar phenotype, `/v1/budgets` as
two gauge tracks, and the streaming turn's tools, subagents and steps, which
energise a circuit board that is lit only where work is running.

**The rule the whole thing is built on: it never invents a reading.** No relay
means neutral scalars and the outer signal ring falls away. No ceiling, or usage
that is not computable outside a run, means a dashed ghost track and no fill — a
gauge at zero would claim "nothing spent", which is a different and more
expensive claim than "no reading". No work means a dark board. This is the one
place it diverges from the Familiar, whose renderer wanders its mood so the
creature still looks alive: a creature may idle plausibly, an instrument that
invents a reading is broken.

### The character registry

Characters were a closed union, so adding one meant editing four core files.
Core now states a contract and discovers what is installed;
`apps/worker/src/components/characters.ts` globs `./*/register.ts`. Nothing in
core names a character it does not ship, and an unregistered id resolves to the
default at render time rather than being rejected at the store — so uninstalling
a plugin costs the Stage its body and nothing else.

## Traps — things this session got wrong

- **A fix was planned for a problem the repo had already solved.** A `linux_only`
  marker was added so the suite would pass on macOS. The hook never ran that
  target; it runs `quality-gate`, which already dispatches to the VM. **Read
  `.githooks/pre-push` before touching the gate.** The marker is inert in the VM
  and only helps someone running pytest on the host directly.
- **Two `pytestmark` assignments silently drop the first.** Two modules already
  had one; adding a second would have removed their existing `skipif`. They are
  lists now, with a comment saying why.
- **A backup went stale mid-edit.** Another session rewrote a component 54
  minutes after it was copied; restoring would have destroyed 75 lines of their
  work. Re-check `git status` before staging, and never restore from a stale
  copy.
- **A false security gap was nearly reported.** A grep for one governance signal
  said a mutation bypassed approval; it uses a different one of the three. The
  SEC-75 test now uses the same three signals the feature ledger classifies by,
  so the two readers agree rather than each inventing a definition.

## Real defects found

- **Schema drift, fixed.** Migration `0068_camera_uvc_leases` creates
  `camera_bindings_owner_idx`; `boltrig/store/schema.sql` never did. A database
  built by migrations and one built by bootstrap differed, so a fresh install
  would silently lack the index the owner-bindings read depends on.
- The gauge's overrun lap was unreachable behind an early return, so 114% drew
  identically to 100% — the one case it exists to distinguish.
- A renderer called React components as plain functions, attaching their hooks
  to the caller; it passed a static render and broke on the first swap.
- An exception class was left behind when the helpers that raise it moved, so
  that error path raised `NameError` instead. No test covered it.

## Outstanding

1. **Migrations 0068-0070 must run per stack before any deploy.** The roll does
   not apply them, and the kernel already assumes that schema.
2. **There is no browser smoke test in the repo.** Retiring `ui/` deleted the
   only one. Recorded as OWED, not waived, in
   `docs/refactoring/order-binding-exemptions.json`, expiring earlier than the
   usual year end so it is revisited.
3. **Jarvis's persona is written but not installed.** The prompt fragment is in
   `apps/worker/src/components/jarvis/soul/JARVIS.md`; installing it is one
   skill upsert. Until then choosing him changes the Stage and nothing about how
   the agent writes, and the settings copy correctly does not claim otherwise.
4. **Maya stays uncommitted, deliberately.** Core is character-agnostic; moving
   her directory into a plugin is the whole migration with no core edit after it.
5. `jarvis.frag`'s single-pass path exists for the desktop GLES host and is
   protected by a parity test, but **nothing has ever run it** there.
