import { Field, Select } from "@/panels/ux";
import { SegmentedV2 } from "@/panels/uxForm";

import type { BindingFormState } from "./useBindingForm";

export function BindingTargetFields({ s }: { s: BindingFormState }) {
  return (
    <div className="form__grid">
      <Field label="Verb" hint="The action to wire up.">
        <Select value={s.verbId} ariaLabel="Verb" onChange={s.setVerbId} options={s.verbOptions} />
      </Field>
      <Field label="Runs via" hint="An adapter (a service) or an agent (a reasoning model).">
        <SegmentedV2
          value={s.targetType}
          ariaLabel="Target type"
          onChange={s.changeTargetType}
          options={[
            { value: "adapter", label: "An adapter" },
            { value: "agent", label: "An agent" },
          ]}
        />
      </Field>
      <Field
        label={s.targetType === "adapter" ? "Which adapter" : "Which agent"}
        hint={
          s.targetType === "adapter"
            ? "The registered adapter that fulfils this verb."
            : "The agent id that fulfils this verb."
        }
      >
        {s.targetType === "adapter" ? (
          <Select value={s.targetRef} ariaLabel="Adapter" onChange={s.setTargetRef} options={s.adapterOptions} />
        ) : (
          <input value={s.targetRef} onChange={(e) => s.setTargetRef(e.target.value)} />
        )}
      </Field>
    </div>
  );
}
