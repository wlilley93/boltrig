import type { PropSpec } from "./schemaTypes";
import { skeletonFor } from "./schemaDefaults";
import type { SchemaFieldContext } from "./schemaTypes";
import { ObjectArrayRow } from "./ObjectArrayRow";

export interface ObjectArrayFieldProps {
  ctx: SchemaFieldContext;
  items: PropSpec;
  rows: unknown[];
}

export function ObjectArrayField({ ctx, items, rows }: ObjectArrayFieldProps) {
  const { path, fieldKey, spec, onChange, required } = ctx;
  const itemProps = items.properties ?? {};
  const itemReq = new Set(items.required ?? []);
  const itemKeys = Object.keys(itemProps);
  const orderedItem = [
    ...itemKeys.filter((k) => itemReq.has(k)),
    ...itemKeys.filter((k) => !itemReq.has(k)),
  ];
  const singular = fieldKey.replace(/s$/, "");

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
    onChange(arr);
  };

  const removeRow = (i: number) => {
    const arr = rows.slice();
    arr.splice(i, 1);
    onChange(arr);
  };

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
      {rows.length === 0 && <span className="ux-field__hint">None yet. Add one below.</span>}
      <div className="stack">
        {rows.map((row, i) => (
          <ObjectArrayRow
            key={i}
            index={i}
            singular={singular}
            row={row}
            itemProps={itemProps}
            itemReq={itemReq}
            orderedItem={orderedItem}
            path={path}
            depth={ctx.depth}
            errors={ctx.errors}
            drafts={ctx.drafts}
            setDrafts={ctx.setDrafts}
            jsonErrs={ctx.jsonErrs}
            setJsonErrs={ctx.setJsonErrs}
            clearJsonErr={ctx.clearJsonErr}
            setRow={setRow}
            removeRow={removeRow}
          />
        ))}
      </div>
      <div>
        <button type="button" className="btn btn--sm" onClick={() => onChange([...rows, seedRow()])}>
          Add {singular}
        </button>
      </div>
    </div>
  );
}
