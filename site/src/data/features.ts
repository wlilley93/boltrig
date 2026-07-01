/**
 * Feature catalogue for the post-story features section (see
 * `components/features/features-section.tsx`). Six themed groups, each with a
 * one-line hook and a handful of concrete capabilities written as buyer
 * outcomes. Pure typed content: no markup, no styling.
 */

export interface FeatureItem {
  /** Short capability name (rendered as the row label). */
  name: string;
  /** One-sentence outcome, plain English, claim-true. */
  outcome: string;
}

export interface FeatureGroup {
  /** Stable id (used for the heading anchor + React key). */
  id: string;
  /** Group heading. */
  title: string;
  /** One-line hook under the heading. */
  hook: string;
  items: FeatureItem[];
}

export const FEATURE_GROUPS: FeatureGroup[] = [
  {
    id: "kernel",
    title: "The governed kernel",
    hook: "Every agent action passes one audited, permissioned checkpoint. No exceptions, no side doors.",
    items: [
      {
        name: "Ordered pre-execution gates",
        outcome:
          "Identity, grants, consequence, human approval, rate limits and idempotency run in order before anything executes.",
      },
      {
        name: "Tamper-evident audit trail",
        outcome:
          "Every action writes exactly one hash-chained record, so the history proves itself under audit.",
      },
      {
        name: "Deny-by-default grants",
        outcome:
          "Agents hold the least privilege the job needs, and authority is re-checked on every call.",
      },
      {
        name: "Hard budget stops",
        outcome: "Per-run budgets halt an agent before it can overspend.",
      },
      {
        name: "Kernel-held credentials",
        outcome:
          "Secrets are resolved inside the checkpoint at the moment of use; agents never see a key.",
      },
    ],
  },
  {
    id: "workforce",
    title: "The agent workforce",
    hook: "A standing org of agents that does real work, not a single chatbot.",
    items: [
      {
        name: "Chief of Staff routing",
        outcome:
          "One front door routes each request to the right department head, which spawns short-lived workers for the task.",
      },
      {
        name: "Skills as data",
        outcome:
          "Agents pull from a shared skill library when the job matches, so new abilities ship without new code.",
      },
      {
        name: "Cheapest-capable model routing",
        outcome: "Each task runs on the least expensive model that can do it well.",
      },
      {
        name: "Sensitive data stays local",
        outcome:
          "Work marked sensitive is routed to local models; misroutes are refused and audited.",
      },
      {
        name: "No-escalation evals",
        outcome:
          "Test agents in a harness that cannot escalate, before you trust them with real work.",
      },
    ],
  },
  {
    id: "command",
    title: "Command and memory",
    hook: "One conversation to run the whole fleet, with memory you can trust.",
    items: [
      {
        name: "One streaming chat",
        outcome:
          "Command every agent from a single conversation, with live reasoning, tool calls and approvals as they happen.",
      },
      {
        name: "Fleet memory",
        outcome:
          "The fleet remembers, recalls, improves and forgets, with provenance on every fact.",
      },
      {
        name: "Screened ingest",
        outcome: "Secrets and prompt injection are caught before they can enter memory.",
      },
      {
        name: "Channel intake",
        outcome:
          "File work from Slack, Discord, Telegram, WhatsApp or signed webhooks; every sender pairs to a real identity and every message inherits governance.",
      },
      {
        name: "Governed outbound",
        outcome: "Messages the fleet sends out are approval-gated and audited.",
      },
    ],
  },
  {
    id: "workflows",
    title: "Workflows and the work board",
    hook: "See every piece of agent and human work, and exactly how it ran.",
    items: [
      {
        name: "Visual workflow canvas",
        outcome: "Drag, connect and ship durable workflows without writing code.",
      },
      {
        name: "Scheduled and event triggers",
        outcome:
          "Automations fire on a clock or on events, through the same checkpoint as everything else.",
      },
      {
        name: "Self-improving library",
        outcome:
          "Workflows that succeed are saved and preferred the next time the same job appears.",
      },
      {
        name: "The work board",
        outcome:
          "One board of all agent and human work, with nested work items and an audit tree on every card.",
      },
      {
        name: "Run inspector",
        outcome: "Open any run and walk the full nested execution behind it.",
      },
    ],
  },
  {
    id: "interop",
    title: "Open interoperability",
    hook: "Open at every edge, governed at every edge.",
    items: [
      {
        name: "Capabilities as MCP tools",
        outcome:
          "Expose granted capabilities to any external AI agent, with full governance applied to every call.",
      },
      {
        name: "Bring your own tools",
        outcome:
          "Plug external MCP tool servers in as new capabilities, inert until reviewed and activated.",
      },
      {
        name: "Integrations as data",
        outcome:
          "Adapters declare their verbs, schemas and rate limits; adding one changes no core code.",
      },
      {
        name: "The studio",
        outcome: "Generate adapters and author verbs and skills from the console.",
      },
      {
        name: "Policy as data",
        outcome:
          "Stand up a new tenant by editing one manifest; config changes are themselves governed actions with history and rollback.",
      },
    ],
  },
  {
    id: "deployment",
    title: "Identity and deployment",
    hook: "Enterprise identity in, one image out, every guarantee tested.",
    items: [
      {
        name: "Enterprise SSO",
        outcome:
          "OIDC sign-in with role and visibility mapping, delegation on behalf of others, and admin-run invitations.",
      },
      {
        name: "Personal agents",
        outcome:
          "Each person gets their own agent, with its own memory, activity log, data export and API tokens.",
      },
      {
        name: "Single-image deploy",
        outcome:
          "Self-host the kernel, database and console as one image on your own infrastructure.",
      },
      {
        name: "Cost and insight reporting",
        outcome: "Spend and activity reporting, scoped to what each role is allowed to see.",
      },
      {
        name: "Provably governed",
        outcome:
          "Every governance guarantee is pinned to a machine-checked test in CI.",
      },
    ],
  },
];
