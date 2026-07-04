import type { ReactNode } from "react";

import { Field } from "../ux";
import type { SchemaFieldContext } from "./schemaTypes";

export interface FieldWrapperProps {
  ctx: SchemaFieldContext;
  wide?: boolean;
  children: ReactNode;
}

export function FieldWrapper({ ctx, wide, children }: FieldWrapperProps) {
  return (
    <Field key={ctx.path} label={ctx.fieldKey} hint={ctx.spec.description} required={ctx.required} error={ctx.errors?.[ctx.path]} wide={wide}>
      {children}
    </Field>
  );
}
