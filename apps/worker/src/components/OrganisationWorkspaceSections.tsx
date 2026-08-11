import { useEffect, useRef, useState } from "react";
import type {
  AddWorkspaceMemberRequest,
  AddWorkspaceMemberResponse,
  CreateWorkspaceRequest,
  DeleteAck,
  GovernedRouteResponse,
  OrganisationView,
  UpdateOrgRequest,
  UpdateOrgResponse,
  UpdateWorkspaceRequest,
  WorkspaceMemberView,
  WorkspaceMutationResponse,
  WorkspaceView,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";

type WorkspaceCreateMutation = {
  body: CreateWorkspaceRequest;
  success: string;
};

type WorkspacePanelMutation =
  | {
    kind: "update";
    workspaceId: string;
    body: UpdateWorkspaceRequest;
    success: string;
  }
  | {
    kind: "member";
    workspaceId: string;
    body: AddWorkspaceMemberRequest;
    success: string;
    isNew: boolean;
  }
  | {
    kind: "remove";
    workspaceId: string;
    userId: string;
    success: string;
  };

export function OrganisationPolicy({
  organisation,
  canAdmin,
  onChanged,
}: {
  organisation: OrganisationView;
  canAdmin: boolean;
  onChanged(): void;
}) {
  const [name, setName] = useState(organisation.name);
  const [slug, setSlug] = useState(organisation.slug);
  const [settings, setSettings] = useState(JSON.stringify(organisation.settings ?? {}, null, 2));
  const [allowKeys, setAllowKeys] = useState(organisation.allow_own_ai_keys);
  const [requireTwoFactor, setRequireTwoFactor] = useState(organisation.require_two_factor);
  const [message, setMessage] = useState("");

  const finalizer = useExactApprovalFinalizer<
    UpdateOrgRequest,
    GovernedRouteResponse<UpdateOrgResponse>
  >({
    isCurrent: (input) => {
      try {
        return routeInputEquals(input, organisationDraft({
          name,
          slug,
          settings: JSON.parse(settings) as Record<string, unknown>,
          allowKeys,
          requireTwoFactor,
        }));
      } catch {
        return false;
      }
    },
    replay: (input, approvalId) => (
      client.updateCurrentOrg(input, approvalId)
    ),
    onApplied: () => {
      setMessage("Organisation policy saved.");
      onChanged();
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result, "The approved organisation policy was refused.",
      ));
    },
  });

  useEffect(() => {
    finalizer.invalidate();
    setName(organisation.name);
    setSlug(organisation.slug);
    setSettings(JSON.stringify(organisation.settings ?? {}, null, 2));
    setAllowKeys(organisation.allow_own_ai_keys);
    setRequireTwoFactor(organisation.require_two_factor);
  }, [organisation]);

  async function save() {
    try {
      const parsed = JSON.parse(settings) as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("Organisation settings must be a JSON object.");
      }
      const input = organisationDraft({
        name,
        slug,
        settings: parsed as Record<string, unknown>,
        allowKeys,
        requireTwoFactor,
      });
      const result = await client.updateCurrentOrg(input);
      if (finalizer.begin(input, result, "Organisation policy change")) {
        setMessage("Pending approval. Continue in the originating chat.");
        return;
      }
      setMessage(responseMessage(result, "Organisation policy saved."));
      if (result.status === "ok") onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Organisation settings must be valid JSON.");
    }
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">Organisation policy</p>
      <h2>{organisation.name}</h2>
      <p>{organisation.slug} · {organisation.id}</p>
      <label>
        <span className="muted small">Organisation name</span>
        <input
          className="field-control"
          aria-label="Organisation name"
          disabled={!canAdmin}
          value={name}
          onChange={(event) => {
            finalizer.invalidate();
            setName(event.target.value);
          }}
        />
      </label>
      <label>
        <span className="muted small">Organisation slug</span>
        <input
          className="field-control"
          aria-label="Organisation slug"
          disabled={!canAdmin}
          value={slug}
          onChange={(event) => {
            finalizer.invalidate();
            setSlug(event.target.value);
          }}
        />
      </label>
      <label>
        <span className="muted small">Organisation settings (JSON object)</span>
        <textarea
          className="field-control code-field"
          disabled={!canAdmin}
          rows={5}
          value={settings}
          onChange={(event) => {
            finalizer.invalidate();
            setSettings(event.target.value);
          }}
        />
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          disabled={!canAdmin}
          checked={allowKeys}
          onChange={(event) => {
            finalizer.invalidate();
            setAllowKeys(event.target.checked);
          }}
        />
        Members may configure their own AI keys
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          disabled={!canAdmin}
          checked={requireTwoFactor}
          onChange={(event) => {
            finalizer.invalidate();
            setRequireTwoFactor(event.target.checked);
          }}
        />
        Require two-factor authentication
      </label>
      {canAdmin ? (
        <button className="primary-button" onClick={() => void save()}>Save policy</button>
      ) : (
        <p className="muted">Organisation administration is restricted by your server role.</p>
      )}
      <ExactApprovalFinalizer controller={finalizer} />
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

export function WorkspaceAdministration({
  currentUser,
  canAdmin,
}: {
  currentUser: string;
  canAdmin: boolean;
}) {
  const [workspaces, setWorkspaces] = useState<WorkspaceView[]>([]);
  const [selected, setSelected] = useState<WorkspaceView | null>(null);
  const [members, setMembers] = useState<WorkspaceMemberView[]>([]);
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const memberSequence = useRef(0);

  const finalizer = useExactApprovalFinalizer<
    WorkspaceCreateMutation,
    GovernedRouteResponse<WorkspaceMutationResponse>
  >({
    isCurrent: (input) => input.body.name === name.trim(),
    replay: (input, approvalId) => (
      client.createWorkspace(input.body, approvalId)
    ),
    onApplied: () => {
      setMessage("Workspace created.");
      setName("");
      refresh();
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result, "The approved workspace creation was refused.",
      ));
    },
  });

  function refresh() {
    finalizer.invalidate();
    void client.workspaces()
      .then((result) => {
        setWorkspaces(result.workspaces);
        setSelected((current) => (
          result.workspaces.find((item) => item.id === current?.id)
          ?? result.workspaces[0]
          ?? null
        ));
      })
      .catch(() => setMessage("Workspaces are unavailable."));
  }

  useEffect(refresh, []);
  useEffect(() => {
    if (!selected) {
      memberSequence.current += 1;
      setMembers([]);
      return;
    }
    const sequence = ++memberSequence.current;
    void client.workspaceMembers(selected.id)
      .then((result) => {
        if (memberSequence.current !== sequence) return;
        setMembers(result.members ?? []);
        if (!result.members) setMessage(result.reason ?? result.status ?? "Roster unavailable.");
      })
      .catch(() => {
        if (memberSequence.current !== sequence) return;
        setMembers([]);
        setMessage("The workspace roster is unavailable.");
      });
  }, [selected]);

  async function create() {
    const input: WorkspaceCreateMutation = {
      body: { name: name.trim() },
      success: "Workspace created.",
    };
    const result = await client.createWorkspace(input.body);
    if (finalizer.begin(input, result, "Workspace creation")) {
      setMessage("Pending approval. Continue in the originating chat.");
      return;
    }
    setMessage(responseMessage(result, "Workspace created."));
    if (result.status === "ok") {
      setName("");
      refresh();
    }
  }

  const ownMembership = members.find((member) => member.user_id === currentUser);
  const canManage = canAdmin || ["owner", "admin"].includes(ownMembership?.role ?? "");

  return (
    <section className="settings-card">
      <p className="eyebrow">Workspaces</p>
      <h2>Membership-scoped workspaces</h2>
      {canAdmin && (
        <div className="inline-actions">
          <input
            className="field-control"
            aria-label="New workspace name"
            placeholder="New workspace"
            value={name}
            onChange={(event) => {
              finalizer.invalidate();
              setName(event.target.value);
            }}
          />
          <button
            className="primary-button"
            disabled={!name.trim()}
            onClick={() => void create()}
          >
            Create
          </button>
        </div>
      )}
      <div className="data-list" aria-label="Workspaces">
        {workspaces.map((workspace) => (
          <button
            className={selected?.id === workspace.id ? "data-row selected" : "data-row"}
            key={workspace.id}
            onClick={() => {
              finalizer.invalidate();
              setSelected(workspace);
            }}
          >
            <span className={`activity-dot ${workspace.status}`} />
            <span className="data-row-copy">
              <strong>{workspace.name}</strong>
              <small>{workspace.slug}</small>
            </span>
            <span className="row-meta">{workspace.status}</span>
          </button>
        ))}
      </div>
      {selected && (
        <WorkspaceMemberPanel
          workspace={selected}
          members={members}
          canManage={canManage}
          onChanged={() => setSelected({ ...selected })}
          onWorkspaceChanged={refresh}
          onMessage={setMessage}
        />
      )}
      <ExactApprovalFinalizer controller={finalizer} />
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

function WorkspaceMemberPanel({
  workspace,
  members,
  canManage,
  onChanged,
  onWorkspaceChanged,
  onMessage,
}: {
  workspace: WorkspaceView;
  members: WorkspaceMemberView[];
  canManage: boolean;
  onChanged(): void;
  onWorkspaceChanged(): void;
  onMessage(message: string): void;
}) {
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("member");
  const [armedId, setArmedId] = useState<string | null>(null);
  const [archiveArmed, setArchiveArmed] = useState(false);
  const [workspaceName, setWorkspaceName] = useState(workspace.name);
  const [settings, setSettings] = useState(JSON.stringify(workspace.settings ?? {}, null, 2));

  const finalizer = useExactApprovalFinalizer<
    WorkspacePanelMutation,
    GovernedRouteResponse<
      WorkspaceMutationResponse | AddWorkspaceMemberResponse | DeleteAck
    >
  >({
    isCurrent: (input) => {
      if (input.workspaceId !== workspace.id) return false;
      if (input.kind === "remove") {
        return members.some((item) => item.user_id === input.userId);
      }
      if (input.kind === "member") {
        if (input.isNew) {
          return input.body.user_id === userId.trim()
            && input.body.role === role;
        }
        return members.some((item) => item.user_id === input.body.user_id);
      }
      if (input.body.status) {
        return input.body.status !== workspace.status;
      }
      try {
        return routeInputEquals(input.body, {
          name: workspaceName.trim(),
          settings: JSON.parse(settings) as Record<string, unknown>,
        });
      } catch {
        return false;
      }
    },
    replay: (input, approvalId) => {
      if (input.kind === "remove") {
        return client.removeWorkspaceMember(
          input.workspaceId, input.userId, approvalId,
        );
      }
      if (input.kind === "member") {
        return client.addWorkspaceMember(
          input.workspaceId, input.body, approvalId,
        );
      }
      return client.updateWorkspace(
        input.workspaceId, input.body, approvalId,
      );
    },
    onApplied: async (_result, input) => {
      onMessage(input.success);
      if (input.kind === "update") {
        onWorkspaceChanged();
      } else {
        if (input.kind === "member" && input.isNew) setUserId("");
        onChanged();
      }
    },
    onRefused: (result) => {
      onMessage(governedResultReason(
        result, "The approved workspace change was refused.",
      ));
    },
  });

  useEffect(() => {
    finalizer.invalidate();
    setWorkspaceName(workspace.name);
    setSettings(JSON.stringify(workspace.settings ?? {}, null, 2));
  }, [workspace]);

  async function add() {
    const input: WorkspacePanelMutation = {
      kind: "member",
      workspaceId: workspace.id,
      body: { user_id: userId.trim(), role },
      success: "Workspace member added.",
      isNew: true,
    };
    const result = await client.addWorkspaceMember(workspace.id, input.body);
    if (finalizer.begin(input, result, "Workspace member addition")) {
      onMessage("Pending approval. Continue in the originating chat.");
      return;
    }
    onMessage(responseMessage(result, input.success));
    if (result.status === "ok") {
      setUserId("");
      onChanged();
    }
  }

  async function remove(memberId: string) {
    if (armedId !== memberId) {
      finalizer.invalidate();
      setArmedId(memberId);
      return;
    }
    const input: WorkspacePanelMutation = {
      kind: "remove",
      workspaceId: workspace.id,
      userId: memberId,
      success: "Workspace member removed.",
    };
    const result = await client.removeWorkspaceMember(workspace.id, memberId);
    if (finalizer.begin(input, result, "Workspace member removal")) {
      onMessage("Pending approval. Continue in the originating chat.");
      setArmedId(null);
      return;
    }
    onMessage(responseMessage(result, input.success));
    setArmedId(null);
    if (result.status === "ok") onChanged();
  }

  async function archive() {
    if (!archiveArmed) {
      finalizer.invalidate();
      setArchiveArmed(true);
      return;
    }
    await updateWorkspaceStatus("archived", "Workspace archived.");
    setArchiveArmed(false);
  }

  async function reactivate() {
    await updateWorkspaceStatus("active", "Workspace reactivated.");
  }

  async function updateWorkspaceStatus(
    status: "active" | "archived",
    success: string,
  ) {
    const input: WorkspacePanelMutation = {
      kind: "update",
      workspaceId: workspace.id,
      body: { status },
      success,
    };
    const result = await client.updateWorkspace(workspace.id, input.body);
    if (finalizer.begin(input, result, "Workspace status change")) {
      onMessage("Pending approval. Continue in the originating chat.");
      return;
    }
    onMessage(responseMessage(result, success));
    if (result.status === "ok") onWorkspaceChanged();
  }

  async function saveWorkspace() {
    try {
      const parsed = JSON.parse(settings) as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("Workspace settings must be a JSON object.");
      }
      const input: WorkspacePanelMutation = {
        kind: "update",
        workspaceId: workspace.id,
        body: {
          name: workspaceName.trim(),
          settings: parsed as Record<string, unknown>,
        },
        success: "Workspace details saved.",
      };
      const result = await client.updateWorkspace(workspace.id, input.body);
      if (finalizer.begin(input, result, "Workspace detail change")) {
        onMessage("Pending approval. Continue in the originating chat.");
        return;
      }
      onMessage(responseMessage(result, input.success));
      if (result.status === "ok") onWorkspaceChanged();
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "Workspace settings must be valid JSON.");
    }
  }

  async function saveExistingMember(
    body: AddWorkspaceMemberRequest,
  ) {
    const input: WorkspacePanelMutation = {
      kind: "member",
      workspaceId: workspace.id,
      body,
      success: "Workspace membership updated.",
      isNew: false,
    };
    const result = await client.addWorkspaceMember(workspace.id, body);
    if (finalizer.begin(input, result, "Workspace membership change")) {
      onMessage("Pending approval. Continue in the originating chat.");
      return;
    }
    onMessage(responseMessage(result, input.success));
    if (result.status === "ok") onChanged();
  }

  return (
    <div className="detail-section">
      <p className="eyebrow">{workspace.name} members</p>
      {canManage && (
        <div className="author-form">
          <label><span>Workspace name</span><input className="field-control" value={workspaceName} onChange={(event) => {
            finalizer.invalidate();
            setWorkspaceName(event.target.value);
          }} /></label>
          <label><span>Workspace settings (JSON object)</span><textarea className="field-control code-field" rows={5} value={settings} onChange={(event) => {
            finalizer.invalidate();
            setSettings(event.target.value);
          }} /></label>
          <button className="secondary-button" disabled={!workspaceName.trim()} onClick={() => void saveWorkspace()}>Save workspace details</button>
        </div>
      )}
      {members.map((member) => (
        <WorkspaceMemberRow
          key={member.user_id}
          member={member}
          canManage={canManage}
          armed={armedId === member.user_id}
          onRemove={() => void remove(member.user_id)}
          onMessage={onMessage}
          onSave={(body) => void saveExistingMember(body)}
          onInvalidate={finalizer.invalidate}
        />
      ))}
      {canManage && (
        <>
          <div className="inline-actions">
            <input
              className="field-control"
              aria-label="Workspace member user id"
              value={userId}
              onChange={(event) => {
                finalizer.invalidate();
                setUserId(event.target.value);
              }}
            />
            <select
              className="field-control compact"
              aria-label="Workspace member role"
              value={role}
              onChange={(event) => {
                finalizer.invalidate();
                setRole(event.target.value);
              }}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
              <option value="owner">Owner</option>
            </select>
            <button className="secondary-button" disabled={!userId.trim()} onClick={() => void add()}>
              Add
            </button>
          </div>
          {workspace.status !== "archived" && (
            <button
              className={archiveArmed ? "danger-button armed" : "danger-button"}
              onClick={() => void archive()}
            >
              {archiveArmed ? "Confirm archive workspace" : "Archive workspace"}
            </button>
          )}
          {workspace.status === "archived" && (
            <button className="secondary-button" onClick={() => void reactivate()}>
              Reactivate workspace
            </button>
          )}
        </>
      )}
      <ExactApprovalFinalizer controller={finalizer} />
    </div>
  );
}

function WorkspaceMemberRow({
  member,
  canManage,
  armed,
  onRemove,
  onMessage,
  onSave,
  onInvalidate,
}: {
  member: WorkspaceMemberView;
  canManage: boolean;
  armed: boolean;
  onRemove(): void;
  onMessage(message: string): void;
  onSave(body: AddWorkspaceMemberRequest): void;
  onInvalidate(): void;
}) {
  const [role, setRole] = useState(member.role);
  const [permissions, setPermissions] = useState(JSON.stringify(member.permissions ?? {}, null, 2));

  useEffect(() => {
    setRole(member.role);
    setPermissions(JSON.stringify(member.permissions ?? {}, null, 2));
  }, [member]);

  async function save(nextRole = role) {
    try {
      const parsed = JSON.parse(permissions) as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("Member permissions must be a JSON object.");
      }
      onSave({
        user_id: member.user_id,
        role: nextRole,
        permissions: parsed as Record<string, unknown>,
      });
    } catch (error) {
      onMessage(error instanceof Error ? error.message : "Member permissions must be valid JSON.");
    }
  }

  return (
    <div className="data-row static editable-row">
      <span className="activity-dot done" />
      <span className="data-row-copy">
        <strong>{member.user_id}</strong>
        <small>{member.role}</small>
      </span>
      {canManage && (
        <>
          <select
            className="field-control compact"
            aria-label={`Workspace role for ${member.user_id}`}
            value={role}
            onChange={(event) => {
              const nextRole = event.target.value;
              onInvalidate();
              setRole(nextRole);
              void save(nextRole);
            }}
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
            <option value="owner">Owner</option>
          </select>
          <details className="row-editor">
            <summary>Permissions</summary>
            <textarea className="field-control code-field" aria-label={`Workspace permissions for ${member.user_id}`} rows={4} value={permissions} onChange={(event) => {
              onInvalidate();
              setPermissions(event.target.value);
            }} />
            <button className="secondary-button" onClick={() => void save()}>Save permissions</button>
          </details>
          <button
            className={armed ? "danger-button armed" : "danger-button"}
            onClick={onRemove}
          >
            {armed ? "Confirm remove" : "Remove"}
          </button>
        </>
      )}
    </div>
  );
}

function responseMessage(result: { status?: string; reason?: string }, success: string): string {
  if (result.status === "ok") return success;
  if (result.status === "pending_human") return "Pending approval. Continue in the originating chat.";
  return result.reason ?? result.status ?? "Unexpected server response.";
}

function organisationDraft({
  name,
  slug,
  settings,
  allowKeys,
  requireTwoFactor,
}: {
  name: string;
  slug: string;
  settings: Record<string, unknown>;
  allowKeys: boolean;
  requireTwoFactor: boolean;
}): UpdateOrgRequest {
  return {
    name: name.trim(),
    slug: slug.trim(),
    settings,
    allow_own_ai_keys: allowKeys,
    require_two_factor: requireTwoFactor,
  };
}

function routeInputEquals(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
