# Boltrig v2 - Path to 10

> Ambition map generated 2026-07-13. A map of the *ceiling* you could commission on Boltrig
> as it stands today, grounded in the real state of the repo. Re-run to refresh the numbers.
> Target: `~/Projects/boltrig` (this repo IS "v2" per `docs/decisions/0011-boltrig-v2-memory-topology.md`).

---

## 1. Rubric - what 10/10 means here

Boltrig is a governed agent-orchestration **kernel + fleet + console**, not a CRUD app. Score it on six axes:

| Axis | 10/10 bar | Today (grounded) | Source |
|---|---|---|---|
| **Kernel correctness & invariant debt** | Binding-invariant gate at **debt 0**, green in required CI | **RED: 5 binding debts** (2x SEC-138, FR-OPS-04, ...) on the working tree | `make invariants` (2026-07-13) |
| **Structure / size ratchets** | All ratchets at or below baseline, no over-limit fns | **RED: 10 violations** - `store/postgres.py` 2386 lines, `store/memory.py` 1093, `store/base.py` 540, `dispatch.invoke` 116/80 | `make structure` |
| **Security posture** | 0 crit / 0 high / 0 med, deploy-hardened | **0 crit, 0 high, 4 med, 7 low, 1 info** (CI mutable tags, IaC, input) | `.skillops/runs/security-suite/findings.md` (2026-07-04) |
| **Landed vs stranded** | Working tree clean; every merge on `main` and pushed | **234 uncommitted paths** (133 modified, 100 untracked) since last commit **2026-07-06** - a full week unlanded | `git status` |
| **Architecture bets finished** | Memory v2 fanout live; external seams real | Memory v2 topology **decided 2026-07-09** (Mem0 primary, Cognee secondary, kernel ledger SoT) but seams scaffolded: live Hatchet, live OIDC IdP, adapter creds, on-box model | `README.md` "Implemented vs scaffolded", decision 0011 |
| **Product surface polish** | Every console panel best-in-class + tested | ~24 UI panels built; code is clean (1 TODO, 16 `type: ignore`, 136 test files) but polish/parity uneven | `ui/src/panels`, grep |

**Headline:** the engine is strong and clean. The gap is not unimagined work - it is (a) a **week of work stranded uncommitted on a red gate**, and (b) two half-finished architectural bets (memory v2, the external seams). Ambition here means *landing and finishing*, then raising each surface.

---

## 2. The program (tiers, highest leverage first)

### Tier 0 - Land the week and go green (ship-stopper)
This is the single biggest lever and it blocks honest measurement of everything else.
- **T0.1** Triage the 234-path working set: separate coherent features (memory v2, UI panels, control-plane, security batches) into reviewable commits; land them. `[workflow]`
- **T0.2** Drive `make invariants` back to **debt 0** - resolve the 5 binding debts (each is a claimed invariant without a passing test: 2x SEC-138 durable-resume snapshot binding, FR-OPS-04 backup-restore, control-approval binding). `[solo]`
- **T0.3** Clear the 10 structure violations - lower stale ratchets, split the over-limit `Dispatcher.invoke` and `InMemoryStore.__init__`. `[solo]`
- **T0.4** Commit, push, and open/merge the PR so the fix actually reaches `main` (nothing is "done" stranded on a local branch). `[solo]`

### Tier 1 - Baseline hardening
- **T1.1** Close the 4 medium security findings: pin CI actions to SHAs (FIND-CI-001), IaC hardening (FIND-IAC-001), input validation (FIND-INP-002), and the CI hygiene item (FIND-CI-002). Then the 7 lows. `[solo]`
- **T1.2** Structural burndown of the three giant store modules (`postgres.py` 2386, `memory.py` 1093, `base.py` 540) into cohesive units without touching the one-dispatch-chokepoint contract. `[workflow]`

### Tier 2 - Finish the architecture bets
- **T2.1** Take **memory v2** end to end: implement/verify the kernel-led fanout (Mem0 primary projection, Cognee secondary graph enrichment, native engines as fallback), all through `memory.*` verbs, with the invariant tests that make the topology binding. `[workflow]`
- **T2.2** Make the **external seams real, one at a time**: live Hatchet engine, live OIDC IdP, a real third-party adapter with credentials, and an on-box sensitive-model route - each behind its existing seam with a live-check test. `[workflow]` (each seam gated on a Principal-supplied dependency: engine host, IdP, creds, on-box model - route around, land what is unblocked)

### Tier 3 - Product ambition (per surface)
Raise each console surface to best-in-class. See the Arsenal for paste-ready asks.
- Chat, Automations/Workflow canvas, Agent Studio/builder, Approvals (HITL), Memory panel, Admin/control-plane, Insight+Eval observability. `[workflow]` each

### Tier 4 - Keep it honest
- **T4.1** Marketing site + docs guide parity with the shipped engine. `[solo]`
- **T4.2** Re-run this board and the security suite after Tier 0-2 to refresh every number. `[solo]`

---

## 3. The arsenal - highest-altitude ask per surface

Paste-ready. Each is an outcome ask, not a tweak.

**Engine room**
- **Kernel / dispatch chokepoint** - "Drive the binding-invariant gate to debt 0 and keep the single dispatch chokepoint (`kernel/dispatch.py`) the only path; prove every K-* and SEC-* invariant has a passing test. Land it green."
- **Registry (nouns/verbs) & grants** - "Audit the noun/verb registry and grant enforcement for completeness against the doctrine's capability primitive; converge on the unified primitive, propose the spec, then implement. Don't stop to ask."
- **Fleet runtime & spawn** - "Bring the permanent-fleet/ephemeral-spawn model to a coherent best-in-class: budget reservation, cheapest-capable runtime selection, recursion-depth enforcement; add the missing tests and land it."
- **Memory (v2 topology)** - "Take Boltrig v2 memory end to end per decision 0011: kernel ledger as SoT, Mem0 primary projection, Cognee secondary enrichment, native fallback, all through `memory.*` verbs. Make the topology binding with invariant tests."
- **Store / Postgres persistence** - "Refactor the three oversized store modules (`postgres.py`, `memory.py`, `base.py`) into cohesive units, clear the structure ratchets, keep persistence guarantees and migration parity intact."
- **Workflows / durable HITL** - "Harden durable execution and HITL pauses: fix the SEC-138 snapshot-binding debts, guarantee approved-snapshot execution and cross-workspace replay rejection, prove it with the live durable-resume suite."
- **Identity / OIDC seam** - "Make first-party login and real OIDC a live, tested path against an actual IdP; propose the config seam, then wire and verify it."
- **Adapters / models / routing** - "Land a real third-party adapter and the sensitive->local model route as live seams with live-check tests; adding an integration must still change no core code."
- **MCP face & Pi sidecar** - "Prove the MCP tool face and the sandboxed Pi sidecar end to end: every `tools/call` runs the full chokepoint, the sidecar has no native tools or credentials (SEC-24/27), and it degrades offline."
- **Observability / audit** - "Bring audit, cost accounting, and run observability to a best-in-class operator view; make every dispatched verb traceable and every cost attributable."

**Console surfaces (`ui/src/panels`)**
- **Chat** - "Bring the Chat panel to a coherent, best-in-class conversational surface: reasoning/tool/sub-agent/inline-HITL streaming, owner-scoped persistence, resilient reconnection. Propose the spec, then build it end to end."
- **Automations / Workflow canvas** - "Make the automations + workflow-canvas surface best-in-class: real run stats, `flow.loop`/control-flow fidelity, run-record persistence, live run view. Land it."
- **Agent Studio / builder** - "Bring the agent builder/studio to a best-in-class authoring surface for defining fleet agents, capabilities, and bindings without editing code."
- **Approvals (HITL)** - "Make the approvals panel the definitive HITL operator surface: pause/resume, snapshot-bound approvals, tamper rejection surfaced in the UI."
- **Memory panel** - "Bring the memory panel to a best-in-class recall/inspection surface over the v2 fanout (ledger + Mem0 + Cognee), with provenance."
- **Admin / control-plane** - "Bring the admin/control-plane surface to a coherent best-in-class fleet-and-tenant control view; propose the IA, then build it."
- **Insight + Eval** - "Make the insight/eval panels a best-in-class quality-and-cost observability surface for fleet runs."

**Cross-cutting systems**
- **Security posture** - "Close all 12 open findings (4 med, 7 low, 1 info), pin CI to SHAs, and re-run the full security suite to a clean 0/0/0. `[workflow]`"
- **CI / release gates** - "Make `make quality` the whole truth: green invariants, structure, typecheck, lint, tests, UI/site e2e, migration parity, and security-source, enforced in required CI."
- **Deploy / ops** - "Prove the secure production overlay + doctor + backup/restore end to end for a real prod cutover per `PROD-CUTOVER-RUNBOOK.md`."
- **Marketing site + docs** - "Bring `site/` and the docs guide to parity with the shipped engine; nothing documented that isn't real, nothing real that's undocumented."
- **Design system / tokens** - "Consolidate the UI design tokens/kit into one coherent system across all 24 panels."

---

## 4. Where to start

**The single highest-leverage, lowest-ambiguity move: Tier 0 - land the week and go green.**

There is a full week of work (234 uncommitted paths since 2026-07-06) sitting on top of a
**red invariant gate (5 debts) and a red structure gate (10 violations)**. Until that lands,
every other number on this board is measured against an unlanded tree, and by the repo's own
governance (binding-invariant gate at debt 0 in required CI) the work is not "done."

Concretely, first move:
1. Triage the working set into coherent commits (memory v2 / UI / control-plane / security).
2. Resolve the 5 binding debts and 10 structure violations so `make invariants` and `make structure` go green.
3. Push and merge to `main`.

Then re-baseline and pick up Tier 2 (finish memory v2 + the external seams).

**Say the word and I'll take the first move now: triage the 234-path working set and drive both gates back to green.**
