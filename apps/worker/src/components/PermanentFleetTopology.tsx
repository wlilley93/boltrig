import { useEffect, useState } from "react";
import type {
  ModelEndpointInfo,
  PermanentFleetApplyResponse,
  PermanentFleetHead,
  PermanentFleetHierarchy,
  PermanentFleetResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";

function blankHead(chief: boolean, index = 1): PermanentFleetHead {
  return {
    name: chief ? "chief-of-staff" : `department-head-${index}`,
    routing_id: chief ? "cos" : `department-${index}`,
    purpose: chief
      ? "Route work across departments"
      : `Own department ${index} work`,
    brief: "",
    runtime: "codex",
    model_endpoint: null,
    supported_skills: ["*"],
    max_depth: chief ? 4 : 3,
    cost_tier: "standard",
    budget: null,
  };
}

const blankHierarchy = (): PermanentFleetHierarchy => ({
  chief: blankHead(true),
  departments: [blankHead(false)],
});

type PermanentFleetMutation = {
  hierarchy: PermanentFleetHierarchy;
  referenceGeneration: string | null;
  referenceRevision: number | null;
};

function sameRouteInput(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function PermanentFleetTopology() {
  const [state, setState] = useState<PermanentFleetResponse | null>(null);
  const [draft, setDraft] = useState<PermanentFleetHierarchy>(blankHierarchy);
  const [endpoints, setEndpoints] = useState<ModelEndpointInfo[]>([]);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const finalizer = useExactApprovalFinalizer<
    PermanentFleetMutation,
    PermanentFleetApplyResponse
  >({
    isCurrent: (input) => (
      sameRouteInput(input.hierarchy, draft)
      && input.referenceGeneration === (state?.generation ?? null)
      && input.referenceRevision === (state?.revision ?? null)
    ),
    replay: (input, approvalId) => (
      client.applyPermanentFleet(input.hierarchy, approvalId)
    ),
    onApplied: async () => {
      setEditing(false);
      await refresh(false);
      setMessage(
        "Desired hierarchy saved. No running worker was mutated; restart the fleet worker to apply it.",
      );
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result,
        "The approved hierarchy change was refused.",
      ));
    },
    onUncertain: async () => {
      await refresh(false);
      setMessage(
        "Canonical fleet state was refreshed; no hierarchy change is inferred.",
      );
    },
  });

  async function refresh(invalidate = true) {
    if (invalidate) finalizer.invalidate();
    try {
      const result = await client.permanentFleet();
      setState(result);
      setDraft(result.hierarchy ?? blankHierarchy());
    } catch {
      setMessage("Permanent fleet desired/observed state is unavailable.");
    }
  }

  useEffect(() => {
    void refresh(false);
    void client.modelEndpoints()
      .then((result) => setEndpoints(result.endpoints))
      .catch(() => setEndpoints([]));
  }, []);

  async function apply() {
    setBusy(true);
    setMessage("");
    const input: PermanentFleetMutation = {
      hierarchy: draft,
      referenceGeneration: state?.generation ?? null,
      referenceRevision: state?.revision ?? null,
    };
    try {
      const result = await client.applyPermanentFleet(input.hierarchy);
      if (finalizer.begin(input, result, "Permanent fleet hierarchy change")) {
        setMessage("The hierarchy change is waiting for approval in Inbox.");
      } else if (result.status === "ok") {
        setMessage(
          "Desired hierarchy saved. No running worker was mutated; restart the fleet worker to apply it.",
        );
        setEditing(false);
        await refresh(false);
      } else {
        setMessage(governedResultReason(result, "The hierarchy was not changed."));
      }
    } catch {
      setMessage("The hierarchy was not changed.");
    } finally {
      setBusy(false);
    }
  }

  const hierarchy = state?.hierarchy;
  return (
    <section className="settings-card permanent-fleet" aria-label="Permanent fleet topology">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Permanent fleet · desired / observed</p>
          <h2>Chief of Staff and department heads</h2>
        </div>
        <div className="inline-actions">
          <span className="row-meta">
            {state?.apply_state === "startup_applied_liveness_unknown"
              ? "startup applied · liveness unknown"
              : state?.apply_state === "restart_required"
                ? "restart required"
                : "not configured"}
          </span>
          <button className="secondary-button" type="button" onClick={() => void refresh()}>
            Refresh
          </button>
          <button className="secondary-button" type="button" onClick={() => { finalizer.invalidate(); setEditing((value) => !value); }}>
            {editing ? "Close editor" : hierarchy ? "Edit topology" : "Configure topology"}
          </button>
        </div>
      </div>
      <p>
        This is the authored org chart. A persistent capability profile is not a
        live head. After restart, the Chief and department profiles resolve their
        runtime lazily for each reasoning call through Boltrig&apos;s admission,
        model-routing and budget gates. A startup record proves only that one worker
        constructed this exact generation; current worker liveness is unknown, and
        endpoint/model liveness is also unproven.
      </p>
      {state?.generation && (
        <p className="muted small">
          Desired generation <code>{state.generation}</code>. Hot application:
          no. Persistent profiles:{" "}
          {state.profiles_reconciled ? "projected" : "awaiting manifest apply or redeploy"}.
        </p>
      )}
      {hierarchy && !editing && (
        <div className="work-project-tree">
          <TopologyCard head={hierarchy.chief} role="Chief of Staff" state={state} />
          <div className="work-project-children">
            {hierarchy.departments.map((head) => (
              <TopologyCard head={head} role="Department head" state={state} key={head.routing_id} />
            ))}
          </div>
        </div>
      )}
      {editing && (
        <form onSubmit={(event) => { event.preventDefault(); void apply(); }}>
          <HeadEditor
            head={draft.chief}
            role="Chief of Staff"
            endpoints={endpoints}
            onChange={(chief) => { finalizer.invalidate(); setDraft({ ...draft, chief }); }}
          />
          {draft.departments.map((head, index) => (
            <div className="detail-section" key={`${head.routing_id}:${index}`}>
              <HeadEditor
                head={head}
                role={`Department head ${index + 1}`}
                endpoints={endpoints}
                onChange={(department) => {
                  finalizer.invalidate();
                  setDraft({
                    ...draft,
                    departments: draft.departments.map((item, itemIndex) => (
                      itemIndex === index ? department : item
                    )),
                  });
                }}
              />
              {draft.departments.length > 1 && (
                <button className="danger-button" type="button" onClick={() => {
                  finalizer.invalidate();
                  setDraft({
                    ...draft,
                    departments: draft.departments.filter((_, itemIndex) => itemIndex !== index),
                  });
                }}>Remove department</button>
              )}
            </div>
          ))}
          <div className="inline-actions">
            <button className="secondary-button" type="button" onClick={() => {
              finalizer.invalidate();
              setDraft({
                ...draft,
                departments: [
                  ...draft.departments,
                  blankHead(false, draft.departments.length + 1),
                ],
              });
            }}>Add department</button>
            <button className="primary-button" disabled={busy || finalizer.busy}>
              {busy ? "Requesting…" : "Request hierarchy change"}
            </button>
          </div>
        </form>
      )}
      {message && <p className="notice" role="status">{message}</p>}
      <ExactApprovalFinalizer controller={finalizer} />
    </section>
  );
}

function TopologyCard({
  head,
  role,
  state,
}: {
  head: PermanentFleetHead;
  role: string;
  state: PermanentFleetResponse;
}) {
  return (
    <article className="work-card">
      <span className="activity-dot paused" />
      <span>
        <strong>{head.name}</strong>
        <small>
          {role} · {role === "Chief of Staff"
            ? `chief route ${head.routing_id}`
            : `department route ${head.routing_id}`} · purpose: {head.purpose}
        </small>
        <small>
          authored profile: {head.runtime} · {head.model_endpoint ?? "process-pinned model"} ·
          {" "}{head.supported_skills.join(", ")}
        </small>
        <small>
          Purpose, brief, runtime, model, skills, depth and cost policy are consumed
          when a worker constructs this generation. Runtime admission happens only
          when the head reasons; this card does not claim that a model is live.
        </small>
      </span>
      <span className="row-meta">
        {state.apply_state === "startup_applied_liveness_unknown"
          ? "policy constructed · liveness unknown"
          : "desired"}
      </span>
    </article>
  );
}

function HeadEditor({
  head,
  role,
  endpoints,
  onChange,
}: {
  head: PermanentFleetHead;
  role: string;
  endpoints: ModelEndpointInfo[];
  onChange(head: PermanentFleetHead): void;
}) {
  return (
    <fieldset className="admin-form compact">
      <legend>{role}</legend>
      <div className="author-grid">
        <label><span>Profile name</span><input className="field-control" required pattern="[a-z0-9][a-z0-9-]{1,62}" value={head.name} onChange={(event) => onChange({ ...head, name: event.target.value.toLowerCase() })} /></label>
        <label><span>Routing identity</span><input className="field-control" required disabled={role === "Chief of Staff"} value={head.routing_id} onChange={(event) => onChange({ ...head, routing_id: event.target.value.toLowerCase() })} /></label>
        <label><span>Runtime profile</span><select className="field-control" value={head.runtime} onChange={(event) => onChange({ ...head, runtime: event.target.value as PermanentFleetHead["runtime"] })}><option value="codex">Codex</option><option value="script">Deterministic script</option></select></label>
        <label><span>Model endpoint profile</span><select className="field-control" value={head.model_endpoint ?? ""} onChange={(event) => onChange({ ...head, model_endpoint: event.target.value || null })}><option value="">Automatic profile</option>{endpoints.filter((endpoint) => endpoint.is_active || endpoint.id === head.model_endpoint).map((endpoint) => <option value={endpoint.id} disabled={!endpoint.is_active} key={endpoint.id}>{endpoint.id} · {endpoint.model}{endpoint.is_active ? "" : " (retired)"}</option>)}</select></label>
        <label><span>Maximum delegation depth</span><input className="field-control" type="number" min="1" max="5" value={head.max_depth} onChange={(event) => onChange({ ...head, max_depth: Number(event.target.value) })} /></label>
        <label><span>Cost tier profile</span><select className="field-control" value={head.cost_tier} onChange={(event) => onChange({ ...head, cost_tier: event.target.value as PermanentFleetHead["cost_tier"] })}><option value="cheap">Cheap</option><option value="standard">Standard</option><option value="expensive">Expensive</option></select></label>
      </div>
      <label><span>Purpose</span><input className="field-control" required maxLength={500} value={head.purpose} onChange={(event) => onChange({ ...head, purpose: event.target.value })} /></label>
      <label><span>Supported skill patterns</span><textarea className="field-control code-field" rows={2} value={head.supported_skills.join(", ")} onChange={(event) => onChange({ ...head, supported_skills: event.target.value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean) })} /><small>Only concrete department skills are consumed by the permanent head; wildcard patterns remain profile metadata.</small></label>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={head.budget !== null}
          onChange={(event) => onChange({
            ...head,
            budget: event.target.checked
              ? {
                  token_limit: null,
                  cost_limit_micros: null,
                  hard_stop: true,
                  window: "monthly",
                }
              : null,
          })}
        />
        <span>Author budget policy for this scope</span>
      </label>
      {head.budget && (
        <div className="author-grid">
          <label><span>Token limit</span><input className="field-control" type="number" min="0" value={head.budget.token_limit ?? ""} onChange={(event) => onChange({ ...head, budget: { ...head.budget!, token_limit: event.target.value === "" ? null : Number(event.target.value) } })} /></label>
          <label><span>Cost limit (micros)</span><input className="field-control" type="number" min="0" value={head.budget.cost_limit_micros ?? ""} onChange={(event) => onChange({ ...head, budget: { ...head.budget!, cost_limit_micros: event.target.value === "" ? null : Number(event.target.value) } })} /></label>
          <label><span>Automatic budget window</span><select className="field-control" value={head.budget.window} onChange={(event) => onChange({ ...head, budget: { ...head.budget!, window: event.target.value as NonNullable<PermanentFleetHead["budget"]>["window"] } })}><option value="run">Per run</option><option value="daily">Daily · UTC</option><option value="monthly">Monthly · UTC</option></select></label>
          <label className="checkbox-row"><input type="checkbox" checked={head.budget.hard_stop} onChange={(event) => onChange({ ...head, budget: { ...head.budget!, hard_stop: event.target.checked } })} /><span>Hard stop</span></label>
        </div>
      )}
      <label><span>Agent brief</span><textarea className="field-control" rows={3} maxLength={8000} value={head.brief} onChange={(event) => onChange({ ...head, brief: event.target.value })} /><small>Stored and versioned. After restart it becomes prompt policy whenever this permanent profile passes runtime admission; deterministic fallback remains available.</small></label>
    </fieldset>
  );
}
