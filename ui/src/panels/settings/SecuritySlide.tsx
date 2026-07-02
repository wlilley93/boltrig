// Settings / Security & Sessions: active sessions, standing tokens and the
// caller's own activity (SET-71, SET-72).
// Mechanical extraction of SecuritySessions from SettingsPanel.tsx (Beat 5).

import { useState } from "react";

import { api } from "../../api/client";
import type { ActivityRow, SessionView } from "../../api/types";
import { useFetch } from "../../useFetch";
import { errText } from "../shared";
import { PageIntro } from "../ux";
import { TokenList } from "./shared";

function SessionsList() {
  const sessions = useFetch(() => api.meSessions(), []);
  const [error, setError] = useState<string | null>(null);

  async function revoke(id: string) {
    if (!window.confirm("Revoke this session?")) return;
    setError(null);
    try {
      const res = await api.revokeSession(id);
      if (res.status === "ok") sessions.reload();
      else setError(res.reason ?? "revoke rejected");
    } catch (err) {
      setError(errText(err));
    }
  }

  const list: SessionView[] = sessions.data?.sessions ?? [];

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Active sessions</h3>
        <button className="btn" onClick={() => sessions.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {sessions.loading && !sessions.data && (
          <p className="muted">Loading...</p>
        )}
        {sessions.error && (
          <p className="error">Failed to load: {sessions.error}</p>
        )}
        {error && <p className="error">{error}</p>}
        {!sessions.loading && list.length === 0 && (
          <p className="muted">No sessions.</p>
        )}
        {list.map((s) => (
          <div className="row-line" key={s.id}>
            <div>
              <code>{s.client ?? "client"}</code>{" "}
              {s.revoked && <span className="badge badge--down">revoked</span>}
              <div className="muted">
                created {s.created_at ?? "-"} - last seen{" "}
                {s.last_seen_at ?? "-"}
              </div>
            </div>
            {!s.revoked && (
              <button className="btn" onClick={() => void revoke(s.id)}>
                Revoke
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivityList() {
  const activity = useFetch(() => api.meActivity(), []);
  const rows: ActivityRow[] = activity.data?.results ?? [];

  return (
    <div className="form">
      <div className="form__title">My activity</div>
      <p className="muted">
        Your own recent actions, filtered to you (SET-72).
      </p>
      {activity.loading && !activity.data && <p className="muted">Loading...</p>}
      {activity.error && (
        <p className="error">Failed to load: {activity.error}</p>
      )}
      {!activity.loading && rows.length === 0 && (
        <p className="muted">No recent activity.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>seq</th>
                <th>ts</th>
                <th>verb</th>
                <th>status</th>
                <th>run_id</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.seq}>
                  <td>{r.seq}</td>
                  <td>{r.ts ?? "-"}</td>
                  <td>
                    <code>{r.verb}</code>
                  </td>
                  <td>{r.status}</td>
                  <td>
                    <code>{r.run_id ?? "-"}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SecuritySessions() {
  return (
    <div className="stack">
      <p className="notice">
        Boltrig stores no passwords and runs no MFA of its own - sign-in, MFA and
        password resets are managed entirely by your identity provider (SET-71).
        Tokens and sessions below are your standing credentials here; revoke any
        you do not recognise.
      </p>
      <div className="cols">
        <SessionsList />
        <TokenList />
      </div>
      <ActivityList />
    </div>
  );
}

export function SecuritySlide() {
  return (
    <section className="panel">
      <PageIntro
        title="Security & Sessions"
        lead="Active sessions, tokens, your own activity."
      />
      <SecuritySessions />
    </section>
  );
}
