# Boltrig console - Enhancement Charter

> The steering + brakes for the Fable run. Pairs with `docs/PATH-TO-10.md` (what to ask) and
> `docs/design/DESIGN-DECISIONS.md` (what is protected). Generated 2026-07-13.
> Governs *executing* the PATH-TO-10 Tier-3 surface asks so deliberate design intent survives.

---

## 1. Screen scorecard - what Fable improves first

Leverage = (usage x strategic weight x quality gap) / effort. Grade is distance from the
console's own DESIGN-v2 / pattern-language bar. Structure status: **settled** (IA is decided,
work is polish/enhance) vs **open** (IA still in flux, may need a spec + sign-off).

| Rank | Surface | Strategic weight | Grade | Structure | Altitude allowed | Notes |
|---|---|---|---|---|---|---|
| 1 | **Chat** | Flagship + default landing; the L2 reference client | B+ | settled (full spec exists) | Enhance | Build to the written chat surface spec; streaming/HITL correctness is no-rewrite |
| 2 | **Automations / Workflow canvas** | Core product loop | B | settled | Enhance | Real run stats already wired; finish run-record fidelity + `flow.loop` UI |
| 3 | **Approvals (HITL)** | Governance-critical; where D6/D7 live | B- | settled | Enhance | Must render the AMENDMENTS approval contract exactly; smallest tolerance for drift |
| 4 | **Agent Studio / builder** | Authoring surface for the fleet | B- | open | Restructure (spec first) | IA for defining agents/capabilities/bindings not fully settled |
| 5 | **Memory panel** | The v2 architectural bet (decision 0011) | C+ | open | Restructure (spec first) | Depends on the Mem0/Cognee fanout landing; provenance IA is new |
| 6 | **Admin / control-plane** | Operator control | C+ | open | Restructure (spec first) | Fleet/tenant control IA to be proposed |
| 7 | **Insight + Eval** | Quality/cost observability | C | open | Restructure (spec first) | New surface shape |
| 8 | **Settings** | Config | B+ | settled (D12/D13) | Polish/Enhance | Recently reworked to a page; hold the line |
| 9 | Home, Channels, Me, DevConsole, CommandPalette, Router, Registry, Kanban | Secondary | B/B- | settled | Polish/Enhance | Token/consistency/a11y sweeps; no IA changes |

**Order of the run:** 1 -> 2 -> 3 first (all *settled*, so Enhance-altitude, no sign-off wall),
then a spec gate before 4 -> 7 (all *open*). Polish sweep (row 9) can run in parallel any time.

## 2. Structure status legend
- **settled** - information architecture is decided and in a spec/canon. Fable may Polish and
  Enhance freely; Restructure still needs a spec.
- **open** - the mental model / data flow is not finalised. Any real improvement is a
  Restructure, which is gated: propose the spec, get sign-off, then build.

## 3. Change-altitude ladder - how far Fable's autonomy goes

Every change sits on a rung; the rung sets the gate. Escalation trigger, one question:
*does this alter something in DESIGN-DECISIONS.md, or the way the screen thinks?* If yes, gate up.

| Rung | What it is | Gate for the Fable run |
|---|---|---|
| **Polish** | tokens, spacing, consistency, a11y, dead code, copy fixes | Just do it. No sign-off. Must obey D8/D9/D11. |
| **Enhance** | rework a component/interaction *within* the existing IA | Decisive call + a one-line work-log note - **unless** it touches a CANON-LOCKED row (then challenge protocol). |
| **Restructure** | change a screen's IA, mental model, or data flow | **Propose the spec first, get sign-off, then build.** This is the line where enhancement becomes total change. Required for every *open* surface above. |
| **Rewrite** | throw away and rebuild | Explicit Will decision only. Everything on the no-rewrite list is **off the table** - strangler-fig instead. |

Land every change as a small reviewable diff. No big-bang panel replacement (it destroys the
ability to say "keep mine").

## 4. Challenge protocol - how Fable's better ideas win

When Fable believes a locked or existing choice is wrong, it does **neither** of the two
failure modes: not silent "fix" (wash-away), not silent obey (wastes a possibly-better idea).
It puts the alternative as a **proposal with the case for it**; Will decides.
- **Accepted** -> update DESIGN-DECISIONS.md to the new canon.
- **Rejected** -> write it into DESIGN-DECISIONS.md with the "why", so it is never re-litigated.

For this repo the protocol has a formal home: a genuine first-impression design fork goes to
the **VJS court**, not to Will directly (per the standing governance). A reversible low-blast
call is a decisive call + a one-line note. Check the citator first.

## 5. Fable-run readiness checklist

Before handing the run to Fable, all green:
- [x] Ambition mapped -> `docs/PATH-TO-10.md`
- [x] Locked decisions recorded -> `docs/design/DESIGN-DECISIONS.md` (D1-D11 canon; **D12-D15 await Will's ratify**)
- [x] No-rewrite list drawn
- [x] Scorecard + altitude ladder + challenge protocol -> this file
- [ ] **Will ratifies D12-D15** (four inferred decisions)
- [ ] **Tier 0 landed first** - the 234-path working set committed and both gates green, so
      Fable starts from a clean, measurable tree (a Fable run on a red tree measures nothing)
- [ ] Each surface ask phrased with `fable-safe-prompt` before sending (layer 3)

## 6. The prime directive handed to Fable
> Improve surface by surface, top-down by leverage. **Read `DESIGN-DECISIONS.md` first.** Polish
> and Enhance freely within the IA; for anything on an *open* surface or that touches a
> CANON-LOCKED row, propose the spec/alternative with its case and wait for sign-off. Never
> rewrite a no-rewrite surface. Land small reviewable diffs. Keep the invariant + structure
> gates green on every commit. Don't stop to ask on Polish/Enhance; do stop on Restructure.
