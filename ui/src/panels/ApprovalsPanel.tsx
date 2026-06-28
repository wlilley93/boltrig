// US-HIL-05: the canonical record of pending human-in-the-loop requests
// (approval / clarification / escalation). Each shows its context, question and
// options, and is answered inline via POST /v1/hitl/{id}/respond.

import { useState } from "react";

import { api } from "../api/client";
import type { HITLRequest } from "../api/types";
import { useFetch } from "../useFetch";

function renderContext(context: unknown): string | null {
  if (context === null || context === undefined) return null;
  if (typeof context === "string") return context;
  try {
    return JSON.stringify(context, null, 2);
  } catch {
    return String(context);
  }
}

function HitlCard({ req, onAnswered }: { req: HITLRequest; onAnswered: () => void }) {
  const [decision, setDecision] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const ctx = renderContext(req.context);
  const options = req.options ?? [];

  async function submit(value: string) {
    if (!value) {
      setError("Provide a decision.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.respondHitl(req.id, { decision: value, notes });
      setDone(`recorded (${res.status})`);
      onAnswered();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="hitl-card">
      <div className="hitl-card__head">
        <span className={`badge badge--type badge--type-${req.type}`}>{req.type}</span>
        {req.urgency ? <span className="badge">{req.urgency}</span> : null}
        {req.status ? <span className="muted">status: {req.status}</span> : null}
        <code className="hitl-card__id">{req.id}</code>
      </div>

      <p className="hitl-card__question">{req.question || "(no question)"}</p>

      {req.work_item_id ? (
        <p className="muted">
          work item: <code>{req.work_item_id}</code>
        </p>
      ) : null}

      {ctx ? (
        <details className="hitl-card__context">
          <summary>context</summary>
          <pre>{ctx}</pre>
        </details>
      ) : null}

      {done ? (
        <p className="ok">Answered: {done}</p>
      ) : (
        <div className="hitl-card__respond">
          {options.length > 0 && (
            <div className="hitl-card__options">
              {options.map((opt) => (
                <button
                  key={opt}
                  className="btn"
                  disabled={busy}
                  onClick={() => submit(opt)}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}

          <div className="hitl-card__custom">
            <input
              className="hitl-card__decision"
              placeholder="decision"
              value={decision}
              disabled={busy}
              onChange={(e) => setDecision(e.target.value)}
            />
            <button className="btn btn--primary" disabled={busy} onClick={() => submit(decision)}>
              {busy ? "..." : "Respond"}
            </button>
          </div>

          <textarea
            className="hitl-card__notes"
            placeholder="notes (optional)"
            value={notes}
            disabled={busy}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
          />

          {error && <p className="error">{error}</p>}
        </div>
      )}
    </article>
  );
}

export function ApprovalsPanel() {
  const hitl = useFetch(() => api.hitl(), [], 8000);
  const requests = hitl.data?.requests ?? [];

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Approvals</h2>
        <div className="panel__actions">
          <span className="muted">{requests.length} pending</span>
          <button className="btn" onClick={() => hitl.reload()}>
            Refresh
          </button>
        </div>
      </div>

      {hitl.loading && !hitl.data && <p className="muted">Loading requests...</p>}
      {hitl.error && <p className="error">Failed to load HITL: {hitl.error}</p>}

      {requests.length === 0 && !hitl.loading && !hitl.error && (
        <p className="muted">No pending human-in-the-loop requests.</p>
      )}

      <div className="hitl-list">
        {requests.map((req) => (
          <HitlCard key={req.id} req={req} onAnswered={() => hitl.reload()} />
        ))}
      </div>
    </section>
  );
}
