// US-HIL-05: the canonical record of pending human-in-the-loop requests
// (approval / clarification / escalation). This is the safety surface: a
// high-consequence action has paused and will not run until a person here
// decides. Each request shows its stakes, and is answered inline via
// POST /v1/hitl/{id}/respond.

import { useState } from "react";

import { api } from "../api/client";
import type { HITLRequest } from "../api/types";
import { useSlideActive } from "../deck/context";
import { useFetch } from "../useFetch";
import { RunLink } from "./shared";
import {
  CONSEQUENCE,
  EmptyState,
  Field,
  Hint,
  InfoCallout,
  PageIntro,
  StatusBadge,
  HITL_TYPE,
  HITL_URGENCY,
} from "./ux";

function renderContext(context: unknown): string | null {
  if (context === null || context === undefined) return null;
  if (typeof context === "string") return context;
  try {
    return JSON.stringify(context, null, 2);
  } catch {
    return String(context);
  }
}

function runFromContext(context: unknown): string | null {
  if (!context || typeof context !== "object") return null;
  const obj = context as Record<string, unknown>;
  const candidate = obj.run_id ?? obj.run;
  return typeof candidate === "string" && candidate ? candidate : null;
}

// Pull the faithful server reason out of a thrown ApiError (its body carries a
// reason on a 403/409) rather than leaking "POST ... -> 403".
function reasonOf(err: unknown): string {
  if (err && typeof err === "object") {
    const body = (err as { body?: unknown }).body;
    if (body && typeof body === "object") {
      const r = (body as { reason?: unknown }).reason;
      if (typeof r === "string" && r) return r;
    }
  }
  return err instanceof Error ? err.message : String(err);
}

// "approve"-like options read as the primary, weighted action; "reject"-like as
// a neutral decline. Everything else is a neutral button.
function optionClass(opt: string): string {
  const o = opt.toLowerCase();
  if (o === "approve" || o === "yes" || o === "allow") return "btn btn--primary";
  if (o === "reject" || o === "no" || o === "deny") return "btn btn--danger";
  return "btn";
}

function HitlCard({ req, onAnswered }: { req: HITLRequest; onAnswered: () => void }) {
  const [decision, setDecision] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [arming, setArming] = useState<string | null>(null); // the option awaiting confirm

  const ctx = renderContext(req.context);
  const runId = runFromContext(req.context);
  const options = req.options ?? [];
  const isApproval = req.type === "approval";

  async function submit(value: string) {
    if (!value) {
      setError("Type your answer first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.respondHitl(req.id, { decision: value, notes });
      const approved = ["approve", "yes", "allow"].includes(value.toLowerCase());
      setDone(
        res.status
          ? approved
            ? "Recorded - this action is now approved and will continue."
            : "Recorded - this action was declined and will not run."
          : "Recorded.",
      );
      onAnswered();
    } catch (err) {
      setError(reasonOf(err));
    } finally {
      setBusy(false);
    }
  }

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

      {done ? (
        <p className="ok">{done}</p>
      ) : (
        <div className="hitl-card__respond">
          {options.length > 0 ? (
            arming ? (
              // deliberate second step: restate the choice, require a confirm
              <InfoCallout tone={arming.toLowerCase() === "reject" ? "warn" : "consequence"}>
                <div className="kv">
                  <span>
                    Confirm: <strong>{arming}</strong> this action? It runs as soon
                    as you confirm.
                  </span>
                </div>
                <div className="kv" style={{ marginTop: 6 }}>
                  <button
                    className={optionClass(arming)}
                    disabled={busy}
                    onClick={() => submit(arming)}
                  >
                    {busy ? "Recording..." : `Confirm ${arming}`}
                  </button>
                  <button className="btn btn--ghost" disabled={busy} onClick={() => setArming(null)}>
                    Cancel
                  </button>
                </div>
              </InfoCallout>
            ) : (
              <>
                <Hint>
                  This decision is deliberate - you will be asked to confirm.
                </Hint>
                <div className="hitl-card__options">
                  {options.map((opt) => (
                    <button
                      key={opt}
                      className={optionClass(opt)}
                      disabled={busy}
                      onClick={() => setArming(opt)}
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              </>
            )
          ) : (
            // no fixed options (a clarification / escalation): a real answer field
            <Field
              label="Your answer"
              hint="This text is sent back to the agent that asked."
              example="Use the staging account, not production"
            >
              <div className="hitl-card__custom">
                <input
                  className="hitl-card__decision"
                  value={decision}
                  disabled={busy}
                  onChange={(e) => setDecision(e.target.value)}
                />
                <button
                  className="btn btn--primary"
                  disabled={busy}
                  onClick={() => submit(decision)}
                >
                  {busy ? "Sending..." : "Send answer"}
                </button>
              </div>
            </Field>
          )}

          <Field
            label="Notes (optional)"
            hint="Your reasoning is recorded in the audit trail."
          >
            <textarea
              className="hitl-card__notes"
              value={notes}
              disabled={busy}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
            />
          </Field>

          {error && <p className="error">{error}</p>}
        </div>
      )}
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
