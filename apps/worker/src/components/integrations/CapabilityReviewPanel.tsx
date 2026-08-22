import { useState } from "react";
import type {
  CapabilityBindingStatus,
  CapabilityBindingView,
} from "@wlilley93/boltrig-web-sdk";

import { ExactApprovalFinalizer } from "../ExactApprovalFinalizer";
import {
  useCapabilityReviewQueue,
  type Decision,
  type QueueFilter,
} from "./useCapabilityReviewQueue";

/**
 * The drain for the review queue.
 *
 * A mapping pack proposes a binding and nothing publishes it: a binding is
 * ineligible for any route until a human approves, because "a declaration is
 * evidence, never the authority to publish itself". Until this panel existed
 * the queue could only be drained by someone who already knew a binding id.
 *
 * Approve and reject are HIGH-consequence governed verbs, so both land in the
 * same approval lane every other governed edit here uses, and the panel never
 * reports a change it did not see land.
 */

const FILTERS: readonly { id: QueueFilter; label: string }[] = [
  { id: "proposed", label: "Needs review" },
  { id: "approved", label: "Approved" },
  { id: "disabled", label: "Refused" },
  { id: "all", label: "All" },
];

/** The page's existing tone vocabulary; no new colour rung is invented here. */
function statusTone(status: CapabilityBindingStatus): string {
  return status === "approved" ? "green" : status === "proposed" ? "amber" : "method";
}

function ReviewFilters({
  active,
  onSelect,
}: {
  active: QueueFilter;
  onSelect(next: QueueFilter): void;
}) {
  return (
    <div aria-label="Review filter" className="plugins-toolbar" role="tablist">
      {FILTERS.map((option) => (
        <button
          aria-selected={active === option.id}
          className={`capability-filter ${active === option.id ? "active" : ""}`}
          key={option.id}
          onClick={() => onSelect(option.id)}
          role="tab"
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function ReviewRow({
  busy,
  onDecide,
  row,
}: {
  busy: boolean;
  onDecide(row: CapabilityBindingView, decision: Decision): void;
  row: CapabilityBindingView;
}) {
  return (
    <li className="capability-row">
      <div className="capability-row-copy">
        <span className="capability-row-name">
          <strong>{row.capability}</strong>
          <span className={`plugins-health ${statusTone(row.status)}`}>{row.status}</span>
          {row.schema_pinned && !row.schema_current && (
            <span className="plugins-health amber">schema drifted</span>
          )}
        </span>
        <span className="capability-row-sub">
          {row.connection?.label ?? "connection unavailable"} · {row.source_operation_id}
        </span>
        {row.source_operation?.description && (
          <span className="capability-row-evidence">{row.source_operation.description}</span>
        )}
        <span className="capability-row-sub muted">
          claimed by {row.created_from}
          {row.reviewed_by ? ` · reviewed by ${row.reviewed_by}` : ""}
        </span>
      </div>
      {row.status === "proposed" && (
        <div className="capability-row-actions">
          <button
            className="primary-button"
            disabled={busy}
            onClick={() => onDecide(row, "approve")}
            type="button"
          >
            Approve
          </button>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => onDecide(row, "reject")}
            type="button"
          >
            Refuse
          </button>
        </div>
      )}
    </li>
  );
}

export function CapabilityReviewPanel() {
  const [filter, setFilter] = useState<QueueFilter>("proposed");
  const queue = useCapabilityReviewQueue(filter);

  return (
    <section aria-labelledby="capability-review-heading" className="plugins-inventory">
      <div className="plugins-inventory-heading">
        <h2 id="capability-review-heading">Review</h2>
        <span>
          {queue.needsReview === 0 ? "Nothing waiting" : `${queue.needsReview} waiting`}
        </span>
      </div>

      <ReviewFilters active={filter} onSelect={setFilter} />
      {queue.message && <p className="plugins-notice" role="status">{queue.message}</p>}
      <ExactApprovalFinalizer controller={queue.finalizer} />

      {queue.state === "loading" && <p className="plugins-empty">Loading the queue…</p>}
      {queue.state === "unavailable" && (
        <p className="plugins-empty">
          The review queue is unavailable. Nothing is assumed about what is approved.
        </p>
      )}
      {queue.state === "ready" && queue.bindings.length === 0 && (
        <p className="plugins-empty">
          No bindings here. A mapping pack proposes one when a provider connection
          for it exists.
        </p>
      )}

      <ul className="capability-list">
        {queue.bindings.map((row) => (
          <ReviewRow
            busy={queue.busyId === row.binding_id || queue.finalizer.busy}
            key={row.binding_id}
            onDecide={queue.decide}
            row={row}
          />
        ))}
      </ul>
    </section>
  );
}
