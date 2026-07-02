// The automations zone anchor. One deck CELL serves two contents keyed off
// the route (the slide reads useRoute() itself, per the deck contract):
//   #/automations          -> the workflow picker (cards over api.workflows())
//   #/automations/<wfid>   -> the existing WorkflowCanvas seeded on that id
// Step columns (one slide per workflow step) land in Beat 3; this beat reuses
// the canvas as-is via its routeWfId seed (see the WorkflowCanvas patch).

import { Suspense, lazy, useMemo, useState } from "react";

import { api } from "../api/client";
import type { WorkflowDetail } from "../api/types";
import type { DeckCol } from "../deck/Deck";
import { navigate, useRoute } from "../router";
import { useFetch } from "../useFetch";
import { useWorkflowDraft } from "./automations/draft";
import { EmptyState, FetchError, PageIntro } from "./ux";

// The canvas pulls in @xyflow/react; lazy-load it so the heavy chunk only
// downloads when a workflow is opened (same code-split as StudioPanel).
const WorkflowCanvas = lazy(() =>
  import("./WorkflowCanvas").then((m) => ({ default: m.WorkflowCanvas })),
);

interface AutomationStep {
  id: string;
}

function extractStepIds(value: unknown): AutomationStep[] {
  if (!value || typeof value !== "object") return [];
  const steps = (value as { steps?: unknown }).steps;
  return Array.isArray(steps)
    ? steps.filter((s): s is AutomationStep =>
        !!s && typeof s === "object" && typeof (s as { id?: unknown }).id === "string",
      )
    : [];
}

export function useAutomationDeckCols(): DeckCol[] {
  const route = useRoute();
  const wfid = route.tab === "automations" ? route.segs[1] : undefined;
  const detail = useFetch<WorkflowDetail | null>(
    () => (wfid ? api.getWorkflow(wfid) : Promise.resolve(null)),
    [wfid],
  );
  const draftSteps = useWorkflowDraft(wfid);
  return useMemo(() => {
    if (!wfid || (!detail.data && !draftSteps)) return [];
    const steps = draftSteps ?? extractStepIds(detail.data?.definition);
    return steps.map((step) => ({
      key: step.id,
      label: step.id,
      path: `/automations/${encodeURIComponent(wfid)}/step/${encodeURIComponent(step.id)}`,
    }));
  }, [wfid, detail.data, draftSteps]);
}

function WorkflowPicker() {
  const workflows = useFetch(() => api.workflows(), []);
  const list = workflows.data?.workflows ?? [];
  const empty = !workflows.loading && !workflows.error && list.length === 0;

  return (
    <section className="panel">
      <PageIntro
        title="Automations"
        lead="Every stored workflow, one card each - open one to see its canvas."
        how="A workflow is a graph of governed steps. Opening a card shows the graph; authoring new workflows lives in the Studio."
        actions={
          <>
            <span className="muted">{list.length} workflow(s)</span>
            <button className="btn" onClick={() => workflows.reload()}>
              Refresh
            </button>
          </>
        }
      />

      {workflows.loading && !workflows.data && <p className="muted">Loading...</p>}
      <FetchError
        error={workflows.error}
        status={workflows.errorStatus}
        onRetry={workflows.reload}
      />

      {empty && (
        <EmptyState
          title="No workflows yet"
          body="Author your first workflow in the Studio - it appears here once saved."
          action={
            <button className="btn btn--primary" onClick={() => navigate("/studio")}>
              Open the Studio
            </button>
          }
        />
      )}

      {list.length > 0 && (
        <div className="wfpick">
          {list.map((w) => (
            <button
              key={`${w.id}@${w.version}`}
              className="wfpick__card"
              title={`Open ${w.id} on the canvas`}
              onClick={() => navigate(`/automations/${encodeURIComponent(w.id)}`)}
            >
              <span className="wfpick__id">
                <code>{w.id}</code>
              </span>
              <span className="wfpick__meta">
                <span className="badge">{w.source}</span>
                <span className="muted">v{w.version}</span>
              </span>
              {w.intent_tags.length > 0 && (
                <span className="wfpick__tags">
                  {w.intent_tags.map((t) => (
                    <code className="tag" key={t}>
                      {t}
                    </code>
                  ))}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function CanvasHost({ wfid }: { wfid: string }) {
  return (
    <section className="panel">
      <div className="auto-canvas__bar">
        <button className="btn btn--ghost" onClick={() => navigate("/automations")}>
          Back to automations
        </button>
        <code className="mono">{wfid}</code>
      </div>
      <Suspense fallback={<p className="muted">Loading canvas...</p>}>
        {/* key resets the canvas per workflow so switching never bleeds state */}
        <WorkflowCanvas key={wfid} routeWfId={wfid} />
      </Suspense>
    </section>
  );
}

export function AutomationsSlide() {
  const route = useRoute();
  const isMine = route.tab === "automations";
  // Remember the wfid last seen while this slide owned the route (the render
  // phase state-adjust pattern), so a kept-mounted neighbour keeps showing the
  // canvas mid-transition instead of flipping back to the picker.
  const [wfid, setWfid] = useState<string | undefined>(undefined);
  if (isMine && route.segs[1] !== wfid) setWfid(route.segs[1]);

  if (wfid) return <CanvasHost wfid={wfid} />;
  return <WorkflowPicker />;
}
