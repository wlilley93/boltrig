# Boltrig console - design tokens and accessibility baseline

This is the documented map of the CSS custom properties in `src/styles.css` and the
accessibility contract the console holds to. It is descriptive: the tokens live in
`styles.css` (the `:root` block plus the theme / density / contrast variants), and this
file explains the scale so new work reuses names instead of hard-coding values.

No em or en dashes anywhere (spaced hyphen, comma, colon, or parentheses only).

## How the layers fit together

Three layers, outermost wins:

1. **Primitives** (`--c-*`): raw hues and tones. Never referenced by a component
   directly - they only feed the semantic tokens. Changing a primitive re-skins every
   semantic token that points at it.
2. **Semantic tokens** (`--color-*`, `--fs-*`, `--dur-*`, `--elev-*`, ...): intent names
   a component may consume (text, surface, accent, run-state, node kind, type scale,
   motion, elevation). The `:root` values are the dark theme; the
   `:root[data-theme="light"]`, `[data-contrast="high"]` and `prefers-color-scheme`
   blocks override only these.
3. **Legacy aliases** (`--bg`, `--text`, `--muted`, `--accent`, ...): the short names the
   original rules were written against. Each points at a semantic token, so old rules
   follow the theme / contrast variants for free. Do not rename these - components
   reference them. New work should prefer the semantic `--color-*` names.

## Color

### Primitive tones

- Ink (surfaces + text), darkest to lightest: `--c-ink-900 800 700 600 500 400 300 250 200 100 050`, then `--c-white`.
  The `250` step (`#6A8099`) was added for muted text so it clears WCAG AA on the dark
  surfaces (see Accessibility below).
- Cyan (the primary "current"): `--c-cyan-600 500 400`.
- Indigo (secondary accent): `--c-indigo-600 550 500`. `550` (`#5E69DD`) is a deeper
  indigo tuned so white labels on the primary accent clear AA; `500` stays for node
  accents where it is not a text background.
- Status: `--c-green-500` (ok), `--c-amber-500` (warn), `--c-red-500` (down),
  `--c-orange-500` (consequence-high), `--c-slate-500` (unknown / consequence-low).

### Semantic color roles

- Surface: `--color-bg-base` `-raised` `-card` `-inset` `-overlay`.
- Border: `--color-border-subtle` `-strong`.
- Text: `--color-text-primary` `-secondary` `-muted` `-oncolor`.
- Accent: `--color-accent` `-hover` `-press`, plus `--color-accent-2` (indigo, the
  primary-button / user-bubble background).
- Status: `--color-ok` `-warn` `-down` `-unknown`.
- Consequence: `--color-consequence-low` `-high`.
- Run state: `--color-run-pending` `-running` `-ok` `-failed` `-skipped` `-paused`.
- Node kind (graphs): `--color-node-kernel` `-service` `-agent` `-trigger`.

## Space, radius, type, motion, elevation

- **Space:** `--gap` (12px; 8px under `data-density="compact"`). Layout helpers
  (`.stack`, `.cols`, `.form__grid`) build off `--gap`.
- **Radius:** `--radius` (8px legacy). The v2 craft layer uses 3px corners directly.
- **Type:** families `--font-ui`, `--font-mono`; size scale `--fs-xs` `-sm` `-md` `-lg`
  `-xl` `-2xl`. Body size scales with `--font-scale` (user appearance setting).
- **Motion:** `--dur-fast` (120ms), `--dur-med` (240ms), `--ease`, `--pulse` (1.6s).
- **Elevation:** `--elev-1`, `--elev-2`, `--glow-accent`.
- **Shell:** `--app-sidebar-width` is written onto `:root` by `App.tsx`; both the sidebar
  and the content offset consume it so they move in lockstep.

## Accessibility baseline (WCAG 2.1 AA)

- **Focus:** one global `:focus-visible` ring (`2px solid var(--color-accent)`,
  `outline-offset: 2px`) on links, buttons, inputs, textareas, selects, summaries and
  `[tabindex]`. Controls whose own `:focus` rule sets `outline: none` (the command
  palette input, the chat composer) add a matching `:focus-visible` ring so keyboard
  focus stays visible; mouse focus keeps the quieter border treatment. The only
  deliberate ringless focus is the deck slide frame, which is a `tabindex=-1` scroll
  container focused programmatically on settle (never by keyboard).
- **Reduced motion:** honoured two ways - the OS `prefers-reduced-motion: reduce` media
  query and the user's own `:root.reduce-motion` class both zero every animation and
  transition. Motion that needs a resting state (the composer glow, the mic pulse, the
  running-node glow) gets an explicit static replacement instead of a frozen frame, and
  the deck's fade / slide choreography checks the same preference in JS and snaps
  instantly.
- **Contrast targets:** body text 4.5:1, large text / UI components / focus rings 3:1.
  Muted text and the primary-accent button background are tuned to clear these on both
  the base and card surfaces (dark theme).
- **Target size:** interactive controls are at least 44x44 CSS px under a coarse pointer
  (`@media (pointer: coarse)`). On fine pointers, dense controls (data-table rows,
  chips, the sidebar collapse affordance) may be smaller, which WCAG 2.2 target-size
  permits for inline / dense UI.
- **Semantics:** the command palette is a labelled `role="dialog"` with a focus trap,
  Escape-to-close, and a `combobox` + `listbox`/`option` result list wired with
  `aria-activedescendant` / `aria-selected`. The deck exposes an `aria-live` settle
  announcer, `aria-current` on the minimap, and `inert` on off-screen slides. The
  sidebar uses `aria-current`, grouped `role="group"` regions, and a keyboard-operable
  `role="separator"` resizer. The workspace switcher is a labelled native `<select>`.
