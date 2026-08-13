import { useEffect, useState } from "react";
import type { ConversationSummary } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { shortDate } from "./format";
import { SectionHead } from "./SectionHead";
import { SettingsRow } from "./rowKit";

// Archived chats on the design's single-line anatomy: label, right-aligned
// date, Bring back. The design groups rows by project — conversations carry
// no project field anywhere in the kernel or SDK, so one honest group header
// carries the count instead. The date is updated_at, the only timestamp the
// kernel exposes, and the foot says so rather than passing it off as an
// archive time.

export function ArchivedSection({ head = true }: { head?: boolean }) {
  const [rows, setRows] = useState<ConversationSummary[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [busy, setBusy] = useState("");

  async function load() {
    try {
      const result = await client.conversations();
      setRows((result.conversations ?? []).filter((row) => row.status === "closed"));
      setState("ready");
    } catch {
      setState("unavailable");
    }
  }
  useEffect(() => { void load(); }, []);

  async function restore(id: string) {
    setBusy(id);
    try {
      await client.restoreMyConversation(id);
      await load();
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      {head && <SectionHead section="archived" />}
      {state === "loading" && <p className="muted small">Loading archived chats…</p>}
      {state === "unavailable" && <p className="notice">Archived chats could not be read.</p>}
      {state === "ready" && (
        <div className="settings-group">
          <div className="settings-group-eyebrow">
            {rows.length === 0
              ? "All chats"
              : `All chats · ${rows.length} ${rows.length === 1 ? "chat" : "chats"}`}
          </div>
          <div className="console-table">
            {rows.length === 0 ? (
              <SettingsRow
                desc="Closed chats land here, and can be brought back."
                title="Nothing is archived"
              />
            ) : rows.map((row) => (
              <div className="settings-archived-row" key={row.id}>
                <span className="settings-archived-title">{row.title || "Untitled task"}</span>
                <span className="settings-archived-date">{shortDate(row.updated_at)}</span>
                <button
                  className="console-lifecycle"
                  disabled={busy === row.id}
                  onClick={() => void restore(row.id)}
                  type="button"
                >{busy === row.id ? "Bringing back…" : "Bring back"}</button>
              </div>
            ))}
          </div>
          {rows.length > 0 && (
            <p className="console-foot">
              Dates show each chat's last activity.
            </p>
          )}
        </div>
      )}
    </>
  );
}
