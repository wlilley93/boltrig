import { useState } from "react";

import { api } from "@/api/client";
import type { AdminInvitation } from "@/api/types";
import { useFetch } from "@/useFetch";
import { errText } from "@/panels/shared";
import {
  EmptyState,
  FetchError,
  Field,
  ROLE_OPTIONS,
  Select,
  TTL_OPTIONS,
  ttlDaysFromSelection,
} from "@/panels/ux";
import { ArmConfirm, Skeleton } from "@/panels/uxFlow";

function useInviteForm(onCreated: () => void) {
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
      const res = await api.createInvitation({
        email: email.trim(),
        role,
        ttl_days: ttlDaysFromSelection(ttl),
      });
      if (res.status === "ok") {
        setMsg(`Invited ${res.email ?? email}.`);
        setEmail("");
        onCreated();
      } else {
        setError(res.reason ?? "invite rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return {
    email,
    setEmail,
    role,
    setRole,
    ttl,
    setTtl,
    busy,
    error,
    msg,
    createInvite,
  };
}

function InviteForm({ form }: { form: ReturnType<typeof useInviteForm> }) {
  return (
    <>
      <div className="form__grid">
        <Field label="Email" required example="ada@example.com">
          <input
            type="email"
            value={form.email}
            onChange={(e) => form.setEmail(e.target.value)}
          />
        </Field>
        <Field label="Role">
          <Select
            value={form.role}
            ariaLabel="Invited role"
            onChange={form.setRole}
            options={ROLE_OPTIONS}
          />
        </Field>
        <Field label="Expires in (days)" hint="How long the invitation stays open.">
          <Select
            value={form.ttl}
            ariaLabel="Invitation expiry"
            onChange={form.setTtl}
            options={TTL_OPTIONS}
          />
        </Field>
      </div>
      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={form.busy}
          onClick={() => void form.createInvite()}
        >
          {form.busy ? "..." : "Send invitation"}
        </button>
        {form.msg && <span className="ok">{form.msg}</span>}
        {form.error && <span className="error">{form.error}</span>}
      </div>
    </>
  );
}

function InviteRow({
  invite,
  onRevoked,
}: {
  invite: AdminInvitation;
  onRevoked: () => void;
}) {
  async function revokeInvite() {
    const res = await api.revokeInvitation(invite.id);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "revoke rejected");
    }
    onRevoked();
  }

  return (
    <div className="row-line">
      <div>
        <code>{invite.email}</code>{" "}
        <span className="muted">as {invite.intended_role}</span>
        <div className="muted">
          {invite.status} - invited by {invite.invited_by} - expires{" "}
          {invite.expires_at ?? "-"}
        </div>
      </div>
      {invite.status === "pending" && (
        <ArmConfirm
          label="Revoke"
          armLabel={
            <>
              Revoke the invitation for <code>{invite.email}</code>? They will not
              be pre-staged when they sign in.
            </>
          }
          confirmLabel="Confirm revoke"
          tone="danger"
          busyLabel="Revoking..."
          onConfirm={revokeInvite}
        />
      )}
    </div>
  );
}

export function InvitationsCard() {
  const invites = useFetch(() => api.adminInvitations(), []);
  const form = useInviteForm(() => invites.reload());

  const invitesDenied =
    invites.data && invites.data.invitations === undefined
      ? invites.data.reason ?? "organisation administration not permitted"
      : null;
  const inviteList = invites.data?.invitations ?? [];

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Invitations</h3>
        <button className="btn" onClick={() => invites.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        <p className="ux-hint">
          An invitation pre-stages a role for an SSO identity. It creates no
          password and grants nothing until the invitee signs in through your IdP
          (SEC-35).
        </p>
        <InviteForm form={form} />
        {invites.loading && !invites.data && <Skeleton variant="rows" />}
        <FetchError
          error={invites.error}
          status={invites.errorStatus}
          onRetry={invites.reload}
        />
        {invitesDenied && <p className="notice warn">denied: {invitesDenied}</p>}
        {!invitesDenied && invites.data && inviteList.length === 0 && (
          <EmptyState
            title="No invitations"
            body="Invite someone above; they get access the first time they sign in through your IdP."
          />
        )}
        {inviteList.map((inv) => (
          <InviteRow key={inv.id} invite={inv} onRevoked={() => invites.reload()} />
        ))}
      </div>
    </div>
  );
}
