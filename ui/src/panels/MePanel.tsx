// Round Three personal surface (any authenticated user). Configure a personal
// agent, invoke it (delegated-only: it runs on-behalf-of you and is capped to
// your grants - the returned effective_grants show that cap, SEC-30), manage
// your own notification prefs, and query memory (scope-filtered: you only see
// your user scope, the org scope and your departments - SEC-31).

import { useState } from "react";

import { api } from "../api/client";
import type {
  MemoryItem,
  NotificationPrefItem,
  SpawnResult,
} from "../api/types";
import { useFetch } from "../useFetch";
import { CodeBlock, GrantList, csvToList, errText } from "./shared";

function PersonalAgent() {
  const [runtime, setRuntime] = useState("pi-worker");
  const [skills, setSkills] = useState("");
  const [cfgBusy, setCfgBusy] = useState(false);
  const [cfgError, setCfgError] = useState<string | null>(null);
  const [cfgMsg, setCfgMsg] = useState<string | null>(null);

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
      setCfgError(errText(err));
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
        <div className="form__title">Configure personal agent</div>
        <div className="form__grid">
          <label className="field">
            <span>runtime</span>
            <input
              value={runtime}
              onChange={(e) => setRuntime(e.target.value)}
            />
          </label>
          <label className="field">
            <span>skills (comma list)</span>
            <input
              value={skills}
              onChange={(e) => setSkills(e.target.value)}
            />
          </label>
        </div>
        <div className="form__actions">
          <button className="btn btn--primary" disabled={cfgBusy} onClick={configure}>
            {cfgBusy ? "..." : "Save agent"}
          </button>
          {cfgMsg && <span className="ok">{cfgMsg}</span>}
          {cfgError && <span className="error">{cfgError}</span>}
        </div>
      </div>

      <div className="form">
        <div className="form__title">Invoke (delegated-only)</div>
        <p className="muted">
          Runs on-behalf-of you, capped to your grants. effective_grants below
          can never exceed your own.
        </p>
        <label className="field">
          <span>message</span>
          <textarea
            className="code"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        </label>
        <div className="form__actions">
          <button className="btn" disabled={invBusy} onClick={invoke}>
            {invBusy ? "..." : "Invoke"}
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

function NotificationPrefs() {
  const prefs = useFetch(() => api.notificationPrefs(), []);

  const [eventType, setEventType] = useState("");
  const [channel, setChannel] = useState("email");
  const [target, setTarget] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function save() {
    if (!eventType.trim() || !channel.trim()) {
      setError("event_type and channel are required.");
      return;
    }
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.putNotificationPref({
        event_type: eventType.trim(),
        channel: channel.trim(),
        target: target.trim() || undefined,
        enabled,
      });
      setMsg(`Saved pref ${res.id}.`);
      prefs.reload();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const list: NotificationPrefItem[] = prefs.data?.prefs ?? [];

  return (
    <div className="stack">
      <div className="form">
        <div className="form__title">Notification preference</div>
        <div className="form__grid">
          <label className="field">
            <span>event_type</span>
            <input
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
            />
          </label>
          <label className="field">
            <span>channel</span>
            <input
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            />
          </label>
          <label className="field">
            <span>target</span>
            <input value={target} onChange={(e) => setTarget(e.target.value)} />
          </label>
          <label className="field">
            <span>enabled</span>
            <select
              value={enabled ? "yes" : "no"}
              onChange={(e) => setEnabled(e.target.value === "yes")}
            >
              <option value="yes">enabled</option>
              <option value="no">disabled</option>
            </select>
          </label>
        </div>
        <div className="form__actions">
          <button className="btn btn--primary" disabled={busy} onClick={save}>
            {busy ? "..." : "Save preference"}
          </button>
          {msg && <span className="ok">{msg}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>My preferences</h3>
          <button className="btn" onClick={() => prefs.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {prefs.loading && !prefs.data && <p className="muted">Loading...</p>}
          {prefs.error && (
            <p className="error">Failed to load: {prefs.error}</p>
          )}
          {!prefs.loading && list.length === 0 && (
            <p className="muted">No preferences set.</p>
          )}
          {list.map((pref) => (
            <div className="row-line" key={pref.id}>
              <div>
                <code>{pref.event_type}</code>{" "}
                <span className="muted">
                  via {pref.channel}
                  {pref.target ? ` -> ${pref.target}` : ""}
                </span>
              </div>
              <span className={`badge ${pref.enabled ? "badge--ok" : ""}`}>
                {pref.enabled ? "on" : "off"}
              </span>
            </div>
          ))}
        </div>
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
        <label className="field">
          <span>kind (optional)</span>
          <input value={kind} onChange={(e) => setKind(e.target.value)} />
        </label>
        <button className="btn btn--primary" disabled={busy} onClick={query}>
          {busy ? "..." : "Query"}
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
      <div className="panel__head">
        <h2>Me</h2>
        <div className="panel__actions">
          <span className="muted">personal agent, prefs and memory</span>
        </div>
      </div>

      <div className="cols">
        <PersonalAgent />
        <div className="stack">
          <NotificationPrefs />
          <MemoryQuery />
        </div>
      </div>
    </section>
  );
}
