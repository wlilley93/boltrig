import { type FormEvent, useEffect, useState } from "react";
import {
  type MemoryCandidateView,
  type MemoryIngestionRow,
  type MemoryTimelineResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";

import { Unavailable } from "./Shell";
import { contentText } from "./contentText";
import { statusClass } from "./statusClass";

/**
 * The memory candidate review queue: conflicted facts and proposed procedures
 * waiting on a human decision.
 *
 * EXTRACTED, NOT REDESIGNED. It arrived inline in `MemoryView`, which the
 * capability-doctrine merge pushed to 564 lines and complexity 35 against
 * ratchets of 456 and 31. The Worker structural ratchet is never raised, so the
 * fix is extraction on a real seam, and this is one: the tab owns state nothing
 * else reads (`candidates`, `timeline`, and its own confirm-arming), calls three
 * endpoints nothing else calls, and renders a surface no other tab shares.
 *
 * The arming state is deliberately LOCAL rather than the parent's shared
 * `armed`. This surface only mounts while its tab is selected, so unmounting is
 * the reset the parent used to do by hand, and a destructive confirm that
 * survives a tab switch is exactly the arming bug the pattern exists to avoid.
 */
export function MemoryReview(
  { onMessage, onCount }: {
    onMessage: (message: string) => void;
    // The parent draws the tab's count badge and owns no candidate state, so the
    // number is reported up rather than the list being lifted. Note the badge
    // was already empty until the tab had been opened once -- the fetch has
    // always been tab-scoped -- and that is unchanged, not newly broken.
    onCount: (count: number) => void;
  },
) {
  const [candidates, setCandidates] = useState<MemoryCandidateView[]>([]);
  const [timeline, setTimeline] = useState<MemoryTimelineResponse | null>(null);
  const [armed, setArmed] = useState<string | null>(null);

  useEffect(() => {
    refreshCandidates();
    // Mount-only: the tab is conditionally rendered, so mounting IS selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function refreshCandidates() {
    setTimeline(null);
    void client.memoryCandidates({ limit: 60 })
      .then((result) => {
        const rows = result.candidates ?? [];
        setCandidates(rows);
        onCount(rows.length);
      })
      .catch(() => onMessage("The candidate queue is unavailable."));
  }

  async function review(candidate: MemoryCandidateView, decision: "approve" | "reject") {
    const key = `${decision}:${candidate.id}`;
    if (armed !== key) {
      setArmed(key);
      return;
    }
    setArmed(null);
    const outcome = await submitReview(candidate, decision);
    onMessage(outcome.message);
    if (outcome.settled) refreshCandidates();
  }

  function showTimeline(candidate: MemoryCandidateView) {
    if (!candidate.memory_key) return;
    if (timeline?.memory_key === candidate.memory_key) {
      setTimeline(null);
      return;
    }
    void client.memoryTimeline({ memory_key: candidate.memory_key })
      .then(setTimeline)
      .catch(() => onMessage("The slot history is unavailable."));
  }

  if (candidates.length === 0) {
    return (
      <Unavailable title="No candidates">
        Nothing is waiting for review. Conflicted facts and proposed procedures appear here for a decision.
      </Unavailable>
    );
  }

  return (
    <div className="memory-grid">{candidates.map((candidate) => (
      <CandidateCard
        key={candidate.id}
        candidate={candidate}
        armed={armed}
        timeline={timeline}
        onReview={review}
        onShowTimeline={showTimeline}
      />
    ))}</div>
  );
}

/**
 * One candidate, and the version history of its slot when asked for.
 *
 * Separate from the queue above because the queue's job is fetching and
 * deciding while this one's is rendering, and together they put the queue's
 * render function at 127 lines against a limit of 80.
 */
function CandidateCard(
  { candidate, armed, timeline, onReview, onShowTimeline }: {
    candidate: MemoryCandidateView;
    armed: string | null;
    timeline: MemoryTimelineResponse | null;
    onReview: (candidate: MemoryCandidateView, decision: "approve" | "reject") => void;
    onShowTimeline: (candidate: MemoryCandidateView) => void;
  },
) {
  const showing = timeline !== null && timeline.memory_key === candidate.memory_key;
  return (
    <article className="memory-card">
      <div className="memory-card-head">
        <span>{candidate.kind}</span>
        <span>{candidate.confidence != null ? `confidence ${candidate.confidence.toFixed(2)}` : "review"}</span>
      </div>
      <p>{contentText(candidate.content)}</p>
      {candidate.memory_key && <small>slot {candidate.memory_key}</small>}
      <small>{candidate.owner_scope} · {candidate.provenance.source_kind || "direct"}{candidate.provenance.source_ref ? ` · ${candidate.provenance.source_ref}` : ""}</small>
      <div className="memory-feedback" aria-label="Candidate review">
        <button
          className={armed === `approve:${candidate.id}` ? "primary-button armed" : "primary-button"}
          onClick={() => onReview(candidate, "approve")}
        >
          {armed === `approve:${candidate.id}` ? "Confirm approve" : "Approve"}
        </button>
        <button
          className={armed === `reject:${candidate.id}` ? "danger-button armed" : "danger-button"}
          onClick={() => onReview(candidate, "reject")}
        >
          {armed === `reject:${candidate.id}` ? "Confirm reject" : "Reject"}
        </button>
        {candidate.memory_key && (
          <button className="secondary-button" onClick={() => onShowTimeline(candidate)}>
            {showing ? "Hide history" : "Slot history"}
          </button>
        )}
      </div>
      {showing && <SlotHistory timeline={timeline} />}
    </article>
  );
}

/** Every version a memory slot has held, newest first as the API returns them. */
function SlotHistory({ timeline }: { timeline: MemoryTimelineResponse }) {
  return (
    <div aria-label="Slot version history">
      {timeline.versions.map((version) => (
        <div className="compact-row" key={version.id}>
          <span className={`activity-dot ${version.status === "active" ? "status-ok" : "status-held"}`} />
          <span>
            <strong>v{version.version} · {String(version.value ?? contentText(version.content))}</strong>
            <small>{version.status}{version.valid_from ? ` · from ${version.valid_from.slice(0, 10)}` : ""}</small>
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Send one decision, answering the approval it raises.
 *
 * Review is high-consequence, so the first call may pend. The operator's
 * confirming click IS that approval: answer the canonical HITL request as this
 * principal, then replay the exact review carrying it. Module-level and
 * dependency-free so the component above stays inside the function ceiling and
 * so this can be reasoned about without a render.
 */
async function submitReview(
  candidate: MemoryCandidateView,
  decision: "approve" | "reject",
): Promise<{ settled: boolean; message: string }> {
  const result = await client.memoryCandidateReview(candidate.id, { decision });
  let final = result;
  if (result.hitl_request_id) {
    const approvalId = result.hitl_request_id;
    try {
      await client.respondHitl(approvalId, "approve");
    } catch {
      // The replay below pends again and surfaces the waiting message.
    }
    final = await client.memoryCandidateReview(candidate.id, { decision }, approvalId);
  }
  if (final.status === "ok") {
    return {
      settled: true,
      message: decision === "approve"
        ? "Candidate approved and active."
        : "Candidate rejected.",
    };
  }
  return {
    settled: false,
    message: final.reason ?? "The review is waiting for approval in the originating chat.",
  };
}

/**
 * The Memory surface's tabs, with the review queue's waiting count.
 *
 * Hoisted out of the render because the badge's conditional was counted against
 * MemoryView's complexity ratchet, and a list of tab labels is a fact about the
 * surface rather than about any one render of it.
 */
export function memoryTabs(reviewCount: number): [string, string][] {
  return [
    ["browse", "Browse"],
    ["recall", "Recall"],
    ["remember", "Remember"],
    ["ingest", "Ingest"],
    ["review", `Review${reviewCount ? ` (${reviewCount})` : ""}`],
  ];
}

/**
 * The recent-ingestion list.
 *
 * Lifted out of MemoryView's render because it reads nothing but the rows it is
 * handed, and the capability-doctrine merge put MemoryView over its function
 * ratchet. Ratchets are never raised, so a self-contained block comes out of the
 * function instead.
 */
export function IngestionHistory({ ingestions }: { ingestions: MemoryIngestionRow[] }) {
  return (
    <section className="settings-card">
      <p className="eyebrow">History</p><h2>Recent ingestions</h2>
      {ingestions.length === 0 ? <p className="muted">No ingestions are visible.</p> : ingestions.map((row) => (
        <div className="compact-row" key={row.id}>
          <span className={`activity-dot ${statusClass(row.status)}`} />
          <span><strong>{row.source_ref}</strong><small>{row.source_kind} · {row.facts_added} added / {row.screened} screened</small></span>
          <span className="row-meta">{row.status}</span>
        </div>
      ))}
    </section>
  );
}

/**
 * The screened-ingestion form.
 *
 * Every field invalidates the pending approval on change, because an approval
 * is exact: it authorises the body the reviewer saw, so editing any field after
 * one is granted must void it rather than silently widen it. That rule is the
 * reason this is a form of controlled inputs rather than an uncontrolled one
 * read at submit, and it moves out of MemoryView with the fields it guards.
 */
export function IngestForm(
  { sourceKind, setSourceKind, sourceRef, setSourceRef, ownerScope, setOwnerScope,
    ingestItems, setIngestItems, scopes, onInvalidate, onSubmit }: {
    sourceKind: string; setSourceKind: (value: string) => void;
    sourceRef: string; setSourceRef: (value: string) => void;
    ownerScope: string; setOwnerScope: (value: string) => void;
    ingestItems: string; setIngestItems: (value: string) => void;
    scopes: string[];
    onInvalidate: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  },
) {
  function edit(set: (value: string) => void) {
    return (event: { target: { value: string } }) => {
      onInvalidate();
      set(event.target.value);
    };
  }
  return (
    <form className="settings-card author-form" onSubmit={onSubmit}>
      <p className="eyebrow">Screened ingestion</p><h2>Ingest an exact source</h2>
      <label><span>Source kind</span><input className="field-control" required value={sourceKind} onChange={edit(setSourceKind)} /></label>
      <label><span>Source reference</span><input className="field-control" required value={sourceRef} onChange={edit(setSourceRef)} /></label>
      <label><span>Owner scope</span><select className="field-control" value={ownerScope} onChange={edit(setOwnerScope)}>
        {scopes.map((scope) => <option value={scope} key={scope}>{scope}</option>)}
      </select></label>
      <label><span>Candidate facts (one per line)</span><textarea className="field-control" rows={7} value={ingestItems} onChange={edit(setIngestItems)} /></label>
      <button className="primary-button">Ingest</button>
    </form>
  );
}
