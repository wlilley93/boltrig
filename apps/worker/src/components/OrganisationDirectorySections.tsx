import { useEffect, useState } from "react";
import type {
  AdminInvitation,
  CreateInvitationRequest,
  CreateInvitationResponse,
  DeleteAck,
  DirectoryUser,
  GovernedRouteResponse,
  OrgMemberView,
  PatchUserRequest,
  PatchUserResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { copySensitiveText } from "../clipboard";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";

type DirectoryMutation = {
  kind: "role" | "status" | "scope";
  userId: string;
  body: PatchUserRequest;
  success: string;
};

type InvitationMutation =
  | { kind: "create"; body: CreateInvitationRequest; success: string }
  | { kind: "revoke"; invitationId: string; success: string };

export function OrganisationRoster() {
  const [members, setMembers] = useState<OrgMemberView[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void client.orgMembers()
      .then((result) => setMembers(result.members))
      .catch(() => setMessage("Organisation membership is unavailable."));
  }, []);

  return (
    <section className="settings-card">
      <p className="eyebrow">Organisation members</p>
      <h2>{members.length} members</h2>
      <div className="data-list" role="region" aria-label="Organisation members">
        {members.map((member) => (
          <div className="data-row static" key={member.user_id}>
            <span className="activity-dot done" />
            <span className="data-row-copy">
              <strong>{member.user_id}</strong>
              <small>Joined {member.created_at || "before activity records"}</small>
            </span>
            <span className="row-meta">{member.role}</span>
          </div>
        ))}
      </div>
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

export function AdminDirectory({ currentRole }: { currentRole: string }) {
  const [users, setUsers] = useState<DirectoryUser[]>([]);
  const [message, setMessage] = useState("");
  const [armedId, setArmedId] = useState<string | null>(null);
  const [scopeDrafts, setScopeDrafts] = useState<Record<string, string>>({});

  const finalizer = useExactApprovalFinalizer<
    DirectoryMutation,
    GovernedRouteResponse<PatchUserResponse>
  >({
    isCurrent: (input) => {
      const user = users.find((item) => item.id === input.userId);
      if (!user) return false;
      if (input.kind === "scope") {
        try {
          return routeInputEquals(input.body.scope, JSON.parse(
            scopeDrafts[input.userId] ?? "{}",
          ));
        } catch {
          return false;
        }
      }
      if (input.kind === "status") {
        return input.body.status === (
          user.status === "active" ? "deactivated" : "active"
        );
      }
      return user.role !== input.body.role;
    },
    replay: (input, approvalId) => (
      client.patchUser(input.userId, input.body, approvalId)
    ),
    onApplied: async (_result, input) => {
      setMessage(input.success);
      refresh();
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result, "The approved user change was refused.",
      ));
    },
  });

  function refresh() {
    finalizer.invalidate();
    void client.adminUsers()
      .then((result) => {
        setUsers(result.users ?? []);
        setScopeDrafts(Object.fromEntries((result.users ?? []).map((user) => [
          user.id,
          JSON.stringify(user.scope ?? {}, null, 2),
        ])));
        if (!result.users) setMessage(result.reason ?? "Directory access denied.");
      })
      .catch(() => setMessage("User directory is unavailable."));
  }

  useEffect(refresh, []);

  async function changeRole(user: DirectoryUser, role: string) {
    finalizer.invalidate();
    const input: DirectoryMutation = {
      kind: "role",
      userId: user.id,
      body: { role },
      success: "User role updated.",
    };
    const result = await client.patchUser(user.id, input.body);
    if (finalizer.begin(input, result, "User role change")) {
      setMessage("Pending approval. Continue in the originating chat.");
      return;
    }
    setMessage(responseMessage(result, input.success));
    if (result.status === "ok") refresh();
  }

  async function changeStatus(user: DirectoryUser) {
    if (armedId !== user.id) {
      finalizer.invalidate();
      setArmedId(user.id);
      return;
    }
    const next = user.status === "active" ? "deactivated" : "active";
    const input: DirectoryMutation = {
      kind: "status",
      userId: user.id,
      body: { status: next },
      success: next === "active" ? "User reactivated." : "User deactivated.",
    };
    const result = await client.patchUser(user.id, input.body);
    if (finalizer.begin(input, result, "User status change")) {
      setMessage("Pending approval. Continue in the originating chat.");
      setArmedId(null);
      return;
    }
    setMessage(responseMessage(result, input.success));
    setArmedId(null);
    if (result.status === "ok") refresh();
  }

  async function saveScope(user: DirectoryUser) {
    try {
      const parsed = JSON.parse(scopeDrafts[user.id] ?? "{}") as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("Scope must be a JSON object.");
      }
      const input: DirectoryMutation = {
        kind: "scope",
        userId: user.id,
        body: { scope: parsed as Record<string, unknown> },
        success: "User scope updated.",
      };
      const result = await client.patchUser(user.id, input.body);
      if (finalizer.begin(input, result, "User scope change")) {
        setMessage("Pending approval. Continue in the originating chat.");
        return;
      }
      setMessage(responseMessage(result, input.success));
      if (result.status === "ok") refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Scope must be valid JSON.");
    }
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">User directory</p>
      <h2>Organisation access</h2>
      <div className="data-list" aria-label="Admin users">
        {users.map((user) => (
          <div className="data-row static editable-row" key={user.id}>
            <span className={`activity-dot ${user.status === "active" ? "done" : "failed"}`} />
            <span className="data-row-copy">
              <strong>{user.display_name || user.email || user.id}</strong>
              <small>{user.status} · {user.source || "local"}</small>
            </span>
            <select
              className="field-control compact"
              aria-label={`Role for ${user.id}`}
              value={user.role}
              onChange={(event) => void changeRole(user, event.target.value)}
            >
              {grantableRoles(currentRole).map((role) => (
                <option value={role} key={role}>{role}</option>
              ))}
              {!grantableRoles(currentRole).includes(user.role) && (
                <option value={user.role}>{user.role}</option>
              )}
            </select>
            <button
              className={armedId === user.id ? "danger-button armed" : user.status === "active" ? "danger-button" : "secondary-button"}
              onClick={() => void changeStatus(user)}
            >
              {armedId === user.id
                ? `Confirm ${user.status === "active" ? "deactivate" : "reactivate"}`
                : user.status === "active" ? "Deactivate" : "Reactivate"}
            </button>
            <details className="row-editor">
              <summary>Scope</summary>
              <textarea
                className="field-control code-field"
                aria-label={`Scope for ${user.id}`}
                rows={5}
                value={scopeDrafts[user.id] ?? "{}"}
                onChange={(event) => {
                  finalizer.invalidate();
                  setScopeDrafts((current) => ({
                    ...current,
                    [user.id]: event.target.value,
                  }));
                }}
              />
              <button className="secondary-button" onClick={() => void saveScope(user)}>Save scope</button>
            </details>
          </div>
        ))}
      </div>
      <ExactApprovalFinalizer controller={finalizer} />
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

export function InvitationAdministration({ currentRole }: { currentRole: string }) {
  const [invitations, setInvitations] = useState<AdminInvitation[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState(grantableRoles(currentRole).at(-1) ?? "member");
  const [armedId, setArmedId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [scope, setScope] = useState("{}");
  const [ttlDays, setTtlDays] = useState("14");
  const [workspaceId, setWorkspaceId] = useState("");
  const [provisionWorkspace, setProvisionWorkspace] = useState("");
  const [provisionOrg, setProvisionOrg] = useState("");
  const [inviteToken, setInviteToken] = useState("");

  const finalizer = useExactApprovalFinalizer<
    InvitationMutation,
    GovernedRouteResponse<CreateInvitationResponse | DeleteAck>
  >({
    isCurrent: (input) => {
      if (input.kind === "revoke") {
        return invitations.some((item) => (
          item.id === input.invitationId && item.status === "pending"
        ));
      }
      try {
        return routeInputEquals(
          input.body,
          invitationDraft({
            email,
            role,
            scope: JSON.parse(scope) as Record<string, unknown>,
            ttlDays,
            workspaceId,
            provisionWorkspace,
            provisionOrg,
            currentRole,
          }),
        );
      } catch {
        return false;
      }
    },
    replay: (input, approvalId) => (
      input.kind === "create"
        ? client.createInvitation(input.body, approvalId)
        : client.revokeInvitation(input.invitationId, approvalId)
    ),
    onApplied: async (result, input) => {
      setMessage(input.success);
      if (input.kind === "create" && "invite_token" in result) {
        setInviteToken(result.invite_token ?? "");
        setEmail("");
      }
      refresh();
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result, "The approved invitation change was refused.",
      ));
    },
  });

  function refresh() {
    finalizer.invalidate();
    void client.adminInvitations()
      .then((result) => {
        setInvitations(result.invitations ?? []);
        if (!result.invitations) setMessage(result.reason ?? "Invitation access denied.");
      })
      .catch(() => setMessage("Invitations are unavailable."));
  }

  useEffect(refresh, []);

  async function invite() {
    try {
      const intendedScope = JSON.parse(scope) as unknown;
      if (!intendedScope || Array.isArray(intendedScope) || typeof intendedScope !== "object") {
        throw new Error("Invitation scope must be a JSON object.");
      }
      const input: InvitationMutation = {
        kind: "create",
        body: invitationDraft({
          email,
          role,
          scope: intendedScope as Record<string, unknown>,
          ttlDays,
          workspaceId,
          provisionWorkspace,
          provisionOrg,
          currentRole,
        }),
        success: "Invitation created.",
      };
      const result = await client.createInvitation(input.body);
      if (finalizer.begin(input, result, "Invitation creation")) {
        setMessage("Pending approval. Continue in the originating chat.");
        return;
      }
      setMessage(responseMessage(result, input.success));
      if (result.status === "ok") {
        setInviteToken(result.invite_token ?? "");
        setEmail("");
        refresh();
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Invitation settings are invalid.");
    }
  }

  async function revoke(id: string) {
    if (armedId !== id) {
      finalizer.invalidate();
      setArmedId(id);
      return;
    }
    const input: InvitationMutation = {
      kind: "revoke",
      invitationId: id,
      success: "Invitation revoked.",
    };
    const result = await client.revokeInvitation(id);
    if (finalizer.begin(input, result, "Invitation revocation")) {
      setMessage("Pending approval. Continue in the originating chat.");
      setArmedId(null);
      return;
    }
    setMessage(responseMessage(result, input.success));
    setArmedId(null);
    if (result.status === "ok") refresh();
  }

  async function copyInvitationLink() {
    const link = `${window.location.origin}${window.location.pathname}#/accept-invite?token=${encodeURIComponent(inviteToken)}`;
    setMessage(await copySensitiveText(link)
      ? "Invitation link copied to the clipboard."
      : "The invitation link could not be copied. Select and copy the one-time token manually before dismissing it.");
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">Invitations</p>
      <h2>Invite-only access</h2>
      <div className="inline-actions">
        <input
          className="field-control"
          aria-label="Invitation email"
          type="email"
          value={email}
          onChange={(event) => {
            finalizer.invalidate();
            setEmail(event.target.value);
          }}
        />
        <select
          className="field-control compact"
          aria-label="Invitation role"
          value={role}
          onChange={(event) => {
            finalizer.invalidate();
            setRole(event.target.value);
          }}
        >
          {grantableRoles(currentRole).map((value) => (
            <option value={value} key={value}>{value}</option>
          ))}
        </select>
        <label>
          <span className="muted small">Expires in days</span>
          <input className="field-control compact" aria-label="Invitation expiry days" type="number" min={1} value={ttlDays} onChange={(event) => {
            finalizer.invalidate();
            setTtlDays(event.target.value);
          }} />
        </label>
        <button className="primary-button" disabled={!email.trim()} onClick={() => void invite()}>
          Invite
        </button>
      </div>
      <div className="author-grid">
        <label><span>Scope (JSON object)</span><textarea className="field-control code-field" aria-label="Invitation scope" rows={4} value={scope} onChange={(event) => {
          finalizer.invalidate();
          setScope(event.target.value);
        }} /></label>
        <label><span>Existing workspace id (optional)</span><input className="field-control" value={workspaceId} onChange={(event) => {
          finalizer.invalidate();
          setWorkspaceId(event.target.value);
        }} /></label>
        <label><span>Provision workspace on acceptance (optional)</span><input className="field-control" value={provisionWorkspace} onChange={(event) => {
          finalizer.invalidate();
          setProvisionWorkspace(event.target.value);
        }} /></label>
        {currentRole === "superadmin" && <label><span>Provision organisation on acceptance (owner only)</span><input className="field-control" value={provisionOrg} onChange={(event) => {
          finalizer.invalidate();
          setProvisionOrg(event.target.value);
        }} /></label>}
      </div>
      {inviteToken && (
        <div className="secret-once" role="status">
          <strong>Invitation token — shown once</strong>
          <code>{inviteToken}</code>
          <button className="secondary-button" onClick={() => void copyInvitationLink()}>Copy invitation link</button>
          <button className="secondary-button" onClick={() => setInviteToken("")}>Dismiss</button>
        </div>
      )}
      <div className="data-list" aria-label="Invitations">
        {invitations.map((invitation) => (
          <div className="data-row static" key={invitation.id}>
            <span className={`activity-dot ${invitation.status}`} />
            <span className="data-row-copy">
              <strong>{invitation.email}</strong>
              <small>{invitation.intended_role} · {invitation.status} · expires {invitation.expires_at ? new Date(invitation.expires_at).toLocaleDateString() : "by server policy"}{invitation.workspace_id ? ` · workspace ${invitation.workspace_id}` : ""}{invitation.provision_workspace_name ? ` · creates ${invitation.provision_workspace_name}` : ""}</small>
            </span>
            {invitation.status === "pending" && (
              <button
                className={armedId === invitation.id ? "danger-button armed" : "danger-button"}
                onClick={() => void revoke(invitation.id)}
              >
                {armedId === invitation.id ? "Confirm revoke" : "Revoke"}
              </button>
            )}
          </div>
        ))}
      </div>
      <ExactApprovalFinalizer controller={finalizer} />
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

function grantableRoles(currentRole: string): string[] {
  const roles = [
    "superadmin",
    "admin",
    "org-admin",
    "department-head",
    "manager",
    "engineer",
    "member",
    "agent",
    "viewer",
  ];
  const index = roles.indexOf(currentRole);
  return index < 0 ? ["member", "agent", "viewer"] : roles.slice(index);
}

function responseMessage(result: { status?: string; reason?: string }, success: string): string {
  if (result.status === "ok") return success;
  if (result.status === "pending_human") return "Pending approval. Continue in the originating chat.";
  return result.reason ?? result.status ?? "Unexpected server response.";
}

function invitationDraft({
  email,
  role,
  scope,
  ttlDays,
  workspaceId,
  provisionWorkspace,
  provisionOrg,
  currentRole,
}: {
  email: string;
  role: string;
  scope: Record<string, unknown>;
  ttlDays: string;
  workspaceId: string;
  provisionWorkspace: string;
  provisionOrg: string;
  currentRole: string;
}): CreateInvitationRequest {
  return {
    email: email.trim(),
    role,
    scope,
    ttl_days: Math.max(1, Number.parseInt(ttlDays, 10) || 14),
    workspace_id: workspaceId.trim() || undefined,
    provision_workspace_name: provisionWorkspace.trim() || undefined,
    provision_org_name: currentRole === "superadmin"
      ? provisionOrg.trim() || undefined
      : undefined,
  };
}

function routeInputEquals(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
