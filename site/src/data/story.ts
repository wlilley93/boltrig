/**
 * Brain Story — chapter content. The scroll narrative renders one panel per
 * entry here (in order), and each index lines up with the camera/focus keyframe
 * at the same index in `src/components/brain/story/story-keyframes.ts`.
 *
 * `kind`:
 *   - `"brain"`    — a narrative panel framing the live particle brain.
 *   - `"takeover"` — a full-screen procedural visual that hides the brain, then
 *                    reveals it again (see `components/story/takeover.tsx`).
 *
 * NOTE: the copy below is DRAFT placeholder text — replace `eyebrow` / `title` /
 * `body` with the final script. Structure, ids and `kind` should stay stable so
 * the camera keyframes remain aligned.
 */
export type StorySectionKind = "brain" | "takeover";

export interface StorySectionData {
  /** Stable id (used as the scroll anchor + React key). */
  id: string;
  kind: StorySectionKind;
  /** Short terminal kicker above the title (rendered with a `›` prompt). */
  eyebrow: string;
  /** The chapter headline — animated in with the text engine. */
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
      "A system resolves out of the dark: agents that act on your behalf, and a governor that never blinks. Boltrig is the operating system for AI agents you can actually put in production - where every action is accountable, not assumed.",
    readouts: [
      { label: "agents", value: "GOVERNED" },
      { label: "status", value: "LIVE" },
    ],
  },
  {
    id: "cortex",
    kind: "brain",
    eyebrow: "The Chokepoint",
    title: "One path. Every action.",
    body:
      "Every tool call, workflow step, and sub-agent spawn passes through a single ten-step dispatch: identity, grants, consequence, rate, idempotency, execute, audit. There is no fast path, no privileged caller, no way around it.",
    readouts: [
      { label: "dispatch", value: "10-STEP" },
      { label: "side doors", value: "NONE" },
    ],
  },
  {
    id: "signals",
    kind: "takeover",
    eyebrow: "In Flight",
    title: "Every action, checked before it happens.",
    body:
      "Step inside the traffic. Each request is an intent in transit - authenticated by construction, weighed against grants and consequence, rate-limited and de-duplicated - all before a single side effect lands.",
    readouts: [
      { label: "checked", value: "PRE-EXECUTE" },
      { label: "gate", value: "GRANTS" },
    ],
  },
  {
    id: "network",
    kind: "brain",
    eyebrow: "Least Privilege",
    title: "No agent exceeds the human behind it.",
    body:
      "Authority is the intersection of an agent's grants and its scope, re-checked on every call. A token can never outgrow the person who issued it, and row-level isolation is enforced at the database, not just in code.",
    readouts: [
      { label: "authority", value: "LEAST-PRIV" },
      { label: "re-checked", value: "EVERY CALL" },
    ],
  },
  {
    id: "vision",
    kind: "brain",
    eyebrow: "Human in the Loop",
    title: "The dangerous ones wait for a person.",
    body:
      "High-consequence actions pause for a human. Approvals are single-use and verb-bound, and can never be self-approved or replayed across calls. Autonomy stops being a leap of faith.",
    readouts: [
      { label: "gate", value: "HITL" },
      { label: "approval", value: "SINGLE-USE" },
    ],
  },
  {
    id: "balance",
    kind: "brain",
    eyebrow: "The Record",
    title: "A record that proves itself.",
    body:
      "Every action writes exactly one hash-chained, HMAC-keyed row. Reorder, drop, or edit anything and re-deriving the chain fails. When someone asks what the agent did, the answer is something you can prove.",
    readouts: [
      { label: "audit", value: "HASH-CHAINED" },
      { label: "tamper", value: "EVIDENT" },
    ],
  },
  {
    id: "whole",
    kind: "brain",
    eyebrow: "In Production",
    title: "Governance that holds up under audit.",
    body:
      "Identity, grants, approvals, and proof - built in, not bolted on. Drop Boltrig behind any system over MCP, put an agent where it counts, and keep the receipts. This is where agents go to work.",
    readouts: [
      { label: "interface", value: "MCP · IN/OUT" },
      { label: "state", value: "READY" },
    ],
    align: "center",
    cta: { label: "Open the console" },
  },
];

/** The index of the takeover chapter (the one that hides the brain). */
export const TAKEOVER_INDEX = STORY_SECTIONS.findIndex((s) => s.kind === "takeover");
