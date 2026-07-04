import { MAX_INSET_DEPTH } from "./schemaDefaults";
import { ControlField } from "./ControlField";
import { JsonField } from "./JsonField";
import type { SchemaFieldContext } from "./schemaTypes";

export interface ObjectFieldProps {
  ctx: SchemaFieldContext;
}

export function ObjectField({ ctx }: ObjectFieldProps) {
  const { spec, value, onChange, fieldKey, required, depth, errors, drafts, setDrafts, jsonErrs, setJsonErrs, clearJsonErr } = ctx;
  const subProps = spec.properties ?? {};
  const subKeys = Object.keys(subProps);
  const openMap = spec.additionalProperties !== undefined && spec.additionalProperties !== false;

  // A closed object with named properties renders as a labelled inset group,
  // recursing so nested groups (budget, sandbox, retrieval) render too, not
  // just the top level. Only a genuinely open map (additionalProperties, no
  // named shape) or a pathologically deep schema keeps the JSON escape hatch.
  if (subKeys.length > 0 && !openMap && depth < MAX_INSET_DEPTH) {
    const obj = (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as Record<string, unknown>;
    const subReq = new Set(spec.required ?? []);
    const orderedSub = [
      ...subKeys.filter((s) => subReq.has(s)),
      ...subKeys.filter((s) => !subReq.has(s)),
    ];
    return (
      <div className="ux-inset ux-field--wide">
        <span className="ux-inset__label">
          {fieldKey}
          {required && (
            <em className="ux-field__req" title="required">
              {" "}
              *
            </em>
          )}
        </span>
        {spec.description && <span className="ux-field__hint">{spec.description}</span>}
        <div className="ux-inset__grid">
          {orderedSub.map((sub) => {
            const childCtx: SchemaFieldContext = {
              path: `${ctx.path}.${sub}`,
              fieldKey: sub,
              spec: subProps[sub],
              value: obj[sub],
              onChange: (nv) => onChange({ ...obj, [sub]: nv }),
              required: subReq.has(sub),
              depth: depth + 1,
              errors,
              drafts,
              setDrafts,
              jsonErrs,
              setJsonErrs,
              clearJsonErr,
            };
            return <ControlField key={childCtx.path} ctx={childCtx} />;
          })}
        </div>
      </div>
    );
  }
  return <JsonField ctx={ctx} />;
}
