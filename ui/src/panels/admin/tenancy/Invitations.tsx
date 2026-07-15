import { useState } from "react";

import { api } from "@/api/client";
import type { AdminInvitation } from "@/api/types";
import { useFetch } from "@/useFetch";
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
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { outputRecord, useControlMutation } from "@/panels/uxFlow/useControlMutation";

function useInviteForm(onCreated: () => void) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("agent");
  const [ttl, setTtl] = useState("14");
  const [msg, setMsg] = useState<string | null>(null);
  const mutation = useControlMutation({
    verb: "control.invitation.create",
    onApplied(output, params) {
      const created = outputRecord(output);
      setMsg(`Invited ${String(created.email ?? params.email)}.`);
      setEmail("");
      onCreated();
    },
  });

  async function createInvite() {
    if (!email.trim()) {
      mutation.onPendingDenied("An email is required.");
      return;
    }
    setMsg(null);
    await mutation.invoke({
      email: email.trim(),
      role,
      ttl_days: ttlDaysFromSelection(ttl),
    });
  }

  return {
    email,
    setEmail,
    role,
    setRole,
    ttl,
    setTtl,
    mutation,
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
          disabled={form.mutation.busy || form.mutation.pending !== null}
          onClick={() => void form.createInvite()}
        >
          {form.mutation.busy ? "..." : "Send invitation"}
        </button>
        {form.msg && <span className="ok">{form.msg}</span>}
        {form.mutation.error && <span className="error">{form.mutation.error}</span>}
      </div>
      {form.mutation.pending && (
        <PendingHumanCard
          hitlRequestId={form.mutation.pending.id}
          noun="control"
          verb="control.invitation.create"
          sentParams={form.mutation.pending.params}
          onApplied={form.mutation.onPendingApplied}
          onDenied={form.mutation.onPendingDenied}
          onReset={form.mutation.resetPending}
        />
      )}
    </>
  );
}

function InviteRow({
  invite,
  onRevoke,
}: {
  invite: AdminInvitation;
  onRevoke: (inviteId: string) => Promise<void>;
}) {
  async function revokeInvite() {
    await onRevoke(invite.id);
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
  const revokeMutation = useControlMutation({
    verb: "control.invitation.revoke",
    onApplied() {
      invites.reload();
    },
  });

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
        {revokeMutation.error && <p className="error">{revokeMutation.error}</p>}
        {revokeMutation.pending && (
          <PendingHumanCard
            hitlRequestId={revokeMutation.pending.id}
            noun="control"
            verb="control.invitation.revoke"
            sentParams={revokeMutation.pending.params}
            onApplied={revokeMutation.onPendingApplied}
            onDenied={revokeMutation.onPendingDenied}
            onReset={revokeMutation.resetPending}
          />
        )}
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
          <InviteRow
            key={inv.id}
            invite={inv}
            onRevoke={async (inviteId) => {
              await revokeMutation.invoke({ invite_id: inviteId });
            }}
          />
        ))}
      </div>
    </div>
  );
}
