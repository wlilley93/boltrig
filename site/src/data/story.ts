/**
 * Brain Story: chapter content. The scroll narrative renders one panel per
 * entry here (in order), and each index lines up with the camera/focus keyframe
 * at the same index in `src/components/brain/story/story-keyframes.ts`.
 *
 * `kind`:
 *   - `"brain"`    : a narrative panel framing the live particle brain.
 *   - `"takeover"` : a full-screen procedural visual that hides the brain, then
 *                    reveals it again (see `components/story/takeover.tsx`).
 *
 * Structure, ids and `kind` must stay stable so the camera keyframes remain
 * aligned. The arc: arrival, the checkpoint, in-flight checks (takeover), the
 * agent workforce, orchestration, interoperability, the finale.
 */
export type StorySectionKind = "brain" | "takeover";

export interface StorySectionData {
  /** Stable id (used as the scroll anchor + React key). */
  id: string;
  kind: StorySectionKind;
  /** Short terminal kicker above the title (rendered with a `›` prompt). */
  eyebrow: string;
  /** The chapter headline, animated in with the text engine. */
  title: string;
  /** Supporting paragraph. */
  body: string;
  /** Optional readout chips shown in the scan frame (label/value pairs). */
  readouts?: { label: string; value: string }[];
  /** Copy alignment. Defaults to the alternating side; `"center"` for the finale. */
  align?: "left" | "right" | "center";
  /** Optional call-to-action button (finale). Clicking it scrolls back to the top. */
  cta?: { label: string };
}

export const STORY_SECTIONS: StorySectionData[] = [
  {
    id: "arrival",
    kind: "brain",
    eyebrow: "Boltrig",
    title: "Autonomy you can put your name to.",
    body:
      "Boltrig is the governed operating system for AI agents. A standing workforce of agents does real work on your behalf, and a control plane checks every move they make. Run agents in production. Keep the receipts. Stay in charge.",
    readouts: [
      { label: "workforce", value: "STANDING" },
      { label: "actions", value: "GOVERNED" },
    ],
  },
  {
    id: "cortex",
    kind: "brain",
    eyebrow: "The Checkpoint",
    title: "One gate. Every action.",
    body:
      "Chat, webhook, or schedule: every agent action passes one audited checkpoint. Identity, grants, consequence, human approval, rate limits, safe retries, in that order. Budgets stop runaway spend. Agents never see a credential. There is no side door.",
    readouts: [
      { label: "gates", value: "ORDERED" },
      { label: "side doors", value: "NONE" },
    ],
  },
  {
    id: "signals",
    kind: "takeover",
    eyebrow: "In Flight",
    title: "Checked before anything happens.",
    body:
      "Step inside the traffic. Each request is an intent in transit: identified, weighed against its grants and its consequences, rate-limited and de-duplicated before a single side effect lands. Every action leaves exactly one tamper-evident record. Denied means denied, and denials are on the record too.",
    readouts: [
      { label: "checked", value: "PRE-EXECUTE" },
      { label: "default", value: "DENY" },
    ],
  },
  {
    id: "network",
    kind: "brain",
    eyebrow: "The Workforce",
    title: "A workforce, not a chatbot.",
    body:
      "A Chief of Staff routes each request to the right department head. Heads spawn short-lived workers carrying exactly the skills the job needs. Every task runs on the cheapest model that can do it well, and sensitive work never leaves your infrastructure.",
    readouts: [
      { label: "org chart", value: "STANDING" },
      { label: "sensitive data", value: "STAYS LOCAL" },
    ],
  },
  {
    id: "vision",
    kind: "brain",
    eyebrow: "The Operation",
    title: "Every job on one board.",
    body:
      "Draw workflows on a canvas, run them on a schedule or on events. Watch agent and human work move across one board, and open any run to see every step it took. File work from the channels you already use. The fleet remembers what it learns, with provenance on every fact.",
    readouts: [
      { label: "workflows", value: "DURABLE" },
      { label: "runs", value: "INSPECTABLE" },
    ],
  },
  {
    id: "balance",
    kind: "brain",
    eyebrow: "The Fabric",
    title: "It governs agents you did not build.",
    body:
      "Expose any granted capability to outside agents as MCP tools, with the full checkpoint applied. Plug external tool servers in as new capabilities, inert until you review and activate them. New integrations are data, not code changes.",
    readouts: [
      { label: "mcp", value: "IN / OUT" },
      { label: "new tools", value: "OFF BY DEFAULT" },
    ],
  },
  {
    id: "whole",
    kind: "brain",
    eyebrow: "In Production",
    title: "Provably governed. Yours to run.",
    body:
      "One self-hosted deploy: kernel, database, console. Enterprise SSO maps your people to roles, the audit record proves what happened, and every governance guarantee is pinned to a machine-checked test in CI. Put agents to work where it counts.",
    readouts: [
      { label: "deploy", value: "SELF-HOSTED" },
      { label: "guarantees", value: "CI-PINNED" },
    ],
    align: "center",
    cta: { label: "Open the console" },
  },
];

/** The index of the takeover chapter (the one that hides the brain). */
export const TAKEOVER_INDEX = STORY_SECTIONS.findIndex((s) => s.kind === "takeover");
