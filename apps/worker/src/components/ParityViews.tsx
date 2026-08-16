import { useEffect, useMemo, useRef, useState } from "react";
import {
  BoltrigApiError,
  type AgentCapabilityAuthorInfo,
  type AuditNode,
  type CapabilityLifecycleResponse,
  type MemoryCandidateView,
  type MemoryFactView,
  type MemoryIngestionRow,
  type MemoryTimelineResponse,
  type RunRow,
  type RunTopologyNode,
  type WorkDetailResponse,
  type WorkItem,
  type WorkStatus,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { useRouteSelection } from "../useRouteSelection";
import { AgentProfileEditor } from "./AgentProfileEditor";
import { AgentTabsStrip } from "./build/AgentTabsStrip";
import {
  ExactApprovalFinalizer,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";
import { PermanentFleetTopology } from "./PermanentFleetTopology";
import { CreateMethodIcon, GovernedCreateModal } from "./GovernedCreateModal";
import { Topbar, Unavailable } from "./Shell";

type SurfaceState = "loading" | "ready" | "denied" | "not-found" | "unavailable";
type DetailState = "idle" | "loading" | "ready" | "denied" | "not-found" | "unavailable";

function failureState(error: unknown): Exclude<SurfaceState, "loading" | "ready"> {
  if (error instanceof BoltrigApiError) {
    if (error.status === 401 || error.status === 403) return "denied";
    if (error.status === 404) return "not-found";
  }
  return "unavailable";
}

export function RunsView() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [surfaceState, setSurfaceState] = useState<SurfaceState>("loading");
  const loadedRuns = useRef(false);
  const [selectedRunId, setSelectedRunId] = useRouteSelection("runs");
  const [selected, setSelected] = useState<RunRow | null>(null);
  const [tree, setTree] = useState<AuditNode | null>(null);
  const [topology, setTopology] = useState<RunTopologyNode | null>(null);
  const runDetailSequence = useRef(0);
  const [query, setQuery] = useState("");
  const [ownerFilter, setOwnerFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [externalRefFilter, setExternalRefFilter] = useState("");
  const [onBehalfOfFilter, setOnBehalfOfFilter] = useState("");
  const [labelFilter, setLabelFilter] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [cancelArmed, setCancelArmed] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  function refresh() {
    setError("");
    void client.runs(runFilters())
      .then((result) => {
        setRuns(result.runs);
        setNextCursor(result.next_cursor ?? null);
        loadedRuns.current = true;
        setSurfaceState("ready");
      })
      .catch((reason) => {
        const state = failureState(reason);
        if (state === "unavailable" && loadedRuns.current) {
          setError("Runs could not be refreshed. Showing the last loaded page.");
          return;
        }
        loadedRuns.current = false;
        setRuns([]);
        setNextCursor(null);
        setSurfaceState(state);
      });
  }

  function runFilters() {
    const filters: Parameters<typeof client.runs>[0] = {};
    if (ownerFilter.trim()) filters.owner = ownerFilter.trim();
    if (sourceFilter.trim()) filters.source = sourceFilter.trim();
    if (externalRefFilter.trim()) filters.externalRef = externalRefFilter.trim();
    if (onBehalfOfFilter.trim()) filters.onBehalfOf = onBehalfOfFilter.trim();
    if (labelFilter.trim()) filters.label = labelFilter.trim();
    return filters;
  }

  useEffect(refresh, []);

  function inspect(row: RunRow) {
    setSelected(row);
    setTree(null);
    setTopology(null);
    setCancelArmed(false);
    if (!row.run_id) {
      runDetailSequence.current += 1;
      return;
    }
    const sequence = ++runDetailSequence.current;
    void Promise.allSettled([
      client.auditTree(row.run_id),
      client.runTopology(row.run_id),
    ]).then(([audit, roster]) => {
      if (runDetailSequence.current !== sequence) return;
      setTree(audit.status === "fulfilled" ? audit.value.root : null);
      setTopology(roster.status === "fulfilled" ? roster.value.root : null);
    });
  }

  useEffect(() => {
    if (!selectedRunId) {
      runDetailSequence.current += 1;
      setSelected(null);
      setTree(null);
      setTopology(null);
      return;
    }
    if (surfaceState !== "ready") return;
    inspect(runs.find((item) => runSelectionId(item) === selectedRunId) ?? {
      run_id: selectedRunId,
      work_item: "Outside the current history page",
      intent: "Selected run",
      status: "detail only",
    });
  }, [runs, selectedRunId, surfaceState]);

  async function cancel(row: RunRow) {
    if (!row.run_id) return;
    if (!cancelArmed) {
      setCancelArmed(true);
      return;
    }
    const result = await client.cancelRun(row.run_id);
    setMessage(result.status === "ok"
      ? "Cancellation requested. Child work will drain under the kernel contract."
      : result.reason ?? `Cancellation status: ${result.status}.`);
    setCancelArmed(false);
    refresh();
  }

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    return term
      ? runs.filter((row) => `${row.intent} ${row.status} ${row.owner ?? ""} ${row.run_id ?? ""}`.toLowerCase().includes(term))
      : runs;
  }, [query, runs]);

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setError("");
    try {
      const result = await client.runs({ ...runFilters(), cursor: nextCursor });
      setRuns((current) => [...current, ...result.runs]);
      setNextCursor(result.next_cursor ?? null);
    } catch {
      setError("More runs could not be loaded.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="page">
      <Topbar title="Runs" status={`${runs.length} visible`} />
      <div className="page-content">
        <div className="page-intro">
          <div>
            <h2>Execution history</h2>
            <p>Scope-filtered runs with their durable execution tree and recorded execution events.</p>
          </div>
          <div className="inline-actions">
            <input className="search" aria-label="Search runs" placeholder="Search runs…" value={query} onChange={(event) => setQuery(event.target.value)} />
            <button className="secondary-button" onClick={refresh}>Refresh</button>
          </div>
        </div>
        <section className="work-filters run-filters" aria-label="Server run filters">
          <input className="field-control" aria-label="Filter runs by owner" placeholder="Owner" value={ownerFilter} onChange={(event) => setOwnerFilter(event.target.value)} />
          <input className="field-control" aria-label="Filter runs by principal" placeholder="On behalf of" value={onBehalfOfFilter} onChange={(event) => setOnBehalfOfFilter(event.target.value)} />
          <input className="field-control" aria-label="Filter runs by label" placeholder="Label" value={labelFilter} onChange={(event) => setLabelFilter(event.target.value)} />
          <input className="field-control" aria-label="Filter runs by source" placeholder="Source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} />
          <input className="field-control" aria-label="Filter runs by external reference" placeholder="External reference" value={externalRefFilter} onChange={(event) => setExternalRefFilter(event.target.value)} />
          <button className="secondary-button" onClick={refresh}>Apply server filters</button>
        </section>
        {error && <p className="notice">{error}</p>}
        {message && <p className="notice" role="status">{message}</p>}
        {surfaceState === "loading" && <Unavailable title="Loading runs">Loading your scoped execution history.</Unavailable>}
        {surfaceState === "denied" && <Unavailable title="Run access denied">Your current role cannot view execution history.</Unavailable>}
        {surfaceState === "not-found" && <Unavailable title="Runs not found">This deployment does not expose the canonical run history route.</Unavailable>}
        {surfaceState === "unavailable" && <Unavailable title="Runs unavailable">Execution history could not be reached.</Unavailable>}
        {surfaceState === "ready" && <div className={selected ? "split-view detail-open" : "split-view"}>
          <section className="data-list" aria-label="Runs">
            {visible.length === 0 && !error ? <Unavailable title="No runs yet">Completed and active agent or workflow runs will appear here.</Unavailable> : visible.map((row) => (
              <button
                className={selectedRunId === runSelectionId(row) ? "data-row selected" : "data-row"}
                key={row.run_id ?? row.work_item}
                onClick={() => setSelectedRunId(runSelectionId(row))}
              >
                <span className={`activity-dot ${statusClass(row.status)}`} />
                <span className="data-row-copy">
                  <strong>{row.intent || row.work_item}</strong>
                  <small>{row.owner || "Unassigned"} · {row.source || "Boltrig"}</small>
                </span>
                <span className="row-meta">{row.status.replaceAll("_", " ")}</span>
              </button>
            ))}
            {nextCursor && (
              <button className="secondary-button load-more" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadingMore ? "Loading…" : "Load more runs"}
              </button>
            )}
          </section>
          {selected && (
            <aside className="detail-panel" aria-label="Run details">
              <div className="detail-heading">
                <div><p className="eyebrow">Run inspector</p><h3>{selected.intent}</h3></div>
                <button className="icon-button" aria-label="Close run details" onClick={() => setSelectedRunId(null)}>×</button>
              </div>
              <dl className="fact-grid">
                <Fact label="Run" value={selected.run_id ?? "Not started"} />
                <Fact label="Status" value={selected.status} />
                <Fact label="Owner" value={selected.owner ?? "Unassigned"} />
                <Fact label="Work item" value={selected.work_item} />
              </dl>
              <div className="detail-section">
                <p className="eyebrow">Cost and execution tree</p>
                {selected.run_id && !tree ? <p className="muted small">No execution events have been recorded yet.</p> : tree && <AuditBranch node={tree} />}
              </div>
              <div className="detail-section">
                <p className="eyebrow">Durable subagent topology</p>
                {topology ? <TopologyBranch node={topology} /> : <p className="muted small">No durable child-work topology is available.</p>}
              </div>
              {selected.run_id
                && runs.some((row) => row.run_id === selected.run_id)
                && !isTerminal(selected.status) && (
                <button className={cancelArmed ? "danger-button armed" : "danger-button"} onClick={() => void cancel(selected)}>
                  {cancelArmed ? "Confirm cancel run" : "Cancel run"}
                </button>
              )}
            </aside>
          )}
        </div>}
      </div>
    </div>
  );
}

function AuditBranch({ node }: { node: AuditNode }) {
  const ownCost = Number(node.cost_micros ?? 0);
  const totalCost = Number(node.total_cost_micros ?? ownCost);
  return (
    <div className="audit-branch">
      <div className="audit-node">
        <span className="mini-familiar" />
        <span><strong>{String(node.actor ?? node.run_id)}</strong><small>{node.actions ?? 0} actions · {node.tokens ?? 0} tokens · {formatCost(totalCost)}</small></span>
      </div>
      {node.children?.map((child) => <AuditBranch node={child} key={child.run_id} />)}
    </div>
  );
}

function TopologyBranch({ node }: { node: RunTopologyNode }) {
  return (
    <div className="audit-branch">
      <div className="audit-node">
        <span className={`activity-dot ${statusClass(node.status)}`} />
        <span><strong>{node.member ?? "Unassigned worker"}</strong><small>{node.task} · depth {node.depth} · {node.attempts} attempts</small></span>
      </div>
      {node.children.map((child) => <TopologyBranch node={child} key={child.run_id} />)}
    </div>
  );
}

type WorkCreateApprovalInput = {
  body: Parameters<typeof client.createWork>[0];
};

type WorkMutationResult = Awaited<ReturnType<typeof client.createWork>>;

export function WorkView() {
  const [selectedWorkId, setSelectedWorkId] = useRouteSelection("work");
  const [items, setItems] = useState<WorkItem[]>([]);
  const [status, setStatus] = useState<WorkStatus | "">("");
  const [mode, setMode] = useState<"project" | "linear" | "board">("project");
  const [query, setQuery] = useState("");
  const [owner, setOwner] = useState("");
  const [source, setSource] = useState("");
  const [convergent, setConvergent] = useState<"" | "yes" | "no">("");
  const [detail, setDetail] = useState<WorkDetailResponse | null>(null);
  const selectedWorkIdRef = useRef(selectedWorkId);
  const workDetailSequence = useRef(0);
  const [error, setError] = useState("");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [createIntent, setCreateIntent] = useState("");
  const [createOwner, setCreateOwner] = useState("");
  const [createParent, setCreateParent] = useState("");
  const [createConvergent, setCreateConvergent] = useState(false);
  const [mutationMessage, setMutationMessage] = useState("");
  const [mutationBusy, setMutationBusy] = useState(false);
  const createFinalizer = useExactApprovalFinalizer<
    WorkCreateApprovalInput,
    WorkMutationResult
  >({
    isCurrent: (input) => (
      input.body.intent === createIntent.trim()
      && input.body.owner_member === (createOwner.trim() || null)
      && input.body.parent_id === (createParent.trim() || null)
      && Boolean(input.body.convergent) === createConvergent
    ),
    replay: (input, approvalId) => client.createWork(input.body, approvalId),
    onApplied: (result) => {
      if (!("item" in result)) return;
      setCreateIntent("");
      setCreateOwner("");
      setCreateParent("");
      setCreateConvergent(false);
      setMutationMessage(
        "Work item created in Boltrig. No source-system writeback was attempted.",
      );
      load();
      inspect(result.item);
    },
    onRefused: (result) => {
      setMutationMessage(workMutationNotice(result, "Work creation"));
    },
    onUncertain: () => {
      load();
    },
  });
  selectedWorkIdRef.current = selectedWorkId;

  function load(nextStatus: WorkStatus | "" = status) {
    createFinalizer.invalidate();
    setError("");
    void client.work(nextStatus || undefined)
      .then((result) => {
        setItems(result.items);
        setNextCursor(result.next_cursor ?? null);
      })
      .catch(() => setError("Work is unavailable."));
  }

  useEffect(() => load(status), [status]);

  function inspect(item: WorkItem) {
    setSelectedWorkId(item.id);
  }

  useEffect(() => {
    if (!selectedWorkId) {
      workDetailSequence.current += 1;
      setDetail(null);
      return;
    }
    const sequence = ++workDetailSequence.current;
    setDetail(null);
    setError("");
    void client.workDetail(selectedWorkId)
      .then((result) => {
        if (
          workDetailSequence.current === sequence
          && selectedWorkIdRef.current === selectedWorkId
        ) setDetail(result);
      })
      .catch(() => {
        if (
          workDetailSequence.current === sequence
          && selectedWorkIdRef.current === selectedWorkId
        ) setError("That work item is outside your current scope or no longer exists.");
      });
    return () => {
      if (workDetailSequence.current === sequence) workDetailSequence.current += 1;
    };
  }, [selectedWorkId]);

  const owners = useMemo(() => [...new Set(items.map((item) => item.owner_member).filter((value): value is string => Boolean(value)))].sort(), [items]);
  const sources = useMemo(() => [...new Set(items.map((item) => item.source).filter((value): value is string => Boolean(value)))].sort(), [items]);
  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    return items.filter((item) => (
      (!term || `${item.intent} ${item.id} ${item.owner_member ?? ""} ${item.source ?? ""}`.toLowerCase().includes(term))
      && (!owner || item.owner_member === owner)
      && (!source || item.source === source)
      && (!convergent || Boolean(item.convergent) === (convergent === "yes"))
    ));
  }, [convergent, items, owner, query, source]);

  const workButton = (item: WorkItem, className = "work-card") => (
    <button className={`${className}${item.convergent ? " convergent" : ""}`} key={item.id} onClick={() => inspect(item)}>
      <span className={`activity-dot ${statusClass(item.status)}`} />
      <span><strong>{item.intent}</strong><small>{item.owner_member || "Unassigned"} · {item.source || "Boltrig"}{item.convergent ? " · convergent goal" : ""}</small></span>
      <span className="row-meta">{item.status.replaceAll("_", " ")}</span>
    </button>
  );

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setError("");
    try {
      const result = await client.work(status || undefined, { cursor: nextCursor });
      setItems((current) => [...current, ...result.items]);
      setNextCursor(result.next_cursor ?? null);
    } catch {
      setError("More work could not be loaded.");
    } finally {
      setLoadingMore(false);
    }
  }

  async function createItem(event: React.FormEvent) {
    event.preventDefault();
    if (!createIntent.trim() || mutationBusy) return;
    setMutationBusy(true);
    setMutationMessage("");
    setError("");
    try {
      const input: WorkCreateApprovalInput = {
        body: {
          intent: createIntent.trim(),
          owner_member: createOwner.trim() || null,
          parent_id: createParent.trim() || null,
          convergent: createConvergent,
          idempotency_key: crypto.randomUUID(),
        },
      };
      const result = await client.createWork(input.body);
      if (result.status === "ok") {
        createFinalizer.clear();
        setCreateIntent("");
        setCreateOwner("");
        setCreateParent("");
        setCreateConvergent(false);
        setMutationMessage("Work item created in Boltrig. No source-system writeback was attempted.");
        load();
        inspect(result.item);
      } else if (createFinalizer.begin(input, result, "Work creation")) {
        setMutationMessage("Work creation is waiting for approval in the originating chat.");
      } else {
        setMutationMessage(workMutationNotice(result, "Work creation"));
      }
    } catch (reason) {
      setError(workMutationError(reason));
    } finally {
      setMutationBusy(false);
    }
  }

  function changed(item: WorkItem, notice: string) {
    setMutationMessage(notice);
    setDetail((current) => (
      current && selectedWorkIdRef.current === item.id ? { ...current, item } : current
    ));
    load();
    const sequence = ++workDetailSequence.current;
    void client.workDetail(item.id).then((result) => {
      if (
        workDetailSequence.current === sequence
        && selectedWorkIdRef.current === item.id
      ) setDetail(result);
    }).catch(() => undefined);
  }

  return (
    <div className="page">
      <Topbar title="Work" status={`${items.length} items`} />
      <div className="page-content">
        <div className="page-intro">
          <div><h2>Work queue</h2><p>Canonical work items from conversations, workflows and channel intake, filtered by your server-side scope.</p></div>
          <div className="tabs compact work-mode" role="group" aria-label="Work view">
            {(["project", "linear", "board"] as const).map((value) => <button type="button" className={mode === value ? "active" : ""} aria-pressed={mode === value} onClick={() => setMode(value)} key={value}>{value[0].toUpperCase() + value.slice(1)}</button>)}
          </div>
        </div>
        <form className="work-filters" aria-label="Create work item" onSubmit={(event) => void createItem(event)}>
          <input className="field-control" aria-label="New work intent" placeholder="Create work item…" required value={createIntent} onChange={(event) => {
            createFinalizer.invalidate();
            setCreateIntent(event.target.value);
          }} />
          <input className="field-control" aria-label="New work owner" placeholder="Owner / department (optional)" value={createOwner} onChange={(event) => {
            createFinalizer.invalidate();
            setCreateOwner(event.target.value);
          }} />
          <input className="field-control" aria-label="New work parent" placeholder="Parent ID (optional)" value={createParent} onChange={(event) => {
            createFinalizer.invalidate();
            setCreateParent(event.target.value);
          }} />
          <label className="checkbox-row"><input type="checkbox" checked={createConvergent} onChange={(event) => {
            createFinalizer.invalidate();
            setCreateConvergent(event.target.checked);
          }} />Convergent goal</label>
          <button className="primary-button" disabled={mutationBusy || !createIntent.trim()} type="submit">{mutationBusy ? "Creating…" : "Create"}</button>
        </form>
        <section className="work-filters" aria-label="Work filters">
          <input className="field-control" aria-label="Search work" placeholder="Search work…" value={query} onChange={(event) => setQuery(event.target.value)} />
          <select className="field-control" aria-label="Filter work status" value={status} onChange={(event) => setStatus(event.target.value as WorkStatus | "")}>
            <option value="">Every status</option>
            {WORK_STATUSES.map((value) => <option value={value} key={value}>{value.replaceAll("_", " ")}</option>)}
          </select>
          <select className="field-control" aria-label="Filter work owner" value={owner} onChange={(event) => setOwner(event.target.value)}><option value="">Every owner</option>{owners.map((value) => <option value={value} key={value}>{value}</option>)}</select>
          <select className="field-control" aria-label="Filter work source" value={source} onChange={(event) => setSource(event.target.value)}><option value="">Every source</option>{sources.map((value) => <option value={value} key={value}>{value}</option>)}</select>
          <select className="field-control" aria-label="Filter convergent work" value={convergent} onChange={(event) => setConvergent(event.target.value as "" | "yes" | "no")}><option value="">Every shape</option><option value="yes">Convergent goals</option><option value="no">Non-convergent work</option></select>
        </section>
        {error && <p className="notice">{error}</p>}
        {mutationMessage && <p className="notice">{mutationMessage}</p>}
        <ExactApprovalFinalizer controller={createFinalizer} />
        <div className={detail ? "split-view detail-open" : "split-view"}>
          <section className={`work-grid ${mode}`}>
            {visible.length === 0 && !error ? <Unavailable title="No work in this view">Change the filters, or give the agent a task to create the first work item.</Unavailable> : (
              mode === "linear"
                ? visible.map((item) => workButton(item))
                : mode === "board"
                  ? WORK_STATUSES.map((lane) => (
                    <section className="work-lane" aria-label={`${lane.replaceAll("_", " ")} work`} key={lane}>
                      <div className="section-heading"><strong>{lane.replaceAll("_", " ")}</strong><span className="row-meta">{visible.filter((item) => item.status === lane).length}</span></div>
                      {visible.filter((item) => item.status === lane).map((item) => workButton(item, "work-card compact"))}
                    </section>
                  ))
                  : projectRoots(visible).map((item) => (
                    <WorkProjectBranch item={item} all={visible} onInspect={inspect} key={item.id} />
                  ))
            )}
            {nextCursor && (
              <button className="secondary-button load-more" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadingMore ? "Loading…" : "Load more work"}
              </button>
            )}
          </section>
          {detail && <WorkDetail detail={detail} onClose={() => setSelectedWorkId(null)} onSelect={inspect} onChanged={changed} />}
        </div>
      </div>
    </div>
  );
}

type WorkDetailApprovalInput =
  | {
    kind: "assign";
    itemId: string;
    ownerMember: string | null;
    idempotencyKey: string;
  }
  | {
    kind: "status";
    itemId: string;
    status: WorkStatus;
    idempotencyKey: string;
  }
  | {
    kind: "parent";
    itemId: string;
    parentId: string | null;
    idempotencyKey: string;
  };

function WorkDetail({ detail, onClose, onSelect, onChanged }: { detail: WorkDetailResponse; onClose(): void; onSelect(item: WorkItem): void; onChanged(item: WorkItem, notice: string): void }) {
  const [owner, setOwner] = useState(detail.item.owner_member ?? "");
  const [parent, setParent] = useState(detail.item.parent_id ?? "");
  const [nextStatus, setNextStatus] = useState<WorkStatus>(detail.item.status);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  // Which form fields the user has edited since the form last matched the
  // canonical item. A ref, not state: it must never itself trigger the sync
  // effect, and it is read only inside handlers and that effect. Cleared per
  // field on a successful submit (the typed value IS canonical then) and
  // wholesale when a different item is shown.
  const dirty = useRef({ owner: false, parent: false, status: false });
  const shownItemId = useRef(detail.item.id);
  const inFlight = detail.item.status === "in_flight";
  const finalizer = useExactApprovalFinalizer<
    WorkDetailApprovalInput,
    WorkMutationResult
  >({
    isCurrent(input) {
      if (input.itemId !== detail.item.id) return false;
      if (input.kind === "assign") {
        return input.ownerMember === (owner.trim() || null);
      }
      if (input.kind === "status") return input.status === nextStatus;
      return input.parentId === (parent.trim() || null);
    },
    replay(input, approvalId) {
      if (input.kind === "assign") {
        return client.assignWork(
          input.itemId,
          input.ownerMember,
          input.idempotencyKey,
          approvalId,
        );
      }
      if (input.kind === "status") {
        return client.transitionWork(
          input.itemId,
          input.status,
          input.idempotencyKey,
          approvalId,
        );
      }
      return client.reparentWork(
        input.itemId,
        input.parentId,
        input.idempotencyKey,
        approvalId,
      );
    },
    onApplied(result, input) {
      if (!("item" in result)) return;
      if (input.kind === "assign") dirty.current.owner = false;
      else if (input.kind === "status") dirty.current.status = false;
      else dirty.current.parent = false;
      const message = input.kind === "assign"
        ? `Assignment updated to ${result.item.owner_member ?? "unassigned"}.`
        : input.kind === "status"
          ? `Status updated to ${result.item.status.replaceAll("_", " ")}.`
          : `Parent updated to ${result.item.parent_id ?? "root"}.`;
      onChanged(result.item, message);
    },
    onRefused(result) {
      setNotice(workMutationNotice(result, "Work update"));
    },
    onUncertain() {
      onChanged(
        detail.item,
        "Approval outcome is uncertain. Refreshing canonical work state.",
      );
    },
  });

  useEffect(() => {
    finalizer.invalidate();
    if (shownItemId.current !== detail.item.id) {
      // A DIFFERENT item: the form belongs to it now, wholesale.
      shownItemId.current = detail.item.id;
      dirty.current = { owner: false, parent: false, status: false };
      setOwner(detail.item.owner_member ?? "");
      setParent(detail.item.parent_id ?? "");
      setNextStatus(detail.item.status);
      setNotice("");
      return;
    }
    // The SAME item refreshed upstream (an agent moved it, a sibling approval
    // landed, the poll ticked). Reconcile only fields the user is not editing:
    // this effect used to reset all three unconditionally, so a background
    // refresh mid-edit silently replaced the typed value and the next Assign
    // submitted the OLD one - an approval collected for an action the user
    // never asked for, which is the one thing an approval must never be.
    if (!dirty.current.owner) setOwner(detail.item.owner_member ?? "");
    if (!dirty.current.parent) setParent(detail.item.parent_id ?? "");
    if (!dirty.current.status) setNextStatus(detail.item.status);
  }, [detail.item.id, detail.item.owner_member, detail.item.parent_id, detail.item.status]);

  async function mutate(kind: "assign" | "status" | "parent", clear = false) {
    setBusy(kind);
    setNotice("");
    try {
      const key = crypto.randomUUID();
      const input: WorkDetailApprovalInput = kind === "assign"
        ? {
          kind,
          itemId: detail.item.id,
          ownerMember: clear ? null : owner.trim() || null,
          idempotencyKey: key,
        }
        : kind === "status"
          ? {
            kind,
            itemId: detail.item.id,
            status: nextStatus,
            idempotencyKey: key,
          }
          : {
            kind,
            itemId: detail.item.id,
            parentId: clear ? null : parent.trim() || null,
            idempotencyKey: key,
          };
      const result = input.kind === "assign"
        ? await client.assignWork(
          input.itemId,
          input.ownerMember,
          input.idempotencyKey,
        )
        : input.kind === "status"
          ? await client.transitionWork(
            input.itemId,
            input.status,
            input.idempotencyKey,
          )
          : await client.reparentWork(
            input.itemId,
            input.parentId,
            input.idempotencyKey,
          );
      if (result.status === "ok") {
        finalizer.clear();
        if (kind === "assign") dirty.current.owner = false;
        else if (kind === "status") dirty.current.status = false;
        else dirty.current.parent = false;
        const message = kind === "assign"
          ? `Assignment updated to ${result.item.owner_member ?? "unassigned"}.`
          : kind === "status"
            ? `Status updated to ${result.item.status.replaceAll("_", " ")}.`
            : `Parent updated to ${result.item.parent_id ?? "root"}.`;
        onChanged(result.item, message);
      } else if (finalizer.begin(input, result, "Work update")) {
        setNotice("Work update is waiting for approval in the originating chat.");
      } else {
        setNotice(workMutationNotice(result, "Work update"));
      }
    } catch (reason) {
      setNotice(workMutationError(reason));
    } finally {
      setBusy("");
    }
  }

  return (
    <aside className="detail-panel" aria-label="Work item details">
      <div className="detail-heading">
        <div><p className="eyebrow">Work item</p><h3>{detail.item.intent}</h3></div>
        <button className="icon-button" aria-label="Close work details" onClick={() => {
          finalizer.invalidate();
          onClose();
        }}>×</button>
      </div>
      <dl className="fact-grid">
        <Fact label="ID" value={detail.item.id} />
        <Fact label="Status" value={detail.item.status.replaceAll("_", " ")} />
        <Fact label="Owner" value={detail.item.owner_member ?? "Unassigned"} />
        <Fact label="Confidence" value={detail.item.confidence == null ? "—" : `${Math.round(detail.item.confidence * 100)}%`} />
        <Fact label="Source" value={detail.item.source ?? "Boltrig"} />
        <Fact label="Shape" value={detail.item.convergent ? "Convergent goal" : "Non-convergent work"} />
        <Fact label="Parent" value={detail.item.parent_id ?? "Root"} />
        <Fact label="Hatchet run" value={detail.item.hatchet_run_id ?? "None"} />
        <Fact label="On behalf of" value={detail.item.on_behalf_of ?? "Self"} />
      </dl>
      <div className="detail-section">
        <p className="eyebrow">Lifecycle</p>
        <div className="stack">
          <label className="field-label">Owner<input className="field-control" value={owner} onChange={(event) => {
            finalizer.invalidate();
            dirty.current.owner = true;
            setOwner(event.target.value);
          }} placeholder="Department or fleet member" /></label>
          <div className="button-row"><button className="primary-button" disabled={Boolean(busy) || inFlight} onClick={() => void mutate("assign")}>{busy === "assign" ? "Saving…" : "Assign"}</button><button className="secondary-button" disabled={Boolean(busy) || inFlight} onClick={() => void mutate("assign", true)}>Unassign</button></div>
          <label className="field-label">Status<select className="field-control" value={nextStatus} onChange={(event) => {
            finalizer.invalidate();
            dirty.current.status = true;
            setNextStatus(event.target.value as WorkStatus);
          }}>{[detail.item.status, ...MANUAL_WORK_TRANSITIONS[detail.item.status]].map((value) => <option value={value} key={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
          <button className="secondary-button" disabled={Boolean(busy) || nextStatus === detail.item.status} onClick={() => void mutate("status")}>{busy === "status" ? "Submitting…" : "Change status"}</button>
          <label className="field-label">Parent<input className="field-control" value={parent} onChange={(event) => {
            finalizer.invalidate();
            dirty.current.parent = true;
            setParent(event.target.value);
          }} placeholder="Root (blank) or parent ID" /></label>
          <div className="button-row"><button className="secondary-button" disabled={Boolean(busy) || inFlight} onClick={() => void mutate("parent")}>{busy === "parent" ? "Submitting…" : "Change parent"}</button><button className="secondary-button" disabled={Boolean(busy) || inFlight} onClick={() => void mutate("parent", true)}>Make root</button></div>
          {notice && <p className="notice">{notice}</p>}
          <ExactApprovalFinalizer controller={finalizer} />
          <p className="muted small">{inFlight ? "This item is in flight, so manual lifecycle controls are locked." : "Status and parent changes pause for approval. Active or leased work is protected from manual edits."}</p>
        </div>
      </div>
      <div className="detail-section">
        <p className="eyebrow">Children</p>
        {detail.children.length === 0 ? <p className="muted small">No child work.</p> : detail.children.map((item) => (
          <button className="child-row" key={item.id} onClick={() => onSelect(item)}>{item.intent}<span>{item.status.replaceAll("_", " ")}</span></button>
        ))}
      </div>
      <div className="detail-section">
        <p className="eyebrow">Audit trail</p>
        {detail.audit.length === 0 ? <p className="muted small">No events recorded.</p> : detail.audit.slice(-200).map((event) => (
          <details className="audit-line work-audit-line" key={`${event.ts}-${event.verb}`}>
            <summary><span className={`activity-dot ${statusClass(event.status)}`} /><span>{event.noun}.{event.verb}<small>{event.actor} ({event.actor_tier}) · {formatDate(event.ts)} · {event.status}</small></span></summary>
            {event.detail != null && <pre>{JSON.stringify(event.detail, null, 2)}</pre>}
          </details>
        ))}
        {detail.audit.length >= 200 && <p className="muted small">Showing the endpoint’s 200-event cap.</p>}
      </div>
    </aside>
  );
}

const WORK_STATUSES: WorkStatus[] = ["pending", "in_flight", "blocked", "awaiting_human", "done", "failed", "cancelled"];
const MANUAL_WORK_TRANSITIONS: Record<WorkStatus, WorkStatus[]> = {
  pending: ["blocked", "awaiting_human", "failed", "cancelled"],
  in_flight: [],
  blocked: ["pending", "failed", "cancelled"],
  awaiting_human: ["blocked", "done", "failed", "cancelled"],
  done: [],
  failed: ["pending"],
  cancelled: [],
};

function workMutationNotice(result: { status: string; reason?: string }, action: string): string {
  if (result.status === "pending_human") return `${action} is waiting for approval in the originating chat.`;
  if (result.status === "denied") return result.reason ?? `${action} was denied.`;
  if (result.status === "degraded") return `${action} could not complete because the control plane is degraded.`;
  return result.reason ?? `${action} failed.`;
}

function workMutationError(reason: unknown): string {
  if (reason instanceof BoltrigApiError && reason.body && typeof reason.body === "object") {
    const body = reason.body as { reason?: unknown };
    if (typeof body.reason === "string") return body.reason;
  }
  return reason instanceof Error ? reason.message : "The Work control plane is unavailable.";
}

function projectRoots(items: WorkItem[]): WorkItem[] {
  const visibleIds = new Set(items.map((item) => item.id));
  const roots = items.filter((item) => !item.parent_id || !visibleIds.has(item.parent_id));
  return roots.length ? roots : items;
}

function WorkProjectBranch({
  item,
  all,
  onInspect,
  depth = 0,
  ancestry = [],
}: {
  item: WorkItem;
  all: WorkItem[];
  onInspect(item: WorkItem): void;
  depth?: number;
  ancestry?: string[];
}) {
  const children = all.filter((candidate) => (
    candidate.parent_id === item.id
    && candidate.id !== item.id
    && !ancestry.includes(candidate.id)
  ));
  return (
    <div className="work-project-branch" style={{ "--work-depth": depth } as React.CSSProperties}>
      <button className={`work-card${item.convergent ? " convergent" : ""}`} onClick={() => onInspect(item)}>
        <span className={`activity-dot ${statusClass(item.status)}`} />
        <span><strong>{item.intent}</strong><small>{children.length} children · {item.owner_member || "Unassigned"}{item.convergent ? " · convergent goal" : ""}</small></span>
        <span className="row-meta">{item.status.replaceAll("_", " ")}</span>
      </button>
      {children.map((child) => <WorkProjectBranch item={child} all={all} onInspect={onInspect} depth={depth + 1} ancestry={[...ancestry, item.id]} key={child.id} />)}
    </div>
  );
}

export function AgentsView() {
  const [selectedAgentName, setSelectedAgentName] = useRouteSelection("agents");
  const [agents, setAgents] = useState<AgentCapabilityAuthorInfo[]>([]);
  const [surfaceState, setSurfaceState] = useState<SurfaceState>("loading");
  const loadedAgents = useRef(false);
  // Names with a pending decision they raised (HITL requested_by /
  // requested_on_behalf_of). This is the only real per-agent "asking" signal
  // this client has; when the decision is not visible to this role the set
  // stays empty and no waiting state is claimed.
  const [askingActors, setAskingActors] = useState<ReadonlySet<string> | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState<AgentCapabilityAuthorInfo | null | undefined>(undefined);
  const [creatingAgent, setCreatingAgent] = useState(false);
  const lifecycleFinalizer = useExactApprovalFinalizer<
    { name: string; action: "retire" | "restore" },
    CapabilityLifecycleResponse
  >({
    isCurrent: (input) => agents.some((agent) => (
      agent.name === input.name
      && agent.is_active === (input.action === "retire")
    )),
    replay: (input, approvalId) => (
      input.action === "retire"
        ? client.retireAgentCapability(input.name, approvalId)
        : client.restoreAgentCapability(input.name, approvalId)
    ),
    onApplied: async (_result, input) => {
      setMessage(
        `${input.name} ${input.action === "retire" ? "retired" : "restored"}.`,
      );
      refresh();
    },
    onRefused: (result) => {
      setMessage(result.reason ?? "The approved profile change was not applied.");
    },
  });
  function refresh() {
    lifecycleFinalizer.invalidate();
    void client.agentCapabilities()
      .then((result) => {
        setAgents(result.agent_capabilities);
        loadedAgents.current = true;
        setSurfaceState("ready");
        setError("");
      })
      .catch((reason) => {
        const state = failureState(reason);
        if (state === "unavailable" && loadedAgents.current) {
          setError("Agent profiles could not be refreshed. Showing the last loaded roster.");
          return;
        }
        loadedAgents.current = false;
        setError("");
        setAgents([]);
        setEditing(undefined);
        setSurfaceState(state);
      });
    void client.hitl()
      .then((result) => {
        setAskingActors(new Set(result.requests.flatMap((request) => (
          [request.requested_by, request.requested_on_behalf_of]
            .filter((value): value is string => Boolean(value))
        ))));
      })
      .catch(() => setAskingActors(null));
  }
  useEffect(refresh, []);
  useEffect(() => {
    lifecycleFinalizer.invalidate();
    if (!selectedAgentName) {
      setEditing((current) => current ? undefined : current);
      return;
    }
    const selectedAgent = agents.find((agent) => agent.name === selectedAgentName);
    if (selectedAgent) setEditing(selectedAgent);
    else if (surfaceState === "ready") setEditing(undefined);
  }, [agents, selectedAgentName, surfaceState]);

  async function changeLifecycle(agent: AgentCapabilityAuthorInfo) {
    setBusy(agent.name);
    setMessage("");
    try {
      const action = agent.is_active ? "retire" : "restore";
      const input = { name: agent.name, action } as const;
      const result = agent.is_active
        ? await client.retireAgentCapability(agent.name)
        : await client.restoreAgentCapability(agent.name);
      if (lifecycleFinalizer.begin(
        input,
        result,
        action === "retire" ? "Profile retirement" : "Profile restore",
      )) {
        setMessage(`${action === "retire" ? "Retirement" : "Restore"} is waiting for approval in the originating chat.`);
      } else if (result.status === "ok") {
        setMessage(`${agent.name} ${action === "retire" ? "retired" : "restored"}.`);
        refresh();
      } else {
        setMessage(result.reason ?? `${agent.name} was not changed.`);
      }
    } catch {
      setMessage("Agent lifecycle management is unavailable.");
    } finally {
      setBusy("");
    }
  }

  const unknownAgent = surfaceState === "ready"
    && Boolean(selectedAgentName)
    && !agents.some((agent) => agent.name === selectedAgentName);
  return (
    <div className="page agents-fleet-shell">
      <div className="agents-fleet-page">
        <div className="agents-fleet-topbar">
          <AgentTabsStrip active="agents" />
          {surfaceState === "ready" && (
            <button
              className="console-primary"
              onClick={() => {
                lifecycleFinalizer.invalidate();
                setMessage("");
                setSelectedAgentName(null);
                setEditing(undefined);
                setCreatingAgent(true);
              }}
              type="button"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
                <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              <span>New agent</span>
            </button>
          )}
        </div>

        {(error || message || lifecycleFinalizer.state !== null) && (
          <div className="agents-fleet-alerts">
            {error && <p className="notice">{error}</p>}
            {message && <p className="notice" role="status">{message}</p>}
            <ExactApprovalFinalizer controller={lifecycleFinalizer} />
          </div>
        )}

        {surfaceState === "loading" && <Unavailable title="Loading agent profiles">Checking the author-visible agent inventory.</Unavailable>}
        {surfaceState === "denied" && <Unavailable title="Agent access denied">Your current role cannot view or author agent profiles.</Unavailable>}
        {surfaceState === "not-found" && <Unavailable title="Agent inventory not found">This deployment does not expose the canonical agent inventory route.</Unavailable>}
        {surfaceState === "unavailable" && <Unavailable title="Agents unavailable">The agent inventory could not be reached.</Unavailable>}
        {surfaceState === "ready" && unknownAgent && <Unavailable title="Agent profile not found">No visible agent profile matches “{selectedAgentName}”.</Unavailable>}
        {surfaceState === "ready" && !unknownAgent && (
          <PermanentFleetTopology
            askingActors={askingActors}
            lifecycleBusy={busy}
            onCreateProfile={(parentName) => {
              lifecycleFinalizer.invalidate();
              setSelectedAgentName(null);
              setEditing(null);
              setMessage(parentName
                ? `Profile author opened from ${parentName}. This profile API does not persist a parent edge.`
                : "");
            }}
            onEditProfile={(agent) => setSelectedAgentName(agent.name)}
            onLifecycle={(agent) => void changeLifecycle(agent)}
            profiles={agents}
          />
        )}
        {surfaceState === "ready" && !unknownAgent && editing !== undefined && (
          <div className="agents-profile-editor-scrim" role="presentation">
            <AgentProfileEditor
              initial={editing}
              onCancel={() => { setEditing(undefined); setSelectedAgentName(null); }}
              onSaved={refresh}
            />
          </div>
        )}
        {surfaceState === "ready" && !unknownAgent && creatingAgent && (
          <GovernedCreateModal
            lead="An agent is someone to hand work to. It can only ever do what you can."
            methods={[
              {
                available: false,
                description: "Start from an agent already doing the job well, then narrow it. Nothing is widened by copying.",
                icon: <CreateMethodIcon kind="copy" />,
                tag: "Recommended",
                title: "Copy one that works",
                unavailableReason: "The capability API does not expose profile cloning.",
              },
              {
                available: false,
                description: "Say what it should look after, then review a proposed capability profile.",
                icon: <CreateMethodIcon kind="describe" />,
                title: "Describe the job",
                unavailableReason: "No proposal-from-description route is exposed.",
              },
              {
                available: true,
                description: "An empty agent with no permissions at all. Add each capability deliberately.",
                icon: <CreateMethodIcon kind="empty" />,
                onSelect: () => {
                  setCreatingAgent(false);
                  setEditing(null);
                },
                title: "Start from nothing",
              },
            ]}
            onClose={() => setCreatingAgent(false)}
            title="New agent"
          />
        )}
      </div>
    </div>
  );
}

// The Knowledge surface was recast to the decided target's file-table +
// detail-rail layout and now lives in its own module; the export stays here
// so App.tsx and Views.tsx keep their import path.
export { KnowledgeView } from "./knowledge/KnowledgeView";

type MemoryApprovalInput =
  | {
    kind: "remember";
    body: Parameters<typeof client.memoryRemember>[0];
  }
  | {
    kind: "improve";
    body: Parameters<typeof client.memoryImprove>[0];
  }
  | {
    kind: "forget";
    body: Parameters<typeof client.memoryForget>[0];
  }
  | {
    kind: "ingest";
    body: Parameters<typeof client.memoryIngest>[0];
  };

type MemoryApprovalResult =
  | Awaited<ReturnType<typeof client.memoryRemember>>
  | Awaited<ReturnType<typeof client.memoryImprove>>
  | Awaited<ReturnType<typeof client.memoryForget>>
  | Awaited<ReturnType<typeof client.memoryIngest>>;

export function MemoryView() {
  const [tab, setTab] = useState<"browse" | "recall" | "remember" | "ingest" | "review">("browse");
  const [facts, setFacts] = useState<MemoryFactView[]>([]);
  const [surfaceState, setSurfaceState] = useState<SurfaceState>("loading");
  const loadedMemory = useRef(false);
  const [selectedFactId, setSelectedFactId] = useRouteSelection("memory");
  const [selectedFact, setSelectedFact] = useState<MemoryFactView | null>(null);
  const [detailState, setDetailState] = useState<DetailState>("idle");
  const [query, setQuery] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [ownerScope, setOwnerScope] = useState("");
  const [recallMode, setRecallMode] = useState<"similarity" | "graph_completion">("graph_completion");
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("fact");
  const [message, setMessage] = useState("");
  const [armed, setArmed] = useState<string | null>(null);
  const [ingestions, setIngestions] = useState<MemoryIngestionRow[]>([]);
  const [sourceKind, setSourceKind] = useState("conversation");
  const [sourceRef, setSourceRef] = useState("");
  const [ingestItems, setIngestItems] = useState("");
  const [candidates, setCandidates] = useState<MemoryCandidateView[]>([]);
  const [timeline, setTimeline] = useState<MemoryTimelineResponse | null>(null);
  const approval = useExactApprovalFinalizer<
    MemoryApprovalInput,
    MemoryApprovalResult
  >({
    isCurrent(input) {
      if (input.kind === "remember") {
        return JSON.stringify(input.body) === JSON.stringify(rememberInput());
      }
      if (input.kind === "improve") {
        return facts.some((fact) => fact.id === input.body.target);
      }
      if (input.kind === "forget") {
        if (input.body.target) {
          return facts.some((fact) => fact.id === input.body.target);
        }
        return facts.some(
          (fact) => fact.provenance.source_ref === input.body.source_ref,
        );
      }
      return JSON.stringify(input.body) === JSON.stringify(ingestInput());
    },
    replay(input, approvalId) {
      if (input.kind === "remember") {
        return client.memoryRemember(input.body, approvalId);
      }
      if (input.kind === "improve") {
        return client.memoryImprove(input.body, approvalId);
      }
      if (input.kind === "forget") {
        return client.memoryForget(input.body, approvalId);
      }
      return client.memoryIngest(input.body, approvalId);
    },
    async onApplied(result, input) {
      if (input.kind === "remember") {
        setMessage("Remembered with provenance.");
        setContent("");
        setTab("browse");
        refresh(true);
        return;
      }
      if (input.kind === "improve") {
        const adjusted = "adjusted" in result ? result.adjusted : undefined;
        setMessage(
          adjusted
            ? input.body.signal === "up"
              ? "Marked as useful. Future recall will rank it more strongly."
              : "Marked as not useful. Future recall will rank it less strongly."
            : "That memory could not be reweighted.",
        );
        refresh(true);
        return;
      }
      if (input.kind === "forget") {
        const removed = "facts_removed" in result
          ? result.facts_removed ?? result.removed?.length ?? 0
          : 0;
        setMessage(
          input.body.source_ref
            ? `Forgot ${removed} facts from that exact source.`
            : "The selected fact was forgotten.",
        );
        setArmed(null);
        refresh(true);
        return;
      }
      const factsAdded = "facts_added" in result ? result.facts_added ?? 0 : 0;
      const ingestionId = "id" in result ? result.id ?? "" : "";
      setMessage(
        `Ingestion ${ingestionId} added ${factsAdded} facts after screening.`,
      );
      setSourceRef("");
      setIngestItems("");
      const history = await client.memoryIngestions();
      setIngestions(history.ingestions ?? []);
      refresh(true);
    },
    onRefused(result) {
      setMessage(result.reason ?? "The approved memory change was not applied.");
    },
    onUncertain() {
      refresh(true);
    },
  });

  function rememberInput(): Parameters<typeof client.memoryRemember>[0] {
    return {
      content: content.trim(),
      kind,
      owner_scope: ownerScope || undefined,
    };
  }

  function ingestInput(): Parameters<typeof client.memoryIngest>[0] {
    return {
      source_kind: sourceKind.trim(),
      source_ref: sourceRef.trim(),
      owner_scope: ownerScope || undefined,
      items: ingestItems.split("\n").map((item) => item.trim()).filter(Boolean),
    };
  }

  function refresh(preserveMessage = false) {
    if (!preserveMessage) setMessage("");
    void client.memoryFacts({ limit: 60 })
      .then((result) => {
        setFacts(result.facts);
        setScopes(result.scopes);
        setOwnerScope((current) => (
          current && result.scopes.includes(current)
            ? current
            : result.scopes[0] ?? ""
        ));
        loadedMemory.current = true;
        setSurfaceState("ready");
      })
      .catch((reason) => {
        const state = failureState(reason);
        if (state === "unavailable" && loadedMemory.current) {
          setMessage("Memory could not be refreshed. Showing the last loaded facts.");
          return;
        }
        loadedMemory.current = false;
        setFacts([]);
        setScopes([]);
        setOwnerScope("");
        setSurfaceState(state);
      });
  }
  useEffect(refresh, []);

  useEffect(() => {
    if (!selectedFactId) {
      setSelectedFact(null);
      setDetailState("idle");
      return;
    }
    if (surfaceState !== "ready") {
      setSelectedFact(null);
      setDetailState("idle");
      return;
    }
    let current = true;
    setTab("browse");
    setSelectedFact(null);
    setDetailState("loading");
    void client.memoryFact(selectedFactId)
      .then((result) => {
        if (current) {
          setSelectedFact(result.fact);
          setDetailState("ready");
        }
      })
      .catch((error) => {
        if (!current) return;
        setSelectedFact(null);
        setDetailState(failureState(error));
      });
    return () => {
      current = false;
    };
  }, [selectedFactId, surfaceState]);

  useEffect(() => {
    if (tab !== "ingest") return;
    void client.memoryIngestions()
      .then((result) => setIngestions(result.ingestions ?? []))
      .catch(() => setMessage("Memory ingestion history is unavailable."));
  }, [tab]);

  useEffect(() => {
    if (tab !== "review") return;
    refreshCandidates();
  }, [tab]);

  async function recall() {
    if (!query.trim()) return;
    const result = await client.memoryRecall({
      query: query.trim(),
      mode: recallMode,
      limit: 16,
      owner_scope: ownerScope || undefined,
    });
    if (result.reason) setMessage(result.reason === "binding_not_found" ? "Memory is not enabled." : result.reason);
    else {
      setFacts(result.facts ?? []);
      setMessage(`${result.count ?? result.facts?.length ?? 0} recalled facts.`);
    }
  }

  async function remember() {
    if (!content.trim()) return;
    approval.invalidate();
    const input: MemoryApprovalInput = {
      kind: "remember",
      body: rememberInput(),
    };
    const result = await client.memoryRemember(input.body);
    if (approval.begin(input, result, "Memory addition")) return;
    setMessage(result.reason ?? (result.status === "ok" ? "Remembered with provenance." : result.status));
    if (result.status === "ok") {
      approval.clear();
      setContent("");
      refresh(true);
      setTab("browse");
    }
  }

  function refreshCandidates() {
    setTimeline(null);
    void client.memoryCandidates({ limit: 60 })
      .then((result) => setCandidates(result.candidates ?? []))
      .catch(() => setMessage("The candidate queue is unavailable."));
  }

  async function review(candidate: MemoryCandidateView, decision: "approve" | "reject") {
    const key = `${decision}:${candidate.id}`;
    if (armed !== key) {
      setArmed(key);
      return;
    }
    setArmed(null);
    // Review is high-consequence, so the first call may pend for an approval.
    // The operator's confirming click IS that approval: answer the canonical
    // HITL request as this principal, then replay the exact review with it.
    const result = await client.memoryCandidateReview(candidate.id, { decision });
    let final = result;
    if (result.hitl_request_id) {
      const approvalId = result.hitl_request_id;
      try {
        await client.respondHitl(approvalId, "approve");
      } catch {
        // The replay below pends again and surfaces the waiting message.
      }
      final = await client.memoryCandidateReview(candidate.id, { decision }, approvalId);
    }
    if (final.status === "ok") {
      setMessage(decision === "approve"
        ? "Candidate approved and active."
        : "Candidate rejected.");
      refreshCandidates();
    } else {
      setMessage(final.reason ?? "The review is waiting for approval in the originating chat.");
    }
  }

  function showTimeline(candidate: MemoryCandidateView) {
    if (!candidate.memory_key) return;
    if (timeline?.memory_key === candidate.memory_key) {
      setTimeline(null);
      return;
    }
    void client.memoryTimeline({ memory_key: candidate.memory_key })
      .then(setTimeline)
      .catch(() => setMessage("The slot history is unavailable."));
  }

  async function forgetSource(sourceRefValue: string) {
    const key = `source:${sourceRefValue}`;
    if (armed !== key) {
      setArmed(key);
      return;
    }
    approval.invalidate();
    const input: MemoryApprovalInput = {
      kind: "forget",
      body: { source_ref: sourceRefValue },
    };
    const result = await client.memoryForget(input.body);
    if (approval.begin(input, result, "Exact-source erasure")) {
      setArmed(null);
      return;
    }
    setMessage(result.reason ?? (
      result.status === "ok"
        ? `Forgot ${result.facts_removed ?? result.removed?.length ?? 0} facts from that exact source.`
        : result.status
    ));
    approval.clear();
    setArmed(null);
    refresh(true);
  }

  async function forget(fact: MemoryFactView) {
    if (armed !== fact.id) {
      setArmed(fact.id);
      return;
    }
    approval.invalidate();
    const input: MemoryApprovalInput = {
      kind: "forget",
      body: { target: fact.id },
    };
    const result = await client.memoryForget(input.body);
    if (approval.begin(input, result, "Memory erasure")) {
      setArmed(null);
      return;
    }
    setMessage(result.reason ?? (
      result.status === "ok"
        ? "The selected fact was forgotten."
        : result.status === "pending_human"
          ? "Forgetting this fact is waiting for approval in the originating chat."
          : result.status
    ));
    approval.clear();
    setArmed(null);
    refresh(true);
  }

  async function improve(fact: MemoryFactView, signal: "up" | "down") {
    approval.invalidate();
    const input: MemoryApprovalInput = {
      kind: "improve",
      body: { target: fact.id, signal },
    };
    const result = await client.memoryImprove(input.body);
    if (approval.begin(input, result, "Memory feedback")) return;
    setMessage(result.reason ?? (
      result.status === "ok" && result.adjusted
        ? signal === "up"
          ? "Marked as useful. Future recall will rank it more strongly."
          : "Marked as not useful. Future recall will rank it less strongly."
        : "That memory could not be reweighted."
    ));
    approval.clear();
  }

  async function ingest(event: React.FormEvent) {
    event.preventDefault();
    if (!sourceRef.trim()) return;
    approval.invalidate();
    const input: MemoryApprovalInput = {
      kind: "ingest",
      body: ingestInput(),
    };
    const result = await client.memoryIngest(input.body);
    if (approval.begin(input, result, "Memory ingestion")) return;
    setMessage(result.reason ?? (
      result.status === "ok"
        ? `Ingestion ${result.id ?? ""} added ${result.facts_added ?? 0} facts after screening.`
        : result.status === "pending_human"
          ? "Ingestion is waiting for approval in the originating chat."
          : `Ingestion status: ${result.status}.`
    ));
    if (result.status === "ok") {
      approval.clear();
      setSourceRef("");
      setIngestItems("");
      const history = await client.memoryIngestions();
      setIngestions(history.ingestions ?? []);
    }
  }

  return (
    <div className="page">
      <Topbar title="Memory" status={`${facts.length} in view`} />
      <div className="page-content">
        <div className="page-intro"><div><h2>Revisable memory</h2><p>Recall, inspect and explicitly change what the assistant remembers, with provenance attached to every fact.</p></div></div>
        {surfaceState === "ready" && <Tabs value={tab} options={[["browse", "Browse"], ["recall", "Recall"], ["remember", "Remember"], ["ingest", "Ingest"], ["review", `Review${candidates.length ? ` (${candidates.length})` : ""}`]]} onChange={(value) => {
          approval.invalidate();
          setArmed(null);
          setTab(value as typeof tab);
        }} />}
        {message && <p className="notice" role="status">{message}</p>}
        <ExactApprovalFinalizer controller={approval} />
        {surfaceState === "loading" && <Unavailable title="Loading memory">Loading facts in your permitted memory scopes.</Unavailable>}
        {surfaceState === "denied" && <Unavailable title="Memory access denied">Your current role cannot browse memory in this workspace.</Unavailable>}
        {surfaceState === "not-found" && <Unavailable title="Memory not found">This deployment does not expose the canonical memory browse route.</Unavailable>}
        {surfaceState === "unavailable" && <Unavailable title="Memory unavailable">The memory service could not be reached.</Unavailable>}
        {surfaceState === "ready" && detailState === "loading" && <Unavailable title="Loading memory detail">Loading the exact scoped fact.</Unavailable>}
        {surfaceState === "ready" && detailState === "denied" && <Unavailable title="Memory detail denied">Your current role cannot inspect that memory fact.</Unavailable>}
        {surfaceState === "ready" && detailState === "not-found" && <Unavailable title="Memory fact not found">That memory fact is outside your current scope or no longer exists.</Unavailable>}
        {surfaceState === "ready" && detailState === "unavailable" && <Unavailable title="Memory detail unavailable">The exact memory fact could not be reached.</Unavailable>}
        {surfaceState === "ready" && detailState === "ready" && selectedFact && (
          <section aria-label="Memory fact details" className="settings-card">
            <div className="editable-row">
              <div>
                <p className="eyebrow">Memory detail</p>
                <h2>{selectedFact.kind.replaceAll("_", " ")}</h2>
              </div>
              <button
                aria-label="Close memory detail"
                className="icon-button"
                onClick={() => setSelectedFactId(null)}
              >
                ×
              </button>
            </div>
            <p>{contentText(selectedFact.content)}</p>
            <dl className="fact-grid">
              <Fact label="Owner scope" value={selectedFact.owner_scope} />
              <Fact label="Data class" value={selectedFact.data_class} />
              <Fact label="Source" value={
                selectedFact.provenance.source_ref
                  ?? selectedFact.provenance.source_kind
                  ?? "direct"
              } />
            </dl>
          </section>
        )}
        {surfaceState === "ready" && tab === "recall" && (
          <form className="search-form" onSubmit={(event) => { event.preventDefault(); void recall(); }}>
            <input className="field-control" aria-label="Recall from memory" placeholder="What do we know about…" value={query} onChange={(event) => setQuery(event.target.value)} />
            <select className="field-control" aria-label="Recall scope" value={ownerScope} onChange={(event) => setOwnerScope(event.target.value)}>
              {scopes.map((scope) => <option value={scope} key={scope}>{scope}</option>)}
            </select>
            <select className="field-control" aria-label="Recall mode" value={recallMode} onChange={(event) => setRecallMode(event.target.value as typeof recallMode)}>
              <option value="graph_completion">Graph completion</option>
              <option value="similarity">Similarity</option>
            </select>
            <button className="primary-button" disabled={!query.trim()}>Recall</button>
          </form>
        )}
        {surfaceState === "ready" && tab === "remember" && (
          <div className="memory-form">
            <label><span>What should Boltrig remember?</span><textarea className="field-control" rows={6} value={content} onChange={(event) => {
              approval.invalidate();
              setContent(event.target.value);
            }} /></label>
            <label><span>Kind</span><input className="field-control" value={kind} onChange={(event) => {
              approval.invalidate();
              setKind(event.target.value);
            }} /></label>
            <label><span>Owner scope</span><select className="field-control" value={ownerScope} onChange={(event) => {
              approval.invalidate();
              setOwnerScope(event.target.value);
            }}>{scopes.map((scope) => <option value={scope} key={scope}>{scope}</option>)}</select></label>
            <button className="primary-button" disabled={!content.trim()} onClick={() => void remember()}>Remember</button>
          </div>
        )}
        {surfaceState === "ready" && tab === "ingest" && (
          <div className="home-columns">
            <form className="settings-card author-form" onSubmit={(event) => void ingest(event)}>
              <p className="eyebrow">Screened ingestion</p><h2>Ingest an exact source</h2>
              <label><span>Source kind</span><input className="field-control" required value={sourceKind} onChange={(event) => {
                approval.invalidate();
                setSourceKind(event.target.value);
              }} /></label>
              <label><span>Source reference</span><input className="field-control" required value={sourceRef} onChange={(event) => {
                approval.invalidate();
                setSourceRef(event.target.value);
              }} /></label>
              <label><span>Owner scope</span><select className="field-control" value={ownerScope} onChange={(event) => {
                approval.invalidate();
                setOwnerScope(event.target.value);
              }}>{scopes.map((scope) => <option value={scope} key={scope}>{scope}</option>)}</select></label>
              <label><span>Candidate facts (one per line)</span><textarea className="field-control" rows={7} value={ingestItems} onChange={(event) => {
                approval.invalidate();
                setIngestItems(event.target.value);
              }} /></label>
              <button className="primary-button">Ingest</button>
            </form>
            <section className="settings-card">
              <p className="eyebrow">History</p><h2>Recent ingestions</h2>
              {ingestions.length === 0 ? <p className="muted">No ingestions are visible.</p> : ingestions.map((row) => (
                <div className="compact-row" key={row.id}>
                  <span className={`activity-dot ${statusClass(row.status)}`} />
                  <span><strong>{row.source_ref}</strong><small>{row.source_kind} · {row.facts_added} added / {row.screened} screened</small></span>
                  <span className="row-meta">{row.status}</span>
                </div>
              ))}
            </section>
          </div>
        )}
        {surfaceState === "ready" && tab === "review" && (
          <>
            {candidates.length === 0 ? (
              <Unavailable title="No candidates">Nothing is waiting for review. Conflicted facts and proposed procedures appear here for a decision.</Unavailable>
            ) : (
              <div className="memory-grid">{candidates.map((candidate) => (
                <article className="memory-card" key={candidate.id}>
                  <div className="memory-card-head">
                    <span>{candidate.kind}</span>
                    <span>{candidate.confidence != null ? `confidence ${candidate.confidence.toFixed(2)}` : "review"}</span>
                  </div>
                  <p>{contentText(candidate.content)}</p>
                  {candidate.memory_key && <small>slot {candidate.memory_key}</small>}
                  <small>{candidate.owner_scope} · {candidate.provenance.source_kind || "direct"}{candidate.provenance.source_ref ? ` · ${candidate.provenance.source_ref}` : ""}</small>
                  <div className="memory-feedback" aria-label="Candidate review">
                    <button
                      className={armed === `approve:${candidate.id}` ? "primary-button armed" : "primary-button"}
                      onClick={() => void review(candidate, "approve")}
                    >
                      {armed === `approve:${candidate.id}` ? "Confirm approve" : "Approve"}
                    </button>
                    <button
                      className={armed === `reject:${candidate.id}` ? "danger-button armed" : "danger-button"}
                      onClick={() => void review(candidate, "reject")}
                    >
                      {armed === `reject:${candidate.id}` ? "Confirm reject" : "Reject"}
                    </button>
                    {candidate.memory_key && (
                      <button className="secondary-button" onClick={() => showTimeline(candidate)}>
                        {timeline?.memory_key === candidate.memory_key ? "Hide history" : "Slot history"}
                      </button>
                    )}
                  </div>
                  {timeline !== null && timeline.memory_key === candidate.memory_key && (
                    <div aria-label="Slot version history">
                      {timeline.versions.map((version) => (
                        <div className="compact-row" key={version.id}>
                          <span className={`activity-dot ${version.status === "active" ? "status-ok" : "status-held"}`} />
                          <span>
                            <strong>v{version.version} · {String(version.value ?? contentText(version.content))}</strong>
                            <small>{version.status}{version.valid_from ? ` · from ${version.valid_from.slice(0, 10)}` : ""}</small>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </article>
              ))}</div>
            )}
          </>
        )}
        {surfaceState === "ready" && (tab === "browse" || tab === "recall") && (
          facts.length === 0 ? <Unavailable title="No memory facts in view">Recall something specific, or remember the first fact.</Unavailable> :
          <div className="memory-grid">{facts.map((fact) => (
            <article className="memory-card" key={fact.id}>
              <div className="memory-card-head"><span>{fact.kind}</span><span>{fact.data_class}</span></div>
              <p>{contentText(fact.content)}</p>
              <small>{fact.owner_scope} · {fact.provenance.source_kind || "direct"}{fact.provenance.source_ref ? ` · ${fact.provenance.source_ref}` : ""}{fact.provenance.hops != null ? ` · ${fact.provenance.hops} hops` : ""}</small>
              {fact.provenance.path?.length ? <small>Path: {fact.provenance.path.join(" → ")}</small> : null}
              <div className="memory-feedback" aria-label="Memory feedback">
                <button className="secondary-button" onClick={() => setSelectedFactId(fact.id)}>Inspect</button>
                <button className="secondary-button" onClick={() => void improve(fact, "up")}>Useful</button>
                <button className="secondary-button" onClick={() => void improve(fact, "down")}>Not useful</button>
              </div>
              <button className={armed === fact.id ? "danger-button armed" : "danger-button"} onClick={() => void forget(fact)}>{armed === fact.id ? "Confirm forget" : "Forget"}</button>
              {fact.provenance.source_ref && (
                <button className={armed === `source:${fact.provenance.source_ref}` ? "danger-button armed" : "secondary-button"} onClick={() => void forgetSource(fact.provenance.source_ref as string)}>
                  {armed === `source:${fact.provenance.source_ref}` ? "Confirm source erase" : "Forget exact source"}
                </button>
              )}
            </article>
          ))}</div>
        )}
      </div>
    </div>
  );
}

function Tabs({ value, options, onChange }: { value: string; options: string[][]; onChange(value: string): void }) {
  return <nav className="tabs" aria-label="View sections">{options.map(([id, label]) => <button className={value === id ? "active" : ""} aria-current={value === id ? "page" : undefined} onClick={() => onChange(id)} key={id}>{label}</button>)}</nav>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function runSelectionId(row: RunRow): string {
  return row.run_id ?? row.work_item;
}

function statusClass(status: string) {
  if (["done", "ok", "completed", "active"].includes(status)) return "ok";
  if (["failed", "error", "cancelled"].includes(status)) return "error";
  if (["blocked", "awaiting_human", "paused", "pending_human"].includes(status)) return "paused";
  return status;
}

function isTerminal(status: string) {
  return ["done", "completed", "failed", "error", "cancelled"].includes(status);
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : value;
}

function formatCost(micros: number) {
  if (!Number.isFinite(micros) || micros <= 0) return "$0.00";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: micros < 10_000 ? 6 : 2,
    maximumFractionDigits: micros < 10_000 ? 6 : 2,
  }).format(micros / 1_000_000);
}

function contentText(content: unknown) {
  if (typeof content === "string") return content;
  try {
    return JSON.stringify(content);
  } catch {
    return String(content);
  }
}
