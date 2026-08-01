import { useEffect, useState } from "react";
import type {
  InvokeRequest,
  InvokeResult,
  ModelEndpointInfo,
  ModelEndpointLifecycleResponse,
  ModelPolicyResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import { Unavailable } from "../Shell";

type ModelEndpointMutation =
  | {
    kind: "upsert";
    request: InvokeRequest;
    params: Record<string, unknown>;
    hydratedExisting: string | null;
  }
  | {
    kind: "retire" | "restore";
    endpoint: ModelEndpointInfo;
  };

function endpointParams(fields: {
  id: string;
  kind: string;
  model: string;
  baseUrl: string;
  fallback: string;
  dataClass: string;
}): Record<string, unknown> {
  return {
    id: fields.id.trim(),
    kind: fields.kind.trim(),
    model: fields.model.trim(),
    base_url: fields.baseUrl.trim() || undefined,
    fallback: fields.fallback.trim() || undefined,
    data_class: fields.dataClass.trim() || "standard",
  };
}

function sameRouteInput(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function ModelEndpointsBuild() {
  const [endpoints, setEndpoints] = useState<ModelEndpointInfo[]>([]);
  const [id, setId] = useState("");
  const [kind, setKind] = useState("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [fallback, setFallback] = useState("");
  const [dataClass, setDataClass] = useState("standard");
  const [message, setMessage] = useState("");
  const [hydratedExisting, setHydratedExisting] = useState<string | null>(null);
  const [references, setReferences] = useState<{
    capabilities: string[];
    fallbacks: string[];
  }>({ capabilities: [], fallbacks: [] });
  const [policy, setPolicy] = useState<ModelPolicyResponse["policy"] | null>(null);
  const [policyMessage, setPolicyMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const selected = endpoints.find((endpoint) => endpoint.id === hydratedExisting);

  const finalizer = useExactApprovalFinalizer<
    ModelEndpointMutation,
    InvokeResult | ModelEndpointLifecycleResponse
  >({
    isCurrent: (input) => {
      if (input.kind === "upsert") {
        return input.hydratedExisting === hydratedExisting
          && sameRouteInput(input.params, endpointParams({
            id,
            kind,
            model,
            baseUrl,
            fallback,
            dataClass,
          }));
      }
      const current = endpoints.find(
        (endpoint) => endpoint.id === input.endpoint.id,
      );
      return hydratedExisting === input.endpoint.id
        && current !== undefined
        && sameRouteInput(current, input.endpoint);
    },
    replay: (input, approvalId) => {
      if (input.kind === "upsert") {
        return client.invoke({ ...input.request, approval_id: approvalId });
      }
      return input.kind === "retire"
        ? client.retireModelEndpoint(input.endpoint.id, approvalId)
        : client.restoreModelEndpoint(input.endpoint.id, approvalId);
    },
    onApplied: async (_result, input) => {
      await refresh(false);
      setMessage(input.kind === "upsert"
        ? "Model endpoint saved."
        : `${input.endpoint.id} ${input.kind === "retire" ? "retired" : "restored"}.`);
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result,
        "The approved model endpoint change was refused.",
      ));
    },
    onUncertain: async () => {
      await refresh(false);
      setMessage(
        "Canonical model endpoint state was refreshed; no endpoint change is inferred.",
      );
    },
  });

  async function refresh(invalidate = true) {
    if (invalidate) finalizer.invalidate();
    try {
      const result = await client.modelEndpoints();
      setEndpoints(result.endpoints);
      if (hydratedExisting) {
        const current = result.endpoints.find(
          (endpoint) => endpoint.id === hydratedExisting,
        );
        if (current) {
          const detail = await client.modelEndpoint(current.id);
          setId(detail.endpoint.id);
          setKind(detail.endpoint.kind);
          setModel(detail.endpoint.model);
          setBaseUrl(detail.endpoint.base_url ?? "");
          setFallback(detail.endpoint.fallback ?? "");
          setDataClass(detail.endpoint.data_class);
          setHydratedExisting(detail.endpoint.id);
          setReferences(
            detail.endpoint.references ?? { capabilities: [], fallbacks: [] },
          );
        } else {
          setHydratedExisting(null);
          setReferences({ capabilities: [], fallbacks: [] });
        }
      }
    } catch {
      setMessage("Model endpoint inventory is unavailable.");
    }
  }

  async function refreshPolicy() {
    try {
      const result = await client.modelPolicy();
      setPolicy(result.policy);
      setPolicyMessage("");
    } catch {
      setPolicy(null);
      setPolicyMessage(
        "Effective model policy evidence is unavailable; endpoint inventory is not treated as routing policy.",
      );
    }
  }

  useEffect(() => {
    void refresh(false);
    void refreshPolicy();
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (endpoints.some((endpoint) => endpoint.id === id.trim()) && hydratedExisting !== id.trim()) {
      setMessage("Load the complete existing endpoint before replacing it.");
      return;
    }
    if (dataClass === "sensitive" && kind !== "local") {
      setMessage("Sensitive endpoints must use the local runtime kind.");
      return;
    }
    const params = endpointParams({
      id,
      kind,
      model,
      baseUrl,
      fallback,
      dataClass,
    });
    const input: ModelEndpointMutation = {
      kind: "upsert",
      hydratedExisting,
      params,
      request: {
        noun: "control",
        verb: "control.model_endpoint.upsert",
        idempotency_key: crypto.randomUUID(),
        params,
      },
    };
    setBusy(true);
    setMessage("");
    try {
      const result = await client.invoke(input.request);
      if (finalizer.begin(input, result, "Model endpoint change")) {
        setMessage("Model endpoint change is waiting for approval in Inbox.");
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
        ? "Endpoint changed in degraded state."
        : "Model endpoint saved.");
      await refresh(false);
    } catch {
      setMessage("The model endpoint was not changed.");
    } finally {
      setBusy(false);
    }
  }

  async function edit(endpoint: ModelEndpointInfo) {
    finalizer.invalidate();
    setMessage("");
    setHydratedExisting(null);
    try {
      const result = await client.modelEndpoint(endpoint.id);
      setId(result.endpoint.id);
      setKind(result.endpoint.kind);
      setModel(result.endpoint.model);
      setBaseUrl(result.endpoint.base_url ?? "");
      setFallback(result.endpoint.fallback ?? "");
      setDataClass(result.endpoint.data_class);
      setHydratedExisting(result.endpoint.id);
      setReferences(result.endpoint.references ?? { capabilities: [], fallbacks: [] });
    } catch {
      setMessage("The complete authoring record could not be loaded, so replacement is disabled.");
    }
  }

  function clearForm() {
    finalizer.invalidate();
    setId("");
    setKind("openai");
    setModel("");
    setBaseUrl("");
    setFallback("");
    setDataClass("standard");
    setHydratedExisting(null);
    setReferences({ capabilities: [], fallbacks: [] });
  }

  async function changeLifecycle(endpoint: ModelEndpointInfo) {
    setBusy(true);
    setMessage("");
    const input: ModelEndpointMutation = {
      kind: endpoint.is_active ? "retire" : "restore",
      endpoint,
    };
    const action = input.kind === "retire" ? "Retirement" : "Restore";
    try {
      const result = input.kind === "retire"
        ? await client.retireModelEndpoint(input.endpoint.id)
        : await client.restoreModelEndpoint(endpoint.id);
      if (finalizer.begin(input, result, `Model endpoint ${action.toLowerCase()}`)) {
        setMessage(`${action} is waiting for approval in Inbox.`);
      } else if (result.status === "ok") {
        setMessage(`${endpoint.id} ${input.kind === "retire" ? "retired" : "restored"}.`);
        await refresh(false);
      } else {
        setMessage(governedResultReason(
          result,
          `${endpoint.id} was not changed.`,
        ));
      }
    } catch {
      setMessage("Model endpoint lifecycle management is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  const activeCount = endpoints.filter((endpoint) => endpoint.is_active).length;

  return (
    <div className="build-layout">
      <section className="settings-card build-inventory">
        <div className="section-heading"><div><p className="eyebrow">{activeCount}/{endpoints.length} active</p><h2>Model endpoints</h2></div><div className="inline-actions"><button className="secondary-button" onClick={clearForm}>New</button><button className="secondary-button" onClick={() => void refresh()}>Refresh</button></div></div>
        {endpoints.length === 0 ? <Unavailable title="No endpoints visible">Add the first governed endpoint, or configure it through a tenant manifest.</Unavailable> : (
          <div className="data-list">{endpoints.map((endpoint) => (
            <button className="data-row" key={endpoint.id} onClick={() => void edit(endpoint)}>
              <span className={`activity-dot ${endpoint.is_active ? "ok" : "paused"}`} />
              <span className="data-row-copy"><strong>{endpoint.id}</strong><small>{endpoint.kind} · {endpoint.model}</small></span>
              <span className="row-meta">{endpoint.status} · {endpoint.data_class}</span>
            </button>
          ))}</div>
        )}
        <div className="settings-subsection">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Process-start evidence</p>
              <h3>Effective model policy</h3>
            </div>
            <button className="secondary-button" onClick={() => void refreshPolicy()}>
              Refresh evidence
            </button>
          </div>
          {policy ? (
            <>
              <div className="data-list">
                <div className="data-row">
                  <span className={`activity-dot ${policy.state === "degraded" ? "warn" : "ok"}`} />
                  <span className="data-row-copy">
                    <strong>Sensitive/local role</strong>
                    <small>
                      {policy.sensitive.endpoint_id ?? "Not configured"} · {policy.sensitive.state}
                    </small>
                  </span>
                  <span className="row-meta">
                    {policy.sensitive.serving_state.replaceAll("_", " ")}
                  </span>
                </div>
                <div className="data-row">
                  <span className="activity-dot paused" />
                  <span className="data-row-copy">
                    <strong>Default role</strong>
                    <small>
                      {policy.default.endpoint_id ?? "Not configured"} · {policy.default.state}
                    </small>
                  </span>
                  <span className="row-meta">inactive · no serving consumer</span>
                </div>
              </div>
              <p className="muted small">
                {policy.prices.length > 0
                  ? `${policy.prices.length} model price ${policy.prices.length === 1 ? "entry" : "entries"} active in this process cost accountant.`
                  : "No per-model prices are configured; cost tiers remain the fallback."}
                {" "}Policy changes apply only after process restart.
                {policy.generation ? ` Generation ${policy.generation.slice(0, 12)}.` : ""}
              </p>
              {policy.prices.length > 0 && (
                <div className="data-list" aria-label="Effective model prices">
                  {policy.prices.map((price) => (
                    <div className="data-row" key={price.model}>
                      <span className="data-row-copy">
                        <strong>{price.model}</strong>
                        <small>micros per token</small>
                      </span>
                      <span className="row-meta">
                        in {price.input_micros_per_token} · out {price.output_micros_per_token}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <Unavailable title="Policy evidence unavailable">
              {policyMessage || "Loading process-start model policy…"}
            </Unavailable>
          )}
        </div>
      </section>
      <form className="settings-card author-form" onSubmit={(event) => void save(event)}>
        <p className="eyebrow">High-consequence routing</p><h2>Create or update an endpoint</h2>
        <p>Sensitive data still routes only to endpoints declared local by server policy. Retiring an endpoint preserves its configuration and references, but every new route or binding to it fails closed until restore.</p>
        <div className="author-grid">
          <label><span>Identifier</span><input className="field-control" required disabled={Boolean(hydratedExisting)} value={id} onChange={(event) => { finalizer.invalidate(); setId(event.target.value); }} /></label>
          <label><span>Kind</span><select className="field-control" value={kind} onChange={(event) => { finalizer.invalidate(); setKind(event.target.value); }}><option value="openai">OpenAI-compatible</option><option value="local">Local</option></select></label>
          <label><span>Model</span><input className="field-control" required value={model} onChange={(event) => { finalizer.invalidate(); setModel(event.target.value); }} /></label>
          <label><span>Base URL (optional)</span><input className="field-control" type="url" value={baseUrl} onChange={(event) => { finalizer.invalidate(); setBaseUrl(event.target.value); }} /></label>
          <label><span>Fallback endpoint id</span><input className="field-control" value={fallback} onChange={(event) => { finalizer.invalidate(); setFallback(event.target.value); }} /><small>Stored for explicit health-based failover; it never bypasses retirement.</small></label>
          <label><span>Data class</span><select className="field-control" value={dataClass} onChange={(event) => { finalizer.invalidate(); setDataClass(event.target.value); }}><option value="standard">Standard</option><option value="sensitive">Sensitive</option></select></label>
        </div>
        {hydratedExisting && (
          <p className="muted small">
            Editing the complete server record for {hydratedExisting}; saving replaces it atomically and preserves its {selected?.status ?? "stored"} lifecycle.
            {" "}Referenced by {references.capabilities.length} agent profiles and {references.fallbacks.length} endpoint fallbacks.
          </p>
        )}
        <div className="inline-actions">
          <button className="primary-button" disabled={busy || finalizer.busy}>Request endpoint change</button>
          {selected && (
            <button
              className="secondary-button"
              type="button"
              disabled={busy}
              onClick={() => void changeLifecycle(selected)}
            >
              {busy ? "Requesting…" : selected.is_active ? "Retire endpoint" : "Restore endpoint"}
            </button>
          )}
        </div>
        {message && <p className="notice" role="status">{message}</p>}
        <ExactApprovalFinalizer controller={finalizer} />
      </form>
    </div>
  );
}
