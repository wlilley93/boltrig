import { Field, Select } from "@/panels/ux";
import { SegmentedV2 } from "@/panels/uxForm";
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { ForbiddenGrantsField } from "./ForbiddenGrantsField";
import type { EvalState } from "./useEvalState";

export function CreateCaseForm({ s }: { s: EvalState }) {
  return (
    <div className="form">
      <div className="form__title">1. Create a case</div>
      <div className="form__grid">
        <Field label="Test" hint="Is the thing under test a skill or a workflow?">
          <SegmentedV2
            value={s.targetKind}
            ariaLabel="Target kind"
            onChange={s.changeTargetKind}
            options={[
              { value: "skill", label: "A skill" },
              { value: "workflow", label: "A workflow" },
            ]}
          />
        </Field>
        <Field label="Which one" hint="The skill or workflow this case runs.">
          <Select value={s.targetRef} ariaLabel="Target" onChange={s.setTargetRef} options={s.targetOptions} />
        </Field>
        <Field
          label="Case id"
          hint="Leave blank to auto-generate. Set one to overwrite an existing case."
        >
          <input value={s.caseId} onChange={(e) => s.setCaseId(e.target.value)} />
        </Field>
      </div>

      <Field
        label="Input"
        hint="The input passed to the skill or workflow under test, as JSON."
        example='{"ticket_id": "4821"}'
      >
        <textarea className="code" value={s.input} onChange={(e) => s.setInput(e.target.value)} />
      </Field>

      <ForbiddenGrantsField s={s} />

      <details>
        <summary className="ux-hint" style={{ cursor: "pointer" }}>
          Advanced: edit assertions as JSON
        </summary>
        <Field label="Assertions (JSON)" hint="The full assertion object. forbidden_grants is the supported key.">
          <textarea className="code" value={s.assertions} onChange={(e) => s.setAssertions(e.target.value)} />
        </Field>
      </details>

      <Field label="Labels" hint="Tags to group cases." example="regression, security">
        <input value={s.labels} onChange={(e) => s.setLabels(e.target.value)} />
      </Field>

      {s.createMutation.pending && (
        <PendingHumanCard
          hitlRequestId={s.createMutation.pending.id}
          noun="control"
          verb="control.eval_case.upsert"
          sentParams={s.createMutation.pending.params}
          onApplied={s.createMutation.onPendingApplied}
          onDenied={s.createMutation.onPendingDenied}
          onReset={s.createMutation.resetPending}
        />
      )}

      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={s.createMutation.busy || s.createMutation.pending !== null}
          onClick={s.createCase}
        >
          {s.createMutation.busy ? "Creating..." : "Create case"}
        </button>
        {s.createMsg && <span className="ok">{s.createMsg}</span>}
        {s.createError && <span className="error">{s.createError}</span>}
        {s.createMutation.error && <span className="error">{s.createMutation.error}</span>}
      </div>
    </div>
  );
}
