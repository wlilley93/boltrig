import { useState, type ReactNode } from "react";

import { api } from "@/api/client";
import type { AdapterInventoryResponse, AdapterRecord } from "@/api/types";
import { CodeBlock, errText } from "@/panels/shared";
import {
  ArmConfirm,
  Disclosure,
  outputRecord,
  useControlMutation,
  type ControlMutationState,
} from "@/panels/uxFlow";
import type { FetchState } from "@/useFetch";

const KNOWN_HEALTH = new Set(["ok", "degraded", "down", "unknown"]);

function healthClass(health: string): string {
  return KNOWN_HEALTH.has(health) ? health : "unknown";
}

function AdapterInventoryRow({
  adapter,
  onChanged,
  renderPending,
}: {
  adapter: AdapterRecord;
  onChanged: () => void;
  renderPending: (mutation: ControlMutationState) => ReactNode;
}) {
  const [reviewOpen, setReviewOpen] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [sourceBusy, setSourceBusy] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [activationMessage, setActivationMessage] = useState<string | null>(null);
  const lifecycle = adapter.activated ? "active" : "inert";
  const health = String(adapter.health || "unknown");
  const mutation = useControlMutation({
    verb: "control.adapter.activate",
    onApplied: (output) => {
      const verbs = outputRecord(output).verbs;
      const count = Array.isArray(verbs) ? verbs.length : 0;
      setActivationMessage(
        `Activated${count > 0 ? ` and published ${count} verb(s)` : ""}.`,
      );
      onChanged();
    },
  });

  async function toggleSource() {
    setReviewOpen(true);
    if (sourceOpen) {
      setSourceOpen(false);
      return;
    }
    setSourceOpen(true);
    if (source !== null || sourceBusy) return;
    setSourceBusy(true);
    setSourceError(null);
    try {
      const response = await api.adapterSource(adapter.id);
      if (response.error) setSourceError(response.error);
      else setSource(response.source ?? "");
    } catch (error) {
      setSourceError(errText(error));
    } finally {
      setSourceBusy(false);
    }
  }

  function toggleReview() {
    if (reviewOpen) {
      setReviewOpen(false);
      setSourceOpen(false);
      return;
    }
    setReviewOpen(true);
  }

  async function activate() {
    setActivationMessage(null);
    await mutation.invoke({ adapter_id: adapter.id });
  }

  return (
    <article className="stack" aria-label={`Adapter ${adapter.id}`}>
      <div className="row-line">
        <div>
          <code>{adapter.id}</code>{" "}
          <span className="muted">
            {adapter.runtime} v{adapter.version}
          </span>
        </div>
        <div className="kv" aria-label="Adapter state">
          <span
            className={`badge ${adapter.activated ? "badge--activated" : "badge--inert"}`}
          >
            {lifecycle}
          </span>
          <span className={`badge badge--${healthClass(health)}`}>
            health: {health}
          </span>
        </div>
      </div>

      <div className="form__actions">
        <button
          type="button"
          className="btn btn--sm"
          aria-expanded={reviewOpen}
          onClick={toggleReview}
        >
          Review
        </button>
        <button
          type="button"
          className="btn btn--sm"
          aria-expanded={sourceOpen}
          disabled={sourceBusy}
          onClick={() => void toggleSource()}
        >
          {sourceBusy ? "Loading source..." : sourceOpen ? "Hide source" : "Source"}
        </button>
        <ArmConfirm
          label={adapter.activated ? "Active" : "Activate"}
          armLabel={`Activate ${adapter.id} and publish its reviewed verbs? A separate human approval is still required.`}
          confirmLabel="Confirm activation"
          tone="consequence"
          busyLabel="Requesting..."
          onConfirm={activate}
          disabled={
            adapter.activated || mutation.busy || mutation.pending !== null
          }
        />
      </div>

      {reviewOpen && (
        <div className="notice" aria-label={`Review ${adapter.id}`}>
          <div className="kv">
            <span>
              Lifecycle <strong>{lifecycle}</strong>
            </span>
            <span>
              Runtime <code>{adapter.runtime}</code>
            </span>
            <span>
              Origin <code>{adapter.source}</code>
            </span>
            <span>
              Health <strong>{health}</strong>
            </span>
          </div>
          <p className="muted">
            Lifecycle controls whether verbs are published. Health is a separate
            best-effort runtime probe and does not make an inert adapter callable.
          </p>
          {sourceOpen && (
            <Disclosure summary="Generated source" defaultOpen>
              {sourceBusy && <p className="muted">Loading source...</p>}
              {sourceError && (
                <p className="error">Source unavailable: {sourceError}</p>
              )}
              {source !== null && <CodeBlock value={source} />}
            </Disclosure>
          )}
        </div>
      )}

      {mutation.pending && (
        renderPending(mutation)
      )}
      {mutation.error && <p className="error">{mutation.error}</p>}
      {activationMessage && <p className="ok">{activationMessage}</p>}
    </article>
  );
}

export function AdapterInventory({
  inventory,
  renderPending,
}: {
  inventory: FetchState<AdapterInventoryResponse>;
  renderPending: (mutation: ControlMutationState) => ReactNode;
}) {
  const records = inventory.data?.adapters ?? [];
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Adapter inventory</h3>
        <button type="button" className="btn" onClick={() => inventory.reload()}>
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
        {records.map((adapter) => (
          <AdapterInventoryRow
            adapter={adapter}
            key={adapter.id}
            onChanged={inventory.reload}
            renderPending={renderPending}
          />
        ))}
      </div>
    </div>
  );
}
