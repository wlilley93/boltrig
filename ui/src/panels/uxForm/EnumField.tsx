import { Select } from "../ux";
import { SegmentedV2 } from "./SegmentedV2";
import { FieldWrapper } from "./FieldWrapper";
import type { SchemaFieldContext } from "./schemaTypes";

export interface EnumFieldProps {
  ctx: SchemaFieldContext;
}

export function EnumField({ ctx }: EnumFieldProps) {
  const { spec, value, onChange, fieldKey } = ctx;
  const v = value == null ? "" : String(value);
  const opts = (spec.enum ?? []).map((e) => ({ value: e, label: e }));
  if (opts.length <= 4) {
    return (
      <FieldWrapper ctx={ctx}>
        <SegmentedV2 value={v} ariaLabel={fieldKey} onChange={onChange} options={opts} />
      </FieldWrapper>
    );
  }
  // no fake blank when a value or default exists (L5/P3)
  return (
    <FieldWrapper ctx={ctx}>
      <Select value={v} ariaLabel={fieldKey} onChange={onChange} options={v === "" ? [{ value: "", label: "Choose..." }, ...opts] : opts} />
    </FieldWrapper>
  );
}
