// Settings / Organisation (org-admin): the user directory and invitations
// (Epic USR). The deck column is cosmetically gated to org-admins; every call
// here uses tolerateStatus so a server denial (403) renders as a notice rather
// than throwing - the server stays the real gate.
// Mechanical extraction of OrganisationSection from SettingsPanel.tsx (Beat 5).

import { useState } from "react";

import { api } from "../../api/client";
import type {
  AdminInvitation,
  DirectoryUser,
  PatchUserRequest,
} from "../../api/types";
import { useFetch } from "../../useFetch";
import { errText, parseJson, prettyJson } from "../shared";
import { PageIntro, ROLE_VALUES } from "../ux";
import { scopeReadable } from "./shared";

// One source of truth for the role set (shared with the identity + admin selects).
const ROLE_OPTIONS: ReadonlyArray<string> = ROLE_VALUES;

function UserRow({
  user,
  onChanged,
}: {
  user: DirectoryUser;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scopeText, setScopeText] = useState(() =>
    prettyJson(user.scope ?? {}),
  );

  async function patch(body: PatchUserRequest) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.patchUser(user.id, body);
      if (res.status === "ok") onChanged();
      else setError(res.reason ?? "update rejected");
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  function saveScope() {
    let scope: Record<string, unknown>;
    try {
      scope = parseJson<Record<string, unknown>>(scopeText, {});
    } catch (err) {
      setError(`scope: ${errText(err)}`);
      return;
    }
    void patch({ scope });
  }

  const deactivated = user.status === "deactivated";

  return (
    <div className="dir-row">
      <div className="row-line dir-row__top">
        <div>
          <code>{user.email ?? user.id}</code>{" "}
          <span className="muted">{user.display_name ?? ""}</span>
          <div className="muted">
            {user.source ?? "idp"}
            {user.source_group ? ` / ${user.source_group}` : ""} - scope:{" "}
            {scopeReadable(user.scope)}
          </div>
          {error && <div className="error">{error}</div>}
        </div>
        <div className="kv">
          <label className="field">
            <span>role</span>
            <select
              value={user.role}
              disabled={busy}
              aria-label={`Role for ${user.email ?? user.id}`}
              onChange={(e) => void patch({ role: e.target.value })}
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <span
            className={`badge ${deactivated ? "badge--down" : "badge--ok"}`}
          >
            {user.status}
          </span>
          <button
            className="btn"
            disabled={busy}
            onClick={() =>
              void patch({ status: deactivated ? "active" : "deactivated" })
            }
          >
            {deactivated ? "Activate" : "Deactivate"}
          </button>
        </div>
      </div>
      <details className="dir-row__scope">
        <summary>Edit scope</summary>
        <label className="field">
          <span>scope (JSON: departments / nouns / verbs visible)</span>
          <textarea
            className="code"
            value={scopeText}
            onChange={(e) => setScopeText(e.target.value)}
          />
        </label>
        <button className="btn" disabled={busy} onClick={saveScope}>
          {busy ? "..." : "Save scope"}
        </button>
      </details>
    </div>
  );
}

function OrganisationSection() {
  const users = useFetch(() => api.adminUsers(), []);
  const invites = useFetch(() => api.adminInvitations(), []);

  const [email, setEmail] = useState("");
  const [role, setRole] = useState("agent");
  const [ttl, setTtl] = useState("14");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function createInvite() {
    if (!email.trim()) {
      setError("An email is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const ttlDays = ttl.trim() ? Number(ttl.trim()) : undefined;
      if (ttlDays !== undefined && Number.isNaN(ttlDays)) {
        setError("ttl_days must be a number.");
        setBusy(false);
        return;
      }
      const res = await api.createInvitation({
        email: email.trim(),
        role,
        ttl_days: ttlDays,
      });
      if (res.status === "ok") {
        setMsg(`Invited ${res.email ?? email}.`);
        setEmail("");
        invites.reload();
      } else {
        setError(res.reason ?? "invite rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function revokeInvite(id: string) {
    if (!window.confirm("Revoke this invitation?")) return;
    setError(null);
    try {
      const res = await api.revokeInvitation(id);
      if (res.status === "ok") invites.reload();
      else setError(res.reason ?? "revoke rejected");
    } catch (err) {
      setError(errText(err));
    }
  }

  // The server returns {status:"denied", reason} (no users/invitations key) when
  // the caller is not an org-admin.
  const usersDenied =
    users.data && users.data.users === undefined
      ? users.data.reason ?? "organisation administration not permitted"
      : null;
  const userList = users.data?.users ?? [];

  const invitesDenied =
    invites.data && invites.data.invitations === undefined
      ? invites.data.reason ?? "organisation administration not permitted"
      : null;
  const inviteList = invites.data?.invitations ?? [];

  return (
    <div className="stack">
      <p className="notice">
        Manage who is in the organisation and what they may do. Deeper
        organisation configuration (privacy, network, models, HITL) lives under
        the Admin tab. Deactivating a user revokes their access immediately
        (US-USR-03).
      </p>

      <div className="list-card">
        <div className="list-card__head">
          <h3>User directory</h3>
          <button className="btn" onClick={() => users.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {users.loading && !users.data && <p className="muted">Loading...</p>}
          {users.error && (
            <p className="error">Failed to load: {users.error}</p>
          )}
          {usersDenied && (
            <p className="notice warn">denied: {usersDenied}</p>
          )}
          {!usersDenied && !users.loading && userList.length === 0 && (
            <p className="muted">No users.</p>
          )}
          {userList.map((u) => (
            <UserRow key={u.id} user={u} onChanged={() => users.reload()} />
          ))}
        </div>
      </div>

      <div className="cols">
        <div className="form">
          <div className="form__title">Invite a user</div>
          <p className="muted">
            An invitation pre-stages a role for an SSO identity. It creates no
            password and grants nothing until the invitee signs in through your
            IdP (SEC-35).
          </p>
          <div className="form__grid">
            <label className="field">
              <span>email</span>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="field">
              <span>role</span>
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>ttl_days</span>
              <input value={ttl} onChange={(e) => setTtl(e.target.value)} />
            </label>
          </div>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={busy}
              onClick={() => void createInvite()}
            >
              {busy ? "..." : "Send invitation"}
            </button>
            {msg && <span className="ok">{msg}</span>}
            {error && <span className="error">{error}</span>}
          </div>
        </div>

        <div className="list-card">
          <div className="list-card__head">
            <h3>Invitations</h3>
            <button className="btn" onClick={() => invites.reload()}>
              Refresh
            </button>
          </div>
          <div className="list-card__body">
            {invites.loading && !invites.data && (
              <p className="muted">Loading...</p>
            )}
            {invites.error && (
              <p className="error">Failed to load: {invites.error}</p>
            )}
            {invitesDenied && (
              <p className="notice warn">denied: {invitesDenied}</p>
            )}
            {!invitesDenied && !invites.loading && inviteList.length === 0 && (
              <p className="muted">No invitations.</p>
            )}
            {inviteList.map((inv: AdminInvitation) => (
              <div className="row-line" key={inv.id}>
                <div>
                  <code>{inv.email}</code>{" "}
                  <span className="muted">as {inv.intended_role}</span>
                  <div className="muted">
                    {inv.status} - invited by {inv.invited_by} - expires{" "}
                    {inv.expires_at ?? "-"}
                  </div>
                </div>
                {inv.status === "pending" && (
                  <button
                    className="btn"
                    onClick={() => void revokeInvite(inv.id)}
                  >
                    Revoke
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function OrganisationSlide() {
  return (
    <section className="panel">
      <PageIntro
        title="Organisation"
        lead="The user directory and invitations."
      />
      <OrganisationSection />
    </section>
  );
}
