# Boltrig design system

Produced with the agents-final **design-agent-suite** in **System mode** (define
tokens + visual language), grounded in the real Boltrig product. Token hierarchy
follows skill 11 (primitive -> semantic -> component, intent-named). Evidence note:
product facts are high-confidence (built this build); the specific visual choices
are design proposals, meant to be the baseline a renderer (claude.ai/design) and
the implementation stay faithful to.

Brand in one line: **a charged graphite instrument** - near-black surfaces, an
electric-cyan "current" for life and primary action, a warm amber-orange reserved
for consequence (the colour of "a human is needed"). Precision instrument /
mission-control, dark-first, quiet until something matters.

## 1. Primitive tokens (raw values - never used directly in components)

```
/* graphite (surfaces -> text) */
--c-ink-900: #0B0E14;  --c-ink-800: #12161F;  --c-ink-700: #1A2030;
--c-ink-600: #232C40;  --c-ink-500: #2E3850;  --c-ink-400: #3A4357;
--c-ink-300: #5A6477;  --c-ink-200: #8A93A6;  --c-ink-100: #C2C9D6;
--c-ink-050: #E6EAF2;  --c-white: #F4F6FB;

/* electric cyan (the current) */
--c-cyan-600: #1FB6D6; --c-cyan-500: #3DD3F0; --c-cyan-400: #6FE3F7;
/* indigo (secondary / agent-flavoured) */
--c-indigo-600: #5E6CF0; --c-indigo-500: #7C8BFF;
/* signals */
--c-green-500: #3FB984; --c-amber-500: #E8B339; --c-red-500: #F0654A;
--c-orange-500: #FF7A45;  /* consequence-high */  --c-slate-500: #5A6477;
```

## 2. Semantic tokens (intent names - what components reference)

Dark theme is primary. Each also has a light and high-contrast value (the app
already drives `data-theme` / `data-contrast` / `data-density` on `:root`).

```
/* surfaces */
--color-bg-base:    var(--c-ink-900);  /* app background */
--color-bg-raised:  var(--c-ink-800);  /* panels */
--color-bg-card:    var(--c-ink-700);  /* cards, nodes, drawer */
--color-bg-overlay: rgba(6,8,12,0.66); /* drawer/scrim */
/* lines + text */
--color-border-subtle: var(--c-ink-500);
--color-border-strong: var(--c-ink-400);
--color-text-primary:  var(--c-ink-050);
--color-text-secondary:var(--c-ink-200);
--color-text-muted:    var(--c-ink-300);
/* accents */
--color-accent:        var(--c-cyan-500);  /* current: live, primary, focus */
--color-accent-hover:  var(--c-cyan-400);
--color-accent-2:      var(--c-indigo-500);/* links, agent */
/* status (health/run outcomes) */
--color-ok: var(--c-green-500); --color-warn: var(--c-amber-500);
--color-down: var(--c-red-500); --color-unknown: var(--c-slate-500);
/* consequence (governance) */
--color-consequence-low:  var(--c-slate-500);
--color-consequence-high: var(--c-orange-500); /* destructive/outbound; needs a human */
/* run / step state */
--color-run-pending: var(--c-ink-400);
--color-run-running: var(--c-cyan-500);
--color-run-ok:      var(--c-green-500);
--color-run-failed:  var(--c-red-500);
--color-run-skipped: var(--c-amber-500);
--color-run-paused:  var(--c-orange-500); /* paused-for-approval */
/* focus */
--focus-ring: 0 0 0 2px var(--c-ink-900), 0 0 0 4px var(--color-accent);
```

## 3. Typography

```
--font-ui:   "Inter", "Geist", system-ui, sans-serif;
--font-mono: "JetBrains Mono", "IBM Plex Mono", ui-monospace, monospace;
```
- **Mono is brand-load-bearing**: every verb id, noun, run id, grant token, and
  audit row renders in `--font-mono`. "Mono = a real system identifier" is a
  recurring signal across the whole UI.
- Scale (rem, 1rem=16px): `--fs-xs .75 / --fs-sm .8125 / --fs-md .9375 /
  --fs-lg 1.125 / --fs-xl 1.5 / --fs-2xl 2`. Weights 400/500/600. Line-height
  1.5 body, 1.25 headings.
- **Density**: `data-density="compact"` tightens spacing + line-height for the
  developer/audit surfaces; comfortable is default.

## 4. Spacing / radius / elevation / motion

```
--space-1:4px --space-2:8px --space-3:12px --space-4:16px --space-5:24px --space-6:32px
--radius-sm:6px --radius-md:8px --radius-lg:12px --radius-pill:999px
--elev-1: 0 1px 2px rgba(0,0,0,.4);
--elev-2: 0 6px 20px rgba(0,0,0,.45);          /* drawer, popovers */
--glow-accent: 0 0 0 1px var(--color-accent), 0 0 14px rgba(61,211,240,.35);
--dur-fast:120ms --dur-med:240ms --ease: cubic-bezier(.2,.6,.2,1);
--pulse: 1.6s ease-in-out infinite;            /* running node */
```
Motion is subtle and purposeful: a running node breathes (`--glow-accent` pulse);
a new stream event gets a brief cyan arrival flash. **All animation is disabled
under `prefers-reduced-motion`** (running -> a static filled cyan ring, no pulse).

## 5. The node visual language (the hero)

Component tokens for the canvas. Node = `--color-bg-card`, `--radius-md`, a
**left accent bar** (4px) keyed to kind, the verb id in mono, a kind chip.

| Kind | Accent | Signal |
| --- | --- | --- |
| **kernel-run** | `--color-border-strong` (steel) | the default governed action; neutral |
| **service** | `--color-accent-2` (indigo) + an outward-arrow / boundary-cut motif | "this leaves the system" |
| **agent** | `--color-accent` (cyan) + a 3-dot "thinking" affordance | the only kind that streams reasoning |
| **trigger** | dashed `--color-warn` + a bolt glyph at the flow head | chat / cron / webhook entry |

**Run state** overlays on any node (border + a small status dot):
pending = dim (`--color-run-pending`, 0.55 opacity) · running = `--glow-accent`
pulse · ok = `--color-run-ok` · failed/error = `--color-run-failed` · skipped =
`--color-run-skipped` muted · **paused-for-approval = `--color-run-paused` with a
steady (non-pulsing) ring + a "needs you" badge** (the unmissable safety state).

A **consequence-high** verb/node carries a small `--color-consequence-high`
marker - it foreshadows that running it will pause for approval.

Edges: 1.5px `--color-border-strong`, animated dash only while a run is live on
that edge. Canvas background: a faint dot grid on `--color-bg-base`; minimal,
high-contrast controls + minimap.

## 6. Accessibility + governance

- **WCAG AA** on all text and on every semantic colour against its surface; the
  status/consequence/run colours are distinguishable without relying on hue alone
  (each pairs with a glyph/label). Visible `--focus-ring` on every interactive
  element; canvas nodes are focusable and operable.
- **Governance (skill 24)**: tokens are versioned in this file; components below
  carry acceptance criteria. Primitive values change rarely; components reference
  semantic tokens only (never primitives or raw hex). Owner: the Boltrig design
  system; consumers: `ui/src/styles.css` (`:root` + `.wf-node--*` + run-state +
  badge classes) and the React panels.

## 7. Map to the existing code

This upgrades the vocabulary already in `ui/src/styles.css` (same shape, better
craft): the `:root` custom-property block, the `data-theme/contrast/density`
variants, `.wf-node--{agent,service,kernel-run,trigger}` + the run-state classes,
the `.badge--*` family (status/health/consequence/role), and the chat chrome
(`.thinking`, `.tool-card`, `.subagent-card`, `.chat-hitl`). Component specs in
`COMPONENT-SPECS.md`; the renderer brief in `CLAUDE-DESIGN-BRIEFING.md`.
