import type { ReactNode } from "react";

import type { VerbInfo } from "../../api/types";
import { CONSEQUENCE, Field, InfoCallout, StatusBadge } from "../ux";
import { ChipPicker, JsonDisclosure } from "../uxForm";
import { ArmConfirm, PendingHumanCard, SaveBar } from "../uxFlow";
import type { SaveParams, WorkflowStep } from "./stepUtils";

export function StepSlideToolbar({
  stepId,
  onInsertBefore,
  onAppendAfter,
  onDelete,
}: {
  stepId: string;
  onInsertBefore: () => void;
  onAppendAfter: () => void;
  onDelete: () => Promise<void>;
}): ReactNode {
  return (
    <div className="au-step__toolbar">
      <button type="button" className="btn" onClick={onInsertBefore}>
        Insert before
      </button>
      <button type="button" className="btn" onClick={onAppendAfter}>
        Append after
      </button>
      <ArmConfirm
        label="Delete step"
        armLabel={<>Delete <code>{stepId}</code>? Downstream steps keep their other parents.</>}
        confirmLabel="Delete"
        busyLabel="Deleting"
        tone="danger"
        onConfirm={onDelete}
      />
    </div>
  );
}

export function ActionCard({
  step,
  verbs,
  currentVerb,
  actionUnavailable,
  onChangeAction,
}: {
  step: WorkflowStep;
  verbs: VerbInfo[];
  currentVerb: VerbInfo | undefined;
  actionUnavailable: boolean;
  onChangeAction: (action: string) => void;
}): ReactNode {
  return (
    <section className="au-step__card">
      <h3>Action</h3>
      <Field
        label="Verb"
        hint="Choose the governed verb this step runs. High-consequence verbs pause at runtime."
        required
      >
        <select
          value={step.action}
          aria-label="Step verb"
          onChange={(e) => onChangeAction(e.target.value)}
        >
          <option value="">Choose a verb</option>
          {actionUnavailable && (
            <option value={step.action}>{step.action} (not available to this identity)</option>
          )}
          {verbs.map((verb) => (
            <option key={verb.id} value={verb.id}>
              {verb.id}
            </option>
          ))}
        </select>
      </Field>
      {currentVerb && (
        <div className="au-step__verbfacts">
          <StatusBadge value={currentVerb.consequence} glossary={CONSEQUENCE} />
          <span className="badge">{currentVerb.binding?.target_type ?? "kernel"}</span>
          {currentVerb.binding?.target_ref && <code>{currentVerb.binding.target_ref}</code>}
        </div>
      )}
      {currentVerb?.consequence === "high" && (
        <InfoCallout tone="consequence">
          This step is high consequence. Runs pause here for human approval
          before it executes.
        </InfoCallout>
      )}
      {actionUnavailable && (
        <InfoCallout tone="warn">
          This saved action is not in the current capability list. You can
          keep it as-is or choose a replacement verb.
        </InfoCallout>
      )}
    </section>
  );
}

export function ParametersCard({
  paramsText,
  paramsError,
  onUpdateParams,
}: {
  paramsText: string;
  paramsError: string | null;
  onUpdateParams: (text: string) => void;
}): ReactNode {
  return (
    <section className="au-step__card">
      <h3>Parameters</h3>
      <JsonDisclosure
        value={paramsText}
        onChange={onUpdateParams}
        error={paramsError}
        summaryNote="Step params"
        defaultOpen
      />
    </section>
  );
}

export function ParentsCard({
  step,
  parentOptions,
  onReplaceStep,
}: {
  step: WorkflowStep;
  parentOptions: {
    value: string;
    label: string;
    disabled?: boolean;
    disabledReason?: string;
  }[];
  onReplaceStep: (next: WorkflowStep) => void;
}): ReactNode {
  return (
    <section className="au-step__card">
      <h3>Runs after</h3>
      <Field
        label="Parent steps"
        hint="This step runs only after every selected parent has completed."
      >
        <ChipPicker
          value={step.parents}
          onChange={(parents) => onReplaceStep({ ...step, parents })}
          options={parentOptions}
          mono
          ariaLabel="Parent steps"
          emptyHint="No parents. This is a root step."
        />
      </Field>
    </section>
  );
}

export function DescriptionCard({
  step,
  onReplaceStep,
}: {
  step: WorkflowStep;
  onReplaceStep: (next: WorkflowStep) => void;
}): ReactNode {
  return (
    <section className="au-step__card">
      <h3>Description</h3>
      <textarea
        value={step.description ?? ""}
        rows={6}
        placeholder="Describe what this step does"
        onChange={(e) =>
          onReplaceStep({ ...step, description: e.target.value || undefined })
        }
      />
    </section>
  );
}

export function StepSlideFooter({
  wfid,
  error,
  pending,
  dirty,
  saving,
  onSave,
  onDiscard,
  onApplied,
  onDenied,
}: {
  wfid: string;
  error: string | null;
  pending: { id: string; params: SaveParams } | null;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onApplied: (result: import("../../api/types").InvokeResult) => void;
  onDenied: (reason: string) => void;
}): ReactNode {
  return (
    <>
      {error && <InfoCallout tone="warn">{error}</InfoCallout>}
      {pending && (
        <PendingHumanCard
          hitlRequestId={pending.id}
          noun="control"
          verb="control.workflow.upsert"
          sentParams={pending.params}
          onApplied={onApplied}
          onDenied={onDenied}
        />
      )}
      <SaveBar
        dirty={dirty}
        saving={saving}
        governed
        label={<>Unsaved changes to <code>{wfid}</code></>}
        saveLabel="Save workflow"
        onSave={onSave}
        onDiscard={onDiscard}
      />
    </>
  );
}
