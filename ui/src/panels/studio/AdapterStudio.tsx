import { useState } from "react";

import { api } from "../../api/client";
import type {
  GenerateAdapterResponse,
  StatusAck,
} from "../../api/types";
import { useFetch } from "../../useFetch";
import { CodeBlock, errText, parseJson } from "../shared";
import {
  PendingHumanCard,
  type ControlMutationState,
} from "../uxFlow";
import { AckLine } from "./AckLine";
import { AdapterInventory } from "./adapterStudio/AdapterInventory";
import { OpenApiImport } from "./adapterStudio/IntegrationFields";

function AdapterActivationPending({
  mutation,
}: {
  mutation: ControlMutationState;
}) {
  if (mutation.pending === null) return null;
  return (
    <PendingHumanCard
      hitlRequestId={mutation.pending.id}
      noun="control"
      verb="control.adapter.activate"
      sentParams={mutation.pending.params}
      onApplied={mutation.onPendingApplied}
      onDenied={mutation.onPendingDenied}
      onReset={mutation.resetPending}
    />
  );
}

// Generate an adapter from an OpenAPI spec. It lands inert (activated: false)
// and reloads the inventory on success so the reviewer sees it immediately.
function GenerateAdapterForm({ onGenerated }: { onGenerated: () => void }) {
  const [adapterId, setAdapterId] = useState("");
  const [spec, setSpec] = useState("");
  const [genBusy, setGenBusy] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [gen, setGen] = useState<GenerateAdapterResponse | null>(null);

  async function generate() {
    if (!adapterId.trim()) {
      setGenError("adapter_id is required.");
      return;
    }
    if (!spec.trim()) {
      setGenError("Import an OpenAPI JSON document first.");
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
      <OpenApiImport value={spec} onChange={setSpec} onError={setGenError} />
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

// Register an MCP server as an adapter source.
function RegisterMcpForm({ onRegistered }: { onRegistered: () => void }) {
  const [mcpId, setMcpId] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpBusy, setMcpBusy] = useState(false);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [mcpAck, setMcpAck] = useState<StatusAck | null>(null);

  async function registerMcp() {
    if (!mcpId.trim()) {
      setMcpError("MCP server id is required.");
      return;
    }
    // SDK 0.2.0 types url as required - the register verb needs somewhere to
    // connect to, so surface that here instead of a server-side rejection.
    if (!mcpUrl.trim()) {
      setMcpError("MCP server URL is required.");
      return;
    }
    setMcpBusy(true);
    setMcpError(null);
    setMcpAck(null);
    try {
      const res = await api.registerMcpServer({
        id: mcpId.trim(),
        url: mcpUrl.trim(),
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
      <p className="muted">
        Credentials must be provisioned through the server-side credential store
        and referenced by deployment configuration. Studio never accepts or
        displays raw MCP tokens.
      </p>
      <div className="form__grid">
        <label className="field">
          <span>id</span>
          <input
            aria-label="MCP server id"
            value={mcpId}
            onChange={(e) => setMcpId(e.target.value)}
          />
        </label>
        <label className="field">
          <span>url</span>
          <input
            aria-label="MCP server URL"
            value={mcpUrl}
            onChange={(e) => setMcpUrl(e.target.value)}
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

export function AdapterStudio() {
  const inventory = useFetch(() => api.adapters(), []);
  const reload = () => inventory.reload();

  return (
    <div className="cols">
      <div className="stack">
        <GenerateAdapterForm onGenerated={reload} />
        <RegisterMcpForm onRegistered={reload} />
      </div>
      <AdapterInventory
        inventory={inventory}
        renderPending={(mutation) => (
          <AdapterActivationPending mutation={mutation} />
        )}
      />
    </div>
  );
}
