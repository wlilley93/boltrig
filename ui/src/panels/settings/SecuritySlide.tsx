// Settings / Security & Sessions: active sessions, standing tokens and the
// caller's own activity (SET-71, SET-72).
// Mechanical extraction of SecuritySessions from SettingsPanel.tsx (Beat 5).

import { api } from "../../api/client";
import type { ActivityRow, SessionView } from "../../api/types";
import { useFetch } from "../../useFetch";
import { RunLink } from "../shared";
import {
  AUDIT_STATUS,
  EmptyState,
  FetchError,
  PageIntro,
  StatusBadge,
} from "../ux";
import { ArmConfirm, Skeleton } from "../uxFlow";
import { TokenList } from "./shared";

function SessionsList() {
  const sessions = useFetch(() => api.meSessions(), []);

  // Throws on a rejected revoke so the row's ArmConfirm renders the reason.
  async function revoke(id: string) {
    const res = await api.revokeSession(id);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "revoke rejected");
    }
    sessions.reload();
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
        {sessions.loading && !sessions.data && <Skeleton variant="rows" />}
        <FetchError
          error={sessions.error}
          status={sessions.errorStatus}
          onRetry={sessions.reload}
        />
        {sessions.data && list.length === 0 && (
          <EmptyState title="No sessions" />
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
              <ArmConfirm
                label="Revoke"
                armLabel="Revoke this session? That device is signed out immediately."
                confirmLabel="Confirm revoke"
                tone="danger"
                busyLabel="Revoking..."
                onConfirm={() => revoke(s.id)}
              />
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
      {activity.loading && !activity.data && <Skeleton variant="rows" />}
      <FetchError
        error={activity.error}
        status={activity.errorStatus}
        onRetry={activity.reload}
      />
      {activity.data && rows.length === 0 && (
        <EmptyState title="No recent activity" />
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Action</th>
                <th>Result</th>
                <th>Run</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.seq}>
                  <td>{r.ts ?? "-"}</td>
                  <td>
                    <code>{r.verb}</code>
                  </td>
                  <td>
                    <StatusBadge value={r.status} glossary={AUDIT_STATUS} />
                  </td>
                  <td>
                    {r.run_id ? (
                      <RunLink runId={r.run_id} />
                    ) : (
                      <span className="muted">-</span>
                    )}
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
