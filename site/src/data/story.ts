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
  /** Optional call-to-action button (finale). `href` overrides the default console link. */
  cta?: { label: string; href?: string };
}

export const STORY_SECTIONS: StorySectionData[] = [
  {
    id: "arrival",
    kind: "brain",
    eyebrow: "Boltrig",
    title: "Run AI agents in production. Prove every move they make.",
    body:
      "Boltrig runs a standing workforce of AI agents and routes every action they take through one audited, permissioned gate. Autonomous work on your own infrastructure, with a tamper-evident record of everything they did and were allowed to do.",
    readouts: [
      { label: "workforce", value: "STANDING" },
      { label: "actions", value: "GOVERNED" },
      { label: "deploy", value: "SELF-HOSTED" },
    ],
  },
  {
    id: "cortex",
    kind: "brain",
    eyebrow: "The Checkpoint",
    title: "One gate. Every action.",
    body:
      "Chat, webhook, or schedule: every agent action passes one audited checkpoint before anything happens. Identity, grants, consequence, human approval when it counts, rate limits, and safe retries, in that fixed order. Credentials resolve inside the gate and never reach the agent, and there is no side door.",
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
      "Step inside the traffic. Every request is an intent in transit: identified, weighed against its grants and its consequences, rate-limited and de-duplicated before a single side effect lands. Every action writes exactly one tamper-evident record, and denials are on the record too.",
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
      "A Chief of Staff routes each request to the right department head, and heads spawn short-lived workers carrying exactly the skills the job needs. Every task runs on the cheapest model that can do it well, and work marked sensitive never leaves your infrastructure. Budgets are reserved before the work starts, not reconciled after the bill lands.",
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
      "Draw workflows on a canvas and run them on a schedule or on events. Watch agent and human work move across one board, and open any run to walk every step it took. New facts the fleet learns carry provenance, so you can trace where every answer came from.",
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
      "One self-hosted deploy: kernel, database, and console, on your own infrastructure. Enterprise SSO maps your people to roles, or run first-party invite-only access as the only door. The audit record proves what happened, and every governance guarantee is pinned to a machine-checked test in CI. Not trust the agent. Check the runtime.",
    readouts: [
      { label: "deploy", value: "SELF-HOSTED" },
      { label: "guarantees", value: "CI-PINNED" },
    ],
    align: "center",
    cta: { label: "Request access", href: "mailto:access@boltrig.io?subject=Boltrig%20access%20request" },
  },
];

/** The index of the takeover chapter (the one that hides the brain). */
export const TAKEOVER_INDEX = STORY_SECTIONS.findIndex((s) => s.kind === "takeover");
