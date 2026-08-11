import { useCallback, useEffect, useRef, useState } from "react";
import {
  BoltrigApiError,
  type AnswerQuestionResponse,
  type HitlPolicyResponse,
  type HITLRequest,
  type RespondResult,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { routeHash } from "../routes";
import { Topbar, Unavailable } from "./Shell";

const POLL_MS = 15_000;
type InboxState = "loading" | "ready" | "denied" | "unavailable";

export function InboxQueue() {
  const [items, setItems] = useState<HITLRequest[]>([]);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState("");
  const [inboxState, setInboxState] = useState<InboxState>("loading");
  const [policy, setPolicy] = useState<HitlPolicyResponse["policy"] | null>(null);
  const inFlight = useRef(new Set<string>());
  const settled = useRef(new Set<string>());
  const loaded = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const result = await client.hitl();
      setItems(result.requests.filter((item) => !settled.current.has(item.id)));
      setLoadError("");
      loaded.current = true;
      setInboxState("ready");
    } catch (reason) {
      if (reason instanceof BoltrigApiError && [401, 403].includes(reason.status)) {
        loaded.current = false;
        setItems([]);
        setLoadError("");
        setInboxState("denied");
      } else if (loaded.current) {
        setLoadError("Inbox could not be refreshed. Showing the last pending requests.");
      } else {
        setLoadError("");
        setInboxState("unavailable");
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
    void Promise.resolve()
      .then(() => client.hitlPolicy())
      .then((result) => setPolicy(result.policy))
      .catch(() => setPolicy(null));
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function submit(item: HITLRequest, decision: string, notes = "") {
    if (inFlight.current.has(item.id)) return;
    inFlight.current.add(item.id);
    setBusy((current) => new Set(current).add(item.id));
    setErrors((current) => ({ ...current, [item.id]: "" }));
    try {
      const result = item.type === "question"
        ? await client.answerQuestion(item.id, decision)
        : await client.respondHitl(item.id, decision, notes);
      if (wasAnswered(result)) {
        settled.current.add(item.id);
        setItems((current) => current.filter((candidate) => candidate.id !== item.id));
      } else {
        setErrors((current) => ({
          ...current,
          [item.id]: result.reason ?? `Response was not accepted (${result.status}).`,
        }));
      }
    } catch {
      setErrors((current) => ({
        ...current,
        [item.id]: "The response could not be sent. It is safe to retry.",
      }));
    } finally {
      inFlight.current.delete(item.id);
      setBusy((current) => {
        const next = new Set(current);
        next.delete(item.id);
        return next;
      });
    }
  }

  return (
    <div className="page">
      <Topbar title="Inbox" status={inboxState === "loading" ? "Loading…" : inboxState === "ready" ? (items.length ? `${items.length} need you` : "Clear") : inboxState === "denied" ? "Restricted" : "Unavailable"} />
      <div className="page-content narrow">
        <div className="page-intro">
          <div>
            <h2>Human decisions</h2>
            <p>Approvals, owner questions, clarifications and escalations from governed runs.</p>
          </div>
          <button className="secondary-button" onClick={() => void refresh()}>Refresh</button>
        </div>
        {loadError && <p className="notice" role="alert">{loadError}</p>}
        {inboxState === "loading" && <Unavailable title="Loading Inbox">Checking for pending human decisions.</Unavailable>}
        {inboxState === "denied" && <Unavailable title="Inbox access denied">Your current role cannot view these human decisions.</Unavailable>}
        {inboxState === "unavailable" && <Unavailable title="Inbox unavailable">Pending decisions could not be reached. No response was sent.</Unavailable>}
        {inboxState === "ready" && items.length === 0 ? (
          <Unavailable title="Nothing waiting">New requests are checked automatically.</Unavailable>
        ) : inboxState === "ready" && items.map((item) => (
          <HitlCard
            item={item}
            busy={busy.has(item.id)}
            error={errors[item.id] ?? ""}
            onSubmit={(decision, notes) => submit(item, decision, notes)}
            key={item.id}
          />
        ))}
        {policy && <HitlPolicyEvidence policy={policy} />}
      </div>
    </div>
  );
}

function HitlPolicyEvidence({
  policy,
}: {
  policy: HitlPolicyResponse["policy"];
}) {
  return (
    <section className="settings-card">
      <p className="eyebrow">Process-start evidence</p>
      <h2>Approval policy</h2>
      <p>
        {policy.blocking_verbs.length} explicitly blocking{" "}
        {policy.blocking_verbs.length === 1 ? "verb" : "verbs"} · timeout{" "}
        {policy.approval_timeout_seconds === null
          ? "not configured"
          : `${policy.approval_timeout_seconds} seconds`}
      </p>
      {policy.blocking_verbs.length > 0 && (
        <p className="muted small">{policy.blocking_verbs.join(", ")}</p>
      )}
      <Unavailable title="Escalation routing is inactive">
        Primary channel, notification routes and escalation chain are stored
        policy only; no serving consumer currently sends or escalates approvals
        through them. Policy changes apply after process restart.
      </Unavailable>
    </section>
  );
}

function HitlCard({
  item,
  busy,
  error,
  onSubmit,
}: {
  item: HITLRequest;
  busy: boolean;
  error: string;
  onSubmit(decision: string, notes?: string): Promise<void>;
}) {
  return (
    <article className="approval-item hitl-card">
      <div className="hitl-heading">
        <div>
          <p className="eyebrow">{item.type} · {item.urgency ?? "normal"}</p>
          <h2>{item.question}</h2>
        </div>
        <span className="row-meta">{item.status ?? "pending"}</span>
      </div>
      <RequestReferences item={item} />
      {item.verb && <p><span className="eyebrow">Action</span><code>{item.verb}</code></p>}
      <LiteralBlock label="Inputs" value={item.inputs} />
      <LiteralBlock label="Context" value={item.context} />
      {item.type === "question" ? (
        <QuestionResponse item={item} busy={busy} onSubmit={onSubmit} />
      ) : (
        <DecisionResponse item={item} busy={busy} onSubmit={onSubmit} />
      )}
      {error && <p className="notice" role="alert">{error}</p>}
    </article>
  );
}

function RequestReferences({ item }: { item: HITLRequest }) {
  return (
    <dl className="hitl-references">
      {item.run_id && (
        <div>
          <dt>Run</dt>
          <dd><a href={routeHash("runs", item.run_id)}>{item.run_id}</a></dd>
        </div>
      )}
      {item.work_item_id && <div><dt>Work item</dt><dd>{item.work_item_id}</dd></div>}
      {item.requested_by && <div><dt>Requested by</dt><dd>{item.requested_by}</dd></div>}
      {item.requested_on_behalf_of && (
        <div><dt>On behalf of</dt><dd>{item.requested_on_behalf_of}</dd></div>
      )}
    </dl>
  );
}

function QuestionResponse({
  item,
  busy,
  onSubmit,
}: {
  item: HITLRequest;
  busy: boolean;
  onSubmit(answer: string): Promise<void>;
}) {
  const [answer, setAnswer] = useState("");
  const options = item.options?.filter(Boolean) ?? [];
  return (
    <div className="hitl-response">
      {options.length > 0 && (
        <div className="button-row hitl-options">
          {options.map((option) => (
            <button
              className="secondary-button"
              disabled={busy}
              key={option}
              onClick={() => void onSubmit(option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
      <label>
        <span className="eyebrow">{item.secure ? "Secure answer" : "Your answer"}</span>
        {item.secure ? (
          <input
            className="field-control"
            aria-label="Secure answer"
            type="password"
            autoComplete="off"
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
          />
        ) : (
          <textarea
            className="field-control"
            aria-label="Question answer"
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
          />
        )}
      </label>
      {item.secure && (
        <p className="muted small">
          The server seals this value and never echoes it.
          {item.secure_purpose ? ` It is used only for ${item.secure_purpose}.` : ""}
        </p>
      )}
      <button
        className="primary-button"
        disabled={busy || (item.secure ? !answer : !answer.trim())}
        onClick={() => void onSubmit(item.secure ? answer : answer.trim())}
      >
        {busy ? "Sending…" : "Send answer"}
      </button>
    </div>
  );
}

function DecisionResponse({
  item,
  busy,
  onSubmit,
}: {
  item: HITLRequest;
  busy: boolean;
  onSubmit(decision: string, notes?: string): Promise<void>;
}) {
  const [notes, setNotes] = useState("");
  const [decision, setDecision] = useState("");
  const [armed, setArmed] = useState("");
  const provided = item.options?.filter(Boolean) ?? [];
  const choices = provided.length > 0
    ? provided
    : (item.type === "approval" ? ["deny", "approve"] : []);

  function choose(value: string) {
    if (item.type === "approval" && armed !== value) {
      setArmed(value);
      return;
    }
    void onSubmit(value, notes.trim());
  }

  return (
    <div className="hitl-response">
      {choices.length > 0 ? (
        <div className="button-row hitl-options">
          {choices.map((choice) => (
            <button
              className={armed === choice ? "primary-button" : "secondary-button"}
              disabled={busy}
              key={choice}
              onClick={() => choose(choice)}
            >
              {armed === choice ? `Confirm ${choice}` : choice}
            </button>
          ))}
        </div>
      ) : (
        <input
          className="field-control"
          aria-label={`${item.type} response`}
          value={decision}
          onChange={(event) => setDecision(event.target.value)}
        />
      )}
      <textarea
        className="field-control"
        aria-label="Response notes"
        placeholder="Optional notes"
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
      />
      {choices.length === 0 && (
        <button
          className="primary-button"
          disabled={busy || !decision.trim()}
          onClick={() => void onSubmit(decision.trim(), notes.trim())}
        >
          {busy ? "Sending…" : "Send response"}
        </button>
      )}
    </div>
  );
}

function LiteralBlock({ label, value }: { label: string; value: unknown }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <details className="hitl-literal">
      <summary>{label}</summary>
      <pre>{literal(value)}</pre>
    </details>
  );
}

function literal(value: unknown): string {
  const rendered = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (rendered || String(value)).slice(0, 8_000);
}

function wasAnswered(result: RespondResult | AnswerQuestionResponse): boolean {
  return result.status === "answered" || result.status === "ok";
}
