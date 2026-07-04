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
    id: "outcomes",
    title: "Finish more operational work",
    hook: "Move recurring requests out of chat threads and into tracked agent runs.",
    items: [
      {
        name: "One place to delegate",
        outcome:
          "Ask Bolt to handle support triage, release prep, renewals, reporting or internal chores from one console.",
      },
      {
        name: "Specialist workers",
        outcome:
          "Department agents spin up focused workers with only the skills and tools each task requires.",
      },
      {
        name: "Durable workflows",
        outcome:
          "Schedule or trigger repeatable workflows so routine work runs without another meeting or reminder.",
      },
      {
        name: "Work board",
        outcome: "Track agent and human work together, with nested tasks, status and ownership in one view.",
      },
      {
        name: "Reusable skills",
        outcome:
          "Package the procedures your team repeats, then let agents pull them only when the job matches.",
      },
    ],
  },
  {
    id: "control",
    title: "Control what agents can change",
    hook: "Give agents useful access without turning them into unbounded service accounts.",
    items: [
      {
        name: "Scoped permissions",
        outcome:
          "Every tool call is checked against the tenant, user and run grants before it executes.",
      },
      {
        name: "Human approvals",
        outcome:
          "High-impact actions pause for a human decision instead of relying on a prompt to be careful.",
      },
      {
        name: "Secrets stay server-side",
        outcome: "Credentials are resolved inside Boltrig for one call and are never handed to the agent.",
      },
      {
        name: "Cost boundaries",
        outcome: "Per-run budgets stop runaway work before it turns into surprise spend.",
      },
      {
        name: "Sensitive routing",
        outcome:
          "Sensitive work can be routed to local models and blocked from unsuitable endpoints.",
      },
    ],
  },
  {
    id: "evidence",
    title: "Show the evidence",
    hook: "Replace vague AI output with a run record your operators and auditors can inspect.",
    items: [
      {
        name: "Live execution stream",
        outcome:
          "Watch reasoning, tool calls, approvals and handoffs as they happen, then reattach if a client drops.",
      },
      {
        name: "Run inspector",
        outcome: "Open any run and walk through the steps, workers and tool receipts behind the result.",
      },
      {
        name: "Audit trail",
        outcome:
          "Every action produces a durable record of who asked, what ran, what changed and whether it was allowed.",
      },
      {
        name: "Memory with provenance",
        outcome: "Facts the fleet remembers carry source context, so teams can trace where an answer came from.",
      },
      {
        name: "Role-scoped reporting",
        outcome: "Cost, activity and audit views are filtered to what each person is allowed to see.",
      },
    ],
  },
  {
    id: "experience",
    title: "Meet teams where they work",
    hook: "Use Boltrig's console, your own frontend, or external agent clients.",
    items: [
      {
        name: "Console chat",
        outcome:
          "Command the fleet from a live conversation with files, approvals, tool receipts and run recovery.",
      },
      {
        name: "Headless engine",
        outcome:
          "Build your own UI over Boltrig's HTTP, SSE and MCP surfaces without forking the engine.",
      },
      {
        name: "MCP in and out",
        outcome: "Expose governed capabilities to external agents and consume reviewed MCP tool servers as new verbs.",
      },
      {
        name: "Channel intake",
        outcome:
          "Route work from chat platforms or signed webhooks while keeping identity, approvals and audit intact.",
      },
      {
        name: "Governed outbound",
        outcome: "Let agents send updates while high-risk messages stay approval-gated and traceable.",
      },
    ],
  },
  {
    id: "extension",
    title: "Bring your domain",
    hook: "Package the nouns, verbs, workflows and rules that make your business specific.",
    items: [
      {
        name: "Plugin bundles",
        outcome: "Ship project adapters, skills and workflows as an adopted bundle loaded by Boltrig at deploy time.",
      },
      {
        name: "Runtime authoring",
        outcome:
          "Author nouns, verbs, bindings, skills and workflows as data from the console or API.",
      },
      {
        name: "External systems",
        outcome:
          "Connect SQL, HTTP, messaging and file-backed systems through the same governed verb model.",
      },
      {
        name: "Client hard gates",
        outcome:
          "Model customer-specific go/no-go checks as governed capabilities rather than hidden application logic.",
      },
      {
        name: "No core fork",
        outcome: "Keep Boltrig's engine standard while each product brings its own domain package.",
      },
    ],
  },
  {
    id: "deployment",
    title: "Run it where the data lives",
    hook: "Self-host the engine and keep enterprise identity, data and credentials under your control.",
    items: [
      {
        name: "Self-hosted stack",
        outcome:
          "Run the kernel, database, console and agent runtime on your own infrastructure.",
      },
      {
        name: "Enterprise access",
        outcome:
          "Use SSO or first-party invite-only access, with roles mapped to what people may see and do.",
      },
      {
        name: "Private credentials",
        outcome:
          "Store model and integration keys server-side, never in browser code or agent prompts.",
      },
      {
        name: "Production deploys",
        outcome: "Build repeatable Docker deployments with Postgres, Redis, Hatchet and the Pi sidecar.",
      },
      {
        name: "Tested guarantees",
        outcome:
          "Security and governance claims are pinned to automated tests before they are treated as product guarantees.",
      },
    ],
  },
];
