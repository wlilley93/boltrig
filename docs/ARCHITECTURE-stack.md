# Boltrig as a stack - the four pieces, the boundary, and the split trigger

> **Runtime currency (2026-07-21):** this disposition describes the stack that
> existed when it was written. Decision 0012 now makes Codex the only target
> agent runtime. The Pi container and other legacy runtime references below are
> implementation history and staged-cutover residue, not the target stack.

A disposition record. The question raised: should Boltrig be split into four
distinct `boltrig-[piece]` units (kernel / frontend / database / agent-runtime)?

This is a consolidation/split fork, governed by the SPEC-LAW-3 three-gate test
(single-source / demonstrated-need / severability) and the
consolidation-over-fragmentation steering principle. It was routed through the VJS
realm: `vjs route` returned **AllowedWithConditions, court_required=false,
log_required=true** (permit `PERMIT-1782822939`, basis `ACT-COMPUTER-FIRST-REALM:s11`
- the kernel is clerk not court, no court trigger fires), and the disposition below
is recorded as binding decision log **LOG-2026-06-30-123606**. It is not a court
matter; it is a routable implementation decision, disposed here against the
ground-truthed code.

## The finding: Boltrig is already a stack with enforced layer boundaries

The four pieces exist today as clean, measured layers, and deploy as four distinct
containers. Splitting the *repo* is not what makes Boltrig a stack - it already is
one.

| Piece | Lives in | Deploy unit (docker-compose) | Measured coupling |
| --- | --- | --- | --- |
| **kernel** (policy core) | `boltrig/kernel` + `boltrig/models` | `kernel` service | imports only the `Store` **Protocol**, never an implementation |
| **database** (persistence) | `boltrig/store` + `schema.sql` + `migrations` | `postgres` + the store impls | **0** imports from kernel/fleet (inverted) |
| **agent-runtime** (the fleet) | `boltrig/fleet` | `fleet-worker` | the Pi sidecar that sat here is retired (decision 0020); `services/channel_gateway` is the remaining severed sidecar, HTTP-only, SEC-28 tested |
| **frontend** | `apps/worker/` | `ui` service | Worker web/Tauri client + build |

Dependency direction is already correct and inverted at the contract: kernel
depends on the `Store` Protocol (not the DB); the runtime depends on kernel
contracts; `models` is a 0-coupled foundation; the channel sidecar imports nothing from
the package and is reached only over the wire. The severability gate of a split is
therefore already PASSED and machine-enforced (`tests/security/test_severability.py`,
SEC-28).

## The disposition: defer the repo-split, formalise the stack in-repo

Under the three-gate test, ground-truthed:

- **Severability: PASS** (proven above).
- **Single-source: FAIL today.** All four pieces share `boltrig/models` + the
  `Store`/`Adapter` Protocols + the event shapes. A 4-repo split duplicates those
  unless a fifth `boltrig-contracts` package is extracted first. Splitting now breaks
  single-source.
- **Demonstrated-need: WEAK today.** Independent deployment already exists at the
  container level. Independent release cadence / separate team / an external
  consumer of one piece - the real reason to pay the multi-repo tax - is not present;
  it is one product built in lockstep rounds behind one green gate.

Two of three gates are not met. The ruling: **the stack model is affirmed; the
repo-split is deferred, not rejected.** Keep one repo and one invariant gate; make
the four boundaries first-class and enforced; extract the shared-contract seam a
future split would cleave along. Split for real only when demonstrated-need arrives.

## The lawful intermediate (what to do now)

1. **Name the four pieces as the canonical architecture** (this document + the
   system overview). The stack is real; treat it as the mental model and the
   deploy model.
2. **Keep the boundaries enforced.** SEC-28 already forbids kernel/models coupling
   to the runtime. Extend the severability test to assert the layer dependency
   rule explicitly: `models` depends on nothing; `store` depends only on `models`;
   `kernel` depends only on `models` + the `Store` Protocol; `fleet` may depend on
   `kernel`; nothing depends on the frontend implementation. A boundary breach fails the gate.
3. **Identify the shared-contract seam** (`boltrig/models` + the `Store`/`Adapter`
   Protocols + the event-shape definitions). This is the future `boltrig-contracts`
   package and the line a repo-split would cut along. Keep it cohesive and
   dependency-free so the cut stays cheap.

## The split trigger (when to actually split repos)

Revisit and convene the court to split a piece into its own repo when ANY holds:

- **Release cadence diverges:** a piece needs to ship on its own schedule (e.g. the
  frontend releasing independently of the kernel).
- **A separate consumer appears:** something outside Boltrig wants to depend on one
  piece alone (e.g. the kernel as an embeddable library, or the contracts package
  consumed by a third party).
- **Ownership diverges:** a distinct team owns a piece end to end.
- **The shared-contract seam is already extracted and stable**, so the split no
  longer risks single-source.

Until then, the multi-repo tax (cross-repo versioning, a split CI/invariant gate,
contract drift) buys nothing the container-level separation does not already
deliver. One repo, four enforced layers, four deploy units: the stack, without the
fragmentation.
