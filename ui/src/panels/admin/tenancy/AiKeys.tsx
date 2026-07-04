import { useMemo, useState } from "react";

import { api } from "@/api/client";
import type { AiKeyLevel, AiKeyView } from "@/api/types";
import { useIdentity } from "@/identity";
import { useFetch } from "@/useFetch";
import { errText } from "@/panels/shared";
import { EmptyState, FetchError, Field, InfoCallout, Select } from "@/panels/ux";
import type { Option } from "@/panels/ux";
import { ArmConfirm, Skeleton } from "@/panels/uxFlow";

import { AI_LEVEL_OPTIONS, AI_MODEL_SUGGESTIONS, AI_PROVIDER_OPTIONS } from "./options";

function useAiKeyForm(
  identity: { tenant: string; subject: string },
  wsOptions: Option[],
  onSaved: () => void,
) {
  const [level, setLevel] = useState<AiKeyLevel>("org");
  const [scopeId, setScopeId] = useState("");
  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState(AI_MODEL_SUGGESTIONS.anthropic[0]);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const scopePlaceholder = useMemo(() => {
    if (level === "org") return identity.tenant;
    if (level === "user") return identity.subject;
    return "workspace id";
  }, [level, identity.tenant, identity.subject]);

  const needsExplicitScope = level === "workspace";
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
        onSaved();
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
    onSaved();
  }

  return {
    level, setLevel, scopeId, setScopeId, provider, setProvider, model, setModel,
    apiKey, setApiKey, busy, error, msg, scopePlaceholder, needsExplicitScope,
    effectiveScope, modelSuggestions, canSubmit, save, remove,
  };
}

function AiKeyRow({
  aiKey,
  onDelete,
}: {
  aiKey: AiKeyView;
  onDelete: (level: string, scopeId: string) => Promise<void>;
}) {
  async function remove() {
    await onDelete(aiKey.level, aiKey.scope_id);
  }

  return (
    <div className="row-line">
      <div>
        <span className="badge">{aiKey.level}</span>{" "}
        <code>{aiKey.scope_id}</code>{" "}
        <span className="muted">
          {aiKey.provider} / {aiKey.model}
        </span>{" "}
        {aiKey.has_key ? (
          <span className="badge badge--ok">key set</span>
        ) : (
          <span className="badge">no key</span>
        )}
      </div>
      <ArmConfirm
        label="Delete"
        armLabel={
          <>
            Delete the <code>{aiKey.level}</code> key for <code>{aiKey.scope_id}</code>?
            The sealed credential is dropped.
          </>
        }
        confirmLabel="Confirm delete"
        tone="danger"
        busyLabel="Deleting..."
        onConfirm={remove}
      />
    </div>
  );
}

function AiKeyModelField({
  provider,
  setProvider,
  model,
  setModel,
  modelSuggestions,
}: {
  provider: string;
  setProvider: (v: string) => void;
  model: string;
  setModel: (v: string) => void;
  modelSuggestions: string[];
}) {
  return (
    <>
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
    </>
  );
}

function AiKeyForm({
  form,
  wsOptions,
}: {
  form: ReturnType<typeof useAiKeyForm>;
  wsOptions: Option[];
}) {
  return (
    <>
      <div className="form__grid">
        <Field label="Level">
          <Select
            value={form.level}
            ariaLabel="AI key level"
            onChange={(v) => form.setLevel(v as AiKeyLevel)}
            options={AI_LEVEL_OPTIONS}
          />
        </Field>
        {form.needsExplicitScope ? (
          <Field label="Workspace" hint="The workspace this key applies to.">
            {wsOptions.length > 0 ? (
              <Select
                value={form.effectiveScope}
                ariaLabel="Workspace for this key"
                onChange={form.setScopeId}
                options={wsOptions}
              />
            ) : (
              <span className="muted">
                No workspaces yet. Create one under Workspaces, then set a workspace key.
              </span>
            )}
          </Field>
        ) : (
          <Field
            label="Applies to"
            hint={form.level === "org" ? "The whole organisation." : "You (your own user)."}
          >
            <span className="muted">
              <code>{form.scopePlaceholder}</code>
            </span>
          </Field>
        )}
        <AiKeyModelField
          provider={form.provider}
          setProvider={form.setProvider}
          model={form.model}
          setModel={form.setModel}
          modelSuggestions={form.modelSuggestions}
        />
        <Field label="API key" hint="Entered once; stored sealed and never shown again.">
          <input
            type="password"
            autoComplete="off"
            value={form.apiKey}
            onChange={(e) => form.setApiKey(e.target.value)}
          />
        </Field>
      </div>
      {form.msg && <p className="ok">{form.msg}</p>}
      {form.error && <InfoCallout tone="warn">{form.error}</InfoCallout>}
      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={!form.canSubmit}
          onClick={() => void form.save()}
        >
          {form.busy ? "Saving..." : "Save key"}
        </button>
      </div>
    </>
  );
}

export function AiKeysCard() {
  const identity = useIdentity();
  const keys = useFetch(() => api.aiKeys(), []);
  // The workspace list feeds the scope picker (never a raw id box) - the same
  // source WorkspacesCard reads.
  const workspaces = useFetch(() => api.workspaces(), []);
  const wsList = workspaces.data?.workspaces ?? [];
  const wsOptions: Option[] = wsList.map((w) => ({ value: w.id, label: w.name }));

  const allowOwn = keys.data?.allow_own_ai_keys ?? false;
  const rows = keys.data?.ai_keys ?? [];

  const form = useAiKeyForm(identity, wsOptions, () => keys.reload());

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
        <AiKeyRow
          key={`${k.level}-${k.scope_id}`}
          aiKey={k}
          onDelete={form.remove}
        />
      ))}

      {!allowOwn && (
        <InfoCallout tone="info">
          The organisation does not allow member-owned AI keys, so only an org key
          is honoured. An org-admin can change this in Organisation policy.
        </InfoCallout>
      )}

      <AiKeyForm form={form} wsOptions={wsOptions} />
    </div>
  );
}
