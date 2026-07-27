// The automations zone anchor. One deck CELL serves two contents keyed off
// the route (the slide reads useRoute() itself, per the deck contract):
//   #/automations          -> the workflow picker (cards over api.workflows())
//   #/automations/<wfid>   -> the existing WorkflowCanvas seeded on that id
// Step columns (one slide per workflow step) land in Beat 3; this beat reuses
// the canvas as-is via its routeWfId seed (see the WorkflowCanvas patch).

import { Suspense, lazy, useMemo, useState, type CSSProperties } from "react";

import { api } from "../api/client";
import type {
  WorkflowDetail,
  WorkflowRunStat,
  WorkflowSummary,
} from "../api/types";
import type { DeckCol } from "../deck/Deck";
import { Familiar, familiarAvailable } from "@/familiar/Familiar";
import { automationRole, automationRunFacts } from "@/familiar/automation";
import { navigate, useRoute } from "../router";
import { useFetch } from "../useFetch";
import {
  deriveCardMeta,
  mergeCardStats,
  type HomeCardMeta,
} from "./automations/cardMeta";
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
  // Run stats are best-effort. When unavailable, cards say that no run history
  // is available rather than filling the gap with generated metrics.
  const stats = useFetch(() => api.workflowStats(), []);
  const statsById = useMemo(() => {
    const m = new Map<string, WorkflowRunStat>();
    for (const s of stats.data?.stats ?? []) m.set(s.workflow_id, s);
    return m;
  }, [stats.data]);
  const list = workflows.data?.workflows ?? [];
  const empty = !workflows.loading && !workflows.error && list.length === 0;

  return (
    <section className="panel">
      <PageIntro
        title="Automations"
        lead="Every stored workflow, one card each. Open one to see its canvas."
        how="A workflow is a graph of governed steps. Opening a card shows the graph; authoring new workflows lives in the Studio."
        actions={
          <>
            <span className="muted">{list.length} workflow(s)</span>
            <button className="btn" onClick={() => workflows.reload()}>
              Refresh
            </button>
            <button
              className="btn btn--primary"
              onClick={() => navigate("/studio")}
            >
              New workflow
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
        <div className="wfhome">
          {list.map((w) => (
            <WorkflowCard
              key={`${w.id}@${w.version}`}
              wf={w}
              stat={statsById.get(w.id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function WorkflowCard({
  wf,
  stat,
}: {
  wf: WorkflowSummary;
  stat?: WorkflowRunStat;
}) {
  const meta: HomeCardMeta = useMemo(
    () => mergeCardStats(deriveCardMeta(wf.id, wf.source, wf.intent_tags), stat),
    [wf.id, wf.source, wf.intent_tags, stat],
  );
  return (
    <button
      type="button"
      className="wfhome__card"
      style={{ "--wf-accent": meta.accent } as CSSProperties}
      title={`Open ${wf.id} on the canvas`}
      onClick={() => navigate(`/automations/${encodeURIComponent(wf.id)}`)}
    >
      <span className="wfhome__accent" />
      <span className="wfhome__body">
        <span className="wfhome__head">
          {familiarAvailable() && (
            // The card's familiar states the automation's RECORD, not this instant: a column
            // of settled bodies with one magenta one is a failing job you find without reading
            // a single date. The shape comes from the intent tags, so the list is scannable by
            // kind before it is read.
            <Familiar
              agent={{ id: wf.id, role: automationRole(wf.id, wf.intent_tags) }}
              size={22}
              run={automationRunFacts({ successRate: meta.successRate, runCount: meta.runCount })}
              title={`${wf.id}: ${meta.hasRunStats ? `${meta.successRate}% of ${meta.runCount} runs succeeded` : "never run"}`}
            />
          )}
          <code className="wfhome__name">{wf.id}</code>
          <span
            className="wfhome__status"
            style={{ color: meta.status.color, borderColor: meta.status.color }}
          >
            {meta.status.label}
          </span>
        </span>
        <p className="wfhome__desc">{meta.description}</p>
        {meta.hasRunStats ? (
          <span className="wfhome__stats">
            <span>{meta.runCount} runs</span>
            <span>{meta.successRate}% ok</span>
            <span>{meta.lastRun}</span>
          </span>
        ) : (
          <span className="wfhome__stats">
            <span>No run history</span>
          </span>
        )}
        <span className="wfhome__foot">
          <span>v{wf.version}</span>
          <span>{wf.source}</span>
        </span>
      </span>
    </button>
  );
}

function CanvasHost({ wfid }: { wfid: string }) {
  return (
    <section className="panel">
      <Suspense fallback={<p className="muted">Loading canvas...</p>}>
        {/* key resets the canvas per workflow so switching never bleeds state;
            the back button now lives in the editor header (sec 22.2). */}
        <WorkflowCanvas
          key={wfid}
          routeWfId={wfid}
          onBack={() => navigate("/automations")}
        />
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
