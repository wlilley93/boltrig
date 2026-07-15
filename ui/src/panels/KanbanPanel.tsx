import { useMemo, useState } from "react";

import { api } from "@/api/client";
import type { WorkStatus } from "@/api/types";
import { useSlideActive } from "@/deck/context";
import { useRoute } from "@/router";
import { useFetch } from "@/useFetch";
import { EmptyState, FetchError, PageIntro } from "@/panels/ux";
import { WorkDetail } from "./workBoard/WorkDetail";
import { WorkFilters } from "./workBoard/WorkFilters";
import { WorkViews } from "./workBoard/WorkViews";
import {
  ALL_STATUSES,
  filterWorkItems,
  ownerOptions,
  sourceOptions,
  type WorkFiltersState,
  type WorkView,
} from "./workBoard/model";

const DEFAULT_FILTERS: WorkFiltersState = {
  query: "",
  status: ALL_STATUSES,
  owner: "all-owners",
  source: "all-sources",
  convergent: "all",
};

export function KanbanPanel() {
  const active = useSlideActive();
  const route = useRoute();
  const detailId = route.tab === "kanban" ? route.param : undefined;
  const [view, setView] = useState<WorkView>("board");
  const [filters, setFilters] = useState<WorkFiltersState>(DEFAULT_FILTERS);
  const serverStatus = filters.status === ALL_STATUSES
    ? undefined
    : filters.status as WorkStatus;
  const work = useFetch(
    () => api.work(serverStatus),
    [serverStatus],
    10000,
    { paused: !active || Boolean(detailId) },
  );
  const items = work.data?.items ?? [];
  const visible = useMemo(
    () => filterWorkItems(items, filters),
    [items, filters],
  );

  if (detailId) return <WorkDetail itemId={detailId} />;

  return (
    <section className="panel work-board-panel">
      <PageIntro
        title="Work queue"
        lead="Trace scoped work from goal to task without inventing local state."
        how="Project shows parent-child structure, Linear shows the operational sequence, and Board groups the same server-owned records by status. Filters narrow only work you are allowed to see."
        howToggle
        actions={
          <>
            <span className="muted">{visible.length} of {items.length}</span>
            <button className="btn" onClick={() => work.reload()}>Refresh</button>
          </>
        }
      />

      <WorkFilters
        filters={filters}
        onChange={setFilters}
        owners={ownerOptions(items)}
        sources={sourceOptions(items)}
        view={view}
        onViewChange={setView}
      />

      {work.loading && !work.data && <p className="muted">Loading scoped work...</p>}
      <FetchError error={work.error} status={work.errorStatus} onRetry={work.reload} />

      {!work.loading && !work.error && items.length === 0 ? (
        <EmptyState
          title="No work yet"
          body="Work items appear here when conversations, workflows, or channel intake create them."
        />
      ) : !work.loading && !work.error && visible.length === 0 ? (
        <EmptyState
          title="Nothing matches this view"
          body="The filters are valid, but no work in your visibility scope matches them."
          action={<button className="btn" onClick={() => setFilters(DEFAULT_FILTERS)}>Clear filters</button>}
        />
      ) : (
        <WorkViews view={view} items={visible} />
      )}

      {work.data?.next_cursor && (
        <p className="work-board__page-note muted">
          Showing the first {work.data.limit ?? items.length} scoped items. Refine the status filter to narrow the server page.
        </p>
      )}
    </section>
  );
}
