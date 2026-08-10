import { useEffect, useState } from "react";
import type { AuditRow, HITLRequest } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { shortDate } from "./format";
import { SettingsGroup, ToneRow, type Tone } from "./rowKit";

// Overnight, told from the record rather than from the design's demo data.
// The gate writes a hash-chained receipt for every night — promote and hold
// alike (verb distill.gate, statuses distill_gate_promote / distill_gate_hold,
// boltrig/distill/adapter.py) — and a night that reaches a person parks as a
// pending_human request. Those two readings are all this client can reach:
// /v1/audit/search drops the receipt detail, so the design's per-check scores
// and corpus composition are not drawn here; the mechanical gates and the
// rules are described as what they are (decision 0023), never as measurements
// this screen did not take. The design's header toggle was a prototype
// state-switcher and is dropped.

type RecordState =
  | { kind: "loading" }
  | { kind: "unavailable"; denied: boolean }
  | { kind: "ready"; receipts: AuditRow[]; pending: HITLRequest | null };

function receiptTone(row: AuditRow): { tone: Tone; state: string } {
  if (row.status === "distill_gate_promote") return { tone: "green", state: "passed" };
  if (row.status === "distill_gate_hold") return { tone: "amber", state: "held back" };
  return { tone: "unknown", state: row.status ?? "recorded" };
}

// The three legs a candidate must survive (boltrig/distill/adapter_gates.py,
// decision 0023 DIS-6/DIS-9). Descriptive, not measured: the scores live in
// the run's own record, which this endpoint does not surface.
const GATES: Array<[string, string]> = [
  ["It still passes your own checks", "The candidate replays this workspace's eval cases; one going backwards fails the gate"],
  ["It writes more like you", "Scored against held-out approved turns it never practised on"],
  ["It has not narrowed", "A version that starts repeating itself is held, however well it scores"],
];

// Decision 0023, in plain words. Static because these are rules of the
// design, not readings.
const RULES: string[] = [
  "Every night starts again from the pinned base model. It never builds on last night's copy, so a bad night cannot compound.",
  "It practises habits, never facts. What it knows stays in Knowledge, where it can be cited, corrected and deleted.",
  "Every adapter records the erasure watermark it was built after; anything you erased is left out of the next rebuild.",
  "A corpus is bound to its owner. The gate refuses to promote an adapter whose corpus belongs to anyone else.",
];

export function OvernightSection({ head = true }: { head?: boolean }) {
  const [state, setState] = useState<RecordState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const receipts = typeof client.auditSearch === "function"
      ? client.auditSearch({ verb: "distill.gate", limit: 50 })
      : Promise.reject(new Error("unavailable"));
    const pending = typeof client.hitl === "function"
      ? client.hitl().catch(() => null)
      : Promise.resolve(null);
    void Promise.all([receipts, pending])
      .then(([auditResult, hitlResult]) => {
        if (cancelled) return;
        const rows = (auditResult.results ?? [])
          .slice()
          .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
        const parked = (hitlResult?.requests ?? [])
          .find((request) => (request.verb ?? "").startsWith("distill.")) ?? null;
        setState({ kind: "ready", receipts: rows, pending: parked });
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        // Only a 403 is about the viewer's role; anything else is a failure to
        // read, which must not be reported as a permission boundary.
        const denied = typeof reason === "object" && reason !== null && "status" in reason
          && (reason as { status?: number }).status === 403;
        setState({ kind: "unavailable", denied });
      });
    return () => { cancelled = true; };
  }, []);

  if (state.kind === "loading") {
    return head ? <Head badge={null} headline="Reading the record…" lead="" /> : null;
  }

  if (state.kind === "unavailable") {
    return (
      <>
        {head && (
          <Head
            badge={null}
            headline="Overnight practice"
            lead="What it consolidates while nothing is running, and what it had to prove before anything was kept."
          />
        )}
        <p className="notice">
          {state.denied
            ? "The record of overnight practice is not readable with your current role."
            : "The record of overnight practice could not be read just now."}
        </p>
        <MechanismBlocks />
      </>
    );
  }

  const { receipts, pending } = state;
  // The verdict must come from a RECEIPT row (distill_gate_promote / hold).
  // The dispatch layer also writes a plain status="ok" row for every
  // distill.gate call, which sorts newest — reading THAT row as the verdict
  // would report every promoted night as held back.
  const latest = receipts.find((row) =>
    row.status === "distill_gate_promote" || row.status === "distill_gate_hold") ?? null;

  let badge: { tone: Tone; word: string } | null;
  let headline: string;
  let lead: string;
  if (pending) {
    badge = { tone: "amber", word: "Waiting on you" };
    headline = "A night is parked, waiting for a person";
    lead = "Nightly practice stops at a human gate. Approve or decline it from the Inbox; nothing is kept until you do.";
  } else if (!latest && receipts.length > 0) {
    badge = null;
    headline = "Gate activity, but no readable verdict";
    lead = "The record carries rows for the gate verb, but none is a promote-or-hold receipt this client can read.";
  } else if (!latest) {
    badge = null;
    headline = "No night has run here yet";
    lead = "Nightly consolidation exists behind governed verbs, but a person starts a night, and this workspace's record shows none so far.";
  } else if (latest.status === "distill_gate_promote") {
    badge = { tone: "green", word: "Passed its checks" };
    headline = "The last practice passed every check";
    lead = "The gate wrote a receipt. Nothing serves until promotion, which is its own approval.";
  } else {
    badge = { tone: "amber", word: "Held back" };
    headline = "The last practice was held back";
    lead = "A failed check keeps yesterday's version in place. The receipt in the record says which.";
  }

  return (
    <>
      {head && <Head badge={badge} headline={headline} lead={lead} />}

      <SettingsGroup
        foot={receipts.length > 0
          ? "One row per gate receipt, straight from the audit record. Passing is not serving: promotion is a separate, recorded act."
          : undefined}
        title="What the record shows"
      >
        {receipts.length === 0 ? (
          <ToneRow
            state="none"
            sub="No gate receipt exists in this workspace's record."
            title="Nothing yet"
            tone="unknown"
          />
        ) : receipts.slice(0, 7).map((row) => {
          const { tone, state: word } = receiptTone(row);
          return (
            <ToneRow
              key={row.seq}
              state={word}
              sub={`Recorded by ${row.actor}`}
              tech={row.run_id ?? undefined}
              title={shortDate(row.ts) || row.ts}
              tone={tone}
            />
          );
        })}
      </SettingsGroup>

      <MechanismBlocks />
    </>
  );
}

function Head({ badge, headline, lead }: {
  badge: { tone: Tone; word: string } | null;
  headline: string;
  lead: string;
}) {
  return (
    <div className="settings-night-head">
      {badge && <span className="settings-night-badge" data-tone={badge.tone}>{badge.word}</span>}
      <h1>{headline}</h1>
      {lead && <p>{lead}</p>}
    </div>
  );
}

function MechanismBlocks() {
  return (
    <div className="settings-night-grid">
      <SettingsGroup
        foot="Each is a measurement, not an opinion, and any one failing keeps yesterday's version. The scores live in the run's own record."
        title="What a night has to prove"
      >
        {GATES.map(([title, sub]) => (
          <ToneRow key={title} state="gate" sub={sub} title={title} tone="unknown" />
        ))}
      </SettingsGroup>
      <div className="settings-group">
        <div className="console-section-title">The rules it works under</div>
        <div className="settings-rules-card">
          {RULES.map((rule) => <span key={rule}>{rule}</span>)}
        </div>
      </div>
    </div>
  );
}
