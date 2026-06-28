// Round Five memory & knowledge surface (Epic MUI). Four sub-tabs behind
// internal state (no router): Recall, Browse, Remember and Ingest. Every view
// is scope-filtered to the caller server-side (SEC-40), so an empty result is
// scoping, not a bug, and each recalled fact carries provenance that shows WHY
// it is known. recall / remember / forget / ingest run the memory.* verbs
// through the kernel chokepoint; when memory is not enabled those routes return
// {status:"error", reason:"binding_not_found"} which this panel surfaces as
// "memory not enabled".

import { useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import type {
  MemoryFactView,
  MemoryIngestResponse,
  MemoryIngestionRow,
  MemoryProvenance,
  MemoryRememberResponse,
  RecallMode,
} from "../api/types";
import { useFetch } from "../useFetch";
import { CodeBlock, errText } from "./shared";

type MemoryTab = "recall" | "browse" | "remember" | "ingest";

const MEMORY_TABS: ReadonlyArray<{ id: MemoryTab; label: string }> = [
  { id: "recall", label: "Recall" },
  { id: "browse", label: "Browse" },
  { id: "remember", label: "Remember" },
  { id: "ingest", label: "Ingest" },
];

// The verb routes answer with {status:"error"|"denied", reason} when memory is
// off or the caller cannot reach a scope. binding_not_found means the memory
// subsystem is not enabled for this tenant.
function isDenied(res: { status?: string }): boolean {
  return res.status === "error" || res.status === "denied";
}

function denialText(reason?: string): string {
  if (!reason || reason === "binding_not_found") return "memory not enabled";
  return reason;
}

// One fact rendered as a card: content plus the metadata (owner_scope, kind,
// data_class) and the provenance that shows how/why it is known. An optional
// footer carries per-tab controls (e.g. the Browse "Forget" button).
function FactCard({
  fact,
  footer,
}: {
  fact: MemoryFactView;
  footer?: ReactNode;
}) {
  const prov: MemoryProvenance = fact.provenance ?? {};
  const hasHops = typeof prov.hops === "number";
  const path = prov.path ?? [];
  return (
    <div className="mem-fact">
      <div className="mem-fact__head">
        <span className="kv">
          <code className="tag">{fact.kind}</code>
          <span className="badge">{fact.owner_scope}</span>
          <span
            className={`badge ${
              fact.data_class === "sensitive" ? "badge--down" : "badge--ok"
            }`}
          >
            {fact.data_class}
          </span>
        </span>
        <code className="muted mem-fact__id">{fact.id}</code>
      </div>

      {typeof fact.content === "string" ? (
        <p className="mem-fact__text">{fact.content}</p>
      ) : (
        <CodeBlock value={fact.content} />
      )}

      <div className="mem-fact__prov">
        <span className="muted">
          via {prov.source_kind ?? "unknown"}
          {prov.source_ref ? " from " : ""}
        </span>
        {prov.source_ref && <code className="tag">{prov.source_ref}</code>}
        {prov.created_at && (
          <span className="muted">{prov.created_at}</span>
        )}
        {hasHops && <span className="badge">hops: {prov.hops}</span>}
      </div>

      {path.length > 0 && (
        <div className="mem-fact__path">
          <span className="muted">path:</span>
          <span className="kv">
            {path.map((step, i) => (
              <code className="tag" key={`${step}-${i}`}>
                {step}
              </code>
            ))}
          </span>
        </div>
      )}

      {footer && <div className="mem-fact__foot">{footer}</div>}
    </div>
  );
}

// --- Recall -----------------------------------------------------------------

function RecallTab() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<RecallMode>("graph_completion");
  const [limit, setLimit] = useState("20");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [facts, setFacts] = useState<MemoryFactView[] | null>(null);
  const [count, setCount] = useState(0);

  async function recall() {
    if (!query.trim()) {
      setError("A query is required.");
      return;
    }
    const parsedLimit = Number.parseInt(limit, 10);
    setBusy(true);
    setError(null);
    setFacts(null);
    try {
      const res = await api.memoryRecall({
        query: query.trim(),
        mode,
        limit: Number.isFinite(parsedLimit) ? parsedLimit : undefined,
      });
      if (isDenied(res)) {
        setError(denialText(res.reason));
        return;
      }
      setFacts(res.facts ?? []);
      setCount(res.count ?? (res.facts ?? []).length);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="form">
        <div className="form__title">Recall</div>
        <p className="muted">
          Results are scope-filtered to you (SEC-40): you only ever see your
          user scope, the org scope and your departments. Each fact shows its
          provenance - in graph mode that includes the hops and the path taken -
          so you can see why a fact is known.
        </p>
        <label className="field">
          <span>query</span>
          <textarea
            className="code"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="form__grid">
          <label className="field">
            <span>mode</span>
            <select
              value={mode}
              onChange={(e) =>
                setMode(
                  e.target.value === "similarity"
                    ? "similarity"
                    : "graph_completion",
                )
              }
            >
              <option value="graph_completion">graph_completion</option>
              <option value="similarity">similarity</option>
            </select>
          </label>
          <label className="field">
            <span>limit</span>
            <input
              value={limit}
              inputMode="numeric"
              onChange={(e) => setLimit(e.target.value)}
            />
          </label>
        </div>
        <div className="form__actions">
          <button className="btn btn--primary" disabled={busy} onClick={recall}>
            {busy ? "..." : "Recall"}
          </button>
          {error && <span className="error">{error}</span>}
        </div>
      </div>

      {facts && (
        <div className="list-card">
          <div className="list-card__head">
            <h3>Results</h3>
            <span className="muted">{count}</span>
          </div>
          <div className="list-card__body">
            {facts.length === 0 ? (
              <p className="muted">No facts in scope for this query.</p>
            ) : (
              <div className="mem-facts">
                {facts.map((f) => (
                  <FactCard fact={f} key={f.id} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// --- Browse -----------------------------------------------------------------

function BrowseTab() {
  const [kind, setKind] = useState("");
  const [applied, setApplied] = useState("");
  const facts = useFetch(
    () => api.memoryFacts({ kind: applied.trim() || undefined }),
    [applied],
  );

  // forget state, keyed by fact id so each row's button is independent.
  const [forgetting, setForgetting] = useState<string | null>(null);
  const [forgetError, setForgetError] = useState<string | null>(null);
  const [forgetMsg, setForgetMsg] = useState<string | null>(null);

  async function forget(id: string) {
    if (!window.confirm(`Forget fact ${id}? This erases it and its edges.`)) {
      return;
    }
    setForgetting(id);
    setForgetError(null);
    setForgetMsg(null);
    try {
      const res = await api.memoryForget({ target: id });
      if (isDenied(res)) {
        setForgetError(denialText(res.reason));
        return;
      }
      setForgetMsg(
        `Forgot ${id}: ${res.facts_removed ?? 0} fact(s) removed.`,
      );
      facts.reload();
    } catch (err) {
      setForgetError(errText(err));
    } finally {
      setForgetting(null);
    }
  }

  const list: MemoryFactView[] = facts.data?.facts ?? [];
  const scopes = facts.data?.scopes ?? [];

  return (
    <div className="stack">
      <div className="form">
        <div className="form__title">Browse facts</div>
        <p className="muted">
          The facts you may see, with provenance. Scope-filtered server-side, so
          another user's or department's memory never appears here.
        </p>
        <div className="form__actions">
          <label className="field">
            <span>kind (optional)</span>
            <input value={kind} onChange={(e) => setKind(e.target.value)} />
          </label>
          <button
            className="btn btn--primary"
            onClick={() => setApplied(kind)}
          >
            Apply
          </button>
          <button className="btn" onClick={() => facts.reload()}>
            Refresh
          </button>
        </div>
        {scopes.length > 0 && (
          <p className="muted">
            scopes:{" "}
            {scopes.map((s) => (
              <code className="tag" key={s}>
                {s}
              </code>
            ))}
          </p>
        )}
        {forgetMsg && <p className="ok">{forgetMsg}</p>}
        {forgetError && <p className="error">{forgetError}</p>}
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>Facts</h3>
          <span className="muted">{list.length}</span>
        </div>
        <div className="list-card__body">
          {facts.loading && !facts.data && <p className="muted">Loading...</p>}
          {facts.error && (
            <p className="error">Failed to load: {facts.error}</p>
          )}
          {!facts.loading && list.length === 0 && (
            <p className="muted">No facts in scope.</p>
          )}
          {list.length > 0 && (
            <div className="mem-facts">
              {list.map((f) => (
                <FactCard
                  fact={f}
                  key={f.id}
                  footer={
                    <button
                      className="btn"
                      disabled={forgetting === f.id}
                      onClick={() => forget(f.id)}
                    >
                      {forgetting === f.id ? "..." : "Forget"}
                    </button>
                  }
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

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
        <label className="field">
          <span>content</span>
          <textarea
            className="code"
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        </label>
        <div className="form__grid">
          <label className="field">
            <span>kind (optional)</span>
            <input value={kind} onChange={(e) => setKind(e.target.value)} />
          </label>
          <label className="field">
            <span>data_class</span>
            <select
              value={dataClass}
              onChange={(e) =>
                setDataClass(
                  e.target.value === "sensitive" ? "sensitive" : "standard",
                )
              }
            >
              <option value="standard">standard</option>
              <option value="sensitive">sensitive</option>
            </select>
          </label>
        </div>
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
        <div className="form__title">Ingest a source</div>
        <p className="muted">
          Cognify a source into memory. Items are screened for injection /
          malware before any of them become facts (SEC-42); screened-out items
          are reported but never persisted.
        </p>
        <div className="form__grid">
          <label className="field">
            <span>source_kind</span>
            <input
              value={sourceKind}
              onChange={(e) => setSourceKind(e.target.value)}
            />
          </label>
          <label className="field">
            <span>source_ref</span>
            <input
              value={sourceRef}
              onChange={(e) => setSourceRef(e.target.value)}
            />
          </label>
        </div>
        <label className="field">
          <span>items (one per line)</span>
          <textarea
            className="code"
            value={items}
            onChange={(e) => setItems(e.target.value)}
          />
        </label>
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
      <div className="panel__head">
        <h2>Memory</h2>
        <div className="panel__actions">
          <span className="muted">scope-filtered knowledge</span>
        </div>
      </div>

      <p className="notice">
        Memory is governed by the kernel: every read is scope-filtered to you
        (SEC-40) and every write runs the memory.* verbs through the chokepoint
        (grant check + audit). If memory is not enabled for this tenant, the
        actions below report "memory not enabled".
      </p>

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
