import { useEffect, useMemo, useState } from "react";

import type { AuditTreeResponse } from "@/api/types";
import { normalizeEvents } from "@/panels/chatTurn";
import { RunApprovals } from "./RunApprovals";
import { RunEventStream } from "./RunEventStream";
import { RunExecutionTree } from "./RunExecutionTree";
import { RunOverview } from "./RunOverview";
import { RunRaw } from "./RunRaw";
import { RunTabs, runTabButtonId, runTabPanelId, runTabs, type RunTabId } from "./RunTabs";
import { RunToolCalls } from "./RunToolCalls";
import type { RunStream } from "./useRunStream";

export interface RunTreeState {
  data: AuditTreeResponse | null;
  loading: boolean;
  error: string | null;
}

export function RunInspector({ tree, stream }: { tree: RunTreeState; stream: RunStream }) {
  const [active, setActive] = useState<RunTabId>("overview");
  const fullTurn = useMemo(() => normalizeEvents(stream.events), [stream.events]);
  const approvalCount = fullTurn.hitls.filter((entry) => entry.kind === "approval").length;
  const tabs = useMemo(
    () => runTabs(fullTurn.tools.length, approvalCount),
    [fullTurn.tools.length, approvalCount],
  );

  useEffect(() => {
    if (!tabs.some((tab) => tab.id === active)) setActive("overview");
  }, [active, tabs]);

  const root = tree.data?.root;
  let panel: JSX.Element;
  switch (active) {
    case "overview":
      panel = <RunOverview root={root} loading={tree.loading} error={tree.error} />;
      break;
    case "timeline":
      panel = (
        <RunEventStream
          turn={stream.turn}
          resolvedHitls={stream.resolvedHitls}
          onResolve={stream.resolveHitl}
          canReplay={stream.canReplay}
          replayIdx={stream.replayIdx}
          setReplayIdx={stream.setReplayIdx}
          eventCount={stream.events.length}
          shownCount={stream.shownEvents.length}
          streamError={stream.streamError}
        />
      );
      break;
    case "tree":
      panel = (
        <RunExecutionTree
          loading={tree.loading && !tree.data}
          error={tree.error}
          root={root}
        />
      );
      break;
    case "tools":
      panel = <RunToolCalls turn={stream.turn} />;
      break;
    case "approvals":
      panel = (
        <RunApprovals
          turn={stream.turn}
          resolvedHitls={stream.resolvedHitls}
          onResolve={stream.resolveHitl}
        />
      );
      break;
    case "raw":
      panel = <RunRaw tree={tree.data} loading={tree.loading} error={tree.error} />;
      break;
  }

  return (
    <section className="run-inspector">
      <RunTabs tabs={tabs} active={active} onChange={setActive} />
      <div
        id={runTabPanelId(active)}
        className={`run-inspector__panel run-inspector__panel--${active}`}
        role="tabpanel"
        aria-labelledby={runTabButtonId(active)}
        tabIndex={0}
      >
        {panel}
      </div>
    </section>
  );
}
