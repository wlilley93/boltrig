// US-HIL-05: the canonical record of pending, caller-visible human-in-the-loop
// requests. Approval, clarification and escalation responses use the generic
// endpoint; owner-scoped questions use their dedicated wrapped answer route.
//
// HitlCard is a thin orchestrator: its state + submit live in useHitlCard and
// the three respond branches (confirm, fixed options, free-text answer) each
// render through their own sub-component in approvalsPanel/.

import { useMemo, useState } from "react";

import { api } from "../api/client";
import type { HITLRequest } from "../api/types";
import { useSlideActive } from "../deck/context";
import { useFetch } from "../useFetch";
import { RunLink } from "./shared";
import {
  CONSEQUENCE,
  EmptyState,
  HITL_TYPE,
  HITL_URGENCY,
  PageIntro,
  Select,
  StatusBadge,
} from "./ux";
import { HitlRespond } from "./approvalsPanel/HitlRespond";
import { useHitlCard } from "./approvalsPanel/useHitlCard";
import {
  ALL_HITL_TYPES,
  ALL_HITL_URGENCIES,
  decisionOptions,
  filterAndSortHitl,
  renderContext,
  runFromContext,
} from "./approvalsPanel/hitlUtils";

function HitlCard({ req, onAnswered }: { req: HITLRequest; onAnswered: () => void }) {
  const h = useHitlCard(req, onAnswered);
  const ctx = renderContext(req.context);
  const runId = req.run_id ?? runFromContext(req.context);
  const options = decisionOptions(req.type, req.options);
  const isApproval = req.type === "approval";

  return (
    <article className="hitl-card">
      <div className="hitl-card__head">
        <StatusBadge value={req.type} glossary={HITL_TYPE} />
        {isApproval && <StatusBadge value="high" glossary={CONSEQUENCE} />}
        {req.urgency ? <StatusBadge value={req.urgency} glossary={HITL_URGENCY} /> : null}
        <code className="hitl-card__id">{req.id}</code>
      </div>

      <p className="hitl-card__question">
        {req.question || "A pending human request needs your response."}
      </p>

      {(req.requested_by || req.verb) && (
        <dl className="hitl-card__action">
          {req.requested_by && (
            <div>
              <dt>Requested by</dt>
              <dd><code>{req.requested_by}</code></dd>
            </div>
          )}
          {req.requested_on_behalf_of && (
            <div>
              <dt>On behalf of</dt>
              <dd><code>{req.requested_on_behalf_of}</code></dd>
            </div>
          )}
          {req.verb && (
            <div>
              <dt>Exact verb</dt>
              <dd><code>{req.verb}</code></dd>
            </div>
          )}
        </dl>
      )}

      {isApproval && req.inputs !== undefined && req.inputs !== null ? (
        <div className="hitl-card__inputs">
          <p>Literal inputs</p>
          <pre>{renderContext(req.inputs)}</pre>
        </div>
      ) : null}

      {req.work_item_id ? (
        <p className="ux-hint">
          Work item: <code className="mono">{req.work_item_id}</code>
        </p>
      ) : null}

      {runId ? (
        <p className="ux-hint">
          Traces to run: <RunLink runId={runId} />
        </p>
      ) : null}

      {ctx ? (
        <details className="hitl-card__context">
          <summary className="ux-hint">
            Full details
          </summary>
          <pre>{ctx}</pre>
        </details>
      ) : null}

      <HitlRespond options={options} h={h} showNotes={req.type !== "question"} />
    </article>
  );
}

export function ApprovalsPanel() {
  // Quiesce the 8s poll while this slide is not the active deck cell; the
  // paused->active edge triggers one immediate refresh (useFetch opts).
  const active = useSlideActive();
  const hitl = useFetch(() => api.hitl(), [], 8000, { paused: !active });
  const requests = hitl.data?.requests ?? [];
  const [typeFilter, setTypeFilter] = useState(ALL_HITL_TYPES);
  const [urgencyFilter, setUrgencyFilter] = useState(ALL_HITL_URGENCIES);
  const visibleRequests = useMemo(
    () => filterAndSortHitl(requests, { type: typeFilter, urgency: urgencyFilter }),
    [requests, typeFilter, urgencyFilter],
  );
  const filtersActive =
    typeFilter !== ALL_HITL_TYPES || urgencyFilter !== ALL_HITL_URGENCIES;

  return (
    <section className="panel">
      <PageIntro
        title="Approvals & requests"
        lead="Review the pending human decisions the server has scoped to you."
        how="Approvals, clarifications, escalations and owner-only questions use their matching governed response path. Every accepted response is recorded; the runtime decides what resumes next."
        actions={
          <>
            <span className="muted">
              {visibleRequests.length} of {requests.length} waiting
            </span>
            <button className="btn" onClick={() => hitl.reload()}>
              Refresh
            </button>
          </>
        }
      />

      {hitl.loading && !hitl.data && <p className="muted">Loading...</p>}
      {hitl.error && <p className="error">Could not load approvals: {hitl.error}</p>}

      {requests.length > 0 && (
        <div className="kv" role="group" aria-label="Request filters">
          <span className="muted">Filter</span>
          <Select
            ariaLabel="Request type filter"
            value={typeFilter}
            onChange={setTypeFilter}
            options={[
              { value: ALL_HITL_TYPES, label: "All types" },
              { value: "approval", label: "Approvals" },
              { value: "escalation", label: "Escalations" },
              { value: "clarification", label: "Clarifications" },
              { value: "question", label: "Questions" },
            ]}
          />
          <Select
            ariaLabel="Request urgency filter"
            value={urgencyFilter}
            onChange={setUrgencyFilter}
            options={[
              { value: ALL_HITL_URGENCIES, label: "All urgency" },
              { value: "blocking", label: "Blocking" },
              { value: "async", label: "Async" },
            ]}
          />
          {filtersActive && (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => {
                setTypeFilter(ALL_HITL_TYPES);
                setUrgencyFilter(ALL_HITL_URGENCIES);
              }}
            >
              Clear filters
            </button>
          )}
        </div>
      )}

      {requests.length === 0 && !hitl.loading && !hitl.error && (
        <EmptyState
          title="No requests waiting - you're all caught up"
          body="When a scoped run needs your approval or answer, it appears here."
        />
      )}

      {requests.length > 0 && visibleRequests.length === 0 && (
        <EmptyState
          title="No requests match these filters"
          body="Clear a filter to return to the full pending queue."
          action={(
            <button
              type="button"
              className="btn"
              onClick={() => {
                setTypeFilter(ALL_HITL_TYPES);
                setUrgencyFilter(ALL_HITL_URGENCIES);
              }}
            >
              Clear filters
            </button>
          )}
        />
      )}

      <div className="hitl-list">
        {visibleRequests.map((req) => (
          <HitlCard key={req.id} req={req} onAnswered={() => hitl.reload()} />
        ))}
      </div>
    </section>
  );
}
