/* Form-primitive register (docs/design/ui-patterns.md section 9): the seat
 * that owns the FORM vocabulary. N1 Switch (+ useSavedWisp), P3 SegmentedV2,
 * N2 CardSelect, N3 ChipPicker (amendment 12 disabled-with-reason variant),
 * N4 EntityPicker, N5 ScopeBuilder, N6 Stepper, N9 JsonDisclosure,
 * N17 OrderedPicker and the P9 SchemaFormV2 upgrade.
 *
 * Contracts every component here honours: presentational only (no fetching,
 * no polling; values flow in via props, out via onChange); semantic --color-*
 * tokens only (the ux- append block in styles.css); the global focus-visible
 * ring and reduce-motion rules are relied on, never restyled; keyboard maps
 * follow P36 (arrows inside pickers, roving tabindex so Tab leaves a widget
 * in one step, Backspace-on-empty removes the last chip). */

import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { prettyJson } from "./shared";
import { CONSEQUENCE, Field, Hint, Select, StatusBadge } from "./ux";
import type { Option } from "./ux";

// Radio-group arrow movement: next enabled index in a wrapping scan. Shared by
// SegmentedV2 and CardSelect so both keep identical radio semantics.
function nextEnabled(
  count: number,
  isDisabled: (i: number) => boolean,
  from: number,
  delta: number,
): number {
  if (count === 0) return -1;
  let i = from;
  for (let hop = 0; hop < count; hop++) {
    i = (i + delta + count) % count;
    if (!isDisabled(i)) return i;
  }
  return -1;
}

// --- N1 Switch: instant-apply boolean (P2). ---------------------------------
// Only for settings where both states are safe and the write applies at once;
// booleans with governance weight stay SegmentedV2 inside a saved form. The
// caller owns the instant-apply contract (optimistic set, busy while
// persisting, revert + faithful error on failure); this renders the states.
export function Switch({
  checked,
  onChange,
  label,
  hint,
  disabled = false,
  busy = false,
  wisp,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  busy?: boolean;
  // the useSavedWisp node, rendered beside the control on successful persist
  wisp?: ReactNode;
}) {
  const labelId = useId();
  const hintId = useId();
  return (
    <div className={`ux-switch ${busy ? "ux-switch--busy" : ""}`}>
      <span className="ux-switch__text">
        <span className="ux-switch__label" id={labelId}>
          {label}
        </span>
        {hint != null && (
          <span className="ux-switch__hint" id={hintId}>
            {hint}
          </span>
        )}
      </span>
      {wisp}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={hint != null ? hintId : undefined}
        aria-busy={busy || undefined}
        className="ux-switch__ctl"
        disabled={disabled || busy}
        onClick={() => onChange(!checked)}
      >
        <span className="ux-switch__thumb" aria-hidden="true" />
      </button>
    </div>
  );
}

// --- N1 companion: the transient "Saved" wisp (P16 autosave affirmation). ---
// Returns [node, trigger]. Render the node where the confirmation should
// appear (e.g. the Switch wisp slot) and call trigger() after a successful
// persist. Fade uses a transition only, so the global reduce-motion rules
// quiet it; the timer (not the animation) removes the text, so the wisp still
// clears when motion is zeroed.
export function useSavedWisp(text: string = "Saved"): [ReactNode, () => void] {
  const [shown, setShown] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const trigger = useCallback(() => {
    setShown(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setShown(false), 1800);
  }, []);
  const node = (
    <span className={`ux-wisp ${shown ? "ux-wisp--on" : ""}`} role="status">
      {shown ? text : ""}
    </span>
  );
  return [node, trigger];
}

// --- P3 SegmentedV2: 2-4 mutually exclusive values, radio semantics. --------
// Upgrade of ux.tsx Segmented: role="radiogroup" + roving tabindex + arrow
// keys (select on move, per native radio behaviour). Reuses the .seg CSS.
export function SegmentedV2({
  value,
  onChange,
  options,
  ariaLabel,
  disabled = false,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
  ariaLabel?: string;
  disabled?: boolean;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const selIdx = options.findIndex((o) => o.value === value);

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (disabled) return;
    const delta =
      e.key === "ArrowRight" || e.key === "ArrowDown"
        ? 1
        : e.key === "ArrowLeft" || e.key === "ArrowUp"
          ? -1
          : 0;
    if (delta === 0) return;
    e.preventDefault();
    const next = nextEnabled(
      options.length,
      () => false,
      selIdx < 0 ? (delta > 0 ? -1 : 0) : selIdx,
      delta,
    );
    if (next < 0) return;
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div className="seg" role="radiogroup" aria-label={ariaLabel} onKeyDown={onKey}>
      {options.map((o, i) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value || (selIdx < 0 && i === 0) ? 0 : -1}
          ref={(el) => {
            refs.current[i] = el;
          }}
          className={`btn btn--seg ${o.value === value ? "btn--seg-on" : ""}`}
          title={o.hint}
          disabled={disabled}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// --- N2 CardSelect: enum whose correct choice needs metadata (P4). ----------
// 2-5 cards, single select, radio semantics (arrows move + select, roving
// tabindex). Badges reuse the existing .badge families.
export interface CardOption {
  value: string;
  label: ReactNode;
  body?: ReactNode;
  badges?: ReactNode;
  disabled?: boolean;
}

export function CardSelect({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: CardOption[];
  ariaLabel?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const selIdx = options.findIndex((o) => o.value === value);

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const delta =
      e.key === "ArrowRight" || e.key === "ArrowDown"
        ? 1
        : e.key === "ArrowLeft" || e.key === "ArrowUp"
          ? -1
          : 0;
    if (delta === 0) return;
    e.preventDefault();
    const next = nextEnabled(
      options.length,
      (i) => !!options[i].disabled,
      selIdx < 0 ? (delta > 0 ? -1 : 0) : selIdx,
      delta,
    );
    if (next < 0) return;
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div className="ux-cardsel" role="radiogroup" aria-label={ariaLabel} onKeyDown={onKey}>
      {options.map((o, i) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value || (selIdx < 0 && i === 0) ? 0 : -1}
          ref={(el) => {
            refs.current[i] = el;
          }}
          className="ux-cardsel__card"
          disabled={o.disabled}
          onClick={() => onChange(o.value)}
        >
          <span className="ux-cardsel__title">{o.label}</span>
          {o.body != null && <span className="ux-cardsel__body">{o.body}</span>}
          {o.badges != null && <span className="ux-cardsel__badges">{o.badges}</span>}
        </button>
      ))}
    </div>
  );
}

// --- N3 ChipPicker: multi-select from a known set (P5). ---------------------
// Selected values are removable chips; a search input filters candidates;
// Backspace in the empty search removes the last chip; ArrowDown enters the
// candidate list (roving via aria-activedescendant, candidates stay out of
// the Tab order). allowFree admits values outside the candidate set, vetted
// by the per-chip validate fn. Amendment 12: candidates may be disabled with
// a visible reason line (the automations parents editor consumes this).
export interface ChipOption {
  value: string;
  label?: string;
  hint?: string;
  disabled?: boolean;
  disabledReason?: string;
}

export function ChipPicker({
  value,
  onChange,
  options = [],
  searchable = true,
  allowFree = false,
  validate,
  mono = false,
  disabled = false,
  placeholder,
  ariaLabel,
  emptyHint,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  options?: ChipOption[];
  searchable?: boolean;
  allowFree?: boolean;
  // free entries only; candidates are pre-vetted. Return a reason to reject.
  validate?: (v: string) => string | null;
  mono?: boolean;
  disabled?: boolean;
  placeholder?: string;
  ariaLabel?: string;
  emptyHint?: ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const [freeError, setFreeError] = useState<string | null>(null);
  const listId = useId();

  const q = query.trim().toLowerCase();
  const cands = useMemo(
    () =>
      options.filter(
        (o) =>
          !value.includes(o.value) &&
          (!q ||
            o.value.toLowerCase().includes(q) ||
            (o.label ?? "").toLowerCase().includes(q)),
      ),
    [options, value, q],
  );
  const enabled = cands.map((c, i) => (c.disabled ? -1 : i)).filter((i) => i >= 0);
  const act = active >= 0 && active < cands.length && !cands[active].disabled ? active : -1;

  function addValue(v: string) {
    if (!value.includes(v)) onChange([...value, v]);
    setQuery("");
    setActive(-1);
    setFreeError(null);
  }

  function addFree() {
    const v = query.trim();
    if (!v) return;
    const err = validate ? validate(v) : null;
    if (err) {
      setFreeError(err);
      return;
    }
    addValue(v);
  }

  const exact = options.some((o) => o.value === query.trim());
  const showFreeRow = allowFree && query.trim().length > 0 && !exact;
  const showInput = searchable && !disabled && (options.length > 0 || allowFree);

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && query === "" && value.length > 0) {
      onChange(value.slice(0, -1));
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const pos = enabled.indexOf(act);
      const next = enabled[Math.min(pos + 1, enabled.length - 1)];
      setActive(next === undefined ? -1 : next);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      const pos = enabled.indexOf(act);
      setActive(pos <= 0 ? -1 : enabled[pos - 1]);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (act >= 0) addValue(cands[act].value);
      else if (allowFree) addFree();
      return;
    }
    if (e.key === "Escape") setActive(-1);
  }

  return (
    <div className={`ux-chips ${mono ? "ux-chips--mono" : ""}`} role="group" aria-label={ariaLabel}>
      <div className="ux-chips__row">
        {value.length === 0 && emptyHint != null && <span className="ux-hint">{emptyHint}</span>}
        {value.map((v) => {
          const opt = options.find((o) => o.value === v);
          return (
            <span key={v} className={`ux-chips__chip ${mono ? "ux-chips__chip--mono" : ""}`}>
              {opt?.label ?? v}
              {!disabled && (
                <button
                  type="button"
                  className="ux-chips__rm"
                  aria-label={`Remove ${v}`}
                  onClick={() => onChange(value.filter((x) => x !== v))}
                >
                  ×
                </button>
              )}
            </span>
          );
        })}
      </div>
      {showInput && (
        <input
          className="ux-chips__search"
          role="combobox"
          aria-expanded={cands.length > 0 || showFreeRow}
          aria-controls={listId}
          aria-activedescendant={act >= 0 ? `${listId}-o${act}` : undefined}
          aria-label={ariaLabel ?? "Add values"}
          value={query}
          placeholder={
            placeholder ?? (options.length > 0 ? "Type to filter..." : "Type a value and press Enter")
          }
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(-1);
            setFreeError(null);
          }}
          onKeyDown={onKey}
        />
      )}
      {freeError && (
        <span className="ux-chips__err" role="alert">
          {freeError}
        </span>
      )}
      {showInput && (cands.length > 0 || showFreeRow) && (
        <div className="ux-chips__list" role="listbox" id={listId} aria-label={ariaLabel}>
          {cands.map((c, i) =>
            c.disabled ? (
              <div
                key={c.value}
                id={`${listId}-o${i}`}
                role="option"
                aria-disabled="true"
                aria-selected="false"
                className="ux-chips__cand ux-chips__cand--off"
              >
                <span>{c.label ?? c.value}</span>
                {c.disabledReason && <span className="ux-chips__cand-why">{c.disabledReason}</span>}
              </div>
            ) : (
              <button
                key={c.value}
                type="button"
                id={`${listId}-o${i}`}
                role="option"
                aria-selected={i === act}
                tabIndex={-1}
                className={`ux-chips__cand ${i === act ? "ux-chips__cand--act" : ""}`}
                onClick={() => addValue(c.value)}
              >
                <span>{c.label ?? c.value}</span>
                {c.hint && <span className="ux-chips__cand-hint">{c.hint}</span>}
              </button>
            ),
          )}
          {showFreeRow && (
            <button
              type="button"
              role="option"
              aria-selected="false"
              tabIndex={-1}
              className="ux-chips__cand"
              onClick={addFree}
            >
              <span>Add "{query.trim()}"</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// --- N4 EntityPicker: reference to one entity, grouped + previewed (P6). ----
// Combobox pattern: a trigger styled as an input opens an in-flow absolute
// panel (no portals; the deck transform breaks position:fixed; z 30 sits
// below drawer 70 / palette 80) with search + grouped listbox. Arrows move,
// Enter selects, Escape closes, outside click closes. renderPreview renders
// the inline preview card under the field once a value is chosen.
export interface EntityItem {
  id: string;
  label?: string;
  badges?: ReactNode;
}

export interface EntityGroup {
  label: string;
  items: EntityItem[];
}

export function EntityPicker({
  value,
  onChange,
  groups,
  placeholder = "Choose...",
  renderPreview,
  disabled = false,
  ariaLabel,
}: {
  value: string | null;
  onChange: (id: string) => void;
  groups: EntityGroup[];
  placeholder?: string;
  renderPreview?: (id: string) => ReactNode;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const baseId = useId();

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const out: { group: string; first: boolean; item: EntityItem }[] = [];
    for (const g of groups) {
      let first = true;
      for (const it of g.items) {
        if (needle && !`${it.id} ${it.label ?? ""}`.toLowerCase().includes(needle)) continue;
        out.push({ group: g.label, first, item: it });
        first = false;
      }
    }
    return out;
  }, [groups, query]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    document.getElementById(`${baseId}-o${active}`)?.scrollIntoView({ block: "nearest" });
  }, [open, active, baseId]);

  const current = useMemo(() => {
    for (const g of groups) for (const it of g.items) if (it.id === value) return it;
    return undefined;
  }, [groups, value]);

  function choose(id: string) {
    onChange(id);
    setOpen(false);
    setQuery("");
    triggerRef.current?.focus();
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, rows.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const row = rows[active];
      if (row) choose(row.item.id);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    }
  }

  return (
    <div className="ux-picker" ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className="ux-picker__trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => {
          setQuery("");
          setActive(0);
          setOpen((o) => !o);
        }}
      >
        {value ? (
          <code className="ux-picker__val">{value}</code>
        ) : (
          <span className="ux-picker__ph">{placeholder}</span>
        )}
        {current?.badges}
        <span className="ux-picker__chev" aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <div className="ux-picker__panel">
          <input
            autoFocus
            role="combobox"
            aria-expanded="true"
            aria-controls={`${baseId}-list`}
            aria-activedescendant={rows.length > 0 ? `${baseId}-o${active}` : undefined}
            aria-label={ariaLabel ?? "Search"}
            value={query}
            placeholder="Type to search..."
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKey}
          />
          <div className="ux-picker__list" role="listbox" id={`${baseId}-list`}>
            {rows.length === 0 && <span className="ux-picker__none">No matches.</span>}
            {rows.map((r, i) => (
              <Fragment key={r.item.id}>
                {r.first && (
                  <div className="ux-picker__group" role="presentation">
                    {r.group}
                  </div>
                )}
                <button
                  type="button"
                  id={`${baseId}-o${i}`}
                  role="option"
                  aria-selected={r.item.id === value}
                  tabIndex={-1}
                  className={`ux-picker__opt ${i === active ? "ux-picker__opt--act" : ""}`}
                  onClick={() => choose(r.item.id)}
                >
                  <code>{r.item.id}</code>
                  {r.item.label && <span className="ux-picker__optlabel">{r.item.label}</span>}
                  {r.item.badges}
                </button>
              </Fragment>
            ))}
          </div>
        </div>
      )}
      {value && renderPreview && <div className="ux-picker__preview">{renderPreview(value)}</div>}
    </div>
  );
}

// --- N5 ScopeBuilder: grant/scope patterns with live match preview (P7). ----
// One value shape serves skill tool_grants, PAT scopes, supported_skills and
// eval forbidden_grants: a string[] of tokens and patterns. The verbs prop is
// the caller-scoped registry (no fetching inside); presets are client-side
// sugar (the value stays the pattern list); warn is the dropped-patterns
// slot. Consequence-high verbs carry the glossary badge (L4: amber only for
// kernel governance).
export interface ScopeVerb {
  id: string;
  noun: string;
  consequence?: string;
}

// Grant token semantics: "*" matches everything; "noun.*" (any trailing "*")
// is a prefix pattern; anything else is an exact verb id.
export function grantMatches(pattern: string, verbId: string): boolean {
  if (pattern === "*") return true;
  if (pattern.endsWith("*")) return verbId.startsWith(pattern.slice(0, -1));
  return pattern === verbId;
}

export function scopeMatches(patterns: string[], verbs: ScopeVerb[]): ScopeVerb[] {
  return verbs.filter((v) => patterns.some((p) => grantMatches(p, v.id)));
}

export function ScopeBuilder({
  value,
  onChange,
  verbs,
  presets,
  warn,
  disabled = false,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  verbs: ScopeVerb[];
  presets?: { label: string; value: string[] }[];
  warn?: ReactNode;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [openNouns, setOpenNouns] = useState<Record<string, boolean>>({});

  const matched = useMemo(() => scopeMatches(value, verbs), [value, verbs]);
  const matchedHigh = matched.filter((v) => v.consequence === "high").length;
  const deadPatterns = useMemo(
    () => value.filter((p) => !verbs.some((v) => grantMatches(p, v.id))),
    [value, verbs],
  );

  const nouns = useMemo(() => {
    const by = new Map<string, ScopeVerb[]>();
    for (const v of verbs) {
      const list = by.get(v.noun);
      if (list) list.push(v);
      else by.set(v.noun, [v]);
    }
    return [...by.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [verbs]);

  const q = query.trim().toLowerCase();

  function add(p: string) {
    if (!value.includes(p)) onChange([...value, p]);
  }

  return (
    <div className="ux-scope">
      {presets && presets.length > 0 && (
        <div className="ux-scope__presets">
          <span className="ux-hint">Presets:</span>
          {presets.map((p) => (
            <button
              key={p.label}
              type="button"
              className="btn btn--sm btn--ghost"
              disabled={disabled}
              onClick={() => onChange([...p.value])}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}
      <div className="ux-chips__row">
        {value.length === 0 && (
          <span className="ux-hint">No grants yet. Add verbs or patterns from the list below.</span>
        )}
        {value.map((p) => {
          const dead = deadPatterns.includes(p);
          return (
            <span
              key={p}
              className={`ux-chips__chip ux-chips__chip--mono ${dead ? "ux-chips__chip--warn" : ""}`}
              title={dead ? "Matches no verbs today. It will apply to future verbs that fit." : undefined}
            >
              {p}
              <button
                type="button"
                className="ux-chips__rm"
                aria-label={`Remove ${p}`}
                disabled={disabled}
                onClick={() => onChange(value.filter((x) => x !== p))}
              >
                ×
              </button>
            </span>
          );
        })}
      </div>
      <input
        className="ux-scope__search"
        type="search"
        value={query}
        placeholder="Filter verbs..."
        aria-label="Filter verbs"
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="ux-scope__tree">
        {nouns.map(([noun, list]) => {
          const hits = q ? list.filter((v) => v.id.toLowerCase().includes(q)) : list;
          if (q && hits.length === 0 && !noun.toLowerCase().includes(q)) return null;
          const shown = q && hits.length > 0 ? hits : list;
          const open = q ? true : (openNouns[noun] ?? false);
          const pattern = `${noun}.*`;
          return (
            <div key={noun} className="ux-scope__noun">
              <div className="ux-scope__nounrow">
                <button
                  type="button"
                  className="ux-scope__toggle"
                  aria-expanded={open}
                  onClick={() => setOpenNouns((m) => ({ ...m, [noun]: !open }))}
                >
                  <span className="ux-scope__caret" aria-hidden="true">
                    {open ? "▾" : "▸"}
                  </span>
                  <span className="ux-scope__nounname">{noun}</span>
                  <span className="ux-scope__count">
                    {list.length} {list.length === 1 ? "verb" : "verbs"}
                  </span>
                </button>
                <button
                  type="button"
                  className="btn btn--sm btn--ghost"
                  disabled={disabled || value.includes(pattern)}
                  title="A pattern also covers verbs added to this noun later."
                  onClick={() => add(pattern)}
                >
                  Add {pattern}
                </button>
                <button
                  type="button"
                  className="btn btn--sm btn--ghost"
                  disabled={disabled}
                  onClick={() => {
                    const next = [...value];
                    for (const v of list) if (!next.includes(v.id)) next.push(v.id);
                    onChange(next);
                  }}
                >
                  Add {list.length} individually
                </button>
              </div>
              {open && (
                <div className="ux-scope__verbs">
                  {shown.map((v) => {
                    const covered = value.some((p) => grantMatches(p, v.id));
                    return (
                      <div key={v.id} className="ux-scope__row">
                        <span className="ux-scope__verbid">{v.id}</span>
                        {v.consequence === "high" && (
                          <StatusBadge value="high" glossary={CONSEQUENCE} />
                        )}
                        {covered ? (
                          <span className="ux-scope__covered">covered</span>
                        ) : (
                          <button
                            type="button"
                            className="btn btn--sm btn--ghost"
                            disabled={disabled}
                            aria-label={`Add ${v.id}`}
                            onClick={() => add(v.id)}
                          >
                            Add
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
        {verbs.length === 0 && <span className="ux-picker__none">No verbs available to this caller.</span>}
      </div>
      <Hint>A pattern like ticket.* also covers verbs added later.</Hint>
      <details className="ux-scope__preview">
        <summary>
          Matches {matched.length} {matched.length === 1 ? "verb" : "verbs"} today ({matchedHigh}{" "}
          high consequence)
        </summary>
        <div className="ux-scope__matchlist">
          {matched.length === 0 ? (
            <span className="ux-hint">Nothing matches yet.</span>
          ) : (
            matched.map((v) => (
              <code key={v.id} className="tag">
                {v.id}
              </code>
            ))
          )}
        </div>
      </details>
      {deadPatterns.length > 0 && (
        <p className="ux-scope__warn">
          {deadPatterns.join(", ")}{" "}
          {deadPatterns.length === 1 ? "matches" : "match"} no verbs today. Patterns apply to
          future verbs that fit.
        </p>
      )}
      {warn != null && <p className="ux-scope__warn">{warn}</p>}
    </div>
  );
}

// --- N6 Stepper: bounded number with a unit (P8). ---------------------------
// input[type=number] flanked by minus/plus, clamped on blur, buttons disabled
// at the bounds. State the range in the owning Field's hint; meta carries a
// caller-computed derived fact (e.g. the expiry date a TTL resolves to).
export function Stepper({
  value,
  onChange,
  min,
  max,
  step = 1,
  unit,
  meta,
  id,
  disabled = false,
  ariaLabel,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  meta?: ReactNode;
  id?: string;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  function clamp(n: number): number {
    let v = n;
    if (typeof min === "number") v = Math.max(min, v);
    if (typeof max === "number") v = Math.min(max, v);
    return v;
  }

  function commit(n: number) {
    const v = clamp(n);
    onChange(v);
    setDraft(String(v));
  }

  const atMin = typeof min === "number" && value <= min;
  const atMax = typeof max === "number" && value >= max;

  return (
    <div className="ux-stepper">
      <button
        type="button"
        className="btn btn--sm ux-stepper__btn"
        aria-label="Decrease"
        disabled={disabled || atMin}
        onClick={() => commit(value - step)}
      >
        -
      </button>
      <span className="ux-stepper__box">
        <input
          id={id}
          type="number"
          inputMode="numeric"
          aria-label={ariaLabel}
          min={min}
          max={max}
          step={step}
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            const n = Number(draft);
            if (draft.trim() === "" || !Number.isFinite(n)) {
              setDraft(String(value));
              return;
            }
            commit(n);
          }}
        />
        {unit && <span className="ux-stepper__unit">{unit}</span>}
      </span>
      <button
        type="button"
        className="btn btn--sm ux-stepper__btn"
        aria-label="Increase"
        disabled={disabled || atMax}
        onClick={() => commit(value + step)}
      >
        +
      </button>
      {meta != null && <span className="ux-stepper__meta">{meta}</span>}
    </div>
  );
}

// --- N9 JsonDisclosure: the collapsed JSON escape hatch (P10). ---------------
// Never the primary control (L1). The CALLER owns the two-way sync and the
// validity (amendment 9: an unparseable escape hatch blocks Save and slide
// navigation on every surface); pass the parse failure via error so the
// collapsed summary stays honest. summaryNote carries quiet facts like
// preserved unknown keys.
export function JsonDisclosure({
  value,
  onChange,
  error,
  summaryNote,
  label = "Advanced: edit as JSON",
  rows = 8,
  defaultOpen = false,
  disabled = false,
}: {
  value: string;
  onChange: (text: string) => void;
  error?: ReactNode;
  summaryNote?: ReactNode;
  label?: string;
  rows?: number;
  defaultOpen?: boolean;
  disabled?: boolean;
}) {
  return (
    <details className={`ux-jsond ${error ? "ux-jsond--invalid" : ""}`} open={defaultOpen}>
      <summary className="ux-jsond__summary">
        <span>{label}</span>
        {error ? (
          <span className="ux-jsond__flag" role="status">
            invalid JSON
          </span>
        ) : (
          summaryNote != null && <span className="ux-jsond__note">{summaryNote}</span>
        )}
      </summary>
      <div className="ux-jsond__body">
        <textarea
          className="ux-jsond__text"
          rows={rows}
          spellCheck={false}
          value={value}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-label={label}
          onChange={(e) => onChange(e.target.value)}
        />
        {error != null && (
          <span className="ux-jsond__err" role="alert">
            {error}
          </span>
        )}
      </div>
    </details>
  );
}

// --- N17 OrderedPicker: an ordered list where position is the value. --------
// Numbered rows with up/down buttons; Alt+ArrowUp/Down moves the focused row;
// every move is announced via a polite live region. Candidates not yet in the
// list render as add affordances (amendment 12 disabled-with-reason honoured).
export function OrderedPicker({
  value,
  onChange,
  options = [],
  mono = true,
  ariaLabel,
  disabled = false,
  emptyHint = "Nothing here yet. Add from the options below; the order is applied top to bottom.",
}: {
  value: string[];
  onChange: (v: string[]) => void;
  options?: ChipOption[];
  mono?: boolean;
  ariaLabel?: string;
  disabled?: boolean;
  emptyHint?: ReactNode;
}) {
  const [announce, setAnnounce] = useState("");
  const labelOf = (v: string) => options.find((o) => o.value === v)?.label ?? v;

  function move(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= value.length) return;
    const next = [...value];
    const [row] = next.splice(i, 1);
    next.splice(j, 0, row);
    onChange(next);
    setAnnounce(`${labelOf(row)} moved to position ${j + 1} of ${next.length}`);
  }

  function remove(i: number) {
    const row = value[i];
    onChange(value.filter((_, x) => x !== i));
    setAnnounce(`${labelOf(row)} removed`);
  }

  function addRow(v: string) {
    onChange([...value, v]);
    setAnnounce(`${labelOf(v)} added at position ${value.length + 1}`);
  }

  const remaining = options.filter((o) => !value.includes(o.value));

  return (
    <div className="ux-ordered" role="group" aria-label={ariaLabel}>
      <div className="ux-vh" aria-live="polite">
        {announce}
      </div>
      {value.length === 0 ? (
        <span className="ux-hint">{emptyHint}</span>
      ) : (
        <ol className="ux-ordered__list">
          {value.map((v, i) => (
            <li
              key={v}
              className="ux-ordered__row"
              tabIndex={0}
              onKeyDown={(e: KeyboardEvent<HTMLLIElement>) => {
                if (disabled || !e.altKey) return;
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  move(i, -1);
                } else if (e.key === "ArrowDown") {
                  e.preventDefault();
                  move(i, 1);
                }
              }}
            >
              <span className="ux-ordered__num" aria-hidden="true">
                {i + 1}
              </span>
              <span className="ux-ordered__label">
                {mono ? <code>{labelOf(v)}</code> : labelOf(v)}
              </span>
              <span className="ux-ordered__acts">
                <button
                  type="button"
                  className="btn btn--sm btn--ghost ux-ordered__btn"
                  aria-label={`Move ${labelOf(v)} up`}
                  disabled={disabled || i === 0}
                  onClick={() => move(i, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="btn btn--sm btn--ghost ux-ordered__btn"
                  aria-label={`Move ${labelOf(v)} down`}
                  disabled={disabled || i === value.length - 1}
                  onClick={() => move(i, 1)}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className="btn btn--sm btn--ghost ux-ordered__btn"
                  aria-label={`Remove ${labelOf(v)}`}
                  disabled={disabled}
                  onClick={() => remove(i)}
                >
                  ×
                </button>
              </span>
            </li>
          ))}
        </ol>
      )}
      {remaining.length > 0 && !disabled && (
        <div className="ux-ordered__add">
          {remaining.map((o) =>
            o.disabled ? (
              <span key={o.value} className="ux-chips__cand ux-chips__cand--off">
                <span>{o.label ?? o.value}</span>
                {o.disabledReason && <span className="ux-chips__cand-why">{o.disabledReason}</span>}
              </span>
            ) : (
              <button
                key={o.value}
                type="button"
                className="ux-chips__addbtn"
                onClick={() => addRow(o.value)}
              >
                + {o.label ?? o.value}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

// --- P9 SchemaFormV2: typed controls from a JSON schema. ---------------------
// The parity engine (L2): renders exactly the input_schema the orchestrator
// validates against. Required properties first (schema order), then optional.
// Per-type controls per P1; nested objects one level deep render as an inset
// group; everything unrenderable falls back to a per-field JsonDisclosure
// (never a whole-form JSON punt). Key the component by the schema's owner
// (e.g. the verb id) so per-field JSON drafts reset when the schema changes.
// Validation timing/copy is the caller's (P13): pass field errors keyed by
// path ("k" or "k.sub"); onValidity reports the per-field JSON parse state
// (amendment 9: callers block save/navigation while false).
interface PropSpec {
  type?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  format?: string;
  items?: PropSpec;
  properties?: Record<string, PropSpec>;
  required?: string[];
  additionalProperties?: unknown;
}

function specOf(schema: unknown): { props: Record<string, PropSpec>; required: Set<string> } {
  const s = (schema ?? {}) as { properties?: Record<string, PropSpec>; required?: string[] };
  return { props: s.properties ?? {}, required: new Set(s.required ?? []) };
}

function skeletonFor(spec: PropSpec): unknown {
  const t = spec.type;
  if (t === "number" || t === "integer") return 0;
  if (t === "boolean") return false;
  if (t === "array") return [];
  if (t === "object") return {};
  return "";
}

// P12: seed a params object so no field opens blank; the schema's own default
// wins over the type's zero-cost skeleton (mirroring the kernel's defaults).
export function schemaDefaults(schema: unknown): Record<string, unknown> {
  const { props } = specOf(schema);
  const out: Record<string, unknown> = {};
  for (const [k, spec] of Object.entries(props)) {
    out[k] = spec.default !== undefined ? spec.default : skeletonFor(spec);
  }
  return out;
}

function isLongText(key: string, spec: PropSpec): boolean {
  if (spec.format === "textarea") return true;
  return /prompt|body|description|notes|message|question/i.test(`${key} ${spec.description ?? ""}`);
}

export function SchemaFormV2({
  schema,
  value,
  onChange,
  errors,
  onValidity,
}: {
  schema: unknown;
  value: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
  errors?: Record<string, string>;
  onValidity?: (valid: boolean) => void;
}) {
  // Per-field JSON escape-hatch drafts: the draft is authoritative while the
  // field is being edited; an unparseable draft never reaches value.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [jsonErrs, setJsonErrs] = useState<Record<string, string>>({});
  const invalid = Object.keys(jsonErrs).length > 0;
  useEffect(() => {
    onValidity?.(!invalid);
  }, [invalid, onValidity]);

  const { props, required } = specOf(schema);
  const keys = Object.keys(props);
  if (keys.length === 0) return null;

  const ordered = [...keys.filter((k) => required.has(k)), ...keys.filter((k) => !required.has(k))];
  const set = (k: string, v: unknown) => onChange({ ...value, [k]: v });

  function clearJsonErr(path: string) {
    setJsonErrs((m) => {
      if (!(path in m)) return m;
      const next = { ...m };
      delete next[path];
      return next;
    });
  }

  function jsonField(
    path: string,
    key: string,
    spec: PropSpec,
    shown: unknown,
    commit: (v: unknown) => void,
    isReq: boolean,
  ): ReactNode {
    const seeded =
      shown === undefined ? (spec.default !== undefined ? spec.default : skeletonFor(spec)) : shown;
    const text = drafts[path] ?? prettyJson(seeded);
    return (
      <Field key={path} label={key} hint={spec.description} required={isReq} error={errors?.[path]} wide>
        <JsonDisclosure
          value={text}
          error={jsonErrs[path]}
          onChange={(t) => {
            setDrafts((d) => ({ ...d, [path]: t }));
            if (t.trim() === "") {
              clearJsonErr(path);
              commit(undefined);
              return;
            }
            try {
              const parsed: unknown = JSON.parse(t);
              clearJsonErr(path);
              commit(parsed);
            } catch {
              setJsonErrs((m) => ({ ...m, [path]: "invalid JSON" }));
            }
          }}
        />
      </Field>
    );
  }

  function control(
    path: string,
    key: string,
    spec: PropSpec,
    cur: unknown,
    commit: (v: unknown) => void,
    isReq: boolean,
    depth: number,
  ): ReactNode {
    const shown = cur === undefined ? spec.default : cur;
    const err = errors?.[path];
    const wrap = (ctl: ReactNode, wide?: boolean) => (
      <Field key={path} label={key} hint={spec.description} required={isReq} error={err} wide={wide}>
        {ctl}
      </Field>
    );

    if (spec.enum && spec.enum.length > 0) {
      const v = shown == null ? "" : String(shown);
      const opts = spec.enum.map((e) => ({ value: e, label: e }));
      if (spec.enum.length <= 4) {
        return wrap(<SegmentedV2 value={v} ariaLabel={key} onChange={commit} options={opts} />);
      }
      // no fake blank when a value or default exists (L5/P3)
      return wrap(
        <Select
          value={v}
          ariaLabel={key}
          onChange={commit}
          options={v === "" ? [{ value: "", label: "Choose..." }, ...opts] : opts}
        />,
      );
    }
    if (spec.type === "boolean") {
      return wrap(
        <SegmentedV2
          value={shown ? "true" : "false"}
          ariaLabel={key}
          onChange={(nv) => commit(nv === "true")}
          options={[
            { value: "true", label: "Yes" },
            { value: "false", label: "No" },
          ]}
        />,
      );
    }
    if (spec.type === "number" || spec.type === "integer") {
      if (typeof spec.minimum === "number" && typeof spec.maximum === "number") {
        return wrap(
          <Stepper
            value={typeof shown === "number" ? shown : spec.minimum}
            min={spec.minimum}
            max={spec.maximum}
            ariaLabel={key}
            onChange={commit}
          />,
        );
      }
      return wrap(
        <input
          type="number"
          aria-label={key}
          value={shown == null ? "" : String(shown)}
          onChange={(e) => commit(e.target.value === "" ? undefined : Number(e.target.value))}
        />,
      );
    }
    if (spec.type === "array") {
      const items = spec.items;
      const arr = Array.isArray(shown) ? shown.map((x) => String(x)) : [];
      if (items?.enum && items.enum.length > 0) {
        return wrap(
          <ChipPicker
            value={arr}
            onChange={commit}
            options={items.enum.map((e) => ({ value: e }))}
            ariaLabel={key}
          />,
          true,
        );
      }
      const scalar = !items || ((items.type === undefined || items.type === "string") && !items.properties);
      if (scalar) {
        // array of scalars: free-entry chips, not a JSON punt (P9)
        return wrap(<ChipPicker value={arr} onChange={commit} allowFree ariaLabel={key} />, true);
      }
      return jsonField(path, key, spec, shown, commit, isReq);
    }
    const objectish = spec.type === "object" || (spec.type === undefined && spec.properties != null);
    if (objectish) {
      const subProps = spec.properties ?? {};
      const subKeys = Object.keys(subProps);
      const openMap = spec.additionalProperties !== undefined && spec.additionalProperties !== false;
      if (depth === 0 && subKeys.length > 0 && !openMap) {
        const obj = (
          shown && typeof shown === "object" && !Array.isArray(shown) ? shown : {}
        ) as Record<string, unknown>;
        const subReq = new Set(spec.required ?? []);
        const orderedSub = [
          ...subKeys.filter((s) => subReq.has(s)),
          ...subKeys.filter((s) => !subReq.has(s)),
        ];
        return (
          <div key={path} className="ux-inset ux-field--wide">
            <span className="ux-inset__label">
              {key}
              {isReq && (
                <em className="ux-field__req" title="required">
                  {" "}
                  *
                </em>
              )}
            </span>
            {spec.description && <span className="ux-field__hint">{spec.description}</span>}
            <div className="ux-inset__grid">
              {orderedSub.map((sub) =>
                control(
                  `${path}.${sub}`,
                  sub,
                  subProps[sub],
                  obj[sub],
                  (nv) => commit({ ...obj, [sub]: nv }),
                  subReq.has(sub),
                  depth + 1,
                ),
              )}
            </div>
          </div>
        );
      }
      return jsonField(path, key, spec, shown, commit, isReq);
    }
    if (spec.type === "string" || spec.type === undefined) {
      const v = shown == null ? "" : String(shown);
      if (isLongText(key, spec)) {
        return wrap(
          <textarea aria-label={key} rows={3} value={v} onChange={(e) => commit(e.target.value)} />,
          true,
        );
      }
      return wrap(<input aria-label={key} value={v} onChange={(e) => commit(e.target.value)} />);
    }
    return jsonField(path, key, spec, shown, commit, isReq);
  }

  return (
    <div className="form__grid">
      {ordered.map((k) => control(k, k, props[k], value[k], (v) => set(k, v), required.has(k), 0))}
    </div>
  );
}
