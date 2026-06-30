// Round Three personal surface (any authenticated user). Configure a personal
// agent, invoke it (delegated-only: it runs on-behalf-of you and is capped to
// your grants - the returned effective_grants show that cap, SEC-30), manage
// your own notification prefs, and query memory (scope-filtered: you only see
// your user scope, the org scope and your departments - SEC-31).

import { useState } from "react";

import { api } from "../api/client";
import type { MemoryItem, SpawnResult } from "../api/types";
import { navigate } from "../router";
import { useFetch } from "../useFetch";
import { CodeBlock, GrantList, apiReason, csvToList, errText } from "./shared";
import { Field, Hint, InfoCallout, PageIntro } from "./ux";

function PersonalAgent() {
  const skillsList = useFetch(() => api.skills(), []);
  const [runtime, setRuntime] = useState("pi-worker");
  const [skills, setSkills] = useState("");
  const [cfgBusy, setCfgBusy] = useState(false);
  const [cfgError, setCfgError] = useState<string | null>(null);
  const [cfgMsg, setCfgMsg] = useState<string | null>(null);

  const availableSkills = skillsList.data?.skills ?? [];
  function addSkill(id: string) {
    const have = csvToList(skills);
    if (!have.includes(id)) setSkills([...have, id].join(", "));
  }

  const [message, setMessage] = useState("");
  const [invBusy, setInvBusy] = useState(false);
  const [invError, setInvError] = useState<string | null>(null);
  const [invResult, setInvResult] = useState<SpawnResult | null>(null);

  async function configure() {
    setCfgBusy(true);
    setCfgError(null);
    setCfgMsg(null);
    try {
      const res = await api.configurePersonalAgent({
        runtime: runtime.trim() || "pi-worker",
        skills: csvToList(skills),
      });
      setCfgMsg(`Saved agent ${res.id} (owner ${res.owner}).`);
    } catch (err) {
      setCfgError(apiReason(err));
    } finally {
      setCfgBusy(false);
    }
  }

  async function invoke() {
    if (!message.trim()) {
      setInvError("A message is required.");
      return;
    }
    setInvBusy(true);
    setInvError(null);
    setInvResult(null);
    try {
      const res = await api.invokePersonalAgent({ message: message.trim() });
      setInvResult(res);
    } catch (err) {
      setInvError(errText(err));
    } finally {
      setInvBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="form">
        <div className="form__title">Your personal agent</div>
        <Hint>An assistant that runs as you, using only the skills you give it.</Hint>
        <div className="form__grid">
          <Field
            label="Runtime"
            hint="The worker that runs your agent. Leave as pi-worker unless told otherwise."
          >
            <input value={runtime} onChange={(e) => setRuntime(e.target.value)} />
          </Field>
          <Field
            label="Skills"
            hint="Which skills your agent may use (comma-separated)."
          >
            <input value={skills} onChange={(e) => setSkills(e.target.value)} />
          </Field>
        </div>
        {availableSkills.length > 0 && (
          <div className="kv">
            <span className="ux-hint">Add a skill:</span>
            {availableSkills.map((s) => (
              <button
                key={s.id}
                type="button"
                className="tag tag--accent"
                style={{ cursor: "pointer" }}
                onClick={() => addSkill(s.id)}
              >
                {s.id}
              </button>
            ))}
          </div>
        )}
        <div className="form__actions">
          <button className="btn btn--primary" disabled={cfgBusy} onClick={configure}>
            {cfgBusy ? "Saving..." : "Save agent"}
          </button>
          {cfgMsg && <span className="ok">{cfgMsg}</span>}
          {cfgError && <span className="error">{cfgError}</span>}
        </div>
      </div>

      <div className="form">
        <div className="form__title">Ask your agent</div>
        <InfoCallout>
          It runs on your behalf and can never do more than you can - the
          permissions it used are shown below as <code>effective_grants</code>.
        </InfoCallout>
        <Field label="Message" hint="What should your agent do?" example="Draft a reply to ticket 4821">
          <textarea
            className="code"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        </Field>
        <div className="form__actions">
          <button className="btn" disabled={invBusy} onClick={invoke}>
            {invBusy ? "Working..." : "Ask"}
          </button>
          {invError && <span className="error">{invError}</span>}
        </div>
        {invResult &&
          (invResult.error || invResult.status === "denied" ? (
            <p className="error">
              {String(invResult.error ?? invResult.reason ?? "no_personal_agent")}
            </p>
          ) : (
            <div className="stack">
              <div className="row-line">
                <span className="muted">effective_grants</span>
                <GrantList grants={invResult.effective_grants} />
              </div>
              <CodeBlock value={invResult} />
            </div>
          ))}
      </div>
    </div>
  );
}

// Notifications are edited in one place (Settings -> Notifications) to avoid two
// divergent editors. This card points there.
function NotificationsPointer() {
  return (
    <div className="form">
      <div className="form__title">Notifications</div>
      <Hint>Choose how and when Boltrig reaches you - approvals, escalations and more.</Hint>
      <div className="form__actions">
        <button className="btn" onClick={() => navigate("/settings")}>
          Manage in Settings
        </button>
      </div>
    </div>
  );
}

function MemoryQuery() {
  const [kind, setKind] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [scopes, setScopes] = useState<string[]>([]);

  async function query() {
    setBusy(true);
    setError(null);
    setItems(null);
    try {
      const res = await api.memoryQuery({ kind: kind.trim() || undefined });
      setItems(res.items);
      setScopes(res.scopes);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">Memory query</div>
      <p className="muted">
        Scope-isolated: you only see your user scope, the org scope and your
        departments (SEC-31).
      </p>
      <div className="form__actions">
        <Field label="Type" hint="Filter to one type of item." example="fact, preference, note">
          <input value={kind} onChange={(e) => setKind(e.target.value)} />
        </Field>
        <button className="btn btn--primary" disabled={busy} onClick={query}>
          {busy ? "Searching..." : "Search"}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
      {items && (
        <div className="stack">
          <p className="muted">
            scopes:{" "}
            {scopes.map((s) => (
              <code className="tag" key={s}>
                {s}
              </code>
            ))}
          </p>
          {items.length === 0 ? (
            <p className="muted">No memory items in scope.</p>
          ) : (
            items.map((m) => (
              <div className="row-line" key={m.id}>
                <div>
                  <code className="tag">{m.kind}</code>{" "}
                  <span className="muted">{m.owner_scope}</span>
                  <CodeBlock value={m.content} />
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export function MePanel() {
  return (
    <section className="panel">
      <PageIntro
        title="Me"
        lead="Your personal agent, notification preferences, and a scoped view of memory."
        how="Your agent runs as you and never exceeds your permissions. Everything here is yours alone."
      />

      <div className="cols">
        <PersonalAgent />
        <div className="stack">
          <NotificationsPointer />
          <MemoryQuery />
        </div>
      </div>
    </section>
  );
}
