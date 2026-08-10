import { useEffect, useState } from "react";
import type { CapabilityChange } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

import "./build.css";

// The decided target closes every Build tab with a "Recently changed" list.
// The only truthful source is the tamper-evident audit stream the old History
// tab read (client.capabilityChangelog). The sentences below are derived from
// the recorded action/actor/ref fields, and any shape this map does not
// recognise falls back to the raw action string rather than a guessed phrase.

const KIND_LABELS: Record<string, string> = {
  skill: "Skill",
  verb: "Action",
  noun: "Thing",
  binding: "Binding",
  adapter: "Adapter",
  workflow: "Routine",
  mcp_server: "MCP server",
  agent_capability: "Agent",
  permanent_fleet: "Fleet",
  eval_case: "Evaluation",
  eval: "Evaluation",
  integration: "Plugin",
  ai_key: "AI key",
  model: "Model",
};

const OP_LABELS: Record<string, string> = {
  define: "definition saved",
  upsert: "definition saved",
  set: "changed",
  update: "changed",
  create: "created",
  archive: "archived",
  restore: "restored",
  activate: "activated",
  deactivate: "deactivated",
  generate: "generated",
  test_spawn: "test-spawned",
  apply: "applied",
  revoke: "revoked",
  delete: "removed",
};

function describeChange(change: CapabilityChange): { title: string; sub: string } {
  const parts = change.action.replace(/^control\./, "").split(".");
  const kind = KIND_LABELS[parts[0]];
  const op = OP_LABELS[parts[parts.length - 1]];
  const refused = change.status && change.status !== "ok" ? ` · ${change.status}` : "";
  if (!kind || !op || parts.length < 2) {
    return {
      title: change.ref || change.action,
      sub: `${change.action} · by ${change.actor}${refused}`,
    };
  }
  return {
    title: change.ref || kind,
    sub: `${kind} · ${op} by ${change.actor}${refused}`,
  };
}

function changeAge(ts: string): string {
  const time = Date.parse(ts);
  if (!Number.isFinite(time)) return "";
  const minutes = Math.max(0, Math.round((Date.now() - time) / 60_000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export function RecentlyChanged({ limit = 6 }: { limit?: number }) {
  const [changes, setChanges] = useState<CapabilityChange[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    void client.capabilityChangelog()
      .then((result) => setChanges(result.changes))
      .catch(() => setFailed(true));
  }, []);

  if (failed) {
    return (
      <section aria-label="Recently changed" className="console-recent">
        <div className="console-section-title">Recently changed</div>
        <p className="console-foot">
          The authoring history is not visible to this role, so nothing is shown
          rather than a guess.
        </p>
      </section>
    );
  }
  if (changes === null) return null;

  return (
    <section aria-label="Recently changed" className="console-recent">
      <div className="console-section-title">Recently changed</div>
      {changes.length === 0 ? (
        <p className="console-foot">No authoring changes are on the record yet.</p>
      ) : (
        <div className="console-table">
          {changes.slice(0, limit).map((change) => {
            const copy = describeChange(change);
            return (
              <div className="console-row" key={`${change.ts}-${change.actor}-${change.action}-${change.ref}`}>
                <span className="console-row-main">
                  <span className="console-row-title"><span>{copy.title}</span></span>
                  <span className="console-row-sub">{copy.sub}</span>
                </span>
                <span className="console-recent-age">{changeAge(change.ts)}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
