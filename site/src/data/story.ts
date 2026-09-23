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
    title: "Put an AI workforce to work without losing control.",
    body:
      "Boltrig gives your team a standing group of AI agents that can triage requests, run workflows, update systems and ask for approval when the work matters. You get faster execution without turning trust, security and accountability into manual follow-up.",
    readouts: [
      { label: "work", value: "DELEGATED" },
      { label: "risk", value: "CONTROLLED" },
      { label: "record", value: "COMPLETE" },
    ],
  },
  {
    id: "cortex",
    kind: "brain",
    eyebrow: "Control",
    title: "Let agents act, but only inside the rules.",
    body:
      "Give agents the tools they need, not blanket access. Boltrig checks who asked, what the agent is allowed to do, whether a human needs to approve it, and whether the request is safe to run before any side effect lands.",
    readouts: [
      { label: "access", value: "SCOPED" },
      { label: "approval", value: "WHEN NEEDED" },
    ],
  },
  {
    id: "signals",
    kind: "takeover",
    eyebrow: "Connected operations",
    title: "Connect your systems. Turn every request into finished work.",
    body:
      "Bring your CRM, support desk, code, docs and internal tools into one governed run. A customer issue, release chore, compliance request or handoff can move across systems with clear ownership, live progress and an inspectable result. Agents do the routine work; people stay in the loop where judgment matters.",
    readouts: [
      { label: "systems", value: "CONNECTED" },
      { label: "requests", value: "ROUTED" },
      { label: "handoffs", value: "VISIBLE" },
    ],
  },
  {
    id: "network",
    kind: "brain",
    eyebrow: "Workforce",
    title: "Specialists for the jobs teams repeat every day.",
    body:
      "Boltrig routes each request to the right specialist for release prep, support triage, dependency checks, renewals, notifications and more. Skills are reusable, costs are bounded, and sensitive work remains on infrastructure you control.",
  },
  {
    id: "vision",
    kind: "brain",
    eyebrow: "Visibility",
    title: "Know what ran, why it ran, and what changed.",
    body:
      "Every agent run leaves a clear trail: the request, the tools used, the approvals requested, the result, and the follow-on work. Leaders get a real operating view instead of a pile of chatbot transcripts and unverifiable summaries.",
    readouts: [
      { label: "runs", value: "TRACEABLE" },
      { label: "evidence", value: "READY" },
    ],
  },
  {
    id: "balance",
    kind: "brain",
    eyebrow: "Integrations",
    title: "Bring your systems, tools and workflows.",
    body:
      "Connect the systems your team already uses and package your own domain verbs, workflows and skills. Boltrig can run behind your own product UI, serve agents over MCP, and keep the same governance across every entry point.",
    readouts: [
      { label: "plugins", value: "ADOPTED" },
      { label: "frontends", value: "HEADLESS" },
    ],
  },
  {
    id: "whole",
    kind: "brain",
    eyebrow: "Production",
    title: "Self-hosted autonomy your security team can accept.",
    body:
      "Run Boltrig on your infrastructure, map users through SSO or first-party access, and keep credentials out of agent hands. The value is simple: more work completed by agents, with the controls and evidence a serious organisation needs.",
    readouts: [
      { label: "deploy", value: "YOUR CLOUD" },
      { label: "proof", value: "AUDITABLE" },
    ],
    align: "center",
    cta: { label: "Request access", href: "mailto:info@boltrig.ai?subject=Boltrig%20access%20request" },
  },
];

/** The index of the takeover chapter (the one that hides the brain). */
export const TAKEOVER_INDEX = STORY_SECTIONS.findIndex((s) => s.kind === "takeover");
