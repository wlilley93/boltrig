// US-HIL-05: the canonical record of pending human-in-the-loop requests
// (approval / clarification / escalation). This is the safety surface: a
// high-consequence action has paused and will not run until a person here
// decides. Each request shows its stakes, and is answered inline via
// POST /v1/hitl/{id}/respond.
//
// HitlCard is a thin orchestrator: its state + submit live in useHitlCard and
// the three respond branches (confirm, fixed options, free-text answer) each
// render through their own sub-component in approvalsPanel/.

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
  StatusBadge,
} from "./ux";
import { HitlRespond } from "./approvalsPanel/HitlRespond";
import { useHitlCard } from "./approvalsPanel/useHitlCard";
import { renderContext, runFromContext } from "./approvalsPanel/hitlUtils";

function HitlCard({ req, onAnswered }: { req: HITLRequest; onAnswered: () => void }) {
  const h = useHitlCard(req, onAnswered);
  const ctx = renderContext(req.context);
  const runId = runFromContext(req.context);
  const options = req.options ?? [];
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
        {req.question || "A high-consequence action needs your decision."}
      </p>

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
          <summary className="ux-hint" style={{ cursor: "pointer" }}>
            Full details
          </summary>
          <pre>{ctx}</pre>
        </details>
      ) : null}

      <HitlRespond options={options} h={h} />
    </article>
  );
}

export function ApprovalsPanel() {
  // Quiesce the 8s poll while this slide is not the active deck cell; the
  // paused->active edge triggers one immediate refresh (useFetch opts).
  const active = useSlideActive();
  const hitl = useFetch(() => api.hitl(), [], 8000, { paused: !active });
  const requests = hitl.data?.requests ?? [];

  return (
    <section className="panel">
      <PageIntro
        title="Approvals"
        lead="The one place you review and sign off on high-consequence actions the system has paused."
        how="Nothing high-impact runs until a person here says yes. Each decision is deliberate and recorded. Take your time."
        actions={
          <>
            <span className="muted">{requests.length} waiting</span>
            <button className="btn" onClick={() => hitl.reload()}>
              Refresh
            </button>
          </>
        }
      />

      {hitl.loading && !hitl.data && <p className="muted">Loading...</p>}
      {hitl.error && <p className="error">Could not load approvals: {hitl.error}</p>}

      {requests.length === 0 && !hitl.loading && !hitl.error && (
        <EmptyState
          title="No approvals waiting - you're all caught up"
          body="When the system pauses a high-consequence action, it appears here for your sign-off."
        />
      )}

      <div className="hitl-list">
        {requests.map((req) => (
          <HitlCard key={req.id} req={req} onAnswered={() => hitl.reload()} />
        ))}
      </div>
    </section>
  );
}
