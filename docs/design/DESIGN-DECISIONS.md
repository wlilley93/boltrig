# Boltrig console - Design Decisions record

> The locked-constraints ledger for the console. **Locked = enhance around it, never silently
> overturn it. Not listed = fair game.** Generated 2026-07-13 for the Fable run.
>
> Two classes of entry:
> - **CANON-LOCKED** - already binding in a committed doctrine doc (DESIGN-v2, the pattern
>   language, AMENDMENTS, tokens). Ratified by virtue of being enacted. Fable inherits these.
> - **INFERRED (ratify)** - read out of the code/specs by this pass. **Will ratifies each
>   before it binds Fable.** A record that guesses intent is worse than none, so these are
>   marked pending until confirmed.

---

## CANON-LOCKED (already binding - do not re-litigate)

| # | Locked decision | Source of law |
|---|---|---|
| D1 | **Spatial deck, not tabs.** Surfaces are slides on a 2D deck (rows/columns), navigated by Ctrl+Alt+Arrow chord + breadcrumb chip. Chat is the top-left anchor and default landing (`#/chat`). | `DESIGN-v2.md` (frozen deck mechanics) |
| D2 | **Keep-alive mount policy.** Visited slides are CSS-hidden (`visibility:hidden` + `inert`), never unmounted - unmount aborts an in-flight stream irreversibly. Stream state lives in a module store to survive remounts. | chat surface spec 1, reader-chat 4 |
| D3 | **No `position:fixed` anywhere.** The deck transform breaks it. Pin by flex; overlays use the z-index stacking scale (drawer 70 / palette 80). | reader-shell 3 |
| D4 | **The five laws (L1-L5).** L1 considered controls (structured pickers over free text/JSON), L2 chat parity (every write flow names its verb path; no UI-only capability), L3 server authority (role gates cosmetic; render the server's `denied` body via `apiReason`, never pre-guess), L4 amber is reserved (`--color-consequence-high` ONLY for kernel governance/HITL; red for local destructive, warn for warnings), L5 no blank-required (every field ships a default). | `ui-patterns.md` five laws |
| D5 | **The P-numbered pattern register is the only source of new components.** A surface needing a control not in the register is a fork *back to the pattern doc*, not a local invention. Raw JSON as a primary control is forbidden (advanced escape hatch only, inside a disclosure). | `ui-patterns.md` P1, section 9 |
| D6 | **Governed-write vocabulary is fixed.** First save of a `control.*` / consequence-high write 202s and pauses: button "Request change", foreshadow "This is a high-consequence change. It will pause for a human approval before it takes effect." Never "may pause"; never an ok-styled Save as the documented first outcome. | AMENDMENTS B/A2 |
| D7 | **Approval does not apply the change.** The HITL gate fires BEFORE execution; the write happens only when the caller re-invokes the SAME verb + params + single-use `approval_id`. The PendingHuman card re-invokes and renders that result, never "flips to ok in place". | AMENDMENTS A1 |
| D8 | **Token layering: primitives -> semantic (`--color-*`) -> legacy aliases.** New work consumes semantic names, never primitives, never hard-coded values. Do not rename legacy aliases (components reference them). Theme/contrast/density variants override only the semantic layer. | `ui/DESIGN-TOKENS.md` |
| D9 | **No em or en dashes** anywhere in UI copy or code. Spaced hyphen, comma, colon, or parentheses only. | DESIGN-TOKENS, global rule |
| D10 | **Every surface declares an 80% path (P20)** completable with Tier-1 controls only, and exposes exactly one `btn--primary` at rest. | ui-patterns P20 |
| D11 | **A11y baseline is a contract, not a nicety** - the `250` ink step and indigo `550` exist specifically to clear WCAG AA on dark surfaces. Contrast/density variants are load-bearing. | DESIGN-TOKENS Accessibility |

## INFERRED (ratify before binding Fable)

| # | Inferred decision | Why I think it's deliberate | Status |
|---|---|---|---|
| D12 | Settings is a full **page**, not a modal/drawer. | Explicit recent commit "settings as a page". | ratify |
| D13 | Full-width panels, collapsible sidebar, **no glide animation**. | Explicit recent commit "Full-width panels, no glide, collapsible sidebar". | ratify |
| D14 | Modals use the mesh background + full-width inputs + softer card. | Explicit recent commit "Polish modals: mesh background...". | ratify |
| D15 | The console and chat are the **only two clients**; there is no third bespoke client surface. | L2 framing treats them as two clients of one verb-space. | ratify |

---

## No-rewrite list (polish-and-extend only; strangler-fig, never restart)

These are load-bearing or hard-won. Improve **in place** behind stable seams. Rewriting them
is a value-destroying trap even when the code looks ugly (ugly != wrong structure).

- **The spatial deck engine** (`ui/src/deck/*`) - frozen mechanics (D1-D3). Extend, never rebuild.
- **The chat streaming + turn normaliser** (`chatTurn*.ts/tsx`, the module stream store) - the
  reasoning/tool/sub-agent/HITL event pipeline is subtle and correctness-critical (D2, D7).
- **The design-token layer** (`ui/src/styles.css` `:root` + variants, `DESIGN-TOKENS.md`) - the
  three-layer cascade and a11y-tuned steps (D8, D11).
- **The pattern language + AMENDMENTS** (`docs/design/ui-patterns.md`, `surfaces/AMENDMENTS.md`) -
  these are the law; changes go *through* them via the challenge protocol, not around them.
- **The kernel verb seam** (`ui/src/api/*`) - the console talks to the kernel through the verb
  space; that boundary is doctrine (L2/L3), not a refactor target.

---

## How Fable uses this file
1. Before touching a surface, read the CANON-LOCKED rows and the no-rewrite list.
2. A change that would overturn any locked row is **not** made silently - it goes through the
   challenge protocol (see `ENHANCEMENT-CHARTER.md` section 4) as a proposal with its case.
3. Anything not listed here is fair game at its altitude (see the ladder).
