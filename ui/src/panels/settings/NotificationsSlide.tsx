// Settings / Notifications: per-user routing of events to channels (SET-30).
// Mechanical extraction of NotificationsSection from SettingsPanel.tsx (Beat 5).

import { useState } from "react";

import { api } from "../../api/client";
import type { MeNotificationItem } from "../../api/types";
import { useFetch } from "../../useFetch";
import { errText } from "../shared";
import { PageIntro } from "../ux";

const EVENT_TYPES: ReadonlyArray<string> = [
  "approval",
  "escalation",
  "work_status",
  "budget_alert",
  "error",
];

const CHANNELS: ReadonlyArray<string> = [
  "in_app",
  "email",
  "slack",
  "teams",
  "webhook",
  "pager",
];

function NotificationsSection() {
  const prefs = useFetch(() => api.meNotifications(), []);

  const [eventType, setEventType] = useState(EVENT_TYPES[0]);
  const [channel, setChannel] = useState(CHANNELS[0]);
  const [target, setTarget] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function save(body: {
    id?: string;
    event_type: string;
    channel: string;
    target?: string;
    enabled?: boolean;
  }) {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.putMeNotification(body);
      if (res.status === "ok") {
        setMsg(`Saved routing ${res.id ?? ""}.`);
        prefs.reload();
      } else {
        setError(res.reason ?? "save rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const list: MeNotificationItem[] = prefs.data?.prefs ?? [];

  return (
    <div className="cols">
      <div className="form">
        <div className="form__title">Add / update routing</div>
        <p className="muted">
          Where each kind of notification reaches you (SET-30). The server stores
          this against your own user scope.
        </p>
        <div className="form__grid">
          <label className="field">
            <span>event type</span>
            <select
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
            >
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>channel</span>
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            >
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>target</span>
            <input
              value={target}
              placeholder="address / channel / url"
              onChange={(e) => setTarget(e.target.value)}
            />
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
          <button
            className="btn btn--primary"
            disabled={busy}
            onClick={() =>
              void save({
                event_type: eventType,
                channel,
                target: target.trim() || undefined,
                enabled,
              })
            }
          >
            {busy ? "..." : "Save routing"}
          </button>
          {msg && <span className="ok">{msg}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>My routing</h3>
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
            <p className="muted">No routing configured.</p>
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
              <div className="kv">
                <span className={`badge ${pref.enabled ? "badge--ok" : ""}`}>
                  {pref.enabled ? "on" : "off"}
                </span>
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() =>
                    void save({
                      id: pref.id,
                      event_type: pref.event_type,
                      channel: pref.channel,
                      target: pref.target ?? undefined,
                      enabled: !pref.enabled,
                    })
                  }
                >
                  {pref.enabled ? "Disable" : "Enable"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function NotificationsSlide() {
  return (
    <section className="panel">
      <PageIntro title="Notifications" lead="What reaches you, and where." />
      <NotificationsSection />
    </section>
  );
}
