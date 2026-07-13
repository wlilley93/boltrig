import { useState } from "react";

import { api } from "../../api/client";
import type {
  AdapterInventoryResponse,
  AdapterRecord,
  GenerateAdapterResponse,
  StatusAck,
} from "../../api/types";
import { useFetch, type FetchState } from "../../useFetch";
import { CodeBlock, errText, parseJson } from "../shared";
import { outputRecord, PendingHumanCard, useControlMutation } from "../uxFlow";
import { AckLine } from "./AckLine";

// Generate an adapter from an OpenAPI spec. It lands inert (activated: false)
// and reloads the inventory on success so the reviewer sees it immediately.
function GenerateAdapterForm({ onGenerated }: { onGenerated: () => void }) {
  const [adapterId, setAdapterId] = useState("");
  const [spec, setSpec] = useState("{}");
  const [genBusy, setGenBusy] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [gen, setGen] = useState<GenerateAdapterResponse | null>(null);

  async function generate() {
    if (!adapterId.trim()) {
      setGenError("adapter_id is required.");
      return;
    }
    let parsedSpec: unknown;
    try {
      parsedSpec = parseJson<unknown>(spec, {});
    } catch (err) {
      setGenError(`spec: ${errText(err)}`);
      return;
    }
    setGenBusy(true);
    setGenError(null);
    setGen(null);
    try {
      const res = await api.generateAdapter({
        adapter_id: adapterId.trim(),
        spec: parsedSpec,
      });
      setGen(res);
      if (res.status === "ok") onGenerated();
    } catch (err) {
      setGenError(errText(err));
    } finally {
      setGenBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">Generate adapter from OpenAPI</div>
      <p className="muted">
        Generated adapters load inert (activated: false): a reviewer must
        activate before any verb is bound (SEC-22).
      </p>
      <label className="field">
        <span>adapter_id</span>
        <input
          value={adapterId}
          onChange={(e) => setAdapterId(e.target.value)}
        />
      </label>
      <label className="field">
        <span>spec (OpenAPI JSON)</span>
        <textarea
          className="code"
          value={spec}
          onChange={(e) => setSpec(e.target.value)}
        />
      </label>
      <div className="form__actions">
        <button
          className="btn btn--primary"
          disabled={genBusy}
          onClick={generate}
        >
          {genBusy ? "..." : "Generate"}
        </button>
        {genError && <span className="error">{genError}</span>}
      </div>
      {gen &&
        (gen.status === "ok" ? (
          <div className="stack">
            <div className="row-line">
              <span>
                <code>{gen.id}</code>{" "}
                <span
                  className={`badge ${gen.activated ? "badge--activated" : "badge--inert"}`}
                >
                  {gen.activated ? "activated" : "inert"}
                </span>
              </span>
              <span className="muted">{gen.verbs?.length ?? 0} verb(s)</span>
            </div>
            <CodeBlock value={gen.verbs ?? []} />
          </div>
        ) : (
          <p className="error">
            {gen.status}: {gen.reason ?? "rejected"}
          </p>
        ))}
    </div>
  );
}

// Activate an inert adapter, binding its verbs. The authenticated approval
// respondent is the reviewer; caller-supplied reviewer text is never trusted.
function ActivateAdapterForm({ onActivated }: { onActivated: () => void }) {
  const [actId, setActId] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [actResult, setActResult] = useState<string[] | null>(null);
  const mutation = useControlMutation({
    verb: "control.adapter.activate",
    onApplied: (output) => {
      const verbs = outputRecord(output).verbs;
      setActResult(
        Array.isArray(verbs)
          ? verbs.filter((verb): verb is string => typeof verb === "string")
          : [],
      );
      onActivated();
    },
  });

  async function activate() {
    if (!actId.trim()) {
      setValidationError("adapter id is required.");
      return;
    }
    setValidationError(null);
    setActResult(null);
    await mutation.invoke({ adapter_id: actId.trim() });
  }

  return (
    <div className="form">
      <div className="form__title">Activate adapter</div>
      <label className="field">
        <span>adapter id</span>
        <input value={actId} onChange={(e) => setActId(e.target.value)} />
      </label>
      {mutation.pending && (
        <PendingHumanCard
          hitlRequestId={mutation.pending.id}
          noun="control"
          verb="control.adapter.activate"
          sentParams={mutation.pending.params}
          onApplied={mutation.onPendingApplied}
          onDenied={mutation.onPendingDenied}
          onReset={mutation.resetPending}
        />
      )}
      <div className="form__actions">
        <button
          className="btn"
          disabled={mutation.busy || mutation.pending !== null}
          onClick={activate}
        >
          {mutation.busy ? "..." : "Activate"}
        </button>
        {(validationError ?? mutation.error) && (
          <span className="error">{validationError ?? mutation.error}</span>
        )}
      </div>
      {actResult && (
        <p className="ok">
          Activated. Bound verbs: {actResult.join(", ") || "(none)"}
        </p>
      )}
    </div>
  );
}

// Register an MCP server as an adapter source.
function RegisterMcpForm({ onRegistered }: { onRegistered: () => void }) {
  const [mcpId, setMcpId] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpToken, setMcpToken] = useState("");
  const [mcpBusy, setMcpBusy] = useState(false);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [mcpAck, setMcpAck] = useState<StatusAck | null>(null);

  async function registerMcp() {
    if (!mcpId.trim()) {
      setMcpError("MCP server id is required.");
      return;
    }
    setMcpBusy(true);
    setMcpError(null);
    setMcpAck(null);
    try {
      const res = await api.registerMcpServer({
        id: mcpId.trim(),
        url: mcpUrl.trim() || undefined,
        token: mcpToken.trim() || undefined,
      });
      setMcpAck(res);
      if (res.status === "ok") onRegistered();
    } catch (err) {
      setMcpError(errText(err));
    } finally {
      setMcpBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">Register MCP server</div>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input value={mcpId} onChange={(e) => setMcpId(e.target.value)} />
        </label>
        <label className="field">
          <span>url</span>
          <input
            value={mcpUrl}
            onChange={(e) => setMcpUrl(e.target.value)}
          />
        </label>
        <label className="field">
          <span>token</span>
          <input
            value={mcpToken}
            onChange={(e) => setMcpToken(e.target.value)}
          />
        </label>
      </div>
      <div className="form__actions">
        <button className="btn" disabled={mcpBusy} onClick={registerMcp}>
          {mcpBusy ? "..." : "Register"}
        </button>
        <AckLine ack={mcpAck} />
        {mcpError && <span className="error">{mcpError}</span>}
      </div>
    </div>
  );
}

function AdapterInventory({
  inventory,
}: {
  inventory: FetchState<AdapterInventoryResponse>;
}) {
  const records: AdapterRecord[] = inventory.data?.adapters ?? [];
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Adapter inventory</h3>
        <button className="btn" onClick={() => inventory.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {inventory.loading && !inventory.data && (
          <p className="muted">Loading...</p>
        )}
        {inventory.error && (
          <p className="error">Failed to load: {inventory.error}</p>
        )}
        {!inventory.loading && records.length === 0 && (
          <p className="muted">No adapters registered.</p>
        )}
        {records.map((a) => (
          <div className="row-line" key={a.id}>
            <div>
              <code>{a.id}</code>{" "}
              <span className="muted">
                {a.runtime} v{a.version}
              </span>
            </div>
            <div className="kv">
              <span
                className={`badge ${a.activated ? "badge--activated" : "badge--inert"}`}
              >
                {a.activated ? "activated" : "inert"}
              </span>
              <span className={`badge badge--${a.health}`}>{a.health}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AdapterStudio() {
  const inventory = useFetch(() => api.adapters(), []);
  const reload = () => inventory.reload();

  return (
    <div className="cols">
      <div className="stack">
        <GenerateAdapterForm onGenerated={reload} />
        <ActivateAdapterForm onActivated={reload} />
        <RegisterMcpForm onRegistered={reload} />
      </div>
      <AdapterInventory inventory={inventory} />
    </div>
  );
}
