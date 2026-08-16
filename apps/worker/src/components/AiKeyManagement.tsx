import { useEffect, useRef, useState } from "react";
import type {
  AiKeyLevel,
  AiKeyModality,
  AiKeyProposalStatus,
  AiKeyProposalView,
  AiKeyView,
  DeleteAiKeyResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";

interface DeleteAiKeyInput {
  level: AiKeyLevel;
  scopeId: string;
  modality: AiKeyModality;
}

const ACTIVE_PROPOSAL_STATES = new Set<AiKeyProposalStatus>([
  "pending",
  "approved",
  "unavailable",
]);

export function AiKeyManagement() {
  const [keys, setKeys] = useState<AiKeyView[]>([]);
  const [allowOwn, setAllowOwn] = useState(false);
  const [level, setLevel] = useState<AiKeyLevel>("user");
  const [scopeId, setScopeId] = useState("");
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [modality, setModality] = useState<AiKeyModality>("text");
  const [baseUrl, setBaseUrl] = useState("");
  const [proposal, setProposal] = useState<AiKeyProposalView | null>(null);
  const [proposalBusy, setProposalBusy] = useState(false);
  const [armed, setArmed] = useState("");
  const [message, setMessage] = useState("");
  // The write-only key is deliberately uncontrolled: plaintext exists only in
  // the password input and the synchronous SDK intake call, never React state.
  const apiKeyInput = useRef<HTMLInputElement>(null);

  const deleteFinalizer = useExactApprovalFinalizer<
    DeleteAiKeyInput,
    DeleteAiKeyResponse
  >({
    isCurrent: (input) => keys.some(
      (item) => item.level === input.level
        && item.scope_id === input.scopeId
        && (item.modality ?? "text") === input.modality,
    ),
    replay: (input, approvalId) => input.modality === "text"
      ? client.deleteAiKey(input.level, input.scopeId, approvalId)
      : client.deleteAiKey(input.level, input.scopeId, approvalId, input.modality),
    onApplied: async () => {
      setMessage("AI key reference removed.");
      await refresh(false);
    },
    onRefused: (result) => setMessage(governedResultReason(
      result,
      result.status ?? "Key removal was refused.",
    )),
  });

  async function refresh(invalidateDelete = true) {
    if (invalidateDelete) deleteFinalizer.invalidate();
    try {
      const [configured, staged] = await Promise.all([
        client.aiKeys(),
        client.aiKeyProposals(),
      ]);
      setKeys(configured.ai_keys ?? []);
      setAllowOwn(configured.allow_own_ai_keys);
      setProposal((staged.proposals ?? [])[0] ?? null);
    } catch {
      setMessage(
        "AI key configuration or sealed-proposal recovery is unavailable. No change is inferred.",
      );
      setProposal((current) => (
        current && ACTIVE_PROPOSAL_STATES.has(current.status)
          ? { ...current, status: "unavailable" }
          : current
      ));
    }
  }
  useEffect(() => {
    void refresh(false);
  }, []);

  function invalidateProposalForEdit() {
    if (!proposal || !ACTIVE_PROPOSAL_STATES.has(proposal.status)) return;
    const proposalId = proposal.id;
    setProposal({ ...proposal, status: "invalidated" });
    void client.invalidateAiKeyProposal(proposalId)
      .catch(() => {
        setProposal((current) => (
          current?.id === proposalId
            ? { ...current, status: "unavailable" }
            : current
        ));
        setMessage(
          "The staged-key invalidation could not be confirmed. Reload to recover its canonical state.",
        );
      });
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const input = apiKeyInput.current;
    if (!input?.value) return;
    setProposalBusy(true);
    setMessage("");
    // setAiKey serializes synchronously. Clear the DOM field before awaiting any
    // network result so plaintext is not retained by the component.
    const submission = client.setAiKey({
      level,
      scope_id: scopeId.trim() || undefined,
      provider: provider.trim(),
      model: model.trim(),
      ...(modality === "vision" ? { modality } : {}),
      base_url: baseUrl.trim() || undefined,
      api_key: input.value,
    });
    input.value = "";
    try {
      const result = await submission;
      if (result.status === "pending_human" && result.proposal) {
        setProposal(result.proposal);
        setMessage(
          "The key is envelope-sealed and waiting for approval. Worker no longer retains the entered value.",
        );
      } else if (result.status === "ok") {
        setProposal(null);
        setMessage("AI key sealed. Worker cannot retrieve or display it.");
        await refresh(false);
      } else {
        setMessage(result.reason ?? `Key proposal status: ${result.status}.`);
        await refresh(false);
      }
    } catch {
      setMessage(
        "The intake result is unavailable. The entered value was cleared; recovering any durable sealed proposal.",
      );
      await refresh(false);
    } finally {
      setProposalBusy(false);
    }
  }

  async function continueProposal() {
    if (!proposal || !ACTIVE_PROPOSAL_STATES.has(proposal.status)) return;
    setProposalBusy(true);
    try {
      const checked = await client.aiKeyProposal(proposal.id);
      if (checked.proposal) setProposal(checked.proposal);
      if (checked.status !== "approved") {
        if (checked.status === "unavailable" || checked.status === "error") {
          setProposal({ ...proposal, status: "unavailable" });
        }
        return;
      }
      const applied = await client.finalizeAiKeyProposal(proposal.id);
      if (applied.status === "ok") {
        setProposal(null);
        setMessage("Approved AI key installed from its sealed proposal.");
        await refresh(false);
        return;
      }
      if (applied.proposal) setProposal(applied.proposal);
      else if (isProposalStatus(applied.status)) {
        setProposal({ ...proposal, status: applied.status });
      }
      setMessage(applied.reason ?? "The approved proposal was not applied.");
    } catch {
      setProposal({ ...proposal, status: "unavailable" });
      setMessage(
        "Proposal status is unavailable. No key installation is inferred.",
      );
    } finally {
      setProposalBusy(false);
    }
  }

  async function remove(item: AiKeyView) {
    const key = `${item.level}:${item.scope_id}:${item.modality ?? "text"}`;
    if (armed !== key) {
      deleteFinalizer.invalidate();
      setArmed(key);
      return;
    }
    const input = {
      level: item.level,
      scopeId: item.scope_id,
      modality: (item.modality ?? "text") as AiKeyModality,
    };
    const result = input.modality === "text"
      ? await client.deleteAiKey(input.level, input.scopeId)
      : await client.deleteAiKey(input.level, input.scopeId, undefined, input.modality);
    setArmed("");
    if (deleteFinalizer.begin(input, result, "AI key removal")) {
      setMessage("Key removal is waiting for approval in the originating chat.");
      return;
    }
    setMessage(
      result.status === "ok"
        ? "AI key reference removed."
        : governedResultReason(result, result.status),
    );
    if (result.status === "ok") await refresh(false);
  }

  return (
    <section className="settings-card author-form">
      <p className="eyebrow">AI provider keys</p>
      <h2>Sealed routing credentials</h2>
      <p>Keys are envelope-sealed before approval. Worker, audit and later reads receive only bounded metadata or configured state.</p>
      {!allowOwn && level !== "org" && <p className="notice">This organisation currently disables workspace and personal AI keys.</p>}
      <form className="author-form" onSubmit={(event) => void save(event)}>
        <div className="author-grid">
          <label><span>Level</span><select className="field-control" value={level} onChange={(event) => { invalidateProposalForEdit(); setLevel(event.target.value as AiKeyLevel); }}><option value="user">Personal</option><option value="workspace">Workspace</option><option value="org">Organisation</option></select></label>
          <label><span>Scope id {level === "workspace" ? "(required)" : "(defaults to current)"}</span><input className="field-control" required={level === "workspace"} value={scopeId} onChange={(event) => { invalidateProposalForEdit(); setScopeId(event.target.value); }} /></label>
          <label><span>Provider</span><input className="field-control" required value={provider} onChange={(event) => { invalidateProposalForEdit(); setProvider(event.target.value); }} /></label>
          <label><span>Model</span><input className="field-control" required value={model} onChange={(event) => { invalidateProposalForEdit(); setModel(event.target.value); }} /></label>
          <label><span>Use for</span><select className="field-control" value={modality} onChange={(event) => { invalidateProposalForEdit(); setModality(event.target.value as AiKeyModality); }}><option value="text">Text · main API key</option><option value="vision">Vision · optional main vision key</option></select></label>
          <label><span>Base URL (optional)</span><input className="field-control" value={baseUrl} onChange={(event) => { invalidateProposalForEdit(); setBaseUrl(event.target.value); }} /></label>
          <label><span>API key (write only)</span><input ref={apiKeyInput} className="field-control" type="password" autoComplete="off" required onChange={invalidateProposalForEdit} /></label>
        </div>
        <button className="primary-button" disabled={proposalBusy || !model.trim() || (!allowOwn && level !== "org")}>Seal key for approval</button>
      </form>
      {proposal && (
        <AiKeyProposalFinalizer
          proposal={proposal}
          busy={proposalBusy}
          onContinue={() => void continueProposal()}
        />
      )}
      <div className="data-list" aria-label="Configured AI keys">
        {keys.map((item) => (
          <div className="data-row static" key={`${item.level}:${item.scope_id}:${item.modality ?? "text"}`}>
            <span className={`activity-dot ${item.has_key ? "ok" : "unknown"}`} />
            <span className="data-row-copy"><strong>{item.provider} · {item.model}</strong><small>{item.level} · {item.scope_id} · {item.modality ?? "text"} · secret {item.has_key ? "configured" : "absent"}</small></span>
            <button className={armed === `${item.level}:${item.scope_id}:${item.modality ?? "text"}` ? "danger-button armed" : "danger-button"} onClick={() => void remove(item)}>{armed === `${item.level}:${item.scope_id}:${item.modality ?? "text"}` ? "Confirm remove" : "Remove"}</button>
          </div>
        ))}
      </div>
      <ExactApprovalFinalizer controller={deleteFinalizer} />
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

function isProposalStatus(value: string): value is AiKeyProposalStatus {
  return [
    "pending",
    "approved",
    "rejected",
    "expired",
    "consumed",
    "invalidated",
    "unavailable",
  ].includes(value);
}

function AiKeyProposalFinalizer({
  proposal,
  busy,
  onContinue,
}: {
  proposal: AiKeyProposalView;
  busy: boolean;
  onContinue: () => void;
}) {
  const copy: Record<AiKeyProposalStatus, [string, string]> = {
    pending: [
      "Sealed key proposal is waiting for approval",
      "Only its provider, model, scope and opaque staged identity are available to the approval flow.",
    ],
    approved: [
      "Sealed key proposal is approved",
      "Apply consumes this exact proposal once; the key never returns to Worker.",
    ],
    rejected: ["Sealed key proposal was rejected", "Staged secret material was removed."],
    expired: ["Sealed key proposal expired", "Staged secret material was removed."],
    consumed: [
      "Sealed key proposal was already consumed",
      "Refresh configured keys before proposing another change.",
    ],
    invalidated: [
      "Sealed key proposal was invalidated",
      "Its form or caller scope changed and staged secret material was removed.",
    ],
    unavailable: [
      "Sealed key proposal state is unavailable",
      "No installation is inferred. Reload to recover canonical requester-owned state.",
    ],
  };
  const text = copy[proposal.status];
  return (
    <div className={`notice ai-key-proposal ${proposal.status}`} role="status">
      <strong>{text[0]}</strong>
      <p>{text[1]}</p>
      {ACTIVE_PROPOSAL_STATES.has(proposal.status) && (
        <button className="secondary-button" disabled={busy} onClick={onContinue}>
          {proposal.status === "approved"
            ? "Apply approved sealed key"
            : "Check approval and apply sealed key"}
        </button>
      )}
    </div>
  );
}
