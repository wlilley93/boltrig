import { useEffect, useMemo, useState } from "react";
import type {
  AuthoredDefinitionLifecycleResponse,
  GovernedRouteResponse,
  NounAuthorView,
  SetBindingRequest,
  StatusAck,
  UpsertNounRequest,
  UpsertVerbRequest,
  VerbInventoryItem,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import { Unavailable } from "../Shell";
import { parseObject, resultMessage } from "./result";

type RegistryMutation =
  | {
    kind: "noun-upsert";
    body: UpsertNounRequest;
    selected: NounAuthorView | null;
  }
  | {
    kind: "noun-archive";
    selected: NounAuthorView;
  }
  | {
    kind: "noun-restore";
    selected: NounAuthorView;
  }
  | {
    kind: "verb-upsert";
    body: UpsertVerbRequest;
    selected: VerbInventoryItem | null;
  }
  | {
    kind: "verb-archive";
    selected: VerbInventoryItem;
  }
  | {
    kind: "verb-restore";
    selected: VerbInventoryItem;
  }
  | {
    kind: "binding-set";
    verbId: string;
    body: SetBindingRequest;
    selected: VerbInventoryItem;
  };

type RegistryMutationResult =
  | GovernedRouteResponse<StatusAck>
  | AuthoredDefinitionLifecycleResponse;

function sameRouteInput(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function RegistryBuild() {
  const [nouns, setNouns] = useState<NounAuthorView[]>([]);
  const [verbs, setVerbs] = useState<VerbInventoryItem[]>([]);
  const [filter, setFilter] = useState("");
  const [message, setMessage] = useState("");
  const [nounId, setNounId] = useState("");
  const [nounDescription, setNounDescription] = useState("");
  const [nounSchema, setNounSchema] = useState("{}");
  const [hydratedNoun, setHydratedNoun] = useState<string | null>(null);
  const [verbId, setVerbId] = useState("");
  const [verbNoun, setVerbNoun] = useState("");
  const [verbDescription, setVerbDescription] = useState("");
  const [consequence, setConsequence] = useState<"low" | "high">("low");
  const [inputSchema, setInputSchema] = useState("{}");
  const [outputSchema, setOutputSchema] = useState("{}");
  const [degradedMode, setDegradedMode] = useState("");
  const [identityMode, setIdentityMode] = useState<"service-principal" | "delegated">("service-principal");
  const [idempotencyMode, setIdempotencyMode] = useState<"cacheable" | "disabled">("cacheable");
  const [hydratedVerb, setHydratedVerb] = useState<string | null>(null);
  const [bindingVerb, setBindingVerb] = useState("");
  const [targetType, setTargetType] = useState<"adapter" | "agent">("adapter");
  const [targetRef, setTargetRef] = useState("");
  const [rateLimit, setRateLimit] = useState("");
  const [lifecycleBusy, setLifecycleBusy] = useState("");
  const [saving, setSaving] = useState(false);

  const hydratedNounRecord = nouns.find((noun) => noun.id === hydratedNoun);
  const hydratedVerbRecord = verbs.find((verb) => verb.id === hydratedVerb);

  function nounBody(): UpsertNounRequest {
    return {
      id: nounId.trim(),
      description: nounDescription.trim() || undefined,
      schema: parseObject(nounSchema, "Noun schema"),
    };
  }

  function verbBody(): UpsertVerbRequest {
    return {
      id: verbId.trim(),
      noun_id: verbNoun.trim(),
      input_schema: parseObject(inputSchema, "Input schema"),
      output_schema: parseObject(outputSchema, "Output schema"),
      description: verbDescription.trim(),
      consequence,
      degraded_mode: degradedMode.trim()
        ? parseObject(degradedMode, "Degraded mode")
        : undefined,
      identity_mode: identityMode,
      idempotency_mode: idempotencyMode,
    };
  }

  function bindingBody(): SetBindingRequest {
    return {
      target_type: targetType,
      target_ref: targetRef.trim(),
      rate_limit: rateLimit.trim()
        ? parseObject(rateLimit, "Rate limit") as SetBindingRequest["rate_limit"]
        : undefined,
    };
  }

  const finalizer = useExactApprovalFinalizer<
    RegistryMutation,
    RegistryMutationResult
  >({
    isCurrent: (input) => {
      try {
        if (input.kind === "noun-upsert") {
          return sameRouteInput(input.body, nounBody())
            && (input.selected?.id ?? null) === hydratedNoun
            && sameRouteInput(input.selected ?? null, hydratedNounRecord ?? null);
        }
        if (input.kind === "noun-archive" || input.kind === "noun-restore") {
          return input.selected.id === hydratedNoun
            && sameRouteInput(input.selected, hydratedNounRecord ?? null);
        }
        if (input.kind === "verb-upsert") {
          return sameRouteInput(input.body, verbBody())
            && (input.selected?.id ?? null) === hydratedVerb
            && sameRouteInput(input.selected ?? null, hydratedVerbRecord ?? null);
        }
        if (input.kind === "binding-set") {
          return input.verbId === bindingVerb.trim()
            && input.selected.id === hydratedVerb
            && sameRouteInput(input.body, bindingBody())
            && sameRouteInput(input.selected, hydratedVerbRecord ?? null);
        }
        return input.selected.id === hydratedVerb
          && sameRouteInput(input.selected, hydratedVerbRecord ?? null);
      } catch {
        return false;
      }
    },
    replay: (input, approvalId) => {
      if (input.kind === "noun-upsert") {
        return client.upsertNoun(input.body, approvalId);
      }
      if (input.kind === "noun-archive") {
        return client.archiveNoun(input.selected.id, approvalId);
      }
      if (input.kind === "noun-restore") {
        return client.restoreNoun(input.selected.id, approvalId);
      }
      if (input.kind === "verb-upsert") {
        return client.upsertVerb(input.body, approvalId);
      }
      if (input.kind === "verb-archive") {
        return client.archiveVerb(input.selected.id, approvalId);
      }
      if (input.kind === "verb-restore") {
        return client.restoreVerb(input.selected.id, approvalId);
      }
      return client.setBinding(input.verbId, input.body, approvalId);
    },
    onApplied: async (_result, input) => {
      await refresh(false);
      if (input.kind === "noun-upsert") {
        setMessage(`Noun ${input.body.id} saved.`);
      } else if (input.kind === "noun-archive" || input.kind === "noun-restore") {
        setMessage(
          `Noun ${input.selected.id} ${input.kind === "noun-archive" ? "archived" : "restored"} without deleting its verbs.`,
        );
      } else if (input.kind === "verb-upsert") {
        setMessage(`Verb ${input.body.id} saved.`);
      } else if (input.kind === "verb-archive" || input.kind === "verb-restore") {
        setMessage(
          `Verb ${input.selected.id} ${input.kind === "verb-archive" ? "archived" : "restored"} with its binding retained.`,
        );
      } else {
        setMessage(`Binding for ${input.verbId} saved.`);
      }
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result,
        "The approved registry change was refused.",
      ));
    },
    onUncertain: async () => {
      await refresh(false);
      setMessage(
        "Canonical registry state was refreshed; no definition change is inferred.",
      );
    },
  });

  async function refresh(invalidate = true) {
    if (invalidate) {
      finalizer.invalidate();
      setMessage("");
    }
    try {
      const [nounResult, verbResult] = await Promise.all([
        client.nouns(),
        client.verbs(),
      ]);
      setNouns(nounResult.nouns);
      setVerbs(verbResult.verbs);
      if (hydratedNoun) {
        if (nounResult.nouns.some((noun) => noun.id === hydratedNoun)) {
          const nounResult = await client.noun(hydratedNoun);
          setNounId(nounResult.noun.id);
          setNounDescription(nounResult.noun.description);
          setNounSchema(JSON.stringify(nounResult.noun.schema, null, 2));
          setHydratedNoun(nounResult.noun.id);
        } else {
          setHydratedNoun(null);
        }
      }
      if (hydratedVerb) {
        if (verbResult.verbs.some((verb) => verb.id === hydratedVerb)) {
          const verbResult = await client.verb(hydratedVerb);
          setVerbId(verbResult.verb.id);
          setVerbNoun(verbResult.verb.noun_id);
          setVerbDescription(verbResult.verb.description);
          setConsequence(verbResult.verb.consequence);
          setInputSchema(JSON.stringify(verbResult.verb.input_schema, null, 2));
          setOutputSchema(JSON.stringify(verbResult.verb.output_schema, null, 2));
          setDegradedMode(verbResult.verb.degraded_mode
            ? JSON.stringify(verbResult.verb.degraded_mode, null, 2)
            : "");
          setIdentityMode(verbResult.verb.identity_mode);
          setIdempotencyMode(verbResult.verb.idempotency_mode);
          setHydratedVerb(verbResult.verb.id);
          setBindingVerb(verbResult.verb.id);
          setTargetType(verbResult.binding?.target_type ?? "adapter");
          setTargetRef(verbResult.binding?.target_ref ?? "");
          setRateLimit(verbResult.binding?.rate_limit
            ? JSON.stringify(verbResult.binding.rate_limit, null, 2)
            : "");
        } else {
          setHydratedVerb(null);
        }
      }
    } catch {
      setMessage("The caller-scoped capability registry is unavailable.");
    }
  }
  useEffect(() => {
    void refresh(false);
  }, []);

  const visible = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return term
      ? verbs.filter((verb) => `${verb.id} ${verb.noun_id} ${verb.binding?.target_ref ?? ""}`.toLowerCase().includes(term))
      : verbs;
  }, [filter, verbs]);
  const visibleNouns = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return term
      ? nouns.filter((noun) => `${noun.id} ${noun.description}`.toLowerCase().includes(term))
      : nouns;
  }, [filter, nouns]);
  async function saveNoun(event: React.FormEvent) {
    event.preventDefault();
    if (nouns.some((noun) => noun.id === nounId.trim()) && hydratedNoun !== nounId.trim()) {
      setMessage("Load the complete existing noun before replacing it.");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const input: RegistryMutation = {
        kind: "noun-upsert",
        body: nounBody(),
        selected: hydratedNounRecord ?? null,
      };
      const result = await client.upsertNoun(input.body);
      if (finalizer.begin(input, result, "Noun definition change")) {
        setMessage("Noun change is waiting for human approval in Inbox.");
        return;
      }
      setMessage(resultMessage(result, `Noun ${nounId.trim()} saved.`));
      if (result.status === "ok") await refresh(false);
    } catch {
      setMessage("The noun was not changed. Check the identifier and your authoring grant.");
    } finally {
      setSaving(false);
    }
  }

  async function saveVerb(event: React.FormEvent) {
    event.preventDefault();
    if (verbs.some((verb) => verb.id === verbId.trim()) && hydratedVerb !== verbId.trim()) {
      setMessage("Load the complete existing verb before replacing it.");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const input: RegistryMutation = {
        kind: "verb-upsert",
        body: verbBody(),
        selected: hydratedVerbRecord ?? null,
      };
      const result = await client.upsertVerb(input.body);
      if (finalizer.begin(input, result, "Verb definition change")) {
        setMessage("Verb change is waiting for human approval in Inbox.");
        return;
      }
      setMessage(resultMessage(result, `Verb ${verbId.trim()} saved.`));
      if (result.status === "ok") await refresh(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The verb was not changed.");
    } finally {
      setSaving(false);
    }
  }

  async function saveBinding(event: React.FormEvent) {
    event.preventDefault();
    if (verbs.some((verb) => verb.id === bindingVerb.trim()) && hydratedVerb !== bindingVerb.trim()) {
      setMessage("Load the complete existing verb before replacing its binding.");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      if (!hydratedVerbRecord) {
        setMessage("Load the complete existing verb before replacing its binding.");
        return;
      }
      const input: RegistryMutation = {
        kind: "binding-set",
        verbId: bindingVerb.trim(),
        body: bindingBody(),
        selected: hydratedVerbRecord,
      };
      const result = await client.setBinding(input.verbId, input.body);
      if (finalizer.begin(input, result, "Verb binding change")) {
        setMessage("Binding change is waiting for human approval in Inbox.");
        return;
      }
      setMessage(resultMessage(result, `Binding for ${bindingVerb.trim()} saved.`));
      if (result.status === "ok") await refresh(false);
    } catch {
      setMessage("The binding was not changed. The target must already be registered.");
    } finally {
      setSaving(false);
    }
  }

  function editNoun(noun: NounAuthorView) {
    finalizer.invalidate();
    setMessage("");
    setNounId(noun.id);
    setNounDescription(noun.description);
    setNounSchema(JSON.stringify(noun.schema, null, 2));
    setHydratedNoun(noun.id);
  }

  async function edit(verb: VerbInventoryItem) {
    finalizer.invalidate();
    setMessage("");
    setHydratedNoun(null);
    setHydratedVerb(null);
    try {
      const [nounResult, verbResult] = await Promise.all([
        client.noun(verb.noun_id),
        client.verb(verb.id),
      ]);
      setNounId(nounResult.noun.id);
      setNounDescription(nounResult.noun.description);
      setNounSchema(JSON.stringify(nounResult.noun.schema, null, 2));
      setHydratedNoun(nounResult.noun.id);
      setVerbId(verbResult.verb.id);
      setVerbNoun(verbResult.verb.noun_id);
      setVerbDescription(verbResult.verb.description);
      setConsequence(verbResult.verb.consequence);
      setInputSchema(JSON.stringify(verbResult.verb.input_schema, null, 2));
      setOutputSchema(JSON.stringify(verbResult.verb.output_schema, null, 2));
      setDegradedMode(verbResult.verb.degraded_mode
        ? JSON.stringify(verbResult.verb.degraded_mode, null, 2)
        : "");
      setIdentityMode(verbResult.verb.identity_mode);
      setIdempotencyMode(verbResult.verb.idempotency_mode);
      setHydratedVerb(verbResult.verb.id);
      setBindingVerb(verbResult.verb.id);
      setTargetType(verbResult.binding?.target_type ?? "adapter");
      setTargetRef(verbResult.binding?.target_ref ?? "");
      setRateLimit(verbResult.binding?.rate_limit
        ? JSON.stringify(verbResult.binding.rate_limit, null, 2)
        : "");
    } catch {
      setMessage("The complete authoring records could not be loaded, so replacement is disabled.");
    }
  }

  async function changeNounLifecycle() {
    if (!hydratedNounRecord) return;
    const action = hydratedNounRecord.is_active ? "archive" : "restore";
    const input: RegistryMutation = {
      kind: action === "archive" ? "noun-archive" : "noun-restore",
      selected: hydratedNounRecord,
    };
    setLifecycleBusy(`noun:${hydratedNounRecord.id}`);
    setMessage("");
    try {
      const result = input.kind === "noun-archive"
        ? await client.archiveNoun(hydratedNounRecord.id)
        : await client.restoreNoun(hydratedNounRecord.id);
      if (finalizer.begin(input, result, `Noun ${action}`)) {
        setMessage(`Noun ${action} is waiting for human approval in Inbox.`);
        return;
      }
      setMessage(
        result.status === "ok"
          ? `Noun ${hydratedNounRecord.id} ${action}d without deleting its verbs.`
          : result.status === "pending_human"
            ? `Noun ${action} is waiting for human approval in Inbox.`
            : result.reason ?? `Noun ${action} was refused.`,
      );
      if (result.status === "ok") await refresh(false);
    } catch {
      setMessage("The noun lifecycle change was unavailable.");
    } finally {
      setLifecycleBusy("");
    }
  }

  async function changeVerbLifecycle() {
    if (!hydratedVerbRecord) return;
    const action = hydratedVerbRecord.is_active ? "archive" : "restore";
    const input: RegistryMutation = {
      kind: action === "archive" ? "verb-archive" : "verb-restore",
      selected: hydratedVerbRecord,
    };
    setLifecycleBusy(`verb:${hydratedVerbRecord.id}`);
    setMessage("");
    try {
      const result = input.kind === "verb-archive"
        ? await client.archiveVerb(hydratedVerbRecord.id)
        : await client.restoreVerb(hydratedVerbRecord.id);
      if (finalizer.begin(input, result, `Verb ${action}`)) {
        setMessage(`Verb ${action} is waiting for human approval in Inbox.`);
        return;
      }
      setMessage(
        result.status === "ok"
          ? `Verb ${hydratedVerbRecord.id} ${action}d with its binding retained.`
          : result.status === "pending_human"
            ? `Verb ${action} is waiting for human approval in Inbox.`
            : result.reason ?? `Verb ${action} was refused.`,
      );
      if (result.status === "ok") await refresh(false);
    } catch {
      setMessage("The verb lifecycle change was unavailable.");
    } finally {
      setLifecycleBusy("");
    }
  }

  function newRecords() {
    finalizer.invalidate();
    setNounId("");
    setNounDescription("");
    setNounSchema("{}");
    setHydratedNoun(null);
    setVerbId("");
    setVerbNoun("");
    setVerbDescription("");
    setConsequence("low");
    setInputSchema("{}");
    setOutputSchema("{}");
    setDegradedMode("");
    setIdentityMode("service-principal");
    setIdempotencyMode("cacheable");
    setHydratedVerb(null);
    setBindingVerb("");
    setTargetType("adapter");
    setTargetRef("");
    setRateLimit("");
  }

  return (
    <div className="build-layout">
      <section className="settings-card build-inventory">
        <div className="section-heading">
          <div><p className="eyebrow">Authored registry</p><h2>Active and archived definitions</h2></div>
          <div className="inline-actions"><button className="secondary-button" onClick={newRecords}>New</button><button className="secondary-button" onClick={() => void refresh()}>Refresh</button></div>
        </div>
        <input className="field-control" aria-label="Filter capabilities" placeholder="Filter noun, verb or binding…" value={filter} onChange={(event) => setFilter(event.target.value)} />
        {visibleNouns.length === 0 && visible.length === 0 ? <Unavailable title="No authored definitions">The registry has no noun or verb records.</Unavailable> : (
          <>
          <div className="data-list compact-list" role="region" aria-label="Authored nouns" tabIndex={0}>
            {visibleNouns.map((noun) => (
              <button className="data-row" key={noun.id} onClick={() => editNoun(noun)}>
                <span className={`activity-dot ${noun.is_active ? "ok" : "paused"}`} />
                <span className="data-row-copy"><strong>{noun.id}</strong><small>{noun.description || "Noun definition"}</small></span>
                <span className="row-meta">{noun.status}</span>
              </button>
            ))}
          </div>
          <div className="data-list compact-list" role="region" aria-label="Authored verbs" tabIndex={0}>
            {visible.map((verb) => (
              <button className="data-row" key={verb.id} onClick={() => void edit(verb)}>
                <span className={`activity-dot ${verb.is_active && verb.noun_status === "active" ? "ok" : "paused"}`} />
                <span className="data-row-copy"><strong>{verb.id}</strong><small>{verb.noun_id}{verb.noun_status === "archived" ? " (archived noun)" : ""} · {verb.binding ? `${verb.binding.target_type}:${verb.binding.target_ref}` : "unbound"}</small></span>
                <span className="row-meta">{verb.status} · {verb.consequence}</span>
              </button>
            ))}
          </div>
          </>
        )}
      </section>
      <div className="build-forms">
        {message && <p className="notice" role="status">{message}</p>}
        <ExactApprovalFinalizer controller={finalizer} />
        <form className="settings-card author-form" onSubmit={(event) => void saveNoun(event)}>
          <p className="eyebrow">Thing</p><h2>Define a noun</h2>
          <label><span>Identifier</span><input className="field-control" required disabled={Boolean(hydratedNoun)} value={nounId} onChange={(event) => { finalizer.invalidate(); setNounId(event.target.value); }} placeholder="ticket" /></label>
          <label><span>Description</span><input className="field-control" value={nounDescription} onChange={(event) => { finalizer.invalidate(); setNounDescription(event.target.value); }} /></label>
          <label><span>Schema</span><textarea className="field-control code-field" rows={4} value={nounSchema} onChange={(event) => { finalizer.invalidate(); setNounSchema(event.target.value); }} /></label>
          {hydratedNoun && <p className="muted small">Editing the complete server record for {hydratedNoun}.</p>}
          <div className="inline-actions">
            <button className="primary-button" disabled={saving || finalizer.busy}>Save noun</button>
            {hydratedNounRecord && hydratedNounRecord.id !== "control" && (
              <button
                className="secondary-button"
                type="button"
                disabled={lifecycleBusy !== "" || finalizer.busy}
                onClick={() => void changeNounLifecycle()}
              >
                {lifecycleBusy === `noun:${hydratedNounRecord.id}`
                  ? hydratedNounRecord.is_active ? "Archiving…" : "Restoring…"
                  : hydratedNounRecord.is_active ? "Archive noun" : "Restore noun"}
              </button>
            )}
          </div>
        </form>
        <form className="settings-card author-form" onSubmit={(event) => void saveVerb(event)}>
          <p className="eyebrow">Action</p><h2>Define a verb</h2>
          <div className="author-grid">
            <label><span>Verb identifier</span><input className="field-control" required disabled={Boolean(hydratedVerb)} value={verbId} onChange={(event) => { finalizer.invalidate(); setVerbId(event.target.value); }} placeholder="ticket.read" /></label>
            <label><span>Noun identifier</span><input className="field-control" required value={verbNoun} onChange={(event) => { finalizer.invalidate(); setVerbNoun(event.target.value); }} placeholder="ticket" /></label>
            <label><span>Consequence</span><select className="field-control" value={consequence} onChange={(event) => { finalizer.invalidate(); setConsequence(event.target.value as "low" | "high"); }}><option value="low">Low</option><option value="high">High</option></select></label>
            <label><span>Identity mode</span><select className="field-control" value={identityMode} onChange={(event) => { finalizer.invalidate(); setIdentityMode(event.target.value as typeof identityMode); }}><option value="service-principal">Service principal</option><option value="delegated">Delegated</option></select></label>
            <label><span>Idempotency</span><select className="field-control" value={idempotencyMode} onChange={(event) => { finalizer.invalidate(); setIdempotencyMode(event.target.value as typeof idempotencyMode); }}><option value="cacheable">Cacheable</option><option value="disabled">Disabled</option></select></label>
          </div>
          <label><span>Description</span><input className="field-control" value={verbDescription} onChange={(event) => { finalizer.invalidate(); setVerbDescription(event.target.value); }} /></label>
          <label><span>Input schema</span><textarea className="field-control code-field" rows={4} value={inputSchema} onChange={(event) => { finalizer.invalidate(); setInputSchema(event.target.value); }} /></label>
          <label><span>Output schema</span><textarea className="field-control code-field" rows={4} value={outputSchema} onChange={(event) => { finalizer.invalidate(); setOutputSchema(event.target.value); }} /></label>
          <label><span>Degraded mode (optional JSON object)</span><textarea className="field-control code-field" rows={4} value={degradedMode} onChange={(event) => { finalizer.invalidate(); setDegradedMode(event.target.value); }} /></label>
          {hydratedVerb && <p className="muted small">Editing the complete server record for {hydratedVerb}; saving replaces it atomically.</p>}
          <div className="inline-actions">
            <button className="primary-button" disabled={saving || finalizer.busy}>Save verb</button>
            {hydratedVerbRecord && !hydratedVerbRecord.id.startsWith("control.") && (
              <button
                className="secondary-button"
                type="button"
                disabled={lifecycleBusy !== "" || finalizer.busy}
                onClick={() => void changeVerbLifecycle()}
              >
                {lifecycleBusy === `verb:${hydratedVerbRecord.id}`
                  ? hydratedVerbRecord.is_active ? "Archiving…" : "Restoring…"
                  : hydratedVerbRecord.is_active ? "Archive verb" : "Restore verb"}
              </button>
            )}
          </div>
        </form>
        <form className="settings-card author-form" onSubmit={(event) => void saveBinding(event)}>
          <p className="eyebrow">Execution</p><h2>Bind a verb</h2>
          <div className="author-grid">
            <label><span>Verb identifier</span><input className="field-control" required disabled={Boolean(hydratedVerb)} value={bindingVerb} onChange={(event) => { finalizer.invalidate(); setBindingVerb(event.target.value); }} /></label>
            <label><span>Target type</span><select className="field-control" value={targetType} onChange={(event) => { finalizer.invalidate(); setTargetType(event.target.value as "adapter" | "agent"); }}><option value="adapter">Adapter</option><option value="agent">Agent</option></select></label>
            <label><span>Registered target</span><input className="field-control" required value={targetRef} onChange={(event) => { finalizer.invalidate(); setTargetRef(event.target.value); }} /></label>
          </div>
          <label><span>Rate limit (optional JSON object)</span><textarea className="field-control code-field" rows={4} value={rateLimit} onChange={(event) => { finalizer.invalidate(); setRateLimit(event.target.value); }} placeholder={'{"per":"minute","max":60,"scope":"tenant"}'} /></label>
          <button
            className="primary-button"
            disabled={saving || finalizer.busy || hydratedVerbRecord?.is_active === false || hydratedVerbRecord?.noun_status === "archived"}
          >
            Save binding
          </button>
          {(hydratedVerbRecord?.is_active === false || hydratedVerbRecord?.noun_status === "archived") && (
            <p className="muted small">Restore the verb and its noun before changing this binding.</p>
          )}
        </form>
      </div>
    </div>
  );
}
