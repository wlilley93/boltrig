import type { VerbInfo } from "@/api/types";
import { Field } from "@/panels/ux";

import type { SkillFormState } from "./useSkillForm";

export function SkillPermissionsFields({
  s,
  verbs,
}: {
  s: SkillFormState;
  verbs: VerbInfo[];
}) {
  return (
    <>
      <Field
        label="Permissions"
        hint="The verbs an agent using this skill may call (comma-separated). It still can't exceed the caller's own grants."
      >
        <input
          value={s.grants}
          placeholder="ticket.read, ticket.comment"
          onChange={(e) => s.setGrants(e.target.value)}
        />
      </Field>
      {verbs.length > 0 && (
        <div className="kv">
          <span className="ux-hint">Add a permission:</span>
          {verbs.map((v) => (
            <button
              key={v.id}
              type="button"
              className="tag tag--accent"
              style={{ cursor: "pointer" }}
              onClick={() => s.addGrant(v.id)}
            >
              {v.id}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
