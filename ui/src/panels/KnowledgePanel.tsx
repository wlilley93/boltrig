import { useState } from "react";

import { api } from "@/api/client";
import type {
  KnowledgeAsset,
  KnowledgeProvider,
  KnowledgeSearchHit,
} from "@/api/types";
import { errText } from "@/panels/shared";
import { EmptyState, Field, Hint, PageIntro } from "@/panels/ux";
import { ByChat } from "@/panels/uxFlow";
import { useFetch } from "@/useFetch";

type Tab = "library" | "search" | "providers";
const TABS: Array<{ id: Tab; label: string }> = [
  { id: "library", label: "Library" },
  { id: "search", label: "Search" },
  { id: "providers", label: "Providers" },
];

export function KnowledgePanel() {
  const [tab, setTab] = useState<Tab>("library");
  const assets = useFetch(() => api.knowledgeAssets(), []);
  const providers = useFetch(() => api.knowledgeProviders(), []);

  return (
    <section className="panel knowledge">
      <PageIntro
        title="Knowledge"
        lead="Your source documents, searchable by filename and passage, with citations back to the original."
        how="Boltrig keeps the original and revision record authoritative. Cognee compiles relationships after that commit; its failure never changes the source. Memory remains a separate, revisable layer."
        howToggle
      />
      <nav className="subtabs" aria-label="Knowledge sections" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={`subtab ${tab === item.id ? "subtab--active" : ""}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      {tab === "library" && (
        <Library
          rows={assets.data?.assets ?? []}
          loading={assets.loading}
          error={assets.error}
          reload={assets.reload}
        />
      )}
      {tab === "search" && <Search />}
      {tab === "providers" && (
        <Providers
          rows={providers.data?.providers ?? []}
          loading={providers.loading}
          error={providers.error}
          reload={providers.reload}
        />
      )}
    </section>
  );
}

function Library({
  rows,
  loading,
  error,
  reload,
}: {
  rows: KnowledgeAsset[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [armed, setArmed] = useState<string | null>(null);

  async function upload() {
    if (!file) return setMessage("Choose a text, Markdown, or PDF file first.");
    if (file.size > 25 * 1024 * 1024) return setMessage("Files are limited to 25 MiB.");
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.uploadKnowledge(file, title);
      setMessage(`Saved ${file.name} as ${result.segment_count} cited passage(s).`);
      setFile(null);
      setTitle("");
      reload();
    } catch (reason) {
      setMessage(errText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function erase(asset: KnowledgeAsset) {
    if (armed !== asset.id) return setArmed(asset.id);
    setMessage(null);
    try {
      const result = await api.eraseKnowledgeAsset(asset.id);
      setMessage(
        result.hitl_request_id
          ? "Erasure is waiting for approval."
          : `${asset.title} was erased from canonical and derived storage.`,
      );
      setArmed(null);
      reload();
    } catch (reason) {
      setMessage(errText(reason));
    }
  }

  async function download(asset: KnowledgeAsset) {
    try {
      const blob = await api.knowledgeOriginal(asset.id);
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = asset.filename;
      link.click();
      URL.revokeObjectURL(href);
    } catch (reason) {
      setMessage(errText(reason));
    }
  }

  return (
    <div className="knowledge__grid">
      <div className="form knowledge__upload">
        <div className="form__title">Add a source</div>
        <Hint>The original is hashed and versioned before text, vectors, or Cognee output is derived.</Hint>
        <Field label="Document" hint="Text, Markdown, or PDF; maximum 25 MiB.">
          <input
            aria-label="Knowledge document"
            type="file"
            accept=".txt,.md,.markdown,.pdf,text/plain,text/markdown,application/pdf"
            onChange={(event) => {
              const next = event.target.files?.[0] ?? null;
              setFile(next);
              if (next && !title) setTitle(next.name.replace(/\.[^.]+$/, ""));
            }}
          />
        </Field>
        <Field label="Title" hint="The human-readable name used in search and citations.">
          <input
            aria-label="Knowledge title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <div className="form__actions">
          <button type="button" className="btn btn--primary" disabled={busy} onClick={upload}>
            {busy ? "Adding…" : "Add to Knowledge"}
          </button>
          {message && <span className="muted" role="status">{message}</span>}
        </div>
      </div>
      <div className="list-card">
        <div className="list-card__head"><h3>Source library</h3><span className="muted">{rows.length}</span></div>
        <div className="list-card__body">
          {loading && rows.length === 0 && <p className="muted">Loading sources…</p>}
          {error && <p className="error">{error}</p>}
          {!loading && !error && rows.length === 0 && (
            <EmptyState title="No source documents yet" body="Add a document to create your first citable Knowledge asset." />
          )}
          <div className="knowledge-list">
            {rows.map((asset) => (
              <article className="knowledge-asset" key={asset.id}>
                <div><strong>{asset.title}</strong><div className="muted">{asset.filename} · {asset.segment_count} passages</div></div>
                <div className="knowledge-asset__actions">
                  <button type="button" className="btn" onClick={() => download(asset)}>Original</button>
                  <button
                    type="button"
                    className={`btn ${armed === asset.id ? "ux-btn--danger" : ""}`}
                    aria-label={armed === asset.id ? `Confirm erase ${asset.title}` : `Erase ${asset.title}`}
                    onClick={() => erase(asset)}
                  >
                    {armed === asset.id ? "Confirm erase" : "Erase"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Search() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<KnowledgeSearchHit[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setHits((await api.knowledgeSearch(query.trim())).hits);
    } catch (reason) {
      setError(errText(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="form">
        <Field label="Search all accessible sources" hint="Use an exact phrase, filename, topic, person, or question.">
          <input
            aria-label="Search Knowledge"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") void run(); }}
            placeholder="Where did we decide the renewal period?"
          />
        </Field>
        <div className="form__actions">
          <button type="button" className="btn btn--primary" disabled={busy || !query.trim()} onClick={run}>
            {busy ? "Searching…" : "Search"}
          </button>
          {query.trim() && <ByChat phrase={`Use Knowledge to answer: ${query.trim()}. Cite every source.`} />}
          {error && <span className="error">{error}</span>}
        </div>
      </div>
      {hits.length === 0 && !busy && (
        <EmptyState title="Search your sources" body="Results include the exact revision, passage, page or paragraph locator, and content hash." />
      )}
      {hits.map((hit) => <SearchResult key={hit.segment_id} hit={hit} />)}
    </div>
  );
}

function SearchResult({ hit }: { hit: KnowledgeSearchHit }) {
  const locator = Object.entries(hit.citation.locator)
    .map(([key, value]) => `${key.replace(/_/g, " ")} ${String(value)}`)
    .join(" · ");
  return (
    <article className="list-card knowledge-hit">
      <div className="list-card__head"><h3>{hit.title}</h3><span className="badge">{hit.score.toFixed(2)}</span></div>
      <div className="list-card__body">
        <p>{hit.text}</p>
        <div className="knowledge-citation">
          <code>{hit.filename}</code><span>{locator || "document passage"}</span>
          <span title={hit.citation.content_hash}>revision {hit.revision_id.slice(-8)}</span>
        </div>
      </div>
    </article>
  );
}

function Providers({
  rows,
  loading,
  error,
  reload,
}: {
  rows: KnowledgeProvider[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}) {
  const [message, setMessage] = useState<string | null>(null);
  async function toggle(provider: KnowledgeProvider) {
    setMessage(null);
    if (provider.status === "unavailable") {
      setMessage(
        provider.last_error
          ? `${provider.display_name} is unavailable: ${provider.last_error}`
          : `${provider.display_name} is unavailable in this build.`,
      );
      return;
    }
    try {
      const result = await api.setKnowledgeProvider(provider.id, !provider.enabled);
      setMessage(
        result.hitl_request_id
          ? `${provider.display_name} enablement is waiting for approval.`
          : `${provider.display_name} ${provider.enabled ? "disabled" : "enabled"}.`,
      );
      reload();
    } catch (reason) {
      setMessage(errText(reason));
    }
  }
  return (
    <div className="stack">
      <div className="list-card">
        <div className="list-card__head"><h3>Knowledge providers</h3><span className="muted">Canonical storage never changes</span></div>
        <div className="list-card__body">
          {loading && rows.length === 0 && <p className="muted">Checking providers…</p>}
          {error && <p className="error">{error}</p>}
          {rows.map((provider) => (
            <div className="knowledge-provider" key={provider.id}>
              <div>
                <strong>{provider.display_name}</strong>
                <div className="muted">{provider.role.replace(/_/g, " ")}</div>
                {provider.last_error && <div className="error">{provider.last_error}</div>}
              </div>
              <div className="knowledge-provider__state">
                {provider.bundled && <span className="badge badge--ok">Bundled default</span>}
                <span className={`badge ${provider.health === "ok" ? "badge--ok" : ""}`}>{provider.status}</span>
                <button
                  type="button"
                  className="btn"
                  disabled={provider.status === "unavailable"}
                  title={provider.status === "unavailable" ? provider.last_error ?? "Unavailable in this build" : undefined}
                  onClick={() => toggle(provider)}
                >
                  {provider.status === "unavailable" ? "Unavailable" : provider.enabled ? "Disable" : "Enable"}
                </button>
              </div>
            </div>
          ))}
          {message && <p className="muted" role="status">{message}</p>}
        </div>
      </div>
      <Hint>Cognee ships enabled as the rebuildable compiler. Mem0 and Supermemory are unavailable in this build; enablement requires a credential-backed projection adapter.</Hint>
    </div>
  );
}
