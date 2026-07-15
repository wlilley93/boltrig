import type { ReactNode } from "react";

import { api } from "@/api/client";
import type { WorkItem } from "@/api/types";
import { navigate } from "@/router";
import { RunLink } from "@/panels/shared";
import { AUDIT_STATUS, FetchError, PageIntro, StatusBadge, WORK_STATUS } from "@/panels/ux";
import { useFetch } from "@/useFetch";

function DetailField({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt>{label}</dt><dd>{children}</dd></div>;
}

function ChildRow({ item }: { item: WorkItem }) {
  return (
    <button className="work-detail__child" onClick={() => navigate(`/kanban/${item.id}`)}>
      <span>{item.intent || "(no description)"}</span>
      <code>{item.id}</code>
      <StatusBadge value={item.status} glossary={WORK_STATUS} />
    </button>
  );
}

export function WorkDetail({ itemId }: { itemId: string }) {
  const detail = useFetch(() => api.workDetail(itemId), [itemId]);
  const data = detail.data;
  return (
    <section className="panel work-detail">
      <PageIntro
        title={data?.item.intent || "Work item"}
        lead="Server-owned context, child work, and the scoped audit trail for one item."
        actions={<button className="btn" onClick={() => navigate("/kanban")}>Back to work queue</button>}
      />
      {detail.loading && !data && <p className="muted">Loading work item...</p>}
      {detail.errorStatus === 404 ? (
        <div className="notice notice--warn">Work item not found or not in your visibility scope.</div>
      ) : (
        <FetchError error={detail.error} status={detail.errorStatus} onRetry={detail.reload} />
      )}
      {data && (
        <>
          <section className="work-detail__summary" aria-labelledby="work-detail-summary">
            <div className="list-card__head">
              <h3 id="work-detail-summary">Context</h3>
              <StatusBadge value={data.item.status} glossary={WORK_STATUS} />
            </div>
            <dl className="work-detail__fields">
              <DetailField label="ID"><code>{data.item.id}</code></DetailField>
              <DetailField label="Owner">{data.item.owner_member || "Unassigned"}</DetailField>
              <DetailField label="Source">{data.item.source || "Unknown"}</DetailField>
              <DetailField label="Confidence">{data.item.confidence == null ? "Unknown" : `${Math.round(data.item.confidence * 100)}%`}</DetailField>
              <DetailField label="Convergent">{data.item.convergent ? "Yes — settles on one answer" : "No — open-ended"}</DetailField>
              <DetailField label="Parent">{data.item.parent_id ? <button className="entity-link" onClick={() => navigate(`/kanban/${data.item.parent_id}`)}>{data.item.parent_id}</button> : "Root item"}</DetailField>
              <DetailField label="On behalf of">{data.item.on_behalf_of || "Not delegated"}</DetailField>
              <DetailField label="Run">{data.item.hatchet_run_id ? <RunLink runId={data.item.hatchet_run_id} /> : "Not started"}</DetailField>
            </dl>
          </section>

          <section className="list-card" aria-labelledby="work-detail-children">
            <div className="list-card__head"><h3 id="work-detail-children">Children</h3><span className="muted">{data.children.length}</span></div>
            <div className="list-card__body work-detail__children">
              {data.children.length ? data.children.map((item) => <ChildRow key={item.id} item={item} />) : <p className="muted">No child work items.</p>}
            </div>
          </section>

          <section className="list-card" aria-labelledby="work-detail-audit">
            <div className="list-card__head"><h3 id="work-detail-audit">Audit trail</h3><span className="muted">Newest last · capped at 200 events</span></div>
            <div className="list-card__body work-audit">
              {data.audit.length ? data.audit.map((event, index) => (
                <article className="work-audit__row" key={`${event.ts}:${index}`}>
                  <time dateTime={event.ts}>{new Date(event.ts).toLocaleString()}</time>
                  <span>{event.actor} <span className="muted">({event.actor_tier})</span></span>
                  <code>{event.noun}.{event.verb}</code>
                  <StatusBadge value={event.status} glossary={AUDIT_STATUS} />
                  {event.detail != null && <details><summary>Details</summary><pre>{JSON.stringify(event.detail, null, 2)}</pre></details>}
                </article>
              )) : <p className="muted">No audit events are visible for this item.</p>}
            </div>
          </section>
        </>
      )}
    </section>
  );
}
