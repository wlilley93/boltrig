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

import { Fragment, useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { prettyJson } from "./shared";
import { CONSEQUENCE, Field, Hint, Select, StatusBadge } from "./ux";
import { SegmentedV2 } from "@/panels/uxForm/SegmentedV2";
import { ChipPicker } from "@/panels/uxForm/ChipPicker";
import type { ChipOption } from "@/panels/uxForm/ChipPicker";

export { nextEnabled } from "@/panels/uxForm/nextEnabled";
export { Switch, useSavedWisp } from "@/panels/uxForm/Switch";
export { SegmentedV2 } from "@/panels/uxForm/SegmentedV2";
export { CardSelect, type CardOption } from "@/panels/uxForm/CardSelect";
export { ChipPicker, type ChipOption } from "@/panels/uxForm/ChipPicker";


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
export interface PropSpec {
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
  // Optional per-property custom control (the admin section flagships). When set,
  // SchemaFormV2 renders this component INSTEAD of deriving a control from the
  // type, so a shape the generic engine cannot express typedly (a role-mapping
  // row, a key/value map) still renders as structured controls rather than a JSON
  // blob. Rendered as a component (JSX element) so it may hold its own row-draft
  // state. The schema stays a client-side descriptor; schemaDefaults ignores this.
  editor?: (props: FieldEditorProps) => ReactNode;
}

// The contract a custom section editor (ui/src/panels/admin/editors/*) is handed
// by SchemaFormV2: the current value + a commit fn (undefined clears the key),
// plus the field framing (label, required, error) so the editor can wrap itself
// in a Field / inset consistently with the generic controls around it.
export interface FieldEditorProps {
  value: unknown;
  onChange: (v: unknown) => void;
  spec: PropSpec;
  path: string;
  label: string;
  required: boolean;
  error?: string;
}

// How deep the typed inset-group / row-card recursion goes before a nested object
// falls back to the per-field JSON escape hatch. One top-level group plus three
// more levels covers every shipped admin section (e.g. tier2[] -> budget, or
// runtimes.pi -> sandbox) without risking an unbounded recurse on a pathological
// schema.
const MAX_INSET_DEPTH = 4;

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

  // Array-of-objects: a labelled block of removable inset row-cards, each an
  // inset sub-form built from items.properties (recursing through control so a
  // row's own nested groups render too), plus an Add button that appends a
  // defaults-seeded row. Reuses the inset + button classes; no bare inputs.
  function objectArray(
    path: string,
    key: string,
    spec: PropSpec,
    items: PropSpec,
    rows: unknown[],
    commit: (v: unknown) => void,
    isReq: boolean,
    depth: number,
  ): ReactNode {
    const itemProps = items.properties ?? {};
    const itemReq = new Set(items.required ?? []);
    const itemKeys = Object.keys(itemProps);
    const orderedItem = [
      ...itemKeys.filter((k) => itemReq.has(k)),
      ...itemKeys.filter((k) => !itemReq.has(k)),
    ];
    const singular = key.replace(/s$/, "");
    const seedRow = (): Record<string, unknown> => {
      const o: Record<string, unknown> = {};
      for (const [k, s] of Object.entries(itemProps)) {
        o[k] = s.default !== undefined ? s.default : skeletonFor(s);
      }
      return o;
    };
    const setRow = (i: number, next: Record<string, unknown>) => {
      const arr = rows.slice();
      arr[i] = next;
      commit(arr);
    };
    const removeRow = (i: number) => {
      const arr = rows.slice();
      arr.splice(i, 1);
      commit(arr);
    };
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
        {rows.length === 0 && <span className="ux-field__hint">None yet. Add one below.</span>}
        <div className="stack">
          {rows.map((row, i) => {
            const obj = (
              row && typeof row === "object" && !Array.isArray(row) ? row : {}
            ) as Record<string, unknown>;
            return (
              <div key={i} className="ux-inset">
                <span
                  className="ux-inset__label"
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
                >
                  <span>
                    {singular} {i + 1}
                  </span>
                  <button
                    type="button"
                    className="btn btn--sm btn--ghost"
                    aria-label={`Remove ${singular} ${i + 1}`}
                    onClick={() => removeRow(i)}
                  >
                    Remove
                  </button>
                </span>
                <div className="ux-inset__grid">
                  {orderedItem.map((sub) =>
                    control(
                      `${path}.${i}.${sub}`,
                      sub,
                      itemProps[sub],
                      obj[sub],
                      (nv) => setRow(i, { ...obj, [sub]: nv }),
                      itemReq.has(sub),
                      depth + 1,
                    ),
                  )}
                </div>
              </div>
            );
          })}
        </div>
        <div>
          <button type="button" className="btn btn--sm" onClick={() => commit([...rows, seedRow()])}>
            Add {singular}
          </button>
        </div>
      </div>
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

    // A section descriptor may pin a dedicated editor for a flagship shape the
    // generic engine cannot express typedly (identity.role_mappings, the models /
    // notifications / chat key-value maps). It renders itself, framing included.
    if (spec.editor) {
      const Editor = spec.editor;
      return (
        <Editor
          key={path}
          value={shown}
          onChange={commit}
          spec={spec}
          path={path}
          label={key}
          required={isReq}
          error={err}
        />
      );
    }

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
      // array of objects: a list of removable inset row-cards, each an inset
      // sub-form from items.properties, with an Add button (P9). The JSON escape
      // hatch stays only for a truly shapeless item (no properties).
      const itemProps = items?.properties ?? {};
      if (Object.keys(itemProps).length > 0) {
        return objectArray(path, key, spec, items!, Array.isArray(shown) ? shown : [], commit, isReq, depth);
      }
      return jsonField(path, key, spec, shown, commit, isReq);
    }
    const objectish = spec.type === "object" || (spec.type === undefined && spec.properties != null);
    if (objectish) {
      const subProps = spec.properties ?? {};
      const subKeys = Object.keys(subProps);
      const openMap = spec.additionalProperties !== undefined && spec.additionalProperties !== false;
      // A closed object with named properties renders as a labelled inset group,
      // recursing so nested groups (budget, sandbox, retrieval) render too, not
      // just the top level. Only a genuinely open map (additionalProperties, no
      // named shape) or a pathologically deep schema keeps the JSON escape hatch.
      if (subKeys.length > 0 && !openMap && depth < MAX_INSET_DEPTH) {
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
