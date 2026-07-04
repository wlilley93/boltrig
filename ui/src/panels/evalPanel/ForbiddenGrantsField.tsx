import { Field, Select } from "@/panels/ux";
import type { EvalState } from "./useEvalState";

// The guided chips + add-permission select for "permissions the run must NOT
// use". Backed by (and written back to) the assertions JSON via the hook.
export function ForbiddenGrantsField({ s }: { s: EvalState }) {
  return (
    <Field
      label="Permissions the run must NOT use"
      hint="The case passes only if none of these appear in the run's actual permissions. This is the core safety check."
    >
      <div className="kv">
        {s.forbidden.length === 0 ? (
          <span className="ux-hint">None set - add one below.</span>
        ) : (
          s.forbidden.map((g) => (
            <button
              key={g}
              type="button"
              className="tag tag--accent"
              title="Remove"
              style={{ cursor: "pointer" }}
              onClick={() => s.toggleForbidden(g)}
            >
              {g} x
            </button>
          ))
        )}
      </div>
      <Select
        value=""
        ariaLabel="Add a forbidden permission"
        onChange={s.toggleForbidden}
        options={[
          { value: "", label: "Add a permission..." },
          ...s.verbs.filter((v) => !s.forbidden.includes(v.id)).map((v) => ({ value: v.id, label: v.id })),
        ]}
      />
    </Field>
  );
}
