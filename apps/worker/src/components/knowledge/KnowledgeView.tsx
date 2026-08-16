import { useEffect, useMemo, useRef, useState } from "react";
import {
  BoltrigApiError,
  type KnowledgeAsset,
  type KnowledgeAssetDetailResponse,
  type KnowledgeMutationResponse,
  type KnowledgeSearchHit,
  type KnowledgeUploadResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { navigate } from "../../routes";
import { useRouteSelection } from "../../useRouteSelection";
import { AgentTabsStrip } from "../build/AgentTabsStrip";
import {
  ExactApprovalFinalizer,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import { Unavailable } from "../Shell";
import { RemembersTab } from "./RemembersTab";

import "./knowledge.css";
import "./KnowledgeParity.css";

// The decided target's Knowledge surface (design lines 897-1045): a file
// table with a persistent right detail rail, a staged upload card, a search
// box, and a "What it remembers" tab. Deviations from the design are honesty
// decisions, each reported to the orchestrator:
//   - Quoted counts and file sizes remain in the decided table geometry, but
//     render an explicit unavailable dash because neither figure exists on an
//     endpoint.
//   - No tombstone row and no "removed, still quotable" copy: erasure is a
//     hard delete, so the rail says the opposite, truthfully.
//   - The upload card shows one real in-flight state and then a receipt of
//     what the commit reported, never timer-driven fake stages.
//   - Provider health and governed enablement live in Settings > Knowledge,
//     keeping this primary surface to the decided Files/What it remembers pair.

type SurfaceState = "loading" | "ready" | "denied" | "not-found" | "unavailable";
type DetailState = "idle" | "loading" | "ready" | "denied" | "not-found" | "unavailable";

type UploadReceipt =
  | { name: string; phase: "sending" }
  | { name: string; phase: "done"; result: KnowledgeUploadResponse }
  | { name: string; phase: "failed" };

function failureState(error: unknown): Exclude<SurfaceState, "loading" | "ready"> {
  if (error instanceof BoltrigApiError) {
    if (error.status === 401 || error.status === 403) return "denied";
    if (error.status === 404) return "not-found";
  }
  return "unavailable";
}

function locatorText(locator: Record<string, unknown>): string {
  return Object.entries(locator)
    .map(([key, value]) => `${key.replaceAll("_", " ")} ${String(value)}`)
    .join(" · ") || "document passage";
}

function segmentLocator(segment: Record<string, unknown>): string {
  const locator = segment.locator;
  return locator && typeof locator === "object"
    ? locatorText(locator as Record<string, unknown>)
    : "document passage";
}

function segmentText(segment: Record<string, unknown>): string {
  const text = typeof segment.text === "string" ? segment.text : "";
  return text.length > 280 ? `${text.slice(0, 280)}…` : text;
}

function addedAge(value: string): string {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return value;
  const days = Math.max(0, Math.floor((Date.now() - time) / 86_400_000));
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days}d ago`;
  if (days < 60) return `${Math.round(days / 7)}w ago`;
  return `${Math.round(days / 30)}mo ago`;
}

function FileIcon() {
  return (
    <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.6" viewBox="0 0 24 24" width="15">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}

export function KnowledgeView() {
  const [selectedAssetId, setSelectedAssetId] = useRouteSelection("knowledge");
  const [tab, setTab] = useState<"files" | "remembers">("files");
  const [assets, setAssets] = useState<KnowledgeAsset[]>([]);
  const [surfaceState, setSurfaceState] = useState<SurfaceState>("loading");
  const loadedKnowledge = useRef(false);
  const [assetOffset, setAssetOffset] = useState<number | null>(0);
  const [assetDetail, setAssetDetail] = useState<KnowledgeAssetDetailResponse | null>(null);
  const [assetDetailState, setAssetDetailState] = useState<DetailState>("idle");
  const selectedAssetIdRef = useRef(selectedAssetId);
  const assetDetailSequence = useRef(0);
  const [filter, setFilter] = useState("");
  const [hits, setHits] = useState<KnowledgeSearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const searchSequence = useRef(0);
  const activeSearchQuery = useRef<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [receipt, setReceipt] = useState<UploadReceipt | null>(null);
  const [eraseArmed, setEraseArmed] = useState(false);
  const [eraseBusy, setEraseBusy] = useState(false);
  const eraseBusyRef = useRef(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const mutationFinalizer = useExactApprovalFinalizer<
    { kind: "erase"; assetId: string },
    KnowledgeMutationResponse
  >({
    isCurrent: (input) => assets.some((asset) => asset.id === input.assetId),
    replay: (input, approvalId) => client.eraseKnowledgeAsset(input.assetId, approvalId),
    onApplied: async (_result, input) => {
      setMessage("The source was erased.");
      if (selectedAssetIdRef.current === input.assetId) {
        setSelectedAssetId(null);
      }
      refresh();
    },
    onRefused: (result) => {
      setMessage(result.reason ?? "The approved Knowledge change was not applied.");
    },
  });
  selectedAssetIdRef.current = selectedAssetId;

  function refresh() {
    mutationFinalizer.invalidate();
    void client.knowledgeAssets(25, 0).then((result) => {
      setAssets(result.assets);
      setAssetOffset(result.next_offset ?? null);
      loadedKnowledge.current = true;
      setSurfaceState("ready");
      setError("");
    }).catch((reason) => {
      const state = failureState(reason);
      if (state === "unavailable" && loadedKnowledge.current) {
        setError("Knowledge could not be refreshed. Showing the last loaded sources.");
        return;
      }
      loadedKnowledge.current = false;
      setError("");
      setAssets([]);
      setAssetOffset(null);
      setSurfaceState(state);
    });
  }

  async function loadMoreAssets() {
    if (assetOffset === null) return;
    const result = await client.knowledgeAssets(25, assetOffset);
    setAssets((current) => [
      ...current,
      ...result.assets.filter(
        (asset) => !current.some((item) => item.id === asset.id),
      ),
    ]);
    setAssetOffset(result.next_offset ?? null);
  }

  useEffect(refresh, []);
  useEffect(() => {
    mutationFinalizer.invalidate();
    setEraseArmed(false);
    if (!selectedAssetId || surfaceState !== "ready") {
      assetDetailSequence.current += 1;
      setAssetDetail(null);
      setAssetDetailState("idle");
      return;
    }
    const sequence = ++assetDetailSequence.current;
    setTab("files");
    setAssetDetail(null);
    setAssetDetailState("loading");
    void client.knowledgeAsset(selectedAssetId)
      .then((result) => {
        if (
          assetDetailSequence.current === sequence
          && selectedAssetIdRef.current === selectedAssetId
        ) {
          setAssetDetail(result);
          setAssetDetailState("ready");
        }
      })
      .catch((reason) => {
        if (
          assetDetailSequence.current === sequence
          && selectedAssetIdRef.current === selectedAssetId
        ) setAssetDetailState(failureState(reason));
      });
    return () => {
      if (assetDetailSequence.current === sequence) assetDetailSequence.current += 1;
    };
  }, [selectedAssetId, surfaceState]);

  const visibleAssets = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return term
      ? assets.filter((asset) => `${asset.title} ${asset.filename}`.toLowerCase().includes(term))
      : assets;
  }, [assets, filter]);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    const query = filter.trim();
    if (!query || activeSearchQuery.current === query) return;
    const sequence = ++searchSequence.current;
    activeSearchQuery.current = query;
    setSearching(true);
    setError("");
    try {
      const result = await client.knowledgeSearch(query);
      if (searchSequence.current === sequence) setHits(result.hits);
    } catch {
      if (searchSequence.current === sequence) {
        setError("Knowledge search is unavailable.");
      }
    } finally {
      if (searchSequence.current === sequence) {
        activeSearchQuery.current = null;
        setSearching(false);
      }
    }
  }

  async function uploadFile(file: File) {
    setMessage("");
    setReceipt({ name: file.name, phase: "sending" });
    try {
      const result = await client.uploadKnowledge(file);
      setReceipt({ name: file.name, phase: "done", result });
      refresh();
      if (result.status === "ok") setSelectedAssetId(result.asset_id);
    } catch {
      setReceipt({ name: file.name, phase: "failed" });
    }
  }

  async function downloadAsset(assetId: string, filename: string) {
    try {
      const blob = await client.knowledgeOriginal(assetId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setMessage("The original source could not be downloaded.");
    }
  }

  async function eraseAsset(assetId: string) {
    if (eraseBusyRef.current) return;
    if (!eraseArmed) {
      setEraseArmed(true);
      return;
    }
    eraseBusyRef.current = true;
    setEraseBusy(true);
    setMessage("");
    const input = { kind: "erase", assetId } as const;
    try {
      const result = await client.eraseKnowledgeAsset(assetId);
      setEraseArmed(false);
      if (mutationFinalizer.begin(input, result, "Knowledge source erasure")) {
        setMessage("Erasure is waiting for approval in the originating chat.");
        return;
      }
      setMessage(
        result.reason ?? (
          result.status === "ok"
            ? "The source was erased."
            : `Erasure status: ${result.status ?? "unknown"}.`
        ),
      );
      if (result.status === "ok") {
        if (selectedAssetIdRef.current === assetId) setSelectedAssetId(null);
        refresh();
      }
    } catch {
      const stillSelected = selectedAssetIdRef.current === assetId;
      setEraseArmed(stillSelected);
      setMessage(
        stillSelected
          ? "Removal could not be confirmed. No success is shown; confirm removal to retry."
          : "Removal could not be confirmed. No success is shown.",
      );
    } finally {
      eraseBusyRef.current = false;
      setEraseBusy(false);
    }
  }

  const storageLine = `${assets.length}${assetOffset !== null ? "+" : ""} `
    + `${assets.length === 1 && assetOffset === null ? "file" : "files"} · originals kept by the `
    + "kernel's knowledge vault, exactly as you gave them. Nothing bigger than "
    + "25 MB, and only text, Markdown and PDF — anything else is refused "
    + "rather than half-read.";

  return (
    <div className="page knowledge-page">
      <div className="knowledge-main">
        <div className="console-page knowledge-col">
          <AgentTabsStrip active="knowledge" />
          <div className="console-head">
            <div>
              <h1>Knowledge</h1>
              <p>Everything boltrig has read. Drop a file in and it becomes quotable, with the page it came from.</p>
            </div>
            <nav aria-label="Knowledge sections" className="console-seg">
              {([["files", "Files"], ["remembers", "What it remembers"]] as const).map(([id, label]) => (
                <button
                  aria-current={tab === id ? "page" : undefined}
                  data-active={tab === id ? "true" : undefined}
                  key={id}
                  onClick={() => setTab(id)}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </nav>
          </div>
          {error && <p className="notice">{error}</p>}
          {message && <p className="notice" role="status">{message}</p>}
          <ExactApprovalFinalizer controller={mutationFinalizer} />
          {surfaceState === "loading" && <Unavailable title="Loading knowledge">Loading sources.</Unavailable>}
          {surfaceState === "denied" && <Unavailable title="Knowledge access denied">Your current role cannot view this source library.</Unavailable>}
          {surfaceState === "not-found" && <Unavailable title="Knowledge not found">This deployment does not expose the canonical knowledge library route.</Unavailable>}
          {surfaceState === "unavailable" && <Unavailable title="Knowledge unavailable">The knowledge service could not be reached.</Unavailable>}
          {surfaceState === "ready" && tab === "files" && (
            <>
              <div className="knowledge-actions">
                <form className="knowledge-search" onSubmit={(event) => void search(event)}>
                  <svg aria-hidden fill="none" height="14" stroke="var(--text-4)" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="14">
                    <circle cx="11" cy="11" r="7" /><line x1="16.5" x2="21" y1="16.5" y2="21" />
                  </svg>
                  <input
                    aria-label="Search Knowledge"
                    onChange={(event) => {
                      searchSequence.current += 1;
                      activeSearchQuery.current = null;
                      setSearching(false);
                      setFilter(event.target.value);
                      setHits(null);
                    }}
                    placeholder="Search inside everything it has read"
                    value={filter}
                  />
                </form>
                <button
                  className="console-primary"
                  disabled={receipt?.phase === "sending"}
                  onClick={() => fileInput.current?.click()}
                  type="button"
                >
                  <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="14">
                    <line x1="12" x2="12" y1="5" y2="19" /><line x1="5" x2="19" y1="12" y2="12" />
                  </svg>
                  <span>Add a file</span>
                </button>
                <input
                  aria-label="Source file"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) void uploadFile(file);
                  }}
                  ref={fileInput}
                  type="file"
                />
              </div>
              {receipt && <UploadReceiptCard onDismiss={() => setReceipt(null)} receipt={receipt} />}
              {hits !== null && (
                <section aria-label="Cited search results" className="console-table-wrap">
                  <div className="knowledge-rail-label">
                    <span>Passages found by meaning</span>
                    <button className="build-back" onClick={() => setHits(null)} style={{ flex: "0 0 auto" }} type="button">Clear results</button>
                  </div>
                  {searching && <p className="console-foot">Searching…</p>}
                  {!searching && hits.length === 0 && <p className="console-foot">No cited passages matched.</p>}
                  {hits.map((hit) => (
                    <article className="search-hit" key={hit.segment_id}>
                      <div><h3>{hit.title}</h3><span className="score">{hit.score.toFixed(2)}</span></div>
                      <p>{hit.text}</p>
                      <small>{hit.filename} · revision {hit.revision_id.slice(-8)} · {locatorText(hit.citation.locator)}</small>
                    </article>
                  ))}
                </section>
              )}
              {assets.length === 0 && !error ? (
                <Unavailable title="No source documents">Add the first source with &ldquo;Add a file&rdquo;.</Unavailable>
              ) : (
                <div className="console-table-wrap">
                  <div className="console-table">
                    <div className="console-table-head">
                      <span aria-hidden className="knowledge-icon-col" />
                      <span style={{ flex: 1 }}>File</span>
                      <span className="knowledge-num">Passages</span>
                      <span className="knowledge-quoted">Quoted</span>
                      <span className="knowledge-size">Size</span>
                      <span className="knowledge-when">Added</span>
                    </div>
                    {visibleAssets.map((asset) => (
                      <button
                        className="console-row"
                        data-selected={selectedAssetId === asset.id ? "true" : undefined}
                        key={asset.id}
                        onClick={() => setSelectedAssetId(asset.id)}
                        type="button"
                      >
                        <span aria-hidden className="knowledge-icon-col"><FileIcon /></span>
                        <span className="console-row-main">
                          <span className="console-row-title"><span>{asset.title}</span></span>
                          <span className="console-row-sub">{asset.filename}</span>
                        </span>
                        <span className="knowledge-num">{asset.segment_count}</span>
                        <span
                          aria-label="Quoted count unavailable"
                          className="knowledge-quoted"
                          title="Quote counts are not exposed by the Knowledge API"
                        >—</span>
                        <span
                          aria-label="File size unavailable"
                          className="knowledge-size"
                          title="File sizes are not exposed by the Knowledge API"
                        >—</span>
                        <span className="knowledge-when">{addedAge(asset.created_at)}</span>
                      </button>
                    ))}
                    {visibleAssets.length === 0 && (
                      <div className="console-row"><span className="console-row-sub">No files match that filter.</span></div>
                    )}
                  </div>
                  {assetOffset !== null && (
                    <button className="secondary-button" onClick={() => void loadMoreAssets()} type="button">
                      Load more sources
                    </button>
                  )}
                  <div className="knowledge-storage-foot">
                    <span>{storageLine}</span>
                    <button
                      onClick={() => navigate("settings", "knowledge")}
                      type="button"
                    >
                      Change where files are kept
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
          {surfaceState === "ready" && tab === "remembers" && <RemembersTab />}
        </div>
      </div>
      {surfaceState === "ready" && tab === "files" && (
        <aside aria-label="Source detail" className="knowledge-rail">
          {!selectedAssetId && (
            <p className="knowledge-rail-note">
              Select a file to see its original, the passages it can quote, and
              where it is kept.
            </p>
          )}
          {selectedAssetId && (
            <div className="knowledge-rail-head">
              <div>
                <h2 className="knowledge-rail-title">{assetDetail?.asset.title ?? "Source detail"}</h2>
                {assetDetail && (
                  <span className="knowledge-rail-meta">
                    {assetDetail.asset.asset_type} · {assetDetail.segments.length} passages · added {addedAge(assetDetail.asset.created_at)}
                  </span>
                )}
              </div>
              <button aria-label="Close source detail" className="icon-button" onClick={() => setSelectedAssetId(null)} type="button">×</button>
            </div>
          )}
          {assetDetailState === "loading" && <p className="knowledge-rail-note">Loading exact source provenance.</p>}
          {assetDetailState === "denied" && <p className="knowledge-rail-note">Your current role cannot inspect this source.</p>}
          {assetDetailState === "not-found" && <p className="knowledge-rail-note">That source is outside the active library or no longer exists.</p>}
          {assetDetailState === "unavailable" && <p className="knowledge-rail-note">Exact source provenance could not be reached.</p>}
          {assetDetailState === "ready" && assetDetail && (
            <>
              <div className="knowledge-rail-section">
                <span className="knowledge-rail-label"><span>The original</span></span>
                <div className="knowledge-original">
                  <span aria-hidden className="knowledge-icon-col"><FileIcon /></span>
                  <span>{assetDetail.asset.filename}</span>
                  <button
                    onClick={() => void downloadAsset(assetDetail.asset.id, assetDetail.asset.filename)}
                    type="button"
                  >
                    Open
                  </button>
                </div>
                <p className="knowledge-rail-note">
                  Kept exactly as you gave it. Everything below was worked out
                  from it, and can be worked out again.
                </p>
              </div>
              <div className="knowledge-rail-section">
                <span className="knowledge-rail-label">
                  <span>Passages it can quote</span>
                  <small>{assetDetail.segments.length}</small>
                </span>
                {assetDetail.segments.length === 0 ? (
                  <p className="knowledge-rail-note">No passages were extracted from this source.</p>
                ) : (
                  <div className="knowledge-passages">
                    {assetDetail.segments.map((segment, index) => (
                      <div className="knowledge-passage" key={typeof segment.id === "string" ? segment.id : index}>
                        <small>{segmentLocator(segment)}</small>
                        <p>{segmentText(segment)}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="knowledge-rail-section">
                <span className="knowledge-rail-label"><span>Where it is kept</span></span>
                <dl className="knowledge-kept">
                  <dt>Source</dt>
                  <dd>{assetDetail.asset.source_ref ?? assetDetail.asset.source_kind}</dd>
                  <dt>Revision</dt>
                  <dd>{assetDetail.asset.revision_id}</dd>
                </dl>
                <details>
                  <summary>Provenance</summary>
                  <pre className="json-block">{JSON.stringify(assetDetail.provenance, null, 2)}</pre>
                </details>
              </div>
              <button
                className="knowledge-remove"
                data-armed={eraseArmed ? "true" : undefined}
                disabled={eraseBusy}
                onClick={() => void eraseAsset(assetDetail.asset.id)}
                type="button"
              >
                {eraseBusy ? "Removing…" : eraseArmed ? "Confirm removal" : "Remove this file"}
              </button>
              <p className="knowledge-remove-note">
                Removal is permanent: its passages stop being quotable and
                citations to it stop resolving. High-consequence removals wait
                for your approval in the originating chat first.
              </p>
            </>
          )}
        </aside>
      )}
    </div>
  );
}

function UploadReceiptCard({ receipt, onDismiss }: {
  receipt: UploadReceipt;
  onDismiss(): void;
}) {
  return (
    <section aria-label="Upload progress" className="knowledge-upload-card">
      <div className="knowledge-upload-head">
        <span aria-hidden className="knowledge-icon-col"><FileIcon /></span>
        <strong>{receipt.name}</strong>
        <span>
          {receipt.phase === "sending" && "Uploading…"}
          {receipt.phase === "done" && (receipt.result.status === "ok" ? "Ready" : `Status: ${receipt.result.status}`)}
          {receipt.phase === "failed" && "Not uploaded"}
        </span>
      </div>
      {receipt.phase === "sending" && (
        <div className="knowledge-upload-row">
          <i aria-hidden />
          <span>
            Sending the file and keeping the original. Nothing is shown as read
            until the kernel confirms it.
          </span>
        </div>
      )}
      {receipt.phase === "failed" && (
        <div className="knowledge-upload-row">
          <i aria-hidden />
          <span>The source was not uploaded. No partial asset is shown as complete.</span>
        </div>
      )}
      {receipt.phase === "done" && (
        <>
          <div className="knowledge-upload-row" data-done="true">
            <i aria-hidden>✓</i>
            <span>Kept your original, unchanged</span>
            {receipt.result.digest && (
              <small>{receipt.result.digest.length > 20 ? `${receipt.result.digest.slice(0, 20)}…` : receipt.result.digest}</small>
            )}
          </div>
          <div className="knowledge-upload-row" data-done="true">
            <i aria-hidden>✓</i>
            <span>
              Read it — {receipt.result.segment_count} {receipt.result.segment_count === 1 ? "passage" : "passages"}
            </span>
          </div>
          {receipt.result.projections.map((projection) => (
            <div
              className="knowledge-upload-row"
              data-done={projection.status === "ok" || projection.status === "ready" ? "true" : undefined}
              key={projection.provider_id}
            >
              <i aria-hidden>{projection.status === "ok" || projection.status === "ready" ? "✓" : ""}</i>
              <span>Indexed by {projection.provider_id}</span>
              <small>{projection.error ?? projection.status}</small>
            </div>
          ))}
          <div className="knowledge-upload-row" data-done={receipt.result.status === "ok" ? "true" : undefined}>
            <i aria-hidden>{receipt.result.status === "ok" ? "✓" : ""}</i>
            <span>
              {receipt.result.status === "ok" ? "Ready to quote" : `Upload finished with status ${receipt.result.status}`}
            </span>
            <small>revision {receipt.result.revision_id.slice(-8)}</small>
          </div>
        </>
      )}
      <button className="knowledge-upload-dismiss" onClick={onDismiss} type="button">Dismiss</button>
    </section>
  );
}
