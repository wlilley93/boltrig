import { ArrayField } from "./ArrayField";
import { BooleanField } from "./BooleanField";
import { EnumField } from "./EnumField";
import { JsonField } from "./JsonField";
import { NumberField } from "./NumberField";
import { ObjectField } from "./ObjectField";
import { StringField } from "./StringField";
import type { SchemaFieldContext } from "./schemaTypes";

export interface ControlFieldProps {
  ctx: SchemaFieldContext;
}

export function ControlField({ ctx }: ControlFieldProps) {
  const { spec } = ctx;
  const shown = ctx.value === undefined ? spec.default : ctx.value;

  // A section descriptor may pin a dedicated editor for a flagship shape the
  // generic engine cannot express typedly (identity.role_mappings, the models /
  // notifications / chat key-value maps). It renders itself, framing included.
  if (spec.editor) {
    const Editor = spec.editor;
    return (
      <Editor
        key={ctx.path}
        value={shown}
        onChange={ctx.onChange}
        spec={spec}
        path={ctx.path}
        label={ctx.fieldKey}
        required={ctx.required}
        error={ctx.errors?.[ctx.path]}
      />
    );
  }

  const childCtx: SchemaFieldContext = { ...ctx, value: shown };

  if (spec.enum && spec.enum.length > 0) return <EnumField ctx={childCtx} />;
  if (spec.type === "boolean") return <BooleanField ctx={childCtx} />;
  if (spec.type === "number" || spec.type === "integer") return <NumberField ctx={childCtx} />;
  if (spec.type === "array") return <ArrayField ctx={childCtx} />;
  const objectish = spec.type === "object" || (spec.type === undefined && spec.properties != null);
  if (objectish) return <ObjectField ctx={childCtx} />;
  if (spec.type === "string" || spec.type === undefined) return <StringField ctx={childCtx} />;
  return <JsonField ctx={childCtx} />;
}
