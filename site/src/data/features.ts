/**
 * Feature catalogue for the post-story features section (see
 * `components/features/features-section.tsx`). Six themed groups, each with a
 * one-line hook and five concrete capabilities written as buyer outcomes.
 * Claims are bounded to shipped behaviour; known seams are not advertised as
 * active capability. Pure typed content: no markup, no styling.
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
          "Use Bolt chat, the work board and workflow runs from one console to delegate and track operational work.",
      },
      {
        name: "Governed agent profiles",
        outcome:
          "Configure specialist workers by runtime, skills, depth, lifecycle and cost tier while caller authority remains the ceiling.",
      },
      {
        name: "Governed workflows",
        outcome:
          "Define and trigger dependency-ordered workflows whose capability steps still cross the kernel.",
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
          "Every capability call is checked against organisation, workspace, caller and run authority before it executes.",
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
        name: "Scoped cost boundaries",
        outcome:
          "Configured organisation and department budgets reserve estimated spend and can hard-stop over-limit spawned agent work.",
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
        name: "Audit and scoped reporting",
        outcome:
          "Governed actions, denials and approvals produce a tamper-evident record, with cost and activity views filtered to the caller's scope.",
      },
      {
        name: "Knowledge with citations",
        outcome:
          "Keep text, Markdown and PDF originals, search authorised passages and return immutable revision citations while memory stays separate.",
      },
      {
        name: "Evaluation cases",
        outcome:
          "Run reusable cases under the initiator's grants and inspect assertions, outputs, effective permissions and history.",
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
        name: "Signed channel intake",
        outcome:
          "Accept identity-bound Microsoft Teams or generic webhook events after signature, replay and rate-limit checks.",
      },
      {
        name: "Governed outbound",
        outcome:
          "Send updates through configured outbound webhook endpoints using one approval-gated and audited high-consequence verb.",
      },
    ],
  },
  {
    id: "extension",
    title: "Bring your domain",
    hook: "Package the nouns, verbs, workflows and rules that make your business specific.",
    items: [
      {
        name: "Deployment bundles",
        outcome:
          "Ship project adapters, skills, workflows and manifest policy as a bundle loaded by Boltrig at deploy time.",
      },
      {
        name: "Live authoring",
        outcome:
          "Author nouns, verbs, bindings, skills, workflows and agent profiles as governed data from the console or API.",
      },
      {
        name: "External systems",
        outcome:
          "Register reviewed HTTP, OpenAPI, SQL and MCP integrations through the same governed verb model.",
      },
      {
        name: "Domain guardrails",
        outcome:
          "Compose customer-specific checks from workflow branches and high-consequence capabilities instead of hidden application logic.",
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
        name: "Organisation and workspace access",
        outcome:
          "Manage members, invitations, workspaces and AI keys with OIDC SSO or first-party invite-only access.",
      },
      {
        name: "Private credentials",
        outcome:
          "Store model and integration keys server-side, never in browser code or agent prompts.",
      },
      {
        name: "Production deploys",
        outcome:
          "Build repeatable Docker deployments for the kernel, database, console, workers and durable services.",
      },
      {
        name: "Tested guarantees",
        outcome:
          "Security and governance claims are pinned to automated tests before they are treated as product guarantees.",
      },
    ],
  },
];
