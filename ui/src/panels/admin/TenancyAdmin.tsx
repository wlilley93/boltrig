// The tenancy-management surface of the admin console (COUNTY 8): the SINGLE
// home for organisation administration - the member directory + their scope,
// invitations, org policy, workspaces + their members, and per-org/workspace/
// user AI keys. It lives inside AdminPanel (a view toggle) rather than as a
// parallel settings system; Settings > Organisation is now only a signpost here.
//
// Every call goes through the governed REST surface (boltrig/kernel/access_
// routes.py) with tolerateStatus, so a server denial (403) renders faithfully
// as a notice; the server stays the real gate. Destructive actions arm with
// ArmConfirm; the AI key is accepted once (a password field cleared on submit)
// and is never shown again (only has_key is ever read back).

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import type {
  AdminInvitation,
  AiKeyLevel,
  DirectoryUser,
  OrgMemberView,
  PatchUserRequest,
  VerbInfo,
  WorkspaceMemberView,
  WorkspaceView,
} from "../../api/types";
import { useIdentity } from "../../identity";
import { useFetch } from "../../useFetch";
import { errText } from "../shared";
import {
  EmptyState,
  Field,
  FetchError,
  InfoCallout,
  ROLE_OPTIONS,
  Select,
  TTL_OPTIONS,
  ttlDaysFromSelection,
} from "../ux";
import type { Option } from "../ux";
import { ChipPicker, ScopeBuilder, Switch } from "../uxForm";
import type { ScopeVerb } from "../uxForm";
import { ArmConfirm, SaveBar, Skeleton } from "../uxFlow";
import { scopeReadable } from "../settings/shared";

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

// A closed set of known providers (was free-text). The server accepts any, but a
// Select keeps the common ones honest and one-click.
const AI_PROVIDER_OPTIONS: Option[] = [
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
  { value: "hermes", label: "Hermes" },
  { value: "vllm", label: "vLLM" },
  { value: "ollama", label: "Ollama" },
];

// Per-provider example models: seed the model field with a sensible default and
// offer one-click suggestions, while still allowing a custom (self-hosted) id.
const AI_MODEL_SUGGESTIONS: Record<string, string[]> = {
  anthropic: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-4"],
  openai: ["gpt-4o", "gpt-4o-mini", "o3-mini"],
  hermes: ["glm-5-turbo", "glm-5"],
  vllm: ["meta-llama/Llama-3.1-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"],
  ollama: ["llama3.1", "qwen2.5", "mistral"],
};

// --- Member directory + scope (Epic USR) ------------------------------------

// A user's permission scope (manifest role-mapping shape): an all-access flag,
// visible departments, and the verb dimension expressed as noun/verb grants.
// ScopeBuilder owns the verb dimension as a flat pattern list; these helpers
// translate the dict <-> patterns while preserving departments and any keys the
// UI does not surface (fail-safe: an unknown scope key is never dropped).
const SCOPE_VERB_KEYS: ReadonlySet<string> = new Set(["all", "nouns", "verbs"]);

function asStringList(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)) : [];
}

function scopeToPatterns(scope: Record<string, unknown>): string[] {
  if (scope.all) return ["*"];
  const nouns = asStringList(scope.nouns).map((n) => `${n}.*`);
  return [...nouns, ...asStringList(scope.verbs)];
}

// The verb-dimension part of a scope dict, derived from the pattern list.
function patternsToScopeVerbPart(patterns: string[]): Record<string, unknown> {
  if (patterns.includes("*")) return { all: true };
  const nouns: string[] = [];
  const verbs: string[] = [];
  for (const p of patterns) {
    if (p === "*") continue;
    if (p.endsWith(".*")) nouns.push(p.slice(0, -2));
    else if (p.endsWith("*")) nouns.push(p.slice(0, -1));
    else verbs.push(p);
  }
  const part: Record<string, unknown> = {};
  if (nouns.length > 0) part.nouns = nouns;
  if (verbs.length > 0) part.verbs = verbs;
  return part;
}

// VerbInfo registry -> ScopeBuilder's verb shape (id + noun + consequence).
function toScopeVerbs(verbs: VerbInfo[]): ScopeVerb[] {
  return verbs.map((v) => ({
    id: v.id,
    noun: v.noun,
    consequence: typeof v.consequence === "string" ? v.consequence : undefined,
  }));
}

function UserRow({
  user,
  verbs,
  onChanged,
}: {
  user: DirectoryUser;
  verbs: ScopeVerb[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const original = user.scope ?? {};
  const [patterns, setPatterns] = useState<string[]>(() =>
    scopeToPatterns(original),
  );
  const [departments, setDepartments] = useState<string[]>(() =>
    asStringList(original.departments),
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
    // Preserve any scope keys the editor does not surface (never drop them), and
    // rewrite only the verb dimension + departments from the controls.
    const scope: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(original)) {
      if (k === "departments" || SCOPE_VERB_KEYS.has(k)) continue;
      scope[k] = v;
    }
    if (departments.length > 0) scope.departments = departments;
    Object.assign(scope, patternsToScopeVerbPart(patterns));
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
          <Select
            value={user.role}
            disabled={busy}
            ariaLabel={`Role for ${user.email ?? user.id}`}
            onChange={(v) => void patch({ role: v })}
            options={ROLE_OPTIONS}
          />
          <span
            className={`badge ${deactivated ? "badge--down" : "badge--ok"}`}
          >
            {user.status}
          </span>
          {deactivated ? (
            // Restorative and low-blast: a plain button, no arm step.
            <button
              className="btn"
              disabled={busy}
              onClick={() => void patch({ status: "active" })}
            >
              Activate
            </button>
          ) : (
            <ArmConfirm
              label="Deactivate"
              armLabel={
                <>
                  Deactivate <code>{user.email ?? user.id}</code>? Their access
                  stops immediately and their tokens stop resolving.
                </>
              }
              confirmLabel="Confirm deactivate"
              tone="danger"
              busyLabel="Deactivating..."
              disabled={busy}
              onConfirm={async () => {
                const res = await api.patchUser(user.id, {
                  status: "deactivated",
                });
                if (res.status !== "ok") {
                  throw new Error(res.reason ?? "update rejected");
                }
                onChanged();
              }}
            />
          )}
        </div>
      </div>
      <details className="dir-row__scope">
        <summary>Edit scope</summary>
        <Field
          label="Departments visible"
          hint="Scope this user to one or more departments."
        >
          <ChipPicker
            value={departments}
            onChange={setDepartments}
            allowFree
            ariaLabel={`Departments for ${user.email ?? user.id}`}
            emptyHint="No departments. Add one to scope this user to a department."
          />
        </Field>
        <Field
          label="Verb grants"
          hint="What this user may call."
        >
          <ScopeBuilder
            value={patterns}
            onChange={setPatterns}
            verbs={verbs}
            presets={[
              { label: "All (org-wide)", value: ["*"] },
              { label: "Clear", value: [] },
            ]}
          />
        </Field>
        <button className="btn" disabled={busy} onClick={saveScope}>
          {busy ? "..." : "Save scope"}
        </button>
      </details>
    </div>
  );
}

function UserDirectoryCard() {
  const users = useFetch(() => api.adminUsers(), []);
  // The caller-scoped verb registry powers the ScopeBuilder live preview; for an
  // org-admin this is the full registry. A read failure just yields an empty
  // list, so the scope editor still functions (patterns still edit cleanly).
  const caps = useFetch(() => api.capabilities(), []);
  const scopeVerbs = toScopeVerbs(caps.data?.verbs ?? []);

  // The server returns {status:"denied", reason} (no users key) when the caller
  // is not an org-admin.
  const usersDenied =
    users.data && users.data.users === undefined
      ? users.data.reason ?? "organisation administration not permitted"
      : null;
  const userList = users.data?.users ?? [];

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Member directory</h3>
        <button className="btn" onClick={() => users.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        <p className="ux-hint">
          Everyone in the organisation, their role and scope. Deactivating a user
          revokes their access immediately (US-USR-03).
        </p>
        {users.loading && !users.data && <Skeleton variant="rows" />}
        <FetchError
          error={users.error}
          status={users.errorStatus}
          onRetry={users.reload}
        />
        {usersDenied && <p className="notice warn">denied: {usersDenied}</p>}
        {!usersDenied && users.data && userList.length === 0 && (
          <EmptyState title="No users" />
        )}
        {userList.map((u) => (
          <UserRow
            key={u.id}
            user={u}
            verbs={scopeVerbs}
            onChanged={() => users.reload()}
          />
        ))}
      </div>
    </div>
  );
}

// --- Invitations (Epic USR) -------------------------------------------------

function InvitationsCard() {
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
      const res = await api.createInvitation({
        email: email.trim(),
        role,
        ttl_days: ttlDaysFromSelection(ttl),
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

  // Throws on a rejected revoke so the row's ArmConfirm renders the reason.
  async function revokeInvite(id: string) {
    const res = await api.revokeInvitation(id);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "revoke rejected");
    }
    invites.reload();
  }

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
        <div className="form__grid">
          <Field label="Email" required example="ada@example.com">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Role">
            <Select
              value={role}
              ariaLabel="Invited role"
              onChange={setRole}
              options={ROLE_OPTIONS}
            />
          </Field>
          <Field
            label="Expires in (days)"
            hint="How long the invitation stays open."
          >
            <Select
              value={ttl}
              ariaLabel="Invitation expiry"
              onChange={setTtl}
              options={TTL_OPTIONS}
            />
          </Field>
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
              <ArmConfirm
                label="Revoke"
                armLabel={
                  <>
                    Revoke the invitation for <code>{inv.email}</code>? They will
                    not be pre-staged when they sign in.
                  </>
                }
                confirmLabel="Confirm revoke"
                tone="danger"
                busyLabel="Revoking..."
                onConfirm={() => revokeInvite(inv.id)}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

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
      <div className="form__title">Organisation policy</div>
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
  // The workspace list feeds the scope picker (never a raw id box) - the same
  // source WorkspacesCard reads.
  const workspaces = useFetch(() => api.workspaces(), []);
  const wsList = workspaces.data?.workspaces ?? [];
  const wsOptions: Option[] = wsList.map((w) => ({ value: w.id, label: w.name }));

  const allowOwn = keys.data?.allow_own_ai_keys ?? false;
  const rows = keys.data?.ai_keys ?? [];

  const [level, setLevel] = useState<AiKeyLevel>("org");
  const [scopeId, setScopeId] = useState("");
  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState(AI_MODEL_SUGGESTIONS.anthropic[0]);
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
  // For a workspace key: the chosen workspace, falling back to the first one so a
  // one-click save still resolves. org/user keys take the server default.
  const effectiveScope = needsExplicitScope
    ? scopeId || wsOptions[0]?.value || ""
    : "";
  const modelSuggestions = AI_MODEL_SUGGESTIONS[provider] ?? [];
  const canSubmit =
    !!provider.trim() &&
    !!model.trim() &&
    !!apiKey.trim() &&
    (!needsExplicitScope || !!effectiveScope) &&
    !busy;

  async function save() {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.setAiKey({
        level,
        scope_id: needsExplicitScope ? effectiveScope : undefined,
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
          key is honoured. An org-admin can change this in Organisation policy.
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
        {needsExplicitScope ? (
          <Field label="Workspace" hint="The workspace this key applies to.">
            {wsOptions.length > 0 ? (
              <Select
                value={effectiveScope}
                ariaLabel="Workspace for this key"
                onChange={setScopeId}
                options={wsOptions}
              />
            ) : (
              <span className="muted">
                No workspaces yet. Create one under Workspaces, then set a
                workspace key.
              </span>
            )}
          </Field>
        ) : (
          <Field
            label="Applies to"
            hint={level === "org" ? "The whole organisation." : "You (your own user)."}
          >
            <span className="muted">
              <code>{scopePlaceholder}</code>
            </span>
          </Field>
        )}
        <Field label="Provider">
          <Select
            value={provider}
            ariaLabel="AI provider"
            onChange={(v) => {
              setProvider(v);
              setModel(AI_MODEL_SUGGESTIONS[v]?.[0] ?? "");
            }}
            options={AI_PROVIDER_OPTIONS}
          />
        </Field>
        <Field
          label="Model"
          example={modelSuggestions[0] ?? "model id"}
          hint="Pick a suggestion or type a custom model id."
        >
          <input value={model} onChange={(e) => setModel(e.target.value)} />
        </Field>
        {modelSuggestions.length > 0 && (
          <div className="kv">
            <span className="ux-hint">Suggestions:</span>
            {modelSuggestions.map((m) => (
              <button
                key={m}
                type="button"
                className="tag tag--accent"
                style={{ cursor: "pointer" }}
                onClick={() => setModel(m)}
              >
                {m}
              </button>
            ))}
          </div>
        )}
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
        The one home for organisation administration: members and their scope,
        invitations, org policy, workspaces, and AI keys. Every action is governed
        server-side - one you are not permitted to take is refused with a reason,
        never silently.
      </p>
      <UserDirectoryCard />
      <div className="cols">
        <div className="stack">
          <OrgSettingsCard />
          <InvitationsCard />
          <AiKeysCard />
        </div>
        <WorkspacesCard />
      </div>
    </div>
  );
}
