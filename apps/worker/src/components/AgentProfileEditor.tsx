import { useEffect, useState } from "react";
import type {
  AgentCapabilityInfo,
  InvokeRequest,
  InvokeResult,
  ModelEndpointInfo,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";
import {
  AgentModelRouting,
  endpointSupports,
  type AgentModelRoutingValue,
} from "./agent/AgentModelRouting";

interface AgentDraft extends AgentModelRoutingValue {
  name: string;
  runtime: string;
  supportedSkills: string;
  maxDepth: number;
  ephemeral: boolean;
  costTier: string;
}

const blank: AgentDraft = {
  name: "",
  runtime: "codex",
  supportedSkills: "*",
  maxDepth: 2,
  ephemeral: true,
  costTier: "standard",
  modelEndpoint: "",
  visionModelEndpoint: "",
  modelRoutes: {},
  modelRouteMode: "multimodal",
};

type AgentProfileMutation = {
  request: InvokeRequest;
  params: Record<string, unknown>;
  profileIdentity: string | null;
};

function draftFor(initial?: AgentCapabilityInfo | null): AgentDraft {
  return initial ? {
    name: initial.name,
    runtime: initial.runtime,
    supportedSkills: initial.supported_skills.join(", "),
    maxDepth: initial.max_depth,
    ephemeral: initial.is_ephemeral,
    costTier: initial.cost_tier,
    modelEndpoint: initial.model_endpoint ?? initial.model_routes?.text ?? "",
    visionModelEndpoint: initial.vision_model_endpoint ?? initial.model_routes?.vision ?? "",
    modelRoutes: { ...(initial.model_routes ?? {}) },
    modelRouteMode: (initial.vision_model_endpoint ?? initial.model_routes?.vision)
      ? "separate"
      : "multimodal",
  } : { ...blank };
}

function profileParams(draft: AgentDraft): Record<string, unknown> {
  const modelRoutes = { ...draft.modelRoutes };
  if (draft.modelEndpoint) modelRoutes.text = draft.modelEndpoint;
  else delete modelRoutes.text;
  if (draft.visionModelEndpoint) modelRoutes.vision = draft.visionModelEndpoint;
  else delete modelRoutes.vision;
  return {
    name: draft.name.trim(),
    runtime: draft.runtime.trim(),
    supported_skills: draft.supportedSkills
      .split(/[,\n]/)
      .map((item) => item.trim())
      .filter(Boolean),
    max_depth: draft.maxDepth,
    is_ephemeral: draft.ephemeral,
    cost_tier: draft.costTier,
    model_endpoint: draft.modelEndpoint || undefined,
    vision_model_endpoint: draft.visionModelEndpoint || undefined,
    model_routes: modelRoutes,
  };
}

function sameRouteInput(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function AgentProfileEditor({
  initial,
  onSaved,
  onCancel,
}: {
  initial?: AgentCapabilityInfo | null;
  onSaved(): void;
  onCancel(): void;
}) {
  const [draft, setDraft] = useState<AgentDraft>(() => draftFor(initial));
  const [modelEndpoints, setModelEndpoints] = useState<ModelEndpointInfo[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const finalizer = useExactApprovalFinalizer<AgentProfileMutation, InvokeResult>({
    isCurrent: (input) => (
      input.profileIdentity === (initial?.name ?? null)
      && sameRouteInput(input.params, profileParams(draft))
    ),
    replay: (input, approvalId) => client.invoke({
      ...input.request,
      approval_id: approvalId,
    }),
    onApplied: (_result, input) => {
      setMessage(`${String(input.params.name)} profile saved.`);
      onSaved();
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result,
        "The approved profile change was refused.",
      ));
    },
    onUncertain: async () => {
      const result = await client.agentCapabilities();
      const profileName = initial?.name ?? draft.name.trim();
      const canonical = result.agent_capabilities.find(
        (profile) => profile.name === profileName,
      );
      if (canonical) setDraft(draftFor(canonical));
      setMessage(
        "Canonical agent profiles were refreshed; no profile change is inferred.",
      );
    },
  });

  const initialKey = JSON.stringify(initial ?? null);
  useEffect(() => {
    finalizer.invalidate();
    setDraft(draftFor(initial));
  }, [initialKey]);

  useEffect(() => {
    void client.modelEndpoints()
      .then((result) => setModelEndpoints(result.endpoints))
      .catch(() => setModelEndpoints([]));
  }, []);

  function updateDraft(next: AgentDraft) {
    finalizer.invalidate();
    setDraft(next);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const textEndpoint = modelEndpoints.find((endpoint) => endpoint.id === draft.modelEndpoint);
    const visionEndpoint = modelEndpoints.find((endpoint) => endpoint.id === draft.visionModelEndpoint);
    if (draft.modelRouteMode === "multimodal" && textEndpoint && (
      !endpointSupports(textEndpoint, "text") || !endpointSupports(textEndpoint, "vision")
    )) {
      setMessage("Choose a model that supports both text and vision, or switch to separate models.");
      setBusy(false);
      return;
    }
    if (draft.modelRouteMode === "separate" && (
      (draft.modelEndpoint && (!textEndpoint || !endpointSupports(textEndpoint, "text")))
      || (draft.visionModelEndpoint && (!visionEndpoint || !endpointSupports(visionEndpoint, "vision")))
    )) {
      setMessage("The selected text and vision endpoints do not advertise the required modalities.");
      setBusy(false);
      return;
    }
    if (draft.modelRouteMode === "separate" && draft.modelEndpoint && !draft.visionModelEndpoint
      && textEndpoint && !endpointSupports(textEndpoint, "vision")) {
      setMessage("This text endpoint is not multimodal. Select a vision override, or leave both routes on the main API defaults.");
      setBusy(false);
      return;
    }
    const params = profileParams(draft);
    const input: AgentProfileMutation = {
      params,
      profileIdentity: initial?.name ?? null,
      request: {
        noun: "control",
        verb: "control.capability.upsert",
        idempotency_key: crypto.randomUUID(),
        params,
      },
    };
    try {
      const result = await client.invoke(input.request);
      if (finalizer.begin(input, result, "Agent profile change")) {
        setMessage("Profile change is waiting for approval in the originating chat.");
        return;
      }
      if (
        result.status === "denied"
        || result.status === "error"
        || result.status === "unavailable"
      ) {
        setMessage(`Not changed: ${result.reason}.`);
        return;
      }
      setMessage(result.status === "degraded"
        ? "The change applied in degraded state; inspect its receipt in the originating chat or Runs."
        : "Agent profile saved.");
      onSaved();
    } catch {
      setMessage("The agent profile was not changed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="settings-card author-form agent-profile-editor" onSubmit={(event) => void save(event)}>
      <div className="section-heading">
        <div><p className="eyebrow">Agent profile</p><h2>{initial ? `Edit ${initial.name}` : "Create an agent"}</h2></div>
        <button className="icon-button" type="button" aria-label="Close profile editor" onClick={() => { finalizer.invalidate(); onCancel(); }}>×</button>
      </div>
      <p>Profiles describe a Boltrig worker Codex may convene. Effective grants remain capped by the initiating identity.</p>
      <div className="author-grid">
        <label><span>Name</span><input className="field-control" required disabled={Boolean(initial)} pattern="[a-z0-9][a-z0-9-]{1,62}" value={draft.name} onChange={(event) => updateDraft({ ...draft, name: event.target.value.toLowerCase() })} /></label>
        <label><span>Runtime</span><select className="field-control" required value={draft.runtime} onChange={(event) => updateDraft({ ...draft, runtime: event.target.value })}>{draft.runtime !== "codex" && <option value={draft.runtime}>{draft.runtime} (legacy)</option>}<option value="codex">Codex</option></select></label>
        <label><span>Maximum delegation depth</span><input className="field-control" type="number" min={1} max={5} value={draft.maxDepth} onChange={(event) => updateDraft({ ...draft, maxDepth: Number(event.target.value) })} /></label>
        <label><span>Cost tier</span><select className="field-control" value={draft.costTier} onChange={(event) => updateDraft({ ...draft, costTier: event.target.value })}><option value="cheap">Cheap</option><option value="standard">Standard</option><option value="expensive">Expensive</option></select></label>
        <AgentModelRouting
          endpoints={modelEndpoints}
          onChange={(routing) => updateDraft({ ...draft, ...routing })}
          value={draft}
        />
        <label className="check-label"><input type="checkbox" checked={draft.ephemeral} onChange={(event) => updateDraft({ ...draft, ephemeral: event.target.checked })} />Ephemeral worker</label>
      </div>
      <label><span>Supported skill patterns</span><textarea className="field-control code-field" rows={4} value={draft.supportedSkills} onChange={(event) => updateDraft({ ...draft, supportedSkills: event.target.value })} /></label>
      <p className="muted small">This is a high-consequence control-plane change and may pause for approval.</p>
      <button className="primary-button" disabled={busy || finalizer.busy}>{busy ? "Requesting…" : "Request profile change"}</button>
      {message && <p className="notice" role="status">{message}</p>}
      <ExactApprovalFinalizer controller={finalizer} />
    </form>
  );
}
