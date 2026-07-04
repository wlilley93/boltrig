import { FieldWrapper } from "./FieldWrapper";
import { isLongText } from "./schemaDefaults";
import type { SchemaFieldContext } from "./schemaTypes";

export interface StringFieldProps {
  ctx: SchemaFieldContext;
}

export function StringField({ ctx }: StringFieldProps) {
  const { spec, value, onChange, fieldKey } = ctx;
  const v = value == null ? "" : String(value);
  if (isLongText(fieldKey, spec)) {
    return (
      <FieldWrapper ctx={ctx} wide>
        <textarea aria-label={fieldKey} rows={3} value={v} onChange={(e) => onChange(e.target.value)} />
      </FieldWrapper>
    );
  }
  return (
    <FieldWrapper ctx={ctx}>
      <input aria-label={fieldKey} value={v} onChange={(e) => onChange(e.target.value)} />
    </FieldWrapper>
  );
}
