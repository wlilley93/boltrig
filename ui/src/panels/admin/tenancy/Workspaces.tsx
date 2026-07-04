import { useCallback, useEffect, useState } from "react";

import { api } from "@/api/client";
import type { OrgMemberView, WorkspaceMemberView, WorkspaceView } from "@/api/types";
import { useFetch } from "@/useFetch";
import { errText } from "@/panels/shared";
import { EmptyState, FetchError, Field, Select } from "@/panels/ux";
import type { Option } from "@/panels/ux";
import { ArmConfirm, Skeleton } from "@/panels/uxFlow";

import { WORKSPACE_ROLE_OPTIONS } from "./options";

function useWorkspaceMembers(workspace: WorkspaceView, open: boolean) {
  const [members, setMembers] = useState<WorkspaceMemberView[] | null>(null);
  const [denied, setDenied] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMembers = useCallback(async () => {
    setLoading(true);
    setDenied(null);
    setError(null);
    try {
      const res = await api.workspaceMembers(workspace.id);
      if (res.members) {
        setMembers(res.members);
      } else {
        setMembers(null);
        setDenied(res.reason ?? "Not permitted.");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setLoading(false);
    }
  }, [workspace.id]);

  useEffect(() => {
    if (open && members === null && denied === null) void loadMembers();
  }, [open, members, denied, loadMembers]);

  return { members, denied, loading, error, loadMembers };
}

function useWorkspaceMutations(
  workspace: WorkspaceView,
  loadMembers: () => Promise<void>,
  onChanged: () => void,
) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add(userId: string, role: string) {
    if (!userId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.addWorkspaceMember(workspace.id, { user_id: userId, role });
      if (res.status === "ok") {
        await loadMembers();
        onChanged();
      } else {
        setError(res.reason ?? "Could not add member.");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(userId: string) {
    const res = await api.removeWorkspaceMember(workspace.id, userId);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "Could not remove member.");
    }
    await loadMembers();
  }

  async function archive() {
    const res = await api.updateWorkspace(workspace.id, { status: "archived" });
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "Could not archive workspace.");
    }
    onChanged();
  }

  return { busy, error, add, remove, archive };
}

function WorkspaceArchiveButton({
  workspace,
  onArchived,
}: {
  workspace: WorkspaceView;
  onArchived: () => Promise<void>;
}) {
  if (workspace.status !== "active") return null;

  return (
    <ArmConfirm
      label="Archive"
      armLabel={
        <>
          Archive <code>{workspace.name}</code>? Members keep no active seat in it
          until it is reactivated.
        </>
      }
      confirmLabel="Confirm archive"
      tone="danger"
      busyLabel="Archiving..."
      onConfirm={onArchived}
    />
  );
}

function WorkspaceMemberRow({
  member,
  workspace,
  onRemoved,
}: {
  member: WorkspaceMemberView;
  workspace: WorkspaceView;
  onRemoved: (userId: string) => Promise<void>;
}) {
  async function remove() {
    await onRemoved(member.user_id);
  }

  return (
    <div className="row-line">
      <div>
        <code>{member.user_id}</code>{" "}
        <span className="muted">as {member.role}</span>
      </div>
      <ArmConfirm
        label="Remove"
        armLabel={
          <>
            Remove <code>{member.user_id}</code> from <code>{workspace.name}</code>?
          </>
        }
        confirmLabel="Confirm remove"
        tone="danger"
        busyLabel="Removing..."
        onConfirm={remove}
      />
    </div>
  );
}

function WorkspaceAddMemberForm({
  orgMembers,
  members,
  busy,
  onAdd,
}: {
  orgMembers: OrgMemberView[];
  members: WorkspaceMemberView[];
  busy: boolean;
  onAdd: (userId: string, role: string) => Promise<void>;
}) {
  const [addUser, setAddUser] = useState("");
  const [addRole, setAddRole] = useState("member");

  const memberIds = new Set(members.map((m) => m.user_id));
  const addOptions: Option[] = orgMembers
    .filter((m) => !memberIds.has(m.user_id))
    .map((m) => ({ value: m.user_id, label: m.user_id }));

  async function add() {
    if (!addUser || busy) return;
    await onAdd(addUser, addRole);
  }

  return (
    <div className="form__grid">
      <Field label="Add member" hint="An existing org user.">
        {addOptions.length > 0 ? (
          <Select
            value={addUser || addOptions[0].value}
            ariaLabel="User to add"
            onChange={setAddUser}
            options={addOptions}
          />
        ) : (
          <span className="muted">Every org member is already in this workspace.</span>
        )}
      </Field>
      <Field label="Role">
        <Select
          value={addRole}
          ariaLabel="Workspace role"
          onChange={setAddRole}
          options={WORKSPACE_ROLE_OPTIONS}
        />
      </Field>
      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={busy || addOptions.length === 0}
          onClick={() => {
            if (!addUser && addOptions.length > 0) setAddUser(addOptions[0].value);
            void add();
          }}
        >
          {busy ? "Adding..." : "Add"}
        </button>
      </div>
    </div>
  );
}

export function WorkspaceRow({
  workspace,
  orgMembers,
  onChanged,
}: {
  workspace: WorkspaceView;
  orgMembers: OrgMemberView[];
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const { members, denied, loading, error: loadError, loadMembers } = useWorkspaceMembers(
    workspace,
    open,
  );
  const { busy, error: mutationError, add, remove, archive } = useWorkspaceMutations(
    workspace,
    loadMembers,
    onChanged,
  );
  const error = loadError ?? mutationError;

  return (
    <div className="dir-row">
      <div className="row-line dir-row__top">
        <div>
          <code>{workspace.name}</code>{" "}
          <span className="muted">{workspace.slug}</span>
          <div className="muted">
            {workspace.status}
            {" - "}
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setOpen((v) => !v)}
            >
              {open ? "Hide members" : "Manage members"}
            </button>
          </div>
        </div>
        <WorkspaceArchiveButton workspace={workspace} onArchived={archive} />
      </div>

      {open && (
        <div className="dir-row__scope">
          {loading && <Skeleton variant="rows" />}
          {denied && <p className="notice warn">denied: {denied}</p>}
          {members && members.length === 0 && <EmptyState title="No members yet" />}
          {members?.map((m) => (
            <WorkspaceMemberRow
              key={m.user_id}
              member={m}
              workspace={workspace}
              onRemoved={remove}
            />
          ))}
          {members && (
            <WorkspaceAddMemberForm
              orgMembers={orgMembers}
              members={members}
              busy={busy}
              onAdd={add}
            />
          )}
          {error && <p className="error">{error}</p>}
        </div>
      )}
    </div>
  );
}

function useWorkspaceCreate(onCreated: () => void) {
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    if (!newName.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.createWorkspace({ name: newName.trim() });
      if (res.status === "ok") {
        setNewName("");
        onCreated();
      } else {
        setError(res.reason ?? "Could not create workspace.");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return { newName, setNewName, busy, error, create };
}

export function WorkspacesCard() {
  const workspaces = useFetch(() => api.workspaces(), []);
  const orgMembers = useFetch(() => api.orgMembers(), []);
  const form = useWorkspaceCreate(() => workspaces.reload());

  const list = workspaces.data?.workspaces ?? [];
  const members = orgMembers.data?.members ?? [];

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Workspaces</h3>
        <button className="btn" onClick={() => workspaces.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {workspaces.loading && !workspaces.data && <Skeleton variant="rows" />}
        <FetchError
          error={workspaces.error}
          status={workspaces.errorStatus}
          onRetry={workspaces.reload}
        />
        {workspaces.data && list.length === 0 && (
          <EmptyState
            title="No workspaces"
            body="Create one below. You are seated as its owner so you can manage it at once."
          />
        )}
        {list.map((w) => (
          <WorkspaceRow
            key={w.id}
            workspace={w}
            orgMembers={members}
            onChanged={() => workspaces.reload()}
          />
        ))}

        <div className="form__grid">
          <Field label="New workspace" hint="Org-admin only. You become its owner.">
            <input
              value={form.newName}
              placeholder="e.g. Growth team"
              onChange={(e) => form.setNewName(e.target.value)}
            />
          </Field>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={form.busy || !form.newName.trim()}
              onClick={() => void form.create()}
            >
              {form.busy ? "Creating..." : "Create workspace"}
            </button>
          </div>
        </div>
        {form.error && <p className="error">{form.error}</p>}
      </div>
    </div>
  );
}
