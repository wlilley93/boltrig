import { Field } from "@/panels/ux";

import type { SkillFormState } from "./useSkillForm";

export function SkillContextFields({ s }: { s: SkillFormState }) {
  return (
    <details>
      <summary className="ux-hint" style={{ cursor: "pointer" }}>
        Advanced: context requirements (JSON)
      </summary>
      <Field
        label="Context requirements (JSON)"
        hint="Fields the skill needs in context before it can run."
        example='{"requires": ["customer_id"]}'
      >
        <textarea
          className="code"
          value={s.ctxReq}
          onChange={(e) => s.setCtxReq(e.target.value)}
        />
      </Field>
    </details>
  );
}
