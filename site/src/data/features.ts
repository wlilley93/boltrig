/**
 * Feature catalogue for the post-story features section (see
 * `components/features/features-section.tsx`). Six themed groups, each with a
 * one-line hook and concrete capabilities written as buyer outcomes.
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
    title: "Connect the work your team already does",
    hook: "Turn requests from customers, colleagues and systems into one visible run.",
    items: [
      {
        name: "One place to route work",
        outcome:
          "Bring chat, webhooks, work boards and workflow runs into one operating view.",
      },
      {
        name: "Governed agent profiles",
        outcome:
          "Give support, release, compliance and operations work to the right specialist without losing the operating context.",
      },
      {
        name: "Tracked workflows",
        outcome:
          "Define multi-step work with dependencies, ownership and a result your team can inspect.",
      },
      {
        name: "Human and agent handoffs",
        outcome: "Track agent and human work together, with nested tasks, status and ownership in one view.",
      },
      {
        name: "Request intake",
        outcome:
          "Accept customer, team and system requests as identity-bound work with a clear owner.",
      },
    ],
  },
  {
    id: "control",
    title: "Keep every action inside the rules",
    hook: "Give agents useful access without handing them a blank cheque.",
    items: [
      {
        name: "Permission checks",
        outcome:
          "Every capability call is checked against organisation, workspace, caller and run authority before it executes.",
      },
      {
        name: "Approval gates",
        outcome:
          "High-impact actions pause for a human decision instead of relying on a prompt to be careful.",
      },
      {
        name: "Secrets stay server-side",
        outcome: "Credentials are resolved inside Boltrig for one call and are never handed to the agent.",
      },
      {
        name: "Private model routing",
        outcome:
          "Sensitive work can be routed to local models and blocked from unsuitable endpoints.",
      },
      {
        name: "Work limits",
        outcome:
          "Reserve organisation and department budgets so over-limit spawned work can be stopped safely.",
      },
    ],
  },
  {
    id: "evidence",
    title: "Make the result provable",
    hook: "Replace vague AI output with a run record operators can inspect and explain.",
    items: [
      {
        name: "Live run history",
        outcome:
          "Watch reasoning, tool calls, approvals and handoffs as they happen, then reattach if a client drops.",
      },
      {
        name: "Run inspector",
        outcome: "Open any run and walk through the steps, workers and tool receipts behind the result.",
      },
      {
        name: "Tamper-evident audit",
        outcome:
          "Actions, denials and approvals produce a tamper-evident record with activity filtered to the caller's scope.",
      },
      {
        name: "Knowledge with citations",
        outcome:
          "Keep text, Markdown and PDF originals, search authorised passages and return immutable revision citations while memory stays separate.",
      },
      {
        name: "Evaluation cases",
        outcome:
          "Run evaluation cases under the initiator's grants and inspect assertions, outputs, effective permissions and history.",
      },
    ],
  },
  {
    id: "experience",
    title: "Meet teams where they work",
    hook: "Use Boltrig's console, your own frontend or the clients your team already trusts.",
    items: [
      {
        name: "Boltrig chat",
        outcome:
          "Command the fleet from a live conversation with files, approvals, tool receipts and run recovery.",
      },
      {
        name: "Your own frontend",
        outcome:
          "Build your own UI over Boltrig's HTTP, SSE and MCP surfaces without forking the engine.",
      },
      {
        name: "MCP in and out",
        outcome: "Expose governed capabilities to external agents and consume reviewed MCP tool servers as new verbs.",
      },
      {
        name: "Signed intake",
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
    title: "Connect the systems that matter",
    hook: "Bring your CRM, support desk, code, docs and internal tools into the same governed model.",
    items: [
      {
        name: "Integration bundles",
        outcome:
          "Ship project adapters, workflows and policy together so a deployment carries its operating model with it.",
      },
      {
        name: "Domain rules",
        outcome:
          "Author the nouns, verbs, bindings and workflows that make your business specific.",
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
    hook: "Self-host Boltrig and keep identity, data and credentials under your control.",
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
