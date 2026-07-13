import { useState } from "react";

import { api } from "@/api/client";
import type { DirectoryUser, PatchUserRequest } from "@/api/types";
import { useFetch } from "@/useFetch";
import { EmptyState, FetchError, Field, ROLE_OPTIONS, Select } from "@/panels/ux";
import { ChipPicker, ScopeBuilder } from "@/panels/uxForm";
import type { ScopeVerb } from "@/panels/uxForm";
import {
  ArmConfirm,
  PendingHumanCard,
  Skeleton,
  useControlMutation,
} from "@/panels/uxFlow";
import { scopeReadable } from "@/panels/settings/shared";

import { asStringList, buildScopePatch, scopeToPatterns, toScopeVerbs } from "./scope";

function usePatchUser(user: DirectoryUser, onChanged: () => void) {
  const update = useControlMutation({
    verb: "control.user.update",
    onApplied: onChanged,
  });
  const deactivate = useControlMutation({
    verb: "control.user.deactivate",
    onApplied: onChanged,
  });

  async function patch(body: PatchUserRequest) {
    await update.invoke({ user_id: user.id, ...body });
  }

  async function deactivateUser() {
    await deactivate.invoke({ user_id: user.id });
  }

  return {
    busy:
      update.busy ||
      deactivate.busy ||
      update.pending !== null ||
      deactivate.pending !== null,
    error: update.error ?? deactivate.error,
    update,
    deactivate,
    patch,
    deactivateUser,
  };
}

function UserRoleControls({
  user,
  busy,
  onPatch,
  onDeactivate,
}: {
  user: DirectoryUser;
  busy: boolean;
  onPatch: (body: PatchUserRequest) => Promise<void>;
  onDeactivate: () => Promise<void>;
}) {
  const deactivated = user.status === "deactivated";

  return (
    <div className="kv">
      <Select
        value={user.role}
        disabled={busy}
        ariaLabel={`Role for ${user.email ?? user.id}`}
        onChange={(v) => void onPatch({ role: v })}
        options={ROLE_OPTIONS}
      />
      <span className={`badge ${deactivated ? "badge--down" : "badge--ok"}`}>
        {user.status}
      </span>
      {deactivated ? (
        <button
          className="btn"
          disabled={busy}
          onClick={() => void onPatch({ status: "active" })}
        >
          Activate
        </button>
      ) : (
        <ArmConfirm
          label="Deactivate"
          armLabel={
            <>
              Deactivate <code>{user.email ?? user.id}</code>? Their access stops
              immediately and their tokens stop resolving.
            </>
          }
          confirmLabel="Confirm deactivate"
          tone="danger"
          busyLabel="Deactivating..."
          disabled={busy}
          onConfirm={onDeactivate}
        />
      )}
    </div>
  );
}

function UserScopeEditor({
  user,
  busy,
  verbs,
  onPatch,
}: {
  user: DirectoryUser;
  busy: boolean;
  verbs: ScopeVerb[];
  onPatch: (body: PatchUserRequest) => Promise<void>;
}) {
  const original = user.scope ?? {};
  const [patterns, setPatterns] = useState<string[]>(() => scopeToPatterns(original));
  const [departments, setDepartments] = useState<string[]>(() =>
    asStringList(original.departments),
  );

  function saveScope() {
    onPatch({ scope: buildScopePatch(original, departments, patterns) });
  }

  return (
    <details className="dir-row__scope">
      <summary>Edit scope</summary>
      <Field label="Departments visible" hint="Scope this user to one or more departments.">
        <ChipPicker
          value={departments}
          onChange={setDepartments}
          allowFree
          ariaLabel={`Departments for ${user.email ?? user.id}`}
          emptyHint="No departments. Add one to scope this user to a department."
        />
      </Field>
      <Field label="Verb grants" hint="What this user may call.">
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
  );
}

export function UserRow({
  user,
  verbs,
  onChanged,
}: {
  user: DirectoryUser;
  verbs: ScopeVerb[];
  onChanged: () => void;
}) {
  const { busy, error, update, deactivate, patch, deactivateUser } =
    usePatchUser(user, onChanged);

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
        <UserRoleControls
          user={user}
          busy={busy}
          onPatch={patch}
          onDeactivate={deactivateUser}
        />
      </div>
      <UserScopeEditor user={user} busy={busy} verbs={verbs} onPatch={patch} />
      {update.pending && (
        <PendingHumanCard
          hitlRequestId={update.pending.id}
          noun="control"
          verb="control.user.update"
          sentParams={update.pending.params}
          onApplied={update.onPendingApplied}
          onDenied={update.onPendingDenied}
          onReset={update.resetPending}
        />
      )}
      {deactivate.pending && (
        <PendingHumanCard
          hitlRequestId={deactivate.pending.id}
          noun="control"
          verb="control.user.deactivate"
          sentParams={deactivate.pending.params}
          onApplied={deactivate.onPendingApplied}
          onDenied={deactivate.onPendingDenied}
          onReset={deactivate.resetPending}
        />
      )}
    </div>
  );
}

export function UserDirectoryCard() {
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
