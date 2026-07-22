import { Field, InfoCallout, Select } from "@/panels/ux";
import { JsonDisclosure, SegmentedV2 } from "@/panels/uxForm";
import { ByChat } from "@/panels/uxFlow";
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { ForbiddenGrantsField } from "./ForbiddenGrantsField";
import type { EvalState } from "./useEvalState";

function objectJsonError(value: string): string | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
      ? null
      : "Enter a JSON object.";
  } catch {
    return "Enter valid JSON before requesting the change.";
  }
}

export function CreateCaseForm({ s }: { s: EvalState }) {
  const inputError = objectJsonError(s.input);
  const assertionsError = objectJsonError(s.assertions);
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

      <JsonDisclosure
        value={s.input}
        onChange={s.setInput}
        error={inputError}
        label="Advanced: edit case input as JSON"
        summaryNote="Defaults to an empty object"
      />

      <ForbiddenGrantsField s={s} />

      <JsonDisclosure
        value={s.assertions}
        onChange={s.setAssertions}
        error={assertionsError}
        label="Advanced: edit assertions as JSON"
        summaryNote="Forbidden grants are guided above"
      />

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

      <InfoCallout tone="consequence">
        This is a high-consequence change. It will pause for a human approval
        before it takes effect.
      </InfoCallout>

      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={
            inputError !== null ||
            assertionsError !== null ||
            s.createMutation.busy ||
            s.createMutation.pending !== null
          }
          onClick={s.createCase}
        >
          {s.createMutation.busy ? "Requesting..." : "Request case change"}
        </button>
        <ByChat
          phrase={`Create an evaluation case for ${s.targetRef || `this ${s.targetKind}`} that must not use ${s.forbidden.join(", ") || "forbidden permissions"}.`}
        />
        {s.createMsg && <span className="ok">{s.createMsg}</span>}
        {s.createError && <span className="error">{s.createError}</span>}
        {s.createMutation.error && <span className="error">{s.createMutation.error}</span>}
      </div>
    </div>
  );
}
