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

import { useEffect, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { prettyJson } from "./shared";
import { Field, Select } from "./ux";
import { SegmentedV2 } from "@/panels/uxForm/SegmentedV2";
import { ChipPicker } from "@/panels/uxForm/ChipPicker";
import type { ChipOption } from "@/panels/uxForm/ChipPicker";
import { Stepper } from "@/panels/uxForm/Stepper";
import { JsonDisclosure } from "@/panels/uxForm/JsonDisclosure";

export { nextEnabled } from "@/panels/uxForm/nextEnabled";
export { Switch, useSavedWisp } from "@/panels/uxForm/Switch";
export { SegmentedV2 } from "@/panels/uxForm/SegmentedV2";
export { CardSelect, type CardOption } from "@/panels/uxForm/CardSelect";
export { ChipPicker, type ChipOption } from "@/panels/uxForm/ChipPicker";


export { EntityPicker, type EntityItem, type EntityGroup } from "@/panels/uxForm/EntityPicker";

export { ScopeBuilder, type ScopeVerb } from "@/panels/uxForm/ScopeBuilder";
export { grantMatches, scopeMatches } from "@/panels/uxForm/scopeMatches";

export { Stepper } from "@/panels/uxForm/Stepper";

export { JsonDisclosure } from "@/panels/uxForm/JsonDisclosure";

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
