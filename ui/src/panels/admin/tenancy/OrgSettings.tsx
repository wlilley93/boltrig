import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { OrganisationView } from "@/api/types";
import { useFetch } from "@/useFetch";
import { FetchError, Field, InfoCallout } from "@/panels/ux";
import { Switch } from "@/panels/uxForm";
import { SaveBar, Skeleton } from "@/panels/uxFlow";
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { useControlMutation } from "@/panels/uxFlow/useControlMutation";

function useOrgForm(org: OrganisationView | null, onSaved: () => void) {
  const [name, setName] = useState("");
  const [allowOwnKeys, setAllowOwnKeys] = useState(false);
  const [require2fa, setRequire2fa] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const mutation = useControlMutation({
    verb: "control.org.update",
    onApplied() {
      setMsg("Saved.");
      onSaved();
    },
  });

  useEffect(() => {
    if (org) {
      setName(org.name);
      setAllowOwnKeys(org.allow_own_ai_keys);
      setRequire2fa(org.require_two_factor);
    }
  }, [org]);

  const dirty =
    !!org &&
    (name.trim() !== org.name ||
      allowOwnKeys !== org.allow_own_ai_keys ||
      require2fa !== org.require_two_factor);

  async function save() {
    if (!dirty || mutation.busy || mutation.pending) return;
    setMsg(null);
    await mutation.invoke({
      name: name.trim(),
      allow_own_ai_keys: allowOwnKeys,
      require_two_factor: require2fa,
    });
  }

  function discard() {
    if (org) {
      setName(org.name);
      setAllowOwnKeys(org.allow_own_ai_keys);
      setRequire2fa(org.require_two_factor);
    }
    mutation.resetPending();
    setMsg(null);
  }

  return {
    name,
    setName,
    allowOwnKeys,
    setAllowOwnKeys,
    require2fa,
    setRequire2fa,
    mutation,
    msg,
    dirty,
    save,
    discard,
  };
}

export function OrgSettingsCard() {
  const org = useFetch(() => api.currentOrg(), []);
  const loaded = org.data?.organisation ?? null;
  const form = useOrgForm(loaded, () => org.reload());

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
            <input value={form.name} onChange={(e) => form.setName(e.target.value)} />
          </Field>
          <Switch
            checked={form.allowOwnKeys}
            onChange={form.setAllowOwnKeys}
            label="Allow member-owned AI keys"
            hint="When on, workspace and user AI keys are honoured. When off, only the org key is used."
          />
          <Switch
            checked={form.require2fa}
            onChange={form.setRequire2fa}
            label="Require two-factor authentication"
            hint="Signals that every member must complete a second factor to sign in."
          />
          {form.msg && <p className="ok">{form.msg}</p>}
          {form.mutation.error && <InfoCallout tone="warn">{form.mutation.error}</InfoCallout>}
          {form.mutation.pending && (
            <PendingHumanCard
              hitlRequestId={form.mutation.pending.id}
              noun="control"
              verb="control.org.update"
              sentParams={form.mutation.pending.params}
              onApplied={form.mutation.onPendingApplied}
              onDenied={form.mutation.onPendingDenied}
              onReset={form.mutation.resetPending}
            />
          )}
          <SaveBar
            dirty={form.dirty}
            saving={form.mutation.busy || form.mutation.pending !== null}
            label={<>Unsaved changes to your organisation</>}
            saveLabel="Save"
            onSave={() => void form.save()}
            onDiscard={form.discard}
          />
        </>
      )}
    </div>
  );
}
