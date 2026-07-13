# Chat surface - enhancement proposals (2026-07-13)

> Output of an Enhance-altitude gap analysis (chat.md spec vs the built surface), governed by
> `../ENHANCEMENT-CHARTER.md` and `../DESIGN-DECISIONS.md`. The Chat surface is **mature and
> deliberately "v3"** (a multi-agent rail), so most spec deltas are the surface's intentional
> divergence from the older single-orchestrator spec, not defects. This board records the
> **challenge-protocol proposals**: changes that need sign-off before an autonomous edit, so
> the v3 authorial intent is not washed away by blind spec-conformance.

## Already applied (zero-risk polish, charter "just do it")
- Conversation rail width 260 -> **280px** (spec chat.md:35). `ui/src/styles.css` `.chat-agent-rail`.
- Conversation header height 45 -> **44px** (spec chat.md:23/66). `ui/src/styles.css` `.chat-header`.
- (Verified NOT a gap: the Send button already carries `aria-label="Send"`, `ComposerParts.tsx:178`.)

Verified green: ui `tsc --noEmit` clean, `make ui-e2e` 8/8.

---

## Proposals needing a decision

Ranked by leverage. Each names the altitude gate from the charter ladder. **Nothing below was
applied autonomously** because each either touches a CANON-LOCKED decision, the no-rewrite
pipeline, the shared deck engine, or the deliberate v3 rail IA.

### P1 - Reading measure 720 -> 860px `[polish, but visible + 7 selectors]`
The transcript content column, composer and statusline center at `min(720px,100%)` across seven
`ui/src/styles.css` selectors; the spec names **860px** three times (chat.md:26/36/75). A verifier
confirmed 720 is unrecorded drift from the imported console UI kit, not a locked decision. Held
because it is the most visible change and spans 7 selectors (3 verified): a one-word yes sweeps
them (ideally to a single `--chat-measure` token); a no records 720 as the deliberate v3 measure.

### P2 - Active conversation is never marked in the rail `[enhance]`
Active state is hardcoded off, so the rail gives no feedback for which conversation is open.
Adding an active-row treatment improves the v3 rail without changing its IA. Held only because it
requires wiring the rail's selection state (medium effort) - low risk, high value, recommended.

### P3 - Inline HITL approve/reject is single-click; console uses an ArmConfirm ritual `[enhance, NO-REWRITE + D6/D7]`
The chat inline HITL card submits a decision on one click; the console `PendingHumanCard` uses an
arm-then-confirm ritual and the full section-5c anatomy/copy. Aligning them is good consistency,
but it touches the **CANON-LOCKED governed-write / approval contract (D6/D7)** and the no-rewrite
`chatTurn*` HITL pipeline. Needs sign-off (challenge protocol), not an autonomous edit.

### P4 - Stream state is component-local, not a module store `[restructure, NO-REWRITE, D2]`
`liveEvents/streaming/stopped/streamError/abortRef` live in React `useState`, not the
`ui/src/chatStream.ts` module store. D2 (keep-alive) means slides are CSS-hidden not unmounted, so
state survives in practice; the residual risk is a hard remount aborting an in-flight stream. This
is a restructure touching the no-rewrite stream pipeline -> sign-off required.

### P5 - Off-screen completion signal absent `[enhance, NO-REWRITE]`
No unseen flags / store-driven cyan pulse on the sidebar map when a response completes off-screen
(spec section 7). Depends on P4 (needs the module store to drive cross-slide signals). Sign-off.

### P6 - The v3 multi-agent rail vs the spec's single date-grouped rail `[restructure, THE fork]`
The built rail is a multi-agent grouped sidebar (agent rows -> per-agent history, All/Unread tabs);
the spec (chat.md:39-52) describes a single chief-of-staff rail with Today/Yesterday/This week/
Earlier date grouping. This is the deliberate v3 IA direction. **Genuine first-impression fork:**
reconcile the spec to bless v3, or the rail back to the spec. Not an autonomous edit - this is a
`not my call - the court` item (design fork), per the standing governance.

### P7 - Responsive rail collapse: 860px breakpoint / z-index 14 vs spec 900px / z-index 30 `[enhance, NO-REWRITE tokens]`
Mechanism matches the spec (absolute slide-over) but the named breakpoint (900px) and overlay
z-index (30, still below drawer 70 / palette 80) differ, and collapse is toggle-driven rather than
auto at the breakpoint. Small, but entangled with the v3 rail's responsive model. Recommend
bundling with a P6 decision.

### P8 - Breadcrumb chip reads "Chat / Chat - 1 of 1" `[polish, SHARED DECK ENGINE]`
`ui/src/deck/DeckSlide.tsx:25-26` duplicates the row/col label for the single-anchor chat row;
spec wants "Chat - 1 of 1". A one-line conditional fix, but it lives in the **shared deck engine**
(no-rewrite, affects every surface's breadcrumb), so it is flagged rather than edited in place.

### P9 - Rail search behind a toggle; no `/` focus shortcut; dead legacy `vh` caps `[polish]`
Minor: rail search is toggle-hidden rather than always present; no `/` shortcut to focus it (must
respect the deck chord guardrail so it never fires in inputs); and the legacy `.chat__rail{max-height:70vh}`
/ `.chat__messages{max-height:60vh}` caps are overridden-dead rather than deleted. Dead-rule
removal in a 7,000-line cascade has non-obvious blast radius, so it is proposed, not swept.

---

## Recommendation
Greenlight **P1 + P2** (visible-but-safe measure alignment + the active-row marker) for an
immediate Enhance pass; route **P6** (the rail IA fork) to the court; hold **P3-P5** behind a
deliberate HITL/stream-store work item since they touch CANON-LOCKED contracts and the no-rewrite
pipeline together.
