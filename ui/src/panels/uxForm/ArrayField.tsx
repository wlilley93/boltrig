import { ChipPicker } from "./ChipPicker";
import { FieldWrapper } from "./FieldWrapper";
import { JsonField } from "./JsonField";
import { ObjectArrayField } from "./ObjectArrayField";
import type { SchemaFieldContext } from "./schemaTypes";

export interface ArrayFieldProps {
  ctx: SchemaFieldContext;
}

export function ArrayField({ ctx }: ArrayFieldProps) {
  const { spec, value, onChange, fieldKey } = ctx;
  const items = spec.items;
  const arr = Array.isArray(value) ? value.map((x) => String(x)) : [];

  if (items?.enum && items.enum.length > 0) {
    return (
      <FieldWrapper ctx={ctx} wide>
        <ChipPicker
          value={arr}
          onChange={onChange}
          options={items.enum.map((e) => ({ value: e }))}
          ariaLabel={fieldKey}
        />
      </FieldWrapper>
    );
  }

  const scalar = !items || ((items.type === undefined || items.type === "string") && !items.properties);
  if (scalar) {
    // array of scalars: free-entry chips, not a JSON punt (P9)
    return (
      <FieldWrapper ctx={ctx} wide>
        <ChipPicker value={arr} onChange={onChange} allowFree ariaLabel={fieldKey} />
      </FieldWrapper>
    );
  }

  // array of objects: a list of removable inset row-cards, each an inset
  // sub-form from items.properties, with an Add button (P9). The JSON escape
  // hatch stays only for a truly shapeless item (no properties).
  const itemProps = items?.properties ?? {};
  if (Object.keys(itemProps).length > 0) {
    return <ObjectArrayField ctx={ctx} items={items!} rows={Array.isArray(value) ? value : []} />;
  }
  return <JsonField ctx={ctx} />;
}
