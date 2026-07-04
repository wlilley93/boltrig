import { useState } from "react";

import { api } from "@/api/client";
import type { MemoryIngestResponse, MemoryIngestionRow } from "@/api/types";
import { useFetch } from "@/useFetch";
import { errText } from "@/panels/shared";
import { Field, Hint, Select } from "@/panels/ux";
import { denialText, isDenied, SOURCE_KIND_OPTIONS } from "@/panels/memoryPanel/helpers";

type IngestFormProps = {
  sourceKind: string;
  setSourceKind: (v: string) => void;
  sourceRef: string;
  setSourceRef: (v: string) => void;
  items: string;
  setItems: (v: string) => void;
  busy: boolean;
  error: string | null;
  result: MemoryIngestResponse | null;
  onSubmit: () => void;
};

function IngestForm(props: IngestFormProps) {
  const {
    sourceKind,
    setSourceKind,
    sourceRef,
    setSourceRef,
    items,
    setItems,
    busy,
    error,
    result,
    onSubmit,
  } = props;
  return (
    <div className="form">
      <div className="form__title">Load a source into memory</div>
      <Hint>
        Each line below becomes a fact. Everything is screened for injection or
        malware before any of it is saved (SEC-42); anything risky is reported
        and never persisted.
      </Hint>
      <div className="form__grid">
        <Field label="Where it comes from" hint="The kind of source you're loading.">
          <Select
            value={sourceKind}
            ariaLabel="Source kind"
            onChange={setSourceKind}
            options={SOURCE_KIND_OPTIONS}
          />
        </Field>
        <Field
          label="Source reference"
          hint="A URL or identifier for the source, for provenance."
          example="https://wiki/onboarding"
        >
          <input
            value={sourceRef}
            onChange={(e) => setSourceRef(e.target.value)}
          />
        </Field>
      </div>
      <Field label="Items" hint="One fact or passage per line.">
        <textarea
          className="code"
          value={items}
          placeholder={"One fact or passage per line\nAnother fact"}
          onChange={(e) => setItems(e.target.value)}
        />
      </Field>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={onSubmit}>
          {busy ? "..." : "Ingest"}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
      {result && (
        <div className="kv">
          <span className="badge badge--ok">{result.ingestion_status}</span>
          <span className="badge">facts_added: {result.facts_added ?? 0}</span>
          <span className="badge">screened: {result.screened ?? 0}</span>
          {result.id && <code className="tag">{result.id}</code>}
        </div>
      )}
    </div>
  );
}

type IngestHistoryProps = {
  rows: MemoryIngestionRow[];
  loading: boolean;
  hasData: boolean;
  error: string | null;
  onRefresh: () => void;
};

function IngestHistory({ rows, loading, hasData, error, onRefresh }: IngestHistoryProps) {
  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Ingestions</h3>
        <div className="panel__actions">
          <span className="muted">{rows.length}</span>
          <button className="btn" onClick={onRefresh}>
            Refresh
          </button>
        </div>
      </div>
      <div className="list-card__body">
        {loading && !hasData && (
          <p className="muted">Loading...</p>
        )}
        {error && (
          <p className="error">Failed to load: {error}</p>
        )}
        {!loading && rows.length === 0 && (
          <p className="muted">No ingestions yet.</p>
        )}
        {rows.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>source_kind</th>
                  <th>source_ref</th>
                  <th>owner_scope</th>
                  <th>status</th>
                  <th>facts_added</th>
                  <th>screened</th>
                  <th>created_at</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.source_kind}</td>
                    <td>
                      <code>{row.source_ref || "-"}</code>
                    </td>
                    <td>{row.owner_scope}</td>
                    <td>{row.status}</td>
                    <td>{row.facts_added}</td>
                    <td>{row.screened}</td>
                    <td>{row.created_at ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export function IngestTab() {
  const ingestions = useFetch(() => api.memoryIngestions(), []);

  const [sourceKind, setSourceKind] = useState("document");
  const [sourceRef, setSourceRef] = useState("");
  const [items, setItems] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MemoryIngestResponse | null>(null);

  async function ingest() {
    if (!sourceKind.trim()) {
      setError("source_kind is required.");
      return;
    }
    // newline-separated lines become items[]; trims and drops empties.
    const lines = items
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.memoryIngest({
        source_kind: sourceKind.trim(),
        source_ref: sourceRef.trim(),
        items: lines,
      });
      if (isDenied(res)) {
        setError(denialText(res.reason));
        return;
      }
      setResult(res);
      ingestions.reload();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const rows: MemoryIngestionRow[] = ingestions.data?.ingestions ?? [];

  return (
    <div className="stack">
      <IngestForm
        sourceKind={sourceKind}
        setSourceKind={setSourceKind}
        sourceRef={sourceRef}
        setSourceRef={setSourceRef}
        items={items}
        setItems={setItems}
        busy={busy}
        error={error}
        result={result}
        onSubmit={ingest}
      />
      <IngestHistory
        rows={rows}
        loading={ingestions.loading}
        hasData={!!ingestions.data}
        error={ingestions.error}
        onRefresh={ingestions.reload}
      />
    </div>
  );
}
