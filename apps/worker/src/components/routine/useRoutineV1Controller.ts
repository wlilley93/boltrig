import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import type { WorkflowSummary } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { navigate } from "../../routes";
import {
  governedResultReason,
  useExactApprovalFinalizer,
  type ExactApprovalFinalizerController,
} from "../ExactApprovalFinalizer";
import {
  EMPTY_DRAFT,
  initialRoutineState,
  isRoutine,
  performRoutineMutation,
  requestFor,
  sameJson,
  scheduleFor,
  timingFrom,
  workflowRun,
  type RoutineDraft,
  type RoutineMutation,
  type RoutineMutationResult,
  type RoutineScreenState,
  type Timing,
} from "./routineV1";

type Patch = Partial<RoutineScreenState>;
type Dispatch = (patch: Patch) => void;

export interface RoutineActions {
  back(): void;
  change(update: Partial<RoutineDraft>): void;
  newRoutine(): void;
  openRoutine(row: WorkflowSummary): void;
  run(): void;
  save(): void;
  saveTiming(): void;
  setTime(value: string): void;
  setTiming(value: Timing): void;
}

export interface RoutineController {
  actions: RoutineActions;
  finalizer: ExactApprovalFinalizerController<RoutineMutation, RoutineMutationResult>;
  routines: WorkflowSummary[];
  state: RoutineScreenState;
}

function reducer(state: RoutineScreenState, patch: Patch) {
  return { ...state, ...patch };
}

export function useRoutineV1Controller(): RoutineController {
  const [state, dispatch] = useReducer(reducer, undefined, initialRoutineState);
  const stateRef = useRef(state);
  stateRef.current = state;
  const refresh = useRoutineRefresh(dispatch);
  const { finalizer, submit } = useRoutineFinalization(stateRef, dispatch, refresh);
  const actions = useRoutineCommands(state, dispatch, finalizer, submit);
  const routines = useMemo(
    () => state.workflows.filter((workflow) => workflow.routine),
    [state.workflows],
  );
  return { actions, finalizer, routines, state };
}

function useRoutineRefresh(dispatch: Dispatch) {
  const refresh = useCallback(async (reopen: string | null) => {
    try {
      const result = await client.workflows();
      const patch: Patch = { workflows: result.workflows, loadState: "ready" };
      if (reopen) Object.assign(patch, await loadRoutine(reopen, result.workflows));
      dispatch(patch);
    } catch {
      dispatch({ loadState: "unavailable" });
    }
  }, []);
  useEffect(() => { void refresh(null); }, [refresh]);
  return refresh;
}

async function loadRoutine(id: string, workflows: WorkflowSummary[]): Promise<Patch> {
  const detail = await client.workflow(id);
  const routine = detail.routine ?? detail.definition._boltrig_routine;
  if (!isRoutine(routine)) throw new Error("not_a_routine");
  const summary = workflows.find((item) => item.id === id);
  const parsed = timingFrom(summary?.schedule?.cron);
  return {
    selectedId: detail.id,
    draft: {
      id: detail.id,
      name: routine.name,
      goal: routine.goal,
      companion: routine.companion_id,
      notifyCompletion: routine.notify?.completion !== false,
    },
    timing: parsed.timing,
    time: parsed.time,
    hasSchedule: Boolean(summary?.schedule),
    dirty: false,
    busy: false,
    message: "",
  };
}

function useRoutineFinalization(
  stateRef: React.MutableRefObject<RoutineScreenState>,
  dispatch: Dispatch,
  refresh: (reopen: string | null) => Promise<void>,
) {
  const apply = useCallback(async (result: RoutineMutationResult, input: RoutineMutation) => {
    if (input.kind === "run") {
      const run = workflowRun(result);
      if (run?.conversation_id) navigate("chat", run.conversation_id);
      else dispatch({ message: "The run was queued, but its chat link was not returned." });
      return;
    }
    const id = input.kind === "save" ? input.body.id : input.workflowId;
    dispatch({ dirty: false, message: appliedMessage(input.kind) });
    await refresh(id);
  }, [refresh]);
  const finalizer = useExactApprovalFinalizer<RoutineMutation, RoutineMutationResult>({
    isCurrent: (input) => mutationIsCurrent(input, stateRef.current),
    replay: performRoutineMutation,
    onApplied: apply,
    onRefused: (result) => dispatch({
      message: governedResultReason(result, "The kernel did not apply this routine change."),
    }),
    onUncertain: async () => refresh(stateRef.current.selectedId),
  });
  async function submit(input: RoutineMutation, label: string) {
    dispatch({ busy: true, message: "" });
    try {
      const result = await performRoutineMutation(input);
      if (finalizer.begin(input, result, label)) {
        dispatch({ message: "Waiting for approval. Continue here after it is approved." });
      } else if (result.status === "ok") await apply(result, input);
      else dispatch({ message: governedResultReason(result, "The request was not applied.") });
    } catch {
      dispatch({ message: "The routine service is unavailable. It is safe to retry." });
    } finally {
      dispatch({ busy: false });
    }
  }
  return { finalizer, submit };
}

function useRoutineCommands(
  state: RoutineScreenState,
  dispatch: Dispatch,
  finalizer: ExactApprovalFinalizerController<RoutineMutation, RoutineMutationResult>,
  submit: (input: RoutineMutation, label: string) => Promise<void>,
): RoutineActions {
  function change(update: Partial<RoutineDraft>) {
    finalizer.invalidate();
    dispatch({ draft: { ...state.draft, ...update }, dirty: true, message: "" });
  }
  function newRoutine() {
    finalizer.invalidate();
    const value = crypto.getRandomValues(new Uint32Array(1))[0];
    dispatch({ selectedId: null, draft: { ...EMPTY_DRAFT, id: `routine-${value.toString(36).slice(0, 5)}` },
      timing: "manual", time: "09:00", hasSchedule: false, dirty: true, message: "" });
  }
  function openRoutine(row: WorkflowSummary) {
    finalizer.invalidate();
    dispatch({ busy: true, message: "" });
    void loadRoutine(row.id, state.workflows).then(dispatch, () => {
      dispatch({ busy: false, message: "This routine could not be opened." });
    });
  }
  return {
    back: () => { finalizer.invalidate(); dispatch({ selectedId: null, dirty: false, message: "" }); },
    change,
    newRoutine,
    openRoutine,
    run: () => { if (state.selectedId) void submit({ kind: "run", workflowId: state.selectedId }, "Run routine"); },
    save: () => { void submit({ kind: "save", body: requestFor(state.draft) }, "Save routine"); },
    saveTiming: () => void submit(timingMutation(state), "Change routine timing"),
    setTime: (time) => { finalizer.invalidate(); dispatch({ time }); },
    setTiming: (timing) => { finalizer.invalidate(); dispatch({ timing }); },
  };
}

function mutationIsCurrent(input: RoutineMutation, state: RoutineScreenState) {
  if (input.kind === "save") return sameJson(input.body, requestFor(state.draft));
  if (state.selectedId !== input.workflowId || state.dirty) return false;
  if (input.kind !== "schedule") return input.kind !== "unschedule" || state.hasSchedule;
  const current = scheduleFor(state.timing, state.time, state.timezone);
  return current?.cron === input.cron && current?.timezone === input.timezone;
}

function timingMutation(state: RoutineScreenState): RoutineMutation {
  const workflowId = state.selectedId;
  if (!workflowId) throw new Error("routine_not_saved");
  const schedule = scheduleFor(state.timing, state.time, state.timezone);
  return schedule
    ? { kind: "schedule", workflowId, ...schedule }
    : { kind: "unschedule", workflowId };
}

function appliedMessage(kind: RoutineMutation["kind"]) {
  if (kind === "save") return "Routine saved.";
  if (kind === "schedule") return "Timing saved.";
  return "Automatic timing turned off.";
}
