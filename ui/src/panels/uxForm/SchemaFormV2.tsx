import { ControlField } from "./ControlField";
import { specOf } from "./schemaDefaults";
import { useSchemaDrafts } from "./useSchemaDrafts";

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
  const { drafts, setDrafts, jsonErrs, setJsonErrs, clearJsonErr } = useSchemaDrafts(onValidity);

  const { props, required } = specOf(schema);
  const keys = Object.keys(props);
  if (keys.length === 0) return null;

  const ordered = [...keys.filter((k) => required.has(k)), ...keys.filter((k) => !required.has(k))];
  const set = (k: string, v: unknown) => onChange({ ...value, [k]: v });

  return (
    <div className="form__grid">
      {ordered.map((k) => (
        <ControlField
          key={k}
          ctx={{
            path: k,
            fieldKey: k,
            spec: props[k],
            value: value[k],
            onChange: (v) => set(k, v),
            required: required.has(k),
            depth: 0,
            errors,
            drafts,
            setDrafts,
            jsonErrs,
            setJsonErrs,
            clearJsonErr,
          }}
        />
      ))}
    </div>
  );
}

export type { PropSpec, FieldEditorProps } from "./schemaTypes";
export { schemaDefaults } from "./schemaDefaults";
