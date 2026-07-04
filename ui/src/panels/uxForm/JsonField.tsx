import { prettyJson } from "../shared";
import { Field } from "../ux";
import { JsonDisclosure } from "./JsonDisclosure";
import { skeletonFor } from "./schemaDefaults";
import type { SchemaFieldContext } from "./schemaTypes";

export interface JsonFieldProps {
  ctx: SchemaFieldContext;
}

export function JsonField({ ctx }: JsonFieldProps) {
  const { path, fieldKey, spec, value, onChange, required, errors, drafts, setDrafts, jsonErrs, setJsonErrs, clearJsonErr } = ctx;
  const seeded = value === undefined ? (spec.default !== undefined ? spec.default : skeletonFor(spec)) : value;
  const text = drafts[path] ?? prettyJson(seeded);
  return (
    <Field key={path} label={fieldKey} hint={spec.description} required={required} error={errors?.[path]} wide>
      <JsonDisclosure
        value={text}
        error={jsonErrs[path]}
        onChange={(t) => {
          setDrafts((d) => ({ ...d, [path]: t }));
          if (t.trim() === "") {
            clearJsonErr(path);
            onChange(undefined);
            return;
          }
          try {
            const parsed: unknown = JSON.parse(t);
            clearJsonErr(path);
            onChange(parsed);
          } catch {
            setJsonErrs((m) => ({ ...m, [path]: "invalid JSON" }));
          }
        }}
      />
    </Field>
  );
}
