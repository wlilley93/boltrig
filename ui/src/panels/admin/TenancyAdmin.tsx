// The tenancy-management surface of the admin console (COUNTY 8): organisation
// policy, workspaces + their members, and per-org/workspace/user AI keys. It
// lives inside AdminPanel (a view toggle) rather than as a parallel settings
// system - the admin console is the one home for org-level administration.
//
// Every call goes through the governed REST surface (boltrig/kernel/access_
// routes.py) with tolerateStatus, so a server denial (403) renders faithfully
// as a notice; the server stays the real gate. Destructive actions arm with
// ArmConfirm; the AI key is accepted once (a password field cleared on submit)
// and is never shown again (only has_key is ever read back).

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import type {
  AiKeyLevel,
  OrgMemberView,
  WorkspaceMemberView,
  WorkspaceView,
} from "../../api/types";
import { useIdentity } from "../../identity";
import { useFetch } from "../../useFetch";
import { errText } from "../shared";
import { EmptyState, Field, FetchError, InfoCallout, Select } from "../ux";
import type { Option } from "../ux";
import { Switch } from "../uxForm";
import { ArmConfirm, SaveBar, Skeleton } from "../uxFlow";

// The per-workspace roles (boltrig/models/tenancy.py WORKSPACE_ROLES). owner
// administers, admin configures, member operates, viewer reads, agent is a
// non-human seat.
const WORKSPACE_ROLE_OPTIONS: Option[] = [
  { value: "member", label: "member", hint: "Operates in the workspace." },
  { value: "viewer", label: "viewer", hint: "Read only." },
  { value: "admin", label: "admin", hint: "Configures the workspace." },
  { value: "owner", label: "owner", hint: "Administers the workspace." },
  { value: "agent", label: "agent", hint: "A non-human runtime seat." },
];

const AI_LEVEL_OPTIONS: Option[] = [
  { value: "org", label: "Organisation", hint: "One key for the whole org." },
  { value: "workspace", label: "Workspace", hint: "A key scoped to one workspace." },
  { value: "user", label: "User", hint: "Your own personal key." },
];

// --- Organisation policy ----------------------------------------------------

function OrgSettingsCard() {
  const org = useFetch(() => api.currentOrg(), []);
  const loaded = org.data?.organisation ?? null;

  const [name, setName] = useState("");
  const [allowOwnKeys, setAllowOwnKeys] = useState(false);
  const [require2fa, setRequire2fa] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  // Seed the form from the loaded org whenever it (re)loads.
  useEffect(() => {
    if (loaded) {
      setName(loaded.name);
      setAllowOwnKeys(loaded.allow_own_ai_keys);
      setRequire2fa(loaded.require_two_factor);
    }
  }, [loaded]);

  const dirty =
    !!loaded &&
    (name.trim() !== loaded.name ||
      allowOwnKeys !== loaded.allow_own_ai_keys ||
      require2fa !== loaded.require_two_factor);

  async function save() {
    if (!dirty || saving) return;
    setSaving(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.updateCurrentOrg({
        name: name.trim(),
        allow_own_ai_keys: allowOwnKeys,
        require_two_factor: require2fa,
      });
      if (res.status === "ok" && res.organisation) {
        setMsg("Saved.");
        org.reload();
      } else {
        setError(res.reason ?? "Update rejected.");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    if (loaded) {
      setName(loaded.name);
      setAllowOwnKeys(loaded.allow_own_ai_keys);
      setRequire2fa(loaded.require_two_factor);
    }
    setError(null);
    setMsg(null);
  }

  return (
    <div className="form">
      <div className="form__title">Organisation</div>
      <p className="ux-hint">
        Your organisation's display name and its org-wide policy flags. Only an
        org-admin may change these; a non-admin save is refused by the server.
      </p>
      {org.loading && !org.data && <Skeleton variant="rows" />}
      <FetchError error={org.error} status={org.errorStatus} onRetry={org.reload} />
      {loaded && (
        <>
          <Field label="Name" hint="The organisation's display name.">
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Switch
            checked={allowOwnKeys}
            onChange={setAllowOwnKeys}
            label="Allow member-owned AI keys"
            hint="When on, workspace and user AI keys are honoured. When off, only the org key is used."
          />
          <Switch
            checked={require2fa}
            onChange={setRequire2fa}
            label="Require two-factor authentication"
            hint="Signals that every member must complete a second factor to sign in."
          />
          {msg && <p className="ok">{msg}</p>}
          {error && <InfoCallout tone="warn">{error}</InfoCallout>}
          <SaveBar
            dirty={dirty}
            saving={saving}
            label={<>Unsaved changes to your organisation</>}
            saveLabel="Save"
            onSave={() => void save()}
            onDiscard={discard}
          />
        </>
      )}
    </div>
  );
}

// --- Workspace members ------------------------------------------------------

function WorkspaceRow({
  workspace,
  orgMembers,
  onChanged,
}: {
  workspace: WorkspaceView;
  orgMembers: OrgMemberView[];
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<WorkspaceMemberView[] | null>(null);
  const [denied, setDenied] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [addUser, setAddUser] = useState("");
  const [addRole, setAddRole] = useState("member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMembers = useCallback(async () => {
    setLoading(true);
    setDenied(null);
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

  // Org members not already in the workspace make the add-picker options.
  const memberIds = new Set((members ?? []).map((m) => m.user_id));
  const addOptions: Option[] = orgMembers
    .filter((m) => !memberIds.has(m.user_id))
    .map((m) => ({ value: m.user_id, label: m.user_id }));

  async function add() {
    if (!addUser || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.addWorkspaceMember(workspace.id, {
        user_id: addUser,
        role: addRole,
      });
      if (res.status === "ok") {
        setAddUser("");
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
        {workspace.status === "active" && (
          <ArmConfirm
            label="Archive"
            armLabel={
              <>
                Archive <code>{workspace.name}</code>? Members keep no active
                seat in it until it is reactivated.
              </>
            }
            confirmLabel="Confirm archive"
            tone="danger"
            busyLabel="Archiving..."
            onConfirm={async () => {
              const res = await api.updateWorkspace(workspace.id, {
                status: "archived",
              });
              if (res.status !== "ok") {
                throw new Error(res.reason ?? "Could not archive workspace.");
              }
              onChanged();
            }}
          />
        )}
      </div>

      {open && (
        <div className="dir-row__scope">
          {loading && <Skeleton variant="rows" />}
          {denied && <p className="notice warn">denied: {denied}</p>}
          {members && members.length === 0 && (
            <EmptyState title="No members yet" />
          )}
          {members?.map((m) => (
            <div className="row-line" key={m.user_id}>
              <div>
                <code>{m.user_id}</code>{" "}
                <span className="muted">as {m.role}</span>
              </div>
              <ArmConfirm
                label="Remove"
                armLabel={
                  <>
                    Remove <code>{m.user_id}</code> from{" "}
                    <code>{workspace.name}</code>?
                  </>
                }
                confirmLabel="Confirm remove"
                tone="danger"
                busyLabel="Removing..."
                onConfirm={() => remove(m.user_id)}
              />
            </div>
          ))}

          {members && (
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
          )}
          {error && <p className="error">{error}</p>}
        </div>
      )}
    </div>
  );
}

function WorkspacesCard() {
  const workspaces = useFetch(() => api.workspaces(), []);
  const orgMembers = useFetch(() => api.orgMembers(), []);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const list = workspaces.data?.workspaces ?? [];
  const members = orgMembers.data?.members ?? [];

  async function create() {
    if (!newName.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.createWorkspace({ name: newName.trim() });
      if (res.status === "ok") {
        setNewName("");
        workspaces.reload();
      } else {
        setError(res.reason ?? "Could not create workspace.");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

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
              value={newName}
              placeholder="e.g. Growth team"
              onChange={(e) => setNewName(e.target.value)}
            />
          </Field>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={busy || !newName.trim()}
              onClick={() => void create()}
            >
              {busy ? "Creating..." : "Create workspace"}
            </button>
          </div>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}

// --- AI keys ----------------------------------------------------------------

function AiKeysCard() {
  const identity = useIdentity();
  const keys = useFetch(() => api.aiKeys(), []);
  const allowOwn = keys.data?.allow_own_ai_keys ?? false;
  const rows = keys.data?.ai_keys ?? [];

  const [level, setLevel] = useState<AiKeyLevel>("org");
  const [scopeId, setScopeId] = useState("");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  // The default scope per level (matches the server): org -> tenant, user ->
  // the caller. A workspace key needs an explicit workspace id.
  const scopePlaceholder = useMemo(() => {
    if (level === "org") return identity.tenant;
    if (level === "user") return identity.subject;
    return "workspace id";
  }, [level, identity.tenant, identity.subject]);

  const needsExplicitScope = level === "workspace";
  const canSubmit =
    !!provider.trim() &&
    !!model.trim() &&
    !!apiKey.trim() &&
    (!needsExplicitScope || !!scopeId.trim()) &&
    !busy;

  async function save() {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.setAiKey({
        level,
        scope_id: scopeId.trim() || undefined,
        provider: provider.trim(),
        model: model.trim(),
        api_key: apiKey,
      });
      if (res.status === "ok") {
        setMsg(`Saved ${res.level} key for ${res.scope_id}.`);
        setApiKey(""); // the key is sealed server-side; never keep it in JS
        keys.reload();
      } else {
        setError(res.reason ?? "Could not save the key.");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(l: string, s: string) {
    const res = await api.deleteAiKey(l, s);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "Could not delete the key.");
    }
    keys.reload();
  }

  return (
    <div className="form">
      <div className="form__title">AI keys</div>
      <p className="ux-hint">
        Provider keys at the org, workspace or user level. A key is stored sealed
        and is never shown again - only whether one is set. Workspace and user
        keys are honoured only when the organisation allows member-owned keys.
      </p>
      {keys.loading && !keys.data && <Skeleton variant="rows" />}
      <FetchError error={keys.error} status={keys.errorStatus} onRetry={keys.reload} />

      {keys.data && rows.length === 0 && <EmptyState title="No AI keys set" />}
      {rows.map((k) => (
        <div className="row-line" key={`${k.level}-${k.scope_id}`}>
          <div>
            <span className="badge">{k.level}</span>{" "}
            <code>{k.scope_id}</code>{" "}
            <span className="muted">
              {k.provider} / {k.model}
            </span>{" "}
            {k.has_key ? (
              <span className="badge badge--ok">key set</span>
            ) : (
              <span className="badge">no key</span>
            )}
          </div>
          <ArmConfirm
            label="Delete"
            armLabel={
              <>
                Delete the <code>{k.level}</code> key for <code>{k.scope_id}</code>?
                The sealed credential is dropped.
              </>
            }
            confirmLabel="Confirm delete"
            tone="danger"
            busyLabel="Deleting..."
            onConfirm={() => remove(k.level, k.scope_id)}
          />
        </div>
      ))}

      {!allowOwn && (
        <InfoCallout tone="info">
          The organisation does not allow member-owned AI keys, so only an org
          key is honoured. An org-admin can change this in Organisation above.
        </InfoCallout>
      )}

      <div className="form__grid">
        <Field label="Level">
          <Select
            value={level}
            ariaLabel="AI key level"
            onChange={(v) => setLevel(v as AiKeyLevel)}
            options={AI_LEVEL_OPTIONS}
          />
        </Field>
        <Field
          label="Scope id"
          hint={
            needsExplicitScope
              ? "The workspace id this key applies to."
              : "Optional - defaults are shown."
          }
          example={scopePlaceholder}
        >
          <input
            value={scopeId}
            placeholder={scopePlaceholder}
            onChange={(e) => setScopeId(e.target.value)}
          />
        </Field>
        <Field label="Provider" example="openai">
          <input value={provider} onChange={(e) => setProvider(e.target.value)} />
        </Field>
        <Field label="Model" example="gpt-4o">
          <input value={model} onChange={(e) => setModel(e.target.value)} />
        </Field>
        <Field label="API key" hint="Entered once; stored sealed and never shown again.">
          <input
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </Field>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {error && <InfoCallout tone="warn">{error}</InfoCallout>}
      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={!canSubmit}
          onClick={() => void save()}
        >
          {busy ? "Saving..." : "Save key"}
        </button>
      </div>
    </div>
  );
}

export function TenancyAdmin() {
  return (
    <div className="stack">
      <p className="notice">
        Organisation policy, workspaces and their members, and AI keys. These are
        governed server-side: an action you are not permitted to take is refused
        with a reason, never silently.
      </p>
      <div className="cols">
        <div className="stack">
          <OrgSettingsCard />
          <AiKeysCard />
        </div>
        <WorkspacesCard />
      </div>
    </div>
  );
}
