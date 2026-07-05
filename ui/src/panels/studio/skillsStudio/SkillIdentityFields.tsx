import { Field } from "@/panels/ux";

import type { SkillFormState } from "./useSkillForm";

export function SkillIdentityFields({ s }: { s: SkillFormState }) {
  return (
    <>
      <div className="form__grid">
        <Field label="Skill id" hint="Lowercase, dotted, unique." example="triage.summarise">
          <input value={s.id} onChange={(e) => s.setId(e.target.value)} />
        </Field>
        <Field label="Version" hint="Semver; bump on every change.">
          <input value={s.version} onChange={(e) => s.setVersion(e.target.value)} />
        </Field>
      </div>
      <Field
        label="Instruction"
        hint="The text injected into the agent when this skill loads."
        example="Summarise the ticket in 3 bullets"
      >
        <textarea
          className="code"
          value={s.fragment}
          onChange={(e) => s.setFragment(e.target.value)}
        />
      </Field>
    </>
  );
}
