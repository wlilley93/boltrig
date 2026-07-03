// Typed editors for the admin sections whose value is an open key/value MAP
// (additionalProperties), which SchemaFormV2 cannot express from the schema alone
// and would otherwise punt to a JSON blob: models.prices (model -> micros),
// notifications.defaults (event -> {channel}), chat.skills_by_role (role ->
// skills). One presentational KeyValueList core renders removable key + value
// rows with an Add button; three thin wrappers configure the key control (a free
// text key, or a Select over a fixed value space) and the value control. Reuses
// the form register + the inset/button classes; no JSON.

import type { ReactNode } from "react";

import type { FieldEditorProps } from "../../uxForm";
import { ChipPicker } from "../../uxForm";
import { Field, ROLE_OPTIONS, Select } from "../../ux";
import type { Option } from "../../ux";

const HEADER_STYLE = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
} as const;

// The channels a notification default may route to (mirrors the manifest's
// teams/email/slack; kept local so the editor stays presentational).
const CHANNEL_OPTIONS: Option[] = [
  { value: "teams", label: "Teams" },
  { value: "email", label: "Email" },
  { value: "slack", label: "Slack" },
];

interface KeyValueConfig {
  // How a NEW key is entered: free text, or picked from a fixed value space.
  keyOptions?: Option[];
  keyLabel: string;
  keyHint?: string;
  keyPlaceholder?: string;
  addLabel: string;
  emptyHint: string;
  // Render the value control for a row; onChange writes the new value back.
  renderValue: (val: unknown, onChange: (v: unknown) => void, keyName: string) => ReactNode;
  // A blank value for a freshly-added row.
  newValue: () => unknown;
  // The next free key to seed an added row with when the key is a Select (the
  // first option not already used); free-text keys start empty.
  seedKey?: (used: string[]) => string;
}

function asMap(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function KeyValueList({ field, config }: { field: FieldEditorProps; config: KeyValueConfig }) {
  const map = asMap(field.value);
  const entries = Object.entries(map);
  const used = entries.map(([k]) => k);

  // Rebuild the object from an index-addressed entries array so key order stays
  // stable across edits (rename replaces the pair at its index; the last write of
  // a colliding key wins on serialise, an acceptable admin edge over a JSON blob).
  const commit = (next: [string, unknown][]) => field.onChange(Object.fromEntries(next));
  const setKey = (i: number, k: string) =>
    commit(entries.map((e, idx) => (idx === i ? [k, e[1]] : e)));
  const setVal = (i: number, v: unknown) =>
    commit(entries.map((e, idx) => (idx === i ? [e[0], v] : e)));
  const remove = (i: number) => commit(entries.filter((_, idx) => idx !== i));
  const add = () => {
    const k = config.keyOptions
      ? (config.seedKey?.(used) ??
        config.keyOptions.find((o) => !used.includes(o.value))?.value ??
        "")
      : "";
    commit([...entries, [k, config.newValue()]]);
  };

  return (
    <div className="ux-inset ux-field--wide">
      <span className="ux-inset__label">
        {field.label}
        {field.required && (
          <em className="ux-field__req" title="required">
            {" "}
            *
          </em>
        )}
      </span>
      {field.spec.description && (
        <span className="ux-field__hint">{field.spec.description}</span>
      )}
      {field.error != null && (
        <span className="ux-field__error" role="alert">
          {field.error}
        </span>
      )}
      {entries.length === 0 && <span className="ux-field__hint">{config.emptyHint}</span>}
      <div className="stack">
        {entries.map(([k, v], i) => (
          <div key={i} className="ux-inset">
            <span className="ux-inset__label" style={HEADER_STYLE}>
              <span>{k || `Entry ${i + 1}`}</span>
              <button
                type="button"
                className="btn btn--sm btn--ghost"
                aria-label={`Remove entry ${i + 1}`}
                onClick={() => remove(i)}
              >
                Remove
              </button>
            </span>
            <div className="ux-inset__grid">
              <Field label={config.keyLabel} hint={config.keyHint}>
                {config.keyOptions ? (
                  <Select
                    ariaLabel={config.keyLabel}
                    value={k}
                    onChange={(nv) => setKey(i, nv)}
                    options={
                      k && config.keyOptions.some((o) => o.value === k)
                        ? config.keyOptions
                        : [{ value: k, label: k || "Choose..." }, ...config.keyOptions]
                    }
                  />
                ) : (
                  <input
                    aria-label={config.keyLabel}
                    placeholder={config.keyPlaceholder}
                    value={k}
                    onChange={(e) => setKey(i, e.target.value)}
                  />
                )}
              </Field>
              {config.renderValue(v, (nv) => setVal(i, nv), k)}
            </div>
          </div>
        ))}
      </div>
      <div>
        <button type="button" className="btn btn--sm" onClick={add}>
          {config.addLabel}
        </button>
      </div>
    </div>
  );
}

// models.prices: model id -> micros-per-token (an unbounded positive integer, so
// a plain number input, the same pattern SchemaFormV2 uses for unbounded numbers).
export function PriceList(field: FieldEditorProps) {
  return (
    <KeyValueList
      field={field}
      config={{
        keyLabel: "Model",
        keyHint: "The model id charged at this price.",
        keyPlaceholder: "claude-sonnet-4-6",
        addLabel: "Add price",
        emptyHint: "No prices yet. A model absent here falls back to its cost-tier default.",
        newValue: () => 0,
        renderValue: (val, onChange) => (
          <Field label="Micros / token" hint="Price in micros per token for budgets and cost true-up.">
            <input
              type="number"
              aria-label="Micros per token"
              value={typeof val === "number" ? String(val) : ""}
              onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
            />
          </Field>
        ),
      }}
    />
  );
}

// notifications.defaults: event -> { channel }. Both the event key and the
// channel value come from a fixed space, so both are Selects.
export function NotificationDefaultsList(field: FieldEditorProps) {
  const EVENT_OPTIONS: Option[] = [
    { value: "approval", label: "Approval" },
    { value: "escalation", label: "Escalation" },
    { value: "budget_alert", label: "Budget alert" },
    { value: "work_status", label: "Work status" },
    { value: "error", label: "Error" },
  ];
  return (
    <KeyValueList
      field={field}
      config={{
        keyOptions: EVENT_OPTIONS,
        keyLabel: "Event",
        keyHint: "The notification event this default routes.",
        addLabel: "Add default",
        emptyHint: "No routing defaults yet.",
        newValue: () => ({ channel: CHANNEL_OPTIONS[0].value }),
        renderValue: (val, onChange) => {
          const channel =
            val && typeof val === "object" && !Array.isArray(val)
              ? String((val as Record<string, unknown>).channel ?? "")
              : "";
          return (
            <Field label="Channel" hint="Where this event is delivered by default.">
              <Select
                ariaLabel="Channel"
                value={channel}
                onChange={(v) => onChange({ channel: v })}
                options={
                  channel && CHANNEL_OPTIONS.some((o) => o.value === channel)
                    ? CHANNEL_OPTIONS
                    : [{ value: channel, label: channel || "Choose..." }, ...CHANNEL_OPTIONS]
                }
              />
            </Field>
          );
        },
      }}
    />
  );
}

// chat.skills_by_role: role -> skill set. The role key is a Select over the
// canonical roles; the value is a free-entry chip list of skill patterns.
export function SkillsByRoleList(field: FieldEditorProps) {
  return (
    <KeyValueList
      field={field}
      config={{
        keyOptions: [...ROLE_OPTIONS],
        keyLabel: "Role",
        keyHint: "The caller role a bare chat turn's skill set applies to.",
        addLabel: "Add role",
        emptyHint: "No per-role skills yet. Unmapped roles use the default skills above.",
        newValue: () => [],
        renderValue: (val, onChange): ReactNode => (
          <Field
            label="Skills"
            hint="Skills a bare turn spawns with (intersected with the caller's grants, so it can only reduce authority)."
          >
            <ChipPicker
              value={Array.isArray(val) ? val.map((x) => String(x)) : []}
              onChange={(v) => onChange(v)}
              allowFree
              ariaLabel="Skills"
            />
          </Field>
        ),
      }}
    />
  );
}
