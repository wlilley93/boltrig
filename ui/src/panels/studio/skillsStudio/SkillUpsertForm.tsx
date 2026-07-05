import type { VerbInfo } from "@/api/types";
import { Hint } from "@/panels/ux";

import { AckLine } from "../AckLine";
import { SkillContextFields } from "./SkillContextFields";
import { SkillIdentityFields } from "./SkillIdentityFields";
import { SkillPermissionsFields } from "./SkillPermissionsFields";
import { useSkillForm } from "./useSkillForm";

// Create-or-update form for a single skill. The caller passes the visible verbs
// (for the "add a permission" buttons) and a reload callback fired on success.
export function SkillUpsertForm({
  verbs,
  onSaved,
}: {
  verbs: VerbInfo[];
  onSaved: () => void;
}) {
  const s = useSkillForm(onSaved);

  return (
    <div className="form">
      <div className="form__title">Create or update a skill</div>
      <Hint>A skill gives an agent an instruction plus the permissions it needs.</Hint>
      <SkillIdentityFields s={s} />
      <SkillPermissionsFields s={s} verbs={verbs} />
      <SkillContextFields s={s} />
      <div className="form__actions">
        <button className="btn btn--primary" disabled={s.busy} onClick={s.upsert}>
          {s.busy ? "..." : "Save skill"}
        </button>
        <AckLine ack={s.ack} />
        {s.error && <span className="error">{s.error}</span>}
      </div>
    </div>
  );
}
