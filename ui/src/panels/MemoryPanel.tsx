// Round Five memory & knowledge surface (Epic MUI). Four sub-tabs behind
// internal state (no router): Recall, Browse, Remember and Ingest. Every view
// is scope-filtered to the caller server-side (SEC-40), so an empty result is
// scoping, not a bug, and each recalled fact carries provenance that shows WHY
// it is known. recall / remember / forget / ingest run the memory.* verbs
// through the kernel chokepoint; when memory is not enabled those routes return
// {status:"error", reason:"binding_not_found"} which this panel surfaces as
// "memory not enabled".

import { useState } from "react";

import { api } from "../api/client";
import type {
  MemoryIngestResponse,
  MemoryIngestionRow,
  MemoryRememberResponse,
} from "../api/types";
import { useFetch } from "../useFetch";
import { errText } from "./shared";
import {
  Field,
  Hint,
  InfoCallout,
  PageIntro,
  Select,
} from "./ux";
import {
  denialText,
  isDenied,
  KIND_OPTIONS,
  MEMORY_TABS,
  SOURCE_KIND_OPTIONS,
  type MemoryTab,
} from "./memoryPanel/helpers";
import { RecallTab } from "./memoryPanel/RecallTab";
import { BrowseTab } from "./memoryPanel/BrowseTab";

// --- Remember ---------------------------------------------------------------

function RememberTab() {
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("");
  const [dataClass, setDataClass] = useState<"standard" | "sensitive">(
    "standard",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MemoryRememberResponse | null>(null);

  async function remember() {
    if (!content.trim()) {
      setError("Content is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.memoryRemember({
        content: content.trim(),
        kind: kind.trim() || undefined,
        data_class: dataClass,
      });
      if (isDenied(res)) {
        setError(denialText(res.reason));
        return;
      }
      setResult(res);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="form">
        <div className="form__title">Remember</div>
        <p className="muted">
          Commit a fact to memory. It is screened before it persists and lands
          in your own scope. Sensitive content is held to a local-only endpoint
          (SEC-43).
        </p>
        <Field
          label="What should the assistant remember?"
          hint="A single fact, in plain language. It is screened before it is saved, and lands in your own scope."
          example="Priya is the account owner for Acme."
        >
          <textarea
            className="code"
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        </Field>
        <div className="form__grid">
          <Field label="Type" hint="What kind of fact this is.">
            <Select
              value={kind || "entity"}
              ariaLabel="Fact type"
              onChange={setKind}
              options={KIND_OPTIONS}
            />
          </Field>
          <Field
            label="Sensitivity"
            hint="Sensitive facts never leave this deployment (SEC-43) - choose this for personal or confidential content."
          >
            <Select
              value={dataClass}
              ariaLabel="Sensitivity"
              onChange={(v) => setDataClass(v === "sensitive" ? "sensitive" : "standard")}
              options={[
                { value: "standard", label: "Standard" },
                { value: "sensitive", label: "Sensitive (kept local-only)" },
              ]}
            />
          </Field>
        </div>
        {dataClass === "sensitive" && (
          <InfoCallout tone="warn">
            Sensitive content is held to a local-only endpoint and never sent to
            an external model.
          </InfoCallout>
        )}
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={busy}
            onClick={remember}
          >
            {busy ? "..." : "Remember"}
          </button>
          {error && <span className="error">{error}</span>}
        </div>
        {result && (
          <div className="stack">
            <p className="ok">
              Saved to scope <code>{result.owner_scope ?? "?"}</code>.
            </p>
            <div className="row-line">
              <span className="muted">fact id(s)</span>
              <span className="kv">
                {(result.fact_ids ?? []).map((id) => (
                  <code className="tag" key={id}>
                    {id}
                  </code>
                ))}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Ingest -----------------------------------------------------------------

function IngestTab() {
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
          <button className="btn btn--primary" disabled={busy} onClick={ingest}>
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

      <div className="list-card">
        <div className="list-card__head">
          <h3>Ingestions</h3>
          <div className="panel__actions">
            <span className="muted">{rows.length}</span>
            <button className="btn" onClick={() => ingestions.reload()}>
              Refresh
            </button>
          </div>
        </div>
        <div className="list-card__body">
          {ingestions.loading && !ingestions.data && (
            <p className="muted">Loading...</p>
          )}
          {ingestions.error && (
            <p className="error">Failed to load: {ingestions.error}</p>
          )}
          {!ingestions.loading && rows.length === 0 && (
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
    </div>
  );
}

// --- the panel --------------------------------------------------------------

export function MemoryPanel() {
  const [sub, setSub] = useState<MemoryTab>("recall");

  return (
    <section className="panel">
      <PageIntro
        title="Memory"
        lead="This is what the assistant remembers - facts it can use to help you."
        how="Recall searches it, Browse lists it, Remember adds a fact, Ingest loads a whole source. You only ever see memory you're allowed to. If memory isn't enabled for your org, the actions report 'memory not enabled'."
      />

      <nav className="subtabs" aria-label="Memory sections">
        {MEMORY_TABS.map((t) => (
          <button
            key={t.id}
            className={`subtab ${sub === t.id ? "subtab--active" : ""}`}
            onClick={() => setSub(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "recall" && <RecallTab />}
      {sub === "browse" && <BrowseTab />}
      {sub === "remember" && <RememberTab />}
      {sub === "ingest" && <IngestTab />}
    </section>
  );
}
