import type { WorkflowSummary } from "@wlilley93/boltrig-web-sdk";

import { FamiliarStage } from "../familiar/FamiliarStage";
import { RESTING_STAGE_STATE } from "../familiar/FamiliarState";
import { JarvisStage } from "../jarvis/JarvisStage";
import { RESTING_JARVIS_STATE } from "../jarvis/JarvisState";
import { Unavailable } from "../Shell";
import type { RoutineActions } from "./useRoutineV1Controller";
import {
  nameOf,
  scheduleLabel,
  type Companion,
  type RoutineScreenState,
  type Timing,
} from "./routineV1";

export function RoutineList({ routines, onOpen, onNew }: {
  routines: WorkflowSummary[];
  onOpen(row: WorkflowSummary): void;
  onNew(): void;
}) {
  if (routines.length === 0) return <Unavailable title="No routines yet">
    <span>Start with one outcome and one moment it should run.</span>{" "}
    <button className="text-button" onClick={onNew} type="button">Create the first routine</button>
  </Unavailable>;
  return <section aria-label="Saved routines" className="routines-v1-grid">
    {routines.map((workflow) => <RoutineListCard
      key={workflow.id}
      workflow={workflow}
      onOpen={onOpen}
    />)}
  </section>;
}

function RoutineListCard({ workflow, onOpen }: {
  workflow: WorkflowSummary;
  onOpen(row: WorkflowSummary): void;
}) {
  const routine = workflow.routine!;
  return <button className="routine-v1-card" onClick={() => onOpen(workflow)} type="button">
    <span className={`routine-v1-orb ${routine.companion_id}`} aria-hidden />
    <span className="routine-v1-card-copy">
      <strong>{routine.name}</strong>
      <span>{routine.goal}</span>
      <small>{scheduleLabel(workflow.schedule?.cron)} · {nameOf(routine.companion_id)}</small>
    </span>
    <span aria-hidden className="routine-v1-chevron">›</span>
  </button>;
}

export function RoutineV1Editor({ state, actions }: {
  state: RoutineScreenState;
  actions: RoutineActions;
}) {
  const canSave = Boolean(state.draft.name.trim() && state.draft.goal.trim());
  return <section className="routine-v1-editor" aria-label="Routine editor">
    <button className="text-button routine-v1-back" onClick={actions.back} type="button">
      ← All routines
    </button>
    <RoutineIdentity state={state} actions={actions} />
    {state.selectedId && <RoutineTiming state={state} actions={actions} />}
    <div className="routine-v1-actions">
      <button className="primary-button" disabled={!canSave || state.busy} onClick={actions.save} type="button">
        Save routine
      </button>
      {state.selectedId && <button className="secondary-button" disabled={state.busy} onClick={actions.run} type="button">
        Run now
      </button>}
    </div>
  </section>;
}

function RoutineIdentity({ state, actions }: {
  state: RoutineScreenState;
  actions: RoutineActions;
}) {
  return <div className="routine-v1-form-card">
    <label><span>Name</span><input
      aria-label="Routine name"
      className="field-control"
      maxLength={120}
      value={state.draft.name}
      onChange={(event) => actions.change({ name: event.target.value })}
      placeholder="Morning priorities"
    /></label>
    <label><span>What should happen?</span><textarea
      aria-label="Routine goal"
      className="field-control routine-v1-goal"
      maxLength={4000}
      value={state.draft.goal}
      onChange={(event) => actions.change({ goal: event.target.value })}
      placeholder="Review what changed overnight, tell me what needs attention, and prepare the first useful next step."
    /></label>
    <CompanionPicker selected={state.draft.companion} onChange={(companion) => actions.change({ companion })} />
    <label className="routine-v1-check">
      <input checked={state.draft.notifyCompletion} onChange={(event) => actions.change({ notifyCompletion: event.target.checked })} type="checkbox" />
      <span><strong>Tell me when it is done</strong><small>Uses the verified notification routes in your account. Requests for approval always notify eligible people.</small></span>
    </label>
    <p className="routine-v1-policy">Workspace policy still decides what needs approval. A routine never widens the agent’s access.</p>
  </div>;
}

function CompanionPicker({ selected, onChange }: {
  selected: Companion;
  onChange(value: Companion): void;
}) {
  return <fieldset className="routine-v1-companions">
    <legend>Who should meet you in the run?</legend>
    <CompanionCard active={selected === "familiar"} id="familiar" onSelect={() => onChange("familiar")} />
    <CompanionCard active={selected === "jarvis"} id="jarvis" onSelect={() => onChange("jarvis")} />
  </fieldset>;
}

function CompanionCard({ active, id, onSelect }: {
  active: boolean;
  id: Companion;
  onSelect(): void;
}) {
  return <button aria-checked={active} className={`routine-v1-companion${active ? " selected" : ""}`}
    onClick={onSelect} role="radio" type="button">
    <span className="routine-v1-character" aria-hidden>
      {id === "familiar"
        ? <FamiliarStage label="" mode="minimised" state={RESTING_STAGE_STATE} />
        : <JarvisStage state={RESTING_JARVIS_STATE} suspended />}
    </span>
    <strong>{nameOf(id)}</strong>
    <small>{id === "familiar" ? "Warm, curious and alive" : "Precise, calm and instrument-like"}</small>
  </button>;
}

function RoutineTiming({ state, actions }: {
  state: RoutineScreenState;
  actions: RoutineActions;
}) {
  return <div className="routine-v1-form-card routine-v1-timing">
    <div><strong>When</strong><p>Each occurrence opens a new run chat in Recents.</p></div>
    <select aria-label="Routine timing" className="field-control" value={state.timing}
      onChange={(event) => actions.setTiming(event.target.value as Timing)}>
      <option value="manual">Only when I run it</option>
      <option value="daily">Every day</option>
      <option value="weekdays">Weekdays</option>
    </select>
    {state.timing !== "manual" && <input aria-label="Routine time" className="field-control" type="time"
      value={state.time} onChange={(event) => actions.setTime(event.target.value)} />}
    <span className="routine-v1-zone">{state.timezone}</span>
    <button className="secondary-button" disabled={state.busy || (state.timing === "manual" && !state.hasSchedule)}
      onClick={actions.saveTiming} type="button">Save timing</button>
  </div>;
}
