import { useMemo, useState } from "react";

import { api } from "@/api/client";
import type { RunRow } from "@/api/types";
import { RunLink } from "@/panels/shared";
import {
  EmptyState,
  FetchError,
  Field,
  PageIntro,
  Select,
  StatusBadge,
  WORK_STATUS,
} from "@/panels/ux";
import { useFetch } from "@/useFetch";
import {
  ALL_CHANNEL_FILTER,
  ALL_OWNER_FILTER,
  ALL_STATUS_FILTER,
  channelFilterValue,
  filterRunRows,
  ownerFilterValue,
  runChannels,
  runOwners,
  runStatusCounts,
  statusFilterValue,
} from "./runsPanel/model";

function RunStatusSummary({ rows }: { rows: ReadonlyArray<RunRow> }) {
  const counts = runStatusCounts(rows);
  return (
    <section className="list-card runs-summary" aria-labelledby="runs-summary-title">
      <div className="list-card__head">
        <h3 id="runs-summary-title">Status summary</h3>
        <span className="muted">{rows.length} total</span>
      </div>
      <div className="list-card__body runs-summary__items">
        {counts.length === 0 ? (
          <span className="muted">No status data yet.</span>
        ) : (
          counts.map(({ status, count }) => (
            <span className="kv runs-summary__item" key={status}>
              <StatusBadge value={status} glossary={WORK_STATUS} />
              <strong aria-label={`${status}: ${count}`}>{count}</strong>
            </span>
          ))
        )}
      </div>
    </section>
  );
}

function RunsTable({ rows }: { rows: ReadonlyArray<RunRow> }) {
  return (
    <div className="table-scroll">
      <table className="data-table runs-table">
        <thead>
          <tr>
            <th>Run</th>
            <th>Intent</th>
            <th>Work item</th>
            <th>Status</th>
            <th>Owner</th>
            <th>Channel</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.run_id ?? "no-run"}:${row.work_item}:${index}`}>
              <td>
                {row.run_id ? (
                  <RunLink runId={row.run_id} />
                ) : (
                  <span className="muted">No run ID</span>
                )}
              </td>
              <td className="runs-table__intent">{row.intent}</td>
              <td><code>{row.work_item}</code></td>
              <td><StatusBadge value={row.status} glossary={WORK_STATUS} /></td>
              <td>
                {row.owner && row.owner.trim() ? (
                  row.owner
                ) : (
                  <span className="muted">No owner</span>
                )}
              </td>
              {/* Which SURFACE this turn arrived through, so one conversation can
                  span an Opbox spotlight and this UI and still say where each turn
                  came from. Absent is the ordinary case (typed into boltrig
                  itself), so it reads as a named value, not a missing one. */}
              <td>
                {row.external_ref && row.external_ref.trim() ? (
                  <code>{row.external_ref}</code>
                ) : (
                  <span className="muted">Direct</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RunsPanel() {
  const runs = useFetch(() => api.runs(), []);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState(ALL_STATUS_FILTER);
  const [owner, setOwner] = useState(ALL_OWNER_FILTER);
  const [channel, setChannel] = useState(ALL_CHANNEL_FILTER);
  const rows = runs.data?.runs ?? [];
  const statusCounts = useMemo(() => runStatusCounts(rows), [rows]);
  const owners = useMemo(() => runOwners(rows), [rows]);
  const channels = useMemo(() => runChannels(rows), [rows]);
  const statusOptions = [
    { value: ALL_STATUS_FILTER, label: "All statuses" },
    ...statusCounts.map(({ status: value }) => ({
      value: statusFilterValue(value),
      label: WORK_STATUS[value]?.label ?? value,
    })),
  ];
  const ownerOptions = [
    { value: ALL_OWNER_FILTER, label: "All owners" },
    ...owners.map((value) => ({
      value: ownerFilterValue(value),
      label: value ?? "No owner",
    })),
  ];
  const channelOptions = [
    { value: ALL_CHANNEL_FILTER, label: "All channels" },
    ...channels.map((value) => ({
      value: channelFilterValue(value),
      label: value ?? "Direct",
    })),
  ];
  const activeStatus = statusOptions.some((option) => option.value === status)
    ? status
    : ALL_STATUS_FILTER;
  const activeOwner = ownerOptions.some((option) => option.value === owner)
    ? owner
    : ALL_OWNER_FILTER;
  const activeChannel = channelOptions.some((option) => option.value === channel)
    ? channel
    : ALL_CHANNEL_FILTER;
  const visibleRows = useMemo(
    () =>
      filterRunRows(rows, {
        query,
        status: activeStatus,
        owner: activeOwner,
        channel: activeChannel,
      }),
    [rows, query, activeStatus, activeOwner, activeChannel],
  );

  return (
    <section className="panel runs-panel">
      <PageIntro
        title="Runs"
        lead="Find and inspect the work-backed runs currently visible in your scope."
        how="This view reports only the run, work item, intent, status, owner, and originating channel returned by the server. It does not yet claim to be a unified history of every runtime. Open a run to inspect its live details and audit context."
        howToggle
        actions={(
          <button className="btn" onClick={runs.reload} disabled={runs.loading && !runs.data}>
            Refresh
          </button>
        )}
      />

      <RunStatusSummary rows={rows} />

      <div className="form__grid runs-filters" aria-label="Run filters">
        <Field label="Search" htmlFor="runs-search" wide>
          <input
            id="runs-search"
            type="search"
            value={query}
            placeholder="Intent, run ID, or work item"
            onChange={(event) => setQuery(event.target.value)}
          />
        </Field>
        <Field label="Status" htmlFor="runs-status">
          <Select
            id="runs-status"
            value={activeStatus}
            options={statusOptions}
            onChange={setStatus}
          />
        </Field>
        <Field label="Owner" htmlFor="runs-owner">
          <Select
            id="runs-owner"
            value={activeOwner}
            options={ownerOptions}
            onChange={setOwner}
          />
        </Field>
        <Field label="Channel" htmlFor="runs-channel">
          <Select
            id="runs-channel"
            value={activeChannel}
            options={channelOptions}
            onChange={setChannel}
          />
        </Field>
      </div>

      <section className="list-card runs-results" aria-labelledby="runs-results-title">
        <div className="list-card__head">
          <h3 id="runs-results-title">Visible runs</h3>
          <span className="muted runs-results__count" aria-live="polite">
            {visibleRows.length} of {rows.length}
          </span>
        </div>
        <div className="list-card__body">
          {runs.loading && !runs.data && <p className="muted">Loading runs...</p>}
          <FetchError error={runs.error} status={runs.errorStatus} onRetry={runs.reload} />
          {!runs.loading && runs.data && rows.length === 0 && (
            <EmptyState
              title="No runs in your scope"
              body="The server did not return any runs for your current visibility scope."
            />
          )}
          {rows.length > 0 && visibleRows.length === 0 && (
            <EmptyState
              title="No runs match these filters"
              body="Change the search, status, or owner filter to widen the result set."
            />
          )}
          {visibleRows.length > 0 && <RunsTable rows={visibleRows} />}
        </div>
      </section>
    </section>
  );
}
