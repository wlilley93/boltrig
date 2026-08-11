// The read-first inspector rail. Facts come before fields: what a step
// touches, whether the kernel can pause it, and what it waits on are stated
// from real registry data (VerbInfo binding/consequence/health) before any
// editable control appears. Every fact names its source honestly — there is no
// invented noun-to-brand table here; an unbound or unknown verb says so.

import { useEffect, useMemo, useRef, useState } from "react";
import type {
  VerbInfo,
  WorkflowScheduleState,
  WorkflowStepResult,
  WorkflowTriggerSummary,
} from "@wlilley93/boltrig-web-sdk";

import {
  isPreservedUnsupportedStep,
  workflowActionLimitation,
  type WorkflowDraft,
  type WorkflowStepDraft,
} from "../../workflowDraft";
import type { GraphProblem } from "./graphChecks";
import {
  BRANCH_OPERATORS,
  simplePredicateFromParams,
  simplePredicateToParams,
} from "./predicates";
import {
  StepKindIcon,
  stepKind,
  type CanvasEdgeRef,
  type CanvasMode,
} from "./RoutineCanvas";
import "./routine.css";

type TriggerView = "manual" | "schedule" | "event";

export interface StepInspectorProps {
  draft: WorkflowDraft;
  verbs: VerbInfo[];
  verbById: Map<string, VerbInfo>;
  selectedStepId: string | null;
  selectedEdge: CanvasEdgeRef | null;
  mode: CanvasMode;
  runSteps: Map<string, WorkflowStepResult> | null;
  problems: GraphProblem[];
  loopBodyIds: Set<string>;
  hasSchedule: boolean;
  cron: string;
  timezone: string;
  scheduleState: WorkflowScheduleState | null;
  triggers: WorkflowTriggerSummary[];
  onStep(index: number, patch: Partial<WorkflowStepDraft>): void;
  onAddStep(): void;
  onRemoveStep(index: number): void;
  onDuplicateStep(id: string): void;
  onRemoveEdge(from: string, to: string): void;
  onSelectStep(id: string | null): void;
}

interface Fact {
  text: string;
  tone?: "amber" | "red" | "green";
}

export function StepInspector(props: StepInspectorProps) {
  const { draft, selectedStepId, selectedEdge } = props;
  // Fields stay visible by default: the worker is a form-first surface and its
  // tests and users reach controls directly. The toggle keeps the design's
  // read-first collapse available without hiding editing behind a click.
  const [fieldsOpen, setFieldsOpen] = useState(true);
  const [triggerView, setTriggerView] = useState<TriggerView | null>(null);

  // Selection is by id, but a rename can pass THROUGH another step's id
  // (backspacing "fetch2" to "fetch" beside an existing "fetch"). While ids
  // collide, prefer the position already being edited over the first textual
  // match — otherwise every further keystroke would silently edit, and the
  // graph would silently rewire, a different step than the one selected.
  const lastIndexRef = useRef(-1);
  const index = useMemo(() => {
    const matches: number[] = [];
    draft.steps.forEach((step, i) => {
      if (step.id.trim() === selectedStepId) matches.push(i);
    });
    if (matches.length > 1 && matches.includes(lastIndexRef.current)) {
      return lastIndexRef.current;
    }
    return matches[0] ?? -1;
  }, [draft.steps, selectedStepId]);
  useEffect(() => {
    lastIndexRef.current = index;
  }, [index]);
  const step = index >= 0 ? draft.steps[index] : null;

  useEffect(() => {
    setTriggerView(null);
  }, [selectedStepId]);

  if (selectedEdge) {
    const { from, to } = selectedEdge;
    return (
      <div className="rc-facts" aria-label="Link inspector">
        <p className="rc-fact">
          <span className="rc-fact-dot" />
          <span>
            {to} waits on {from}. Nothing starts until every step it waits on
            has finished.
          </span>
        </p>
        <div className="rc-inline-actions">
          <button
            className="danger-button"
            onClick={() => props.onRemoveEdge(from, to)}
            type="button"
          >
            Remove this link
          </button>
        </div>
      </div>
    );
  }

  if (!step) {
    return (
      <div className="rc-facts" aria-label="Step inspector">
        <p className="rc-fact">
          <span className="rc-fact-dot" />
          <span>
            Pick a step to see what it does and what it may touch. Drag a step
            to move it, drag from its right-hand dot to make one wait on
            another, and the + adds a step after it.
          </span>
        </p>
        {draft.steps.length === 0 && (
          <div className="rc-inline-actions">
            <button className="secondary-button" onClick={props.onAddStep} type="button">
              Add step
            </button>
          </div>
        )}
        {draft.steps.map((item, itemIndex) => {
          const record = props.mode === "last"
            ? props.runSteps?.get(item.id.trim())
            : undefined;
          return (
            <button
              className="rc-problem"
              // Position-qualified: ids can transiently collide mid-rename.
              key={`${item.id}-${itemIndex}`}
              onClick={() => props.onSelectStep(item.id.trim())}
              type="button"
            >
              <span
                className="rc-problem-dot"
                style={{ background: "var(--switch-off)" }}
              />
              <span style={{ flex: 1, minWidth: 0 }}>
                {item.id.trim() || "unnamed step"}
                {" · "}
                {item.action.trim() || "nothing set yet"}
                {record ? ` · ${record.status}` : ""}
              </span>
            </button>
          );
        })}
      </div>
    );
  }

  const stepId = step.id.trim();
  const action = step.action.trim();
  const kind = stepKind(action);
  const verb = props.verbById.get(action);
  const locked = isPreservedUnsupportedStep(step);
  const limitation = workflowActionLimitation(action);
  const stepProblems = props.problems.filter((problem) => problem.stepId === stepId);
  const facts = buildFacts(step, kind, verb, props, stepProblems);

  return (
    <div aria-label="Step inspector">
      <div className="rc-rail-head">
        <span className="rc-node-icon" data-kind={kind}>
          <StepKindIcon kind={kind} size={16} />
        </span>
        <span className="rc-rail-title">
          <strong>{stepId || "unnamed step"}</strong>
          <code>{action || "nothing set yet"}</code>
        </span>
      </div>
      <div className="rc-facts">
        {facts.map((fact) => (
          <p className="rc-fact" data-tone={fact.tone} key={fact.text}>
            <span className="rc-fact-dot" />
            <span>{fact.text}</span>
          </p>
        ))}
      </div>
      {kind === "trigger" && (
        <TriggerFacts
          {...props}
          view={triggerView}
          onView={setTriggerView}
        />
      )}
      <button
        aria-expanded={fieldsOpen}
        className="rc-fields-toggle"
        onClick={() => setFieldsOpen((open) => !open)}
        type="button"
      >
        {fieldsOpen ? "Hide its fields" : "Its fields"}
      </button>
      {fieldsOpen && (
        <div className="rc-fields">
          <label>
            <span>Step id</span>
            <input
              className="field-control"
              disabled={locked}
              value={step.id}
              onChange={(event) => {
                props.onStep(index, { id: event.target.value });
                props.onSelectStep(event.target.value.trim());
              }}
            />
          </label>
          <label>
            <span>Governed action</span>
            <input
              className="field-control"
              disabled={locked}
              list="worker-actions"
              value={step.action}
              onChange={(event) => props.onStep(index, { action: event.target.value })}
            />
          </label>
          <label>
            <span>Depends on</span>
            <select
              className="field-control parent-select"
              disabled={locked}
              multiple
              value={step.parents}
              onChange={(event) => props.onStep(index, {
                parents: [...event.target.selectedOptions].map((option) => option.value),
              })}
            >
              {draft.steps
                .filter((_, candidate) => candidate !== index)
                .map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.id || "unnamed"}
                  </option>
                ))}
            </select>
          </label>
          <label>
            <span>Description</span>
            <input
              className="field-control"
              disabled={locked}
              value={step.description}
              onChange={(event) => props.onStep(index, { description: event.target.value })}
            />
          </label>
          <BranchArmField
            draft={draft}
            index={index}
            locked={locked}
            step={step}
            onStep={props.onStep}
          />
          {action === "flow.branch" && (
            <PredicateEditor
              index={index}
              locked={locked}
              step={step}
              onStep={props.onStep}
            />
          )}
          <label>
            <span>Parameters (JSON object)</span>
            <textarea
              className="field-control params-editor"
              disabled={locked}
              value={step.paramsText}
              onChange={(event) => props.onStep(index, { paramsText: event.target.value })}
            />
          </label>
          {action === "flow.loop" && (
            <small className="loop-contract-note" role="note">
              Use exactly one item source: a literal <code>items</code> array or an
              ancestor <code>items_from</code> reference such as
              <code>$fetch.output.rows</code>. Boltrig runs at most 100 items in
              stable array order; the selected values must fit 256 KiB.
            </small>
          )}
          {(props.loopBodyIds.has(stepId) || step.loopBindingsText.trim() !== "{}") && (
            <label>
              <span>Loop bindings (JSON object)</span>
              <textarea
                aria-label={`Loop bindings for ${stepId || `step ${index + 1}`}`}
                className="field-control params-editor"
                disabled={locked}
                value={step.loopBindingsText}
                onChange={(event) => props.onStep(index, {
                  loopBindingsText: event.target.value,
                })}
              />
              <small>
                Map an existing top-level parameter to <code>item</code> or
                <code>index</code>. Values are replaced as typed JSON before the
                governed action is schema-checked. Up to 32 bindings are allowed.
              </small>
            </label>
          )}
          {limitation && (
            <small className="unsupported-action" role="note">
              {limitation} {locked
                ? "Worker preserves this existing step exactly and locks its fields."
                : "Worker cannot author this action; choose a supported action before saving."}
            </small>
          )}
          {!limitation && kind === "act" && props.verbs.length > 0 && !verb && (
            <small className="unresolved-action">
              This action is not in the caller-scoped registry. It will fail
              closed unless available at run time.
            </small>
          )}
          <div className="rc-inline-actions">
            <button
              aria-label={`Remove ${stepId || `step ${index + 1}`}`}
              className="danger-button"
              disabled={locked}
              onClick={() => props.onRemoveStep(index)}
              type="button"
            >
              Remove
            </button>
            <button
              className="secondary-button"
              disabled={locked}
              onClick={() => props.onDuplicateStep(stepId)}
              type="button"
            >
              Duplicate
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// --- facts ------------------------------------------------------------------

function buildFacts(
  step: WorkflowStepDraft,
  kind: ReturnType<typeof stepKind>,
  verb: VerbInfo | undefined,
  props: StepInspectorProps,
  stepProblems: GraphProblem[],
): Fact[] {
  const facts: Fact[] = [];
  const action = step.action.trim();

  if (step.parents.length === 0) {
    facts.push({ text: "Nothing comes before it — it starts the run." });
  } else {
    facts.push({ text: `Waits on ${listOf(step.parents)}.` });
  }

  if (kind === "act") {
    if (verb?.binding?.target_type === "adapter") {
      facts.push({ text: `Runs through the ${verb.binding.target_ref} adapter.` });
    } else if (verb?.binding?.target_type === "agent") {
      facts.push({ text: `Calls the ${verb.binding.target_ref} agent.` });
    } else if (verb) {
      facts.push({ text: "No adapter or agent binding is registered for this action." });
    } else if (props.verbs.length > 0 && action) {
      facts.push({
        text: "Not in the caller-scoped action registry — an unknown request is refused, not guessed at.",
        tone: "amber",
      });
    }
    if (verb?.consequence === "high") {
      facts.push({
        text: "High consequence action: the kernel can pause it for a human decision. That comes from the action, not from this routine.",
        tone: "amber",
      });
    } else if (verb?.consequence === "low") {
      facts.push({ text: "Low consequence action.", tone: "green" });
    }
    const health = typeof verb?.health === "string" ? verb.health : "";
    if (health === "down" || health === "degraded") {
      facts.push({
        text: `Its adapter reports ${health}. The step fails closed rather than guessing.`,
        tone: health === "down" ? "red" : "amber",
      });
    }
  } else if (kind === "code") {
    facts.push({
      text: "Recognised, and never carried out: there is no code sandbox, so the kernel records the intent with executed=false.",
      tone: "amber",
    });
  } else if (kind === "branch") {
    facts.push({
      text: "Steps below declare which label they want; the rest are skipped. An operator the engine does not recognise is false, so an unknown comparison stops rather than guesses.",
    });
  } else if (kind === "loop") {
    facts.push({
      text: "The steps inside the dashed outline run once per item. The list is capped at 100 items; anything past the cap is skipped, never quietly dropped.",
    });
  } else if (kind === "end") {
    facts.push({ text: "A marker, not an action. The walk stops here." });
  }

  if (props.mode === "last") {
    const record = props.runSteps?.get(step.id.trim());
    if (record) {
      facts.push({
        text: `In the painted run: ${record.status}${record.reason ? ` · ${record.reason}` : ""}.`,
        tone: record.status === "ok"
          ? "green"
          : record.status === "failed" || record.status === "error"
            ? "red"
            : "amber",
      });
    }
  }

  for (const problem of stepProblems) {
    facts.push({ text: problem.text, tone: problem.tone });
  }
  return facts;
}

// --- what starts it (trigger step) ------------------------------------------

/**
 * The design's manual/schedule/event/plugin segmented control, mapped onto the
 * trigger surfaces this deployment really has: by hand (always true), the cron
 * schedule (client.scheduleWorkflow, edited in the governed schedule section),
 * and webhook/channel bindings (the trigger panel). There is no plugin trigger
 * source in the kernel, so no fourth segment is drawn.
 */
function TriggerFacts(
  props: StepInspectorProps & {
    view: TriggerView | null;
    onView(view: TriggerView): void;
  },
) {
  const active: TriggerView = props.view
    ?? (props.hasSchedule ? "schedule" : props.triggers.length > 0 ? "event" : "manual");
  const options: [TriggerView, string][] = [
    ["manual", "By hand"],
    ["schedule", "A schedule"],
    ["event", "Something arrives"],
  ];
  return (
    <div className="rc-facts" aria-label="What starts it">
      <div className="rc-seg" role="group" aria-label="What starts it">
        {options.map(([view, label]) => (
          <button
            data-active={active === view ? "true" : undefined}
            key={view}
            onClick={() => props.onView(view)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      {active === "manual" && (
        <p className="rc-fact">
          <span className="rc-fact-dot" />
          <span>
            You start it here with Start it now, or use Queue run in the
            scheduling and history disclosure. Those governed paths always
            exist, whatever else is bound.
          </span>
        </p>
      )}
      {active === "schedule" && (
        <p className="rc-fact" data-tone={props.hasSchedule ? undefined : "amber"}>
          <span className="rc-fact-dot" />
          <span>
            {props.hasSchedule
              ? `Cron ${props.cron} · ${props.timezone}${
                props.scheduleState?.observed.next_run_at
                  ? ` · next ${props.scheduleState.observed.next_run_at}`
                  : ""
              }${
                props.scheduleState
                  ? ` · scheduler ${props.scheduleState.observed.status.replace("_", " ")}`
                  : ""
              }. Change it in the Cron schedule section below — schedule changes stay governed.`
              : "No schedule is saved. Set one in the Cron schedule section below; saving a schedule is a governed change."}
          </span>
        </p>
      )}
      {active === "event" && (
        <p className="rc-fact" data-tone={props.triggers.length > 0 ? undefined : "amber"}>
          <span className="rc-fact-dot" />
          <span>
            {props.triggers.length > 0
              ? `${props.triggers.length} event ${props.triggers.length === 1 ? "binding" : "bindings"}: ${
                listOf(props.triggers.map((trigger) => (
                  `${trigger.name} (${trigger.source}${trigger.enabled ? "" : ", disabled"})`
                )))
              }. Manage them in the event-source section below.`
              : "No webhook or channel binding starts this routine yet. Bind one in the event-source section below; deliveries are re-checked against current authority every time."}
          </span>
        </p>
      )}
    </div>
  );
}

// --- fields helpers ---------------------------------------------------------

function BranchArmField({
  draft,
  index,
  locked,
  step,
  onStep,
}: {
  draft: WorkflowDraft;
  index: number;
  locked: boolean;
  step: WorkflowStepDraft;
  onStep(index: number, patch: Partial<WorkflowStepDraft>): void;
}) {
  const actionByStepId = new Map(
    draft.steps.map((item) => [item.id, item.action]),
  );
  const hasBranchParent = step.parents.some(
    (parent) => actionByStepId.get(parent) === "flow.branch",
  );
  if (!step.branchArm && !hasBranchParent) return null;
  const legacyBranch = Boolean(
    step.branchArm && !["true", "false"].includes(step.branchArm),
  );
  return (
    <label>
      <span>Branch arm</span>
      <select
        aria-label={`Branch arm for ${step.id || `step ${index + 1}`}`}
        className="field-control"
        disabled={locked}
        value={step.branchArm}
        onChange={(event) => onStep(index, { branchArm: event.target.value })}
      >
        <option value="">Always</option>
        <option value="true">IF / true</option>
        <option value="false">ELSE / false</option>
        {legacyBranch && (
          <option value={step.branchArm}>
            Existing unsupported label: {step.branchArm}
          </option>
        )}
      </select>
      <small>Runs only when every branch-producing parent matches this arm.</small>
    </label>
  );
}

/**
 * Structured left/op/right editor for flow.branch, writing the exact predicate
 * shape control_flow.eval_predicate reads. It only takes over when the stored
 * params ARE that simple shape; multi-case and bare-value predicates keep the
 * raw JSON editor so a shape this control cannot represent is never clobbered.
 */
function PredicateEditor({
  index,
  locked,
  step,
  onStep,
}: {
  index: number;
  locked: boolean;
  step: WorkflowStepDraft;
  onStep(index: number, patch: Partial<WorkflowStepDraft>): void;
}) {
  let params: Record<string, unknown> | null = null;
  try {
    const parsed: unknown = JSON.parse(step.paramsText.trim() || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      params = parsed as Record<string, unknown>;
    }
  } catch {
    params = null;
  }
  const predicate = params ? simplePredicateFromParams(params) : null;
  if (!predicate) {
    return (
      <small role="note">
        {params && Array.isArray(params.cases)
          ? "This branch uses the multi-case cases[] form. Edit it as JSON below; the structured editor stays out of the way so no case is lost."
          : "This predicate is not the simple left/op/right shape, so it is edited as JSON below."}
      </small>
    );
  }
  const patch = (next: Partial<typeof predicate>) => {
    onStep(index, {
      paramsText: JSON.stringify(
        simplePredicateToParams({ ...predicate, ...next }),
        null,
        2,
      ),
    });
  };
  return (
    <div className="rc-pred">
      <span style={{
        fontSize: "10.5px",
        fontWeight: 600,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        color: "var(--text-4)",
      }}
      >
        Takes the true path when
      </span>
      <input
        aria-label="Predicate left value"
        className="field-control"
        disabled={locked}
        placeholder="$step.output.field"
        value={predicate.left}
        onChange={(event) => patch({ left: event.target.value })}
      />
      <div className="rc-pred-row">
        <select
          aria-label="Predicate operator"
          className="field-control"
          disabled={locked}
          value={predicate.op}
          onChange={(event) => patch({ op: event.target.value })}
        >
          {BRANCH_OPERATORS.map((op) => (
            <option key={op} value={op}>{op}</option>
          ))}
          {!BRANCH_OPERATORS.includes(predicate.op as never) && (
            <option value={predicate.op}>{predicate.op} (unknown: always false)</option>
          )}
        </select>
        <input
          aria-label="Predicate right value"
          className="field-control"
          disabled={locked}
          placeholder="value or $ref"
          value={predicate.right}
          onChange={(event) => patch({ right: event.target.value })}
        />
      </div>
      <small>
        With no comparison at all every branch is true; an operator the engine
        does not recognise is false, so an unknown comparison stops rather than
        guesses.
      </small>
    </div>
  );
}

function listOf(items: string[]): string {
  if (items.length === 0) return "nothing";
  if (items.length === 1) return items[0];
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
