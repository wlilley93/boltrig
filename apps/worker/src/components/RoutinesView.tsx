import { ExactApprovalFinalizer } from "./ExactApprovalFinalizer";
import { Topbar, Unavailable } from "./Shell";
import {
  RoutineList,
  RoutineV1Editor,
} from "./routine/RoutineV1Editor";
import { useRoutineV1Controller } from "./routine/useRoutineV1Controller";

import "./RoutinesView.css";

/** V1 is intentionally conversational: one goal, one trigger, one run chat.
 * The old graph editor remains out of the route until an Advanced v2 has its
 * own product and authority contract. */
export function RoutinesView() {
  const controller = useRoutineV1Controller();
  const { actions, finalizer, routines, state } = controller;
  const editing = state.selectedId !== null || state.dirty;
  const legacyCount = state.workflows.length - routines.length;

  return <div className="page routines-v1">
    <Topbar title="Routines" status={`${routines.length} saved`} />
    <div className="page-content routines-v1-content">
      <RoutineIntro onNew={actions.newRoutine} />
      {state.loadState === "loading" && (
        <Unavailable title="Loading routines">Loading routines.</Unavailable>
      )}
      {state.loadState === "unavailable" && (
        <Unavailable title="Routines unavailable">The routine library could not be reached.</Unavailable>
      )}
      {state.loadState === "ready" && !editing && (
        <RoutineList routines={routines} onOpen={actions.openRoutine} onNew={actions.newRoutine} />
      )}
      {state.loadState === "ready" && !editing && legacyCount > 0 && (
        <p className="muted small routines-v1-legacy">
          {legacyCount} earlier graph {legacyCount === 1 ? "workflow remains" : "workflows remain"}
          {" "}stored. Advanced editing is deferred to v2.
        </p>
      )}
      {editing && <RoutineV1Editor state={state} actions={actions} />}
      <ExactApprovalFinalizer controller={finalizer} />
      {state.message && (
        <p className="notice routines-v1-notice" role="status">{state.message}</p>
      )}
    </div>
  </div>;
}

function RoutineIntro({ onNew }: { onNew(): void }) {
  return <header className="routines-v1-intro">
    <div>
      <p className="eyebrow">Automatic work</p>
      <h2>Say what should happen. Follow each run as a chat.</h2>
      <p>
        A routine starts on its own, but it never disappears into a graph.
        Results, tool use and any approval stay in the run conversation.
      </p>
    </div>
    <button className="primary-button" onClick={onNew} type="button">New routine</button>
  </header>;
}
