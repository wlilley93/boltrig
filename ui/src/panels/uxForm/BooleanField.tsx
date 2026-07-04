import { SegmentedV2 } from "./SegmentedV2";
import { FieldWrapper } from "./FieldWrapper";
import type { SchemaFieldContext } from "./schemaTypes";

export interface BooleanFieldProps {
  ctx: SchemaFieldContext;
}

export function BooleanField({ ctx }: BooleanFieldProps) {
  const { value, onChange, fieldKey } = ctx;
  return (
    <FieldWrapper ctx={ctx}>
      <SegmentedV2
        value={value ? "true" : "false"}
        ariaLabel={fieldKey}
        onChange={(nv) => onChange(nv === "true")}
        options={[
          { value: "true", label: "Yes" },
          { value: "false", label: "No" },
        ]}
      />
    </FieldWrapper>
  );
}
