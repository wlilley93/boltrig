import { Stepper } from "./Stepper";
import { FieldWrapper } from "./FieldWrapper";
import type { SchemaFieldContext } from "./schemaTypes";

export interface NumberFieldProps {
  ctx: SchemaFieldContext;
}

export function NumberField({ ctx }: NumberFieldProps) {
  const { spec, value, onChange, fieldKey } = ctx;
  if (typeof spec.minimum === "number" && typeof spec.maximum === "number") {
    return (
      <FieldWrapper ctx={ctx}>
        <Stepper
          value={typeof value === "number" ? value : spec.minimum}
          min={spec.minimum}
          max={spec.maximum}
          ariaLabel={fieldKey}
          onChange={onChange}
        />
      </FieldWrapper>
    );
  }
  return (
    <FieldWrapper ctx={ctx}>
      <input
        type="number"
        aria-label={fieldKey}
        value={value == null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      />
    </FieldWrapper>
  );
}
