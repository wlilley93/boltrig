import React from "react";
import ReactDOM from "react-dom/client";
import type { ConversationResponse } from "@wlilley93/boltrig-web-sdk";

import "../../src/styles.css";
import manifest from "./states.json";

type VisualState = (typeof manifest.states)[number];
type SelectorAwareVisualState = VisualState & {
  required_presence_selectors?: readonly string[];
  required_absence_selectors?: readonly string[];
  required_visible_selectors?: readonly string[];
  required_text?: readonly string[];
  required_exact_text?: ReadonlyArray<{
    selector: string;
    text: string;
  }>;
  required_visible_counts?: ReadonlyArray<{
    selector: string;
    count: number;
  }>;
  required_absent_text?: readonly string[];
  required_geometry?: ReadonlyArray<{
    selector: string;
    width?: number;
    height?: number;
    x?: number;
    y?: number;
    tolerance?: number;
  }>;
  required_computed_styles?: ReadonlyArray<{
    selector: string;
    property: string;
    value: string;
  }>;
};

type VisualCaptureContract = {
  schema: "boltrig-worker-visual-capture-contract.v1";
  state: string;
  expectedHash: string;
  actualHash: string;
  viewport: { width: number; height: number; devicePixelRatio: number };
  output: string | null;
  ready: boolean;
  settledAt: string | null;
  stableFrames: number;
  pendingRequests: number;
  missingRequestPrefixes: string[];
  fixtureMisses: string[];
  contractMisses: string[];
  requestedPaths: string[];
};

const query = new URLSearchParams(window.location.search);
const legacyScreen = query.get("screen");
const legacyState = query.get("palette") === "1"
  ? "command-palette"
  : legacyScreen === "agents"
    ? "agents"
    : legacyScreen === "integrations"
      ? "plugins"
      : legacyScreen === "settings/you"
        ? "settings-you"
        : legacyScreen === "chat/run-thread"
          ? "chat-run"
          : legacyScreen === "chat/voice-thread"
            ? "call"
            : "new-chat";
const requestedStateId = query.get("state") ?? legacyState;
const selectedVisualState = manifest.states.find((state) => state.id === requestedStateId);
if (!selectedVisualState) {
  throw new Error(
    `Unknown visual state “${requestedStateId}”. Use one of: ${manifest.states.map((state) => state.id).join(", ")}.`,
  );
}
const visualState: SelectorAwareVisualState = selectedVisualState;
const visualTheme = query.get("theme") === "light" ? "light" : "dark";

const now = "2026-08-11T03:30:00Z";
const frozenNow = Date.parse(now);
Date.now = () => frozenNow;
let visualRandomSeed = 0x0b017a1;
Math.random = () => {
  visualRandomSeed = (Math.imul(visualRandomSeed, 1_664_525) + 1_013_904_223) >>> 0;
  return visualRandomSeed / 0x1_0000_0000;
};

document.documentElement.dataset.theme = visualTheme;
document.documentElement.dataset.visualState = visualState.id;
document.documentElement.dataset.visualViewport = `${manifest.viewport.width}x${manifest.viewport.height}`;
// This entrypoint intentionally bypasses main.tsx so requests can be mocked
// before the client is imported. Mirror the fixture's persisted/server motion
// setting here as well, before Familiar renderers are constructed.
document.documentElement.classList.add("reduce-motion");
document.title = `Boltrig parity · ${visualState.label}`;
window.location.hash = visualState.hash;

try {
  localStorage.setItem("boltrig.appearance", JSON.stringify({
    theme: visualTheme,
    density: "comfortable",
    fontScale: "1",
    reducedMotion: true,
    highContrast: false,
  }));
  localStorage.setItem("boltrig-worker-theme", visualTheme);
  // Exercise the real two-group TaskList hierarchy. The fixture owns only the
  // presentation preference; every row still comes from the conversation
  // response above, and no pinned task is invented outside that contract.
  localStorage.setItem(
    "boltrig-worker-pinned-conversations",
    JSON.stringify(["vendor-invoice-triage"]),
  );
  localStorage.removeItem("boltrig-worker-voice-banner-dismissed");
} catch {
  // A visual runner with storage disabled still receives the server fixture.
}

const activeConversationId = visualState.id === "call"
  ? "voice-thread"
  : visualState.id === "chat-direction"
    ? "direction-thread"
    : "run-thread";

const conversations = [
  {
    id: activeConversationId,
    title: visualState.id === "chat-direction"
      ? "Desktop chat evidence"
      : visualState.id === "call"
        ? "Renewal outreach"
        : "Renewal outreach, top 20 accounts",
    status: "active",
    updated_at: now,
  },
  { id: "vendor-invoice-triage", title: "Vendor invoice triage", status: "active", updated_at: now },
  { id: "q3-pipeline-hygiene", title: "Q3 pipeline hygiene sweep", status: "active", updated_at: now },
  { id: "onboarding-lakeside", title: "Onboarding: Lakeside", status: "active", updated_at: now },
];

const voiceThread = {
  messages: [],
  active_run_id: null,
} satisfies ConversationResponse;

const runThread = {
  messages: [
    {
      id: "run-user-1",
      role: "user",
      content: "Draft renewal outreach for the top 20 accounts, and raise a ticket for anything flagged at risk.",
      created_at: "2026-08-11T03:28:00Z",
    },
    {
      id: "run-assistant-1",
      role: "assistant",
      content: "Twenty accounts fall inside the renewal window. I drafted outreach for each in the account owner's voice, and read health signals from your CRM.\n\nThree came back at risk: Northwind, Lakeside and Vertex. Raising tickets is something you asked to approve yourself, so I've stopped there.",
      run_id: "run-renewal-review",
      created_at: "2026-08-11T03:29:12Z",
      events: [
        {
          type: "model_routing", run_id: "run-renewal-review",
          selected_profile_id: "best", routing_class: "balanced",
          reason: "workspace_default", overridden: false,
        },
        {
          type: "subagent", child_run_id: "run-lyell-renewals",
          task: "Review renewal health signals", skills: ["research", "summarise"],
          name: "Lyell", role: "research", color: "#267a91", step_count: 3,
          familiar_genotype: familiarGenotype(
            "Lyell", ["#267a91", "#18304a", "#f0c37b"],
          ),
        },
        {
          type: "subagent", child_run_id: "run-hutton-renewals",
          task: "Draft 20 outreach messages", skills: ["draft", "write"],
          name: "Hutton", role: "builder", color: "#315e78", step_count: 3,
          familiar_genotype: familiarGenotype(
            "Hutton", ["#315e78", "#18304a", "#f0c37b"],
          ),
        },
        {
          type: "subagent", child_run_id: "run-noether-renewals",
          task: "Check three at-risk accounts against policy", skills: ["policy", "review"],
          name: "Noether", role: "guardian", color: "#46b881", step_count: 3,
          familiar_genotype: familiarGenotype(
            "Noether", ["#46b881", "#18304a", "#f0c37b"],
          ),
        },
        {
          type: "subagent", child_run_id: "run-brunel-renewals",
          task: "Summarise what changed", skills: ["analyse", "summarise"],
          name: "Brunel", role: "analyst", color: "#9b7bff", step_count: 2,
          familiar_genotype: familiarGenotype(
            "Brunel", ["#9b7bff", "#18304a", "#f0c37b"],
          ),
        },
        {
          type: "subagent", child_run_id: "run-curie-renewals",
          task: "Check the drafts read well", skills: ["read", "review"],
          name: "Curie", role: "reviewer", color: "#d97757", step_count: 2,
          familiar_genotype: familiarGenotype(
            "Curie", ["#d97757", "#18304a", "#f0c37b"],
          ),
        },
        {
          type: "tool_call", run_id: "run-renewal-review",
          tool: "crm.health.read", call_id: "call-renewal-health",
          args_summary: { keys: ["window", "status"], count: 2 }, consequence: "low",
        },
        {
          type: "tool_result", run_id: "run-renewal-review",
          verb: "crm.health.read", call_id: "call-renewal-health", status: "ok",
          result_summary: { keys: ["accounts", "as_of"], status: "ok" },
        },
        { type: "subagent_end", child_run_id: "run-lyell-renewals", status: "ok" },
        { type: "subagent_end", child_run_id: "run-hutton-renewals", status: "ok" },
        { type: "subagent_end", child_run_id: "run-noether-renewals", status: "ok" },
        { type: "subagent_end", child_run_id: "run-brunel-renewals", status: "ok" },
        { type: "subagent_end", child_run_id: "run-curie-renewals", status: "ok" },
        {
          type: "text_delta",
          delta: "Twenty accounts fall inside the renewal window. I drafted outreach for each in the account owner's voice, and read health signals from your CRM.\n\nThree came back at risk: Northwind, Lakeside and Vertex. Raising tickets is something you asked to approve yourself, so I've stopped there.",
        },
      ],
    },
  ],
  active_run_id: null,
};

// Additive evidence state for DECISION-0005 / DIR-0008 / DIR-0009. Every
// activity row is a completed persisted receipt. Nothing here claims a live
// process, a media session, spend, or an actionable approval.
const directionThread = {
  conversation: { agent_address: "chief-of-staff", workspace_id: null },
  messages: [
    {
      id: "direction-user-1",
      role: "user",
      content: "Reconcile the desktop chat chrome with the supplied Codex references.",
      recipient_agent_address: "chief-of-staff",
      created_at: "2026-08-11T03:24:00Z",
      attachments: [{
        name: "codex-chat-reference.png",
        media_type: "image/png",
        size: 28_823,
        data: "iVBORw0KGgo=",
      }],
    },
    {
      id: "direction-assistant-1",
      role: "assistant",
      content: "I mapped the chat chrome to the supplied references and kept the exact implementation receipts available.",
      author_agent_address: "chief-of-staff",
      run_id: "run-chat-direction-ui",
      created_at: "2026-08-11T03:25:00Z",
      events: [
        {
          type: "text_delta",
          delta: "I mapped the chat chrome to the supplied references and kept the exact implementation receipts available.",
        },
        { type: "tool_call", run_id: "run-chat-direction-ui", tool: "figma.get_design_context", call_id: "call-direction-figma" },
        { type: "tool_result", run_id: "run-chat-direction-ui", verb: "figma.get_design_context", call_id: "call-direction-figma", status: "ok" },
        { type: "tool_call", run_id: "run-chat-direction-ui", tool: "file.read", call_id: "call-direction-read" },
        { type: "tool_result", run_id: "run-chat-direction-ui", verb: "file.read", call_id: "call-direction-read", status: "ok" },
        { type: "tool_call", run_id: "run-chat-direction-ui", tool: "apply_patch", call_id: "call-direction-edit" },
        { type: "tool_result", run_id: "run-chat-direction-ui", verb: "apply_patch", call_id: "call-direction-edit", status: "ok" },
        { type: "tool_call", run_id: "run-chat-direction-ui", tool: "exec_command", call_id: "call-direction-command" },
        { type: "tool_result", run_id: "run-chat-direction-ui", verb: "exec_command", call_id: "call-direction-command", status: "ok" },
      ],
    },
    {
      id: "direction-user-2",
      role: "user",
      content: "Prepare the deterministic preview and evidence inspection.",
      recipient_agent_address: "chief-of-staff",
      created_at: "2026-08-11T03:26:00Z",
    },
    {
      id: "direction-assistant-2",
      role: "assistant",
      content: "The preview and inspection receipts completed without inventing live state.",
      author_agent_address: "chief-of-staff",
      run_id: "run-chat-direction-evidence",
      created_at: "2026-08-11T03:27:00Z",
      events: [
        {
          type: "text_delta",
          delta: "The preview and inspection receipts completed without inventing live state.",
        },
        {
          type: "subagent", child_run_id: "run-vds-scout-direction",
          task: "Check VDS direction coverage", skills: ["audit"],
          name: "Vds scout", role: "reviewer", color: "#267a91",
          familiar_genotype: familiarGenotype(
            "Lyell", ["#e85d75", "#3b1f30", "#f0c37b"],
          ),
        },
        {
          type: "subagent", child_run_id: "run-repo-scout-direction",
          task: "Check implementation receipts", skills: ["review"],
          name: "Repo scout", role: "reviewer", color: "#9b7bff",
          familiar_genotype: familiarGenotype(
            "Hutton", ["#35c2d4", "#18304a", "#d7f6fb"],
          ),
        },
        {
          type: "subagent", child_run_id: "run-capture-scout-direction",
          task: "Check deterministic capture inputs", skills: ["evidence"],
          name: "Capture scout", role: "reviewer", color: "#46b881",
          familiar_genotype: familiarGenotype(
            "Noether", ["#9b7bff", "#2f2357", "#f0c37b"],
          ),
        },
        { type: "tool_call", run_id: "run-chat-direction-evidence", tool: "background.process.preview", call_id: "call-direction-background" },
        { type: "tool_result", run_id: "run-chat-direction-evidence", verb: "background.process.preview", call_id: "call-direction-background", status: "ok" },
        { type: "tool_call", run_id: "run-chat-direction-evidence", tool: "computer.use.inspect", call_id: "call-direction-computer" },
        { type: "tool_result", run_id: "run-chat-direction-evidence", verb: "computer.use.inspect", call_id: "call-direction-computer", status: "ok" },
        { type: "subagent_end", child_run_id: "run-vds-scout-direction", status: "ok" },
        { type: "subagent_end", child_run_id: "run-repo-scout-direction", status: "ok" },
        { type: "subagent_end", child_run_id: "run-capture-scout-direction", status: "ok" },
        {
          type: "display_object",
          run_id: "run-chat-direction-evidence",
          object: {
            schema: "boltrig.display.v1",
            id: "direction-slack-draft",
            kind: "slack.message.draft",
            title: "Draft update for #launch",
            status: "draft",
            revision: 1,
            data: {
              channel_id: "slack-primary",
              workspace_label: "Acme",
              recipient: "#launch",
              body: "The review evidence is ready. I will hold this draft until you send it.",
            },
            actions: [
              { id: "edit", label: "Edit", intent: "edit" },
              { id: "change-recipient", label: "Change recipient", intent: "change_recipient" },
              { id: "send", label: "Send", intent: "send", style: "primary" },
              { id: "discard", label: "Discard", intent: "discard" },
            ],
            provenance: {
              run_id: "run-chat-direction-evidence",
              agent_address: "chief-of-staff",
              provider: "Slack",
              connection_label: "Acme",
            },
          },
        },
      ],
    },
  ],
  active_run_id: null,
};

const profiles = [
  profile("chief-of-staff", "Chief of Staff", ["coordinate", "delegate", "report"], 4, "expensive"),
  profile("revenue-ops", "Revenue Ops", ["crm", "forecast", "report"], 3, "standard"),
  profile("Lyell", "Lyell", ["research", "summarise"], 2, "cheap"),
  profile("Hutton", "Hutton", ["analysis", "report"], 2, "standard"),
  profile("Noether", "Noether", ["model", "analyse"], 2, "standard"),
  profile("Curie", "Curie", ["research", "knowledge"], 1, "cheap"),
  profile("Brunel", "Brunel", ["build", "operate"], 1, "standard"),
];

const hierarchy = {
  chief: head("chief-of-staff", "chief-of-staff", ["coordinate", "delegate", "report"], 4, "expensive"),
  departments: [
    head("revenue-ops", "revenue-ops", ["crm", "forecast", "report"], 3, "standard"),
    head("Lyell", "lyell", ["research", "summarise"], 2, "cheap"),
    head("Hutton", "hutton", ["analysis", "report"], 2, "standard"),
    head("Noether", "noether", ["model", "analyse"], 2, "standard"),
    head("Curie", "curie", ["research", "knowledge"], 1, "cheap"),
    head("Brunel", "brunel", ["build", "operate"], 1, "standard"),
  ],
};

const integrations = [
  integration("slack", "Slack", "communications", "Team messages and approvals", "oauth2", "certified"),
  integration("gmail", "Gmail", "communications", "Read and draft mail", "oauth2", "certified"),
  integration("google-calendar", "Google Calendar", "work", "Calendars and events", "oauth2", "certified"),
  integration("notion", "Notion", "work", "Pages and workspace knowledge", "oauth2", "certified"),
  integration("figma", "Figma", "storage_design", "Design files and comments", "oauth2", "certified"),
  integration("github", "GitHub", "work", "Repositories, issues and pull requests", "oauth2", "certified"),
  integration("linear", "Linear", "work", "Issues and project tracking", "oauth2", "certifying"),
  integration("hubspot", "HubSpot", "crm_sales", "CRM records and pipelines", "oauth2", "certifying"),
  integration("stripe", "Stripe", "finance", "Payments and finance", "manual_secret", "uncertified"),
];

const connections = integrations.slice(0, 6).map((item, index) => ({
  id: `connection-${item.id}`,
  integration_id: item.id,
  label: index === 0 ? "Boltrig workspace" : "Connected account",
  health: index === 4 ? "degraded" : "ok",
  credential_ref_present: true,
  accounts: [],
  enabled_tools: [],
  last_checked_at: now,
  created_at: now,
}));

const routines = [
  workflow("renewal-outreach", ["crm.account.read", "crm.health.read", "doc.write", "ticket.create", "work.report"], ["revenue", "renewal"], "learned", { cron: "0 8 * * 1", timezone: "Europe/London" }),
  workflow("invoice-triage", ["mail.read", "invoice.read", "invoice.classify", "work.report"], ["finance", "inbox"], "generated"),
  workflow("pipeline-hygiene", ["crm.pipeline.read", "crm.account.update", "work.report"], ["revenue", "quality"], "precreated", { cron: "0 7 * * 1-5", timezone: "Europe/London" }),
  workflow("onboarding-check", ["crm.account.read", "calendar.read", "doc.write"], ["onboarding"], "learned"),
  workflow("weekly-board-pack", ["work.read", "doc.write", "mail.draft"], ["leadership", "reporting"], "generated", { cron: "0 15 * * 5", timezone: "Europe/London" }),
];

const fixtures: Record<string, unknown> = {
  "/v1/me/settings": {
    profile: { id: "will", email: "will@boltrig.com", display_name: "Will Lilley", role: "org-admin" },
    settings: {
      theme: visualTheme,
      density: "comfortable",
      font_scale: "1",
      "a11y.reduced_motion": true,
      "a11y.high_contrast": false,
      developer_details: false,
    },
  },
  "/v1/me/approval-posture": {
    posture: "risk_based",
    source: "safe_default",
    enforcement: {
      applies_to: "delegated_agent_adapter_calls",
      workspace_blocking_verbs_remain: true,
      control_plane_approvals_remain: true,
      direct_human_consequence_gate_remains: true,
      authority_is_never_widened: true,
    },
  },
  "/v1/me/notifications": {
    prefs: [{
      id: "notification-approval-slack",
      event_type: "approval",
      channel: "slack",
      target: "ops",
      enabled: true,
      deliverable: true,
    }],
    catalogue: {
      events: [
        { id: "approval", label: "Approvals", description: "Needs you" },
        { id: "escalation", label: "Escalations", description: "Needs authority" },
        { id: "work_status", label: "Work status", description: "Lane changes" },
      ],
      transports: [{
        id: "slack", platform: "slack", label: "Slack",
        delivery_mode: "durable_outbox",
        targets: [{ id: "ops", label: "Ops" }],
      }],
    },
  },
  "/v1/orgs/current": {
    organisation: {
      id: "acme", name: "acme", slug: "acme", settings: {},
      allow_own_ai_keys: true, require_two_factor: false,
    },
  },
  "/v1/workspaces": {
    // The capture's authenticated execution context is "production", but it
    // deliberately has no user-created projects. This keeps the existing
    // Projects/Recents empty-state contract truthful now that the sidebar loads
    // the real workspace catalogue for project grouping.
    workspaces: [],
  },
  "/v1/named-agents": {
    named_agents: [{
      address: "chief-of-staff",
      name: "Chief of Staff",
      topology: "tier1_peer",
      session: "durable_logical",
      runtime: "claude-code",
      model_endpoint: null,
      supported_skills: ["coordinate", "delegate", "report"],
      max_depth: 4,
      cost_tier: "expensive",
      purpose: "Coordinate peer agents and report to the user.",
      scope_id: null,
      default_for_intake: true,
      enabled: true,
    }],
  },
  "/v1/console/overview": {
    generated_at: now, tenant_id: "acme", workspace_id: "production", scope: [],
    platform: { components: [], runtimes: [] }, models: [],
    cost: { total_cost_micros: 0, by_actor: {}, by_status: {} },
    budgets: [], recent_runs: [], approvals: [],
    counts: { visible_events: 0, recent_runs: 0, pending_approvals: 0 },
  },
  "/v1/conversations": { conversations, next_offset: null },
  "/v1/conversations/run-thread": runThread,
  "/v1/conversations/direction-thread": directionThread,
  "/v1/conversations/voice-thread": voiceThread,
  "/v1/artifacts": { artifacts: [], next_cursor: null },
  "/v1/chat/config": {
    attachments: {
      max_count: 5, max_bytes: 8_000_000, max_total_bytes: 20_000_000,
      model_readable_media_types: ["image/png", "image/jpeg", "text/plain"],
    },
  },
  "/v1/familiar/phenotype": {
    phenotype: { state: "resting", intensity: 0, confidence: 1, observed_at: now },
  },
  "/v1/model-profiles": {
    profiles: [{
      id: "best", label: "Best available", routing_class: "balanced",
      data_classes: [], available: true,
    }],
  },
  "/v1/chat/model-choices": {
    status: "ok",
    reason: null,
    choices: [
      {
        id: "reasoning-route",
        model_name: "openai/gpt-5.4",
        available: true,
        is_default: true,
        modalities: ["text", "vision"],
        unavailable_reason: null,
      },
      {
        id: "writing-route",
        model_name: "anthropic/claude-sonnet-4-5",
        available: true,
        is_default: false,
        modalities: ["text"],
        unavailable_reason: null,
      },
    ],
    default_choice_id: "reasoning-route",
    default_model_name: "openai/gpt-5.4",
    default_available: true,
    default_unavailable_reason: null,
  },
  "/readyz": { status: "degraded", checks: { vault: { status: "not_ready" } } },
  "/v1/agent-capabilities": { agent_capabilities: profiles },
  "/v1/permanent-fleet": {
    status: "configured", hierarchy, generation: "fixture", revision: 7,
    apply_state: "startup_applied_liveness_unknown", hot_applied: false,
    runtime_liveness: "unknown_not_probed_by_startup", profiles_reconciled: true,
    observations: [],
  },
  "/v1/model-endpoints": { endpoints: [] },
  "/v1/hitl": { requests: [] },
  "/v1/integrations/catalogue": { integrations },
  "/v1/integrations/connections": { connections },
  "/v1/addons": {
    scope: { tenant_id: "acme", workspace_id: "production" },
    addons: [
      addon("filesystem-mcp", "Filesystem MCP", "ready"),
      addon("github-mcp", "GitHub MCP", "ready"),
      addon("browser-mcp", "Browser MCP", "degraded"),
    ],
  },
  "/v1/mcp/servers": {
    truncated: false,
    servers: [
      mcpServer("filesystem", "ok", 12),
      mcpServer("github", "ok", 18),
      mcpServer("browser", "degraded", 7),
    ],
  },
  "/v1/workflows": { workflows: routines },
  "/v1/workflow-stats": {
    stats: routines.map((routine, index) => ({
      workflow_id: routine.id,
      run_count: 18 - index * 2,
      success_count: 17 - index * 2,
      last_run_at: index === 3 ? null : now,
    })),
  },
  "/v1/capabilities": {
    verbs: [...new Set(["voice.call", ...routines.flatMap((routine) => (
      (routine.definition.steps as Array<{ action: string }>).map((step) => step.action)
    ))])].map((id) => ({ id, noun: id.split(".")[0] })),
  },
  "/v1/calls/current": {
    call: visualState.id === "call" ? {
      id: "call-visual", conversation_id: "voice-thread", status: "active",
      provider_class: "realtime_voice", started_at: "2026-08-11T03:27:46Z",
      participants: [
        participant("chief", "chief of staff", "agent", "#4b78ae"),
        participant("lyell", "Lyell", "agent", "#267a91"),
        participant("hutton", "Hutton", "agent", "#315e78"),
        participant("noether", "Noether", "agent", "#46b881"),
        participant("will", "Will", "user", "#0a84ff"),
      ],
    } : null,
  },
  "/v1/calls/call-visual/events": {
    events: [{
      id: "line-1", call_id: "call-visual", type: "transcript",
      payload: {
        kind: "output",
        text: "Revenue-ops came back: three of the twenty are at risk. I can have the tickets raised, but you asked to approve those yourself.",
      },
      participant_id: "chief", created_at: now,
    }],
  },
  "/v1/calls": { calls: [] },
};

const requestedPaths: string[] = [];
const fixtureMisses: string[] = [];
let pendingRequests = 0;
let paletteOpenRequested = false;
let visualStabilityFingerprint: string | null = null;
let visualStableFrames = 0;
let visualStabilityFrame: number | null = null;
let latestMissingRequestPrefixes: string[] = [];
let latestContractMisses: string[] = [];
const visualWindow = window as typeof window & {
  __boltrigVisualRequests?: string[];
  __boltrigVisualFixtureMisses?: string[];
  __boltrigVisualState?: VisualState;
  __boltrigVisualCaptureContract?: VisualCaptureContract;
};
visualWindow.__boltrigVisualRequests = requestedPaths;
visualWindow.__boltrigVisualFixtureMisses = fixtureMisses;
visualWindow.__boltrigVisualState = visualState;

const runEventFixtures: Record<string, unknown[]> = {
  "run-renewal-review": [
    {
      type: "tool_call", run_id: "run-renewal-review", tool: "crm.health.read",
      call_id: "call-renewal-health",
      input: { window: "30d", status: ["healthy", "at_risk"] },
      args_summary: { keys: ["status", "window"], count: 2 },
    },
    {
      type: "tool_result", run_id: "run-renewal-review",
      call_id: "call-renewal-health", status: "ok",
      output: { accounts: 20, as_of: now },
      result_summary: { keys: ["accounts", "as_of"] },
    },
  ],
  "run-chat-direction-ui": [
    {
      type: "tool_call", run_id: "run-chat-direction-ui", tool: "figma.get_design_context",
      call_id: "call-direction-figma", input: { node_id: "5:2" },
      args_summary: { keys: ["node_id"], count: 1 },
    },
    {
      type: "tool_result", run_id: "run-chat-direction-ui",
      call_id: "call-direction-figma", status: "ok",
      output: { nodes: 1 }, result_summary: { keys: ["nodes"] },
    },
    {
      type: "tool_call", run_id: "run-chat-direction-ui", tool: "file.read",
      call_id: "call-direction-read", input: { path: "apps/worker/src/components/ChatView.tsx" },
      args_summary: { keys: ["path"], count: 1 },
    },
    {
      type: "tool_result", run_id: "run-chat-direction-ui",
      call_id: "call-direction-read", status: "ok",
      output: { bytes: 8432 }, result_summary: { keys: ["bytes"] },
    },
    {
      type: "tool_call", run_id: "run-chat-direction-ui", tool: "apply_patch",
      call_id: "call-direction-edit", input: { files: ["ChatView.tsx"] },
      args_summary: { keys: ["files"], count: 1 },
    },
    {
      type: "tool_result", run_id: "run-chat-direction-ui",
      call_id: "call-direction-edit", status: "ok",
      output: { changed_files: 1 }, result_summary: { keys: ["changed_files"] },
    },
    {
      type: "tool_call", run_id: "run-chat-direction-ui", tool: "exec_command",
      call_id: "call-direction-command",
      input: { cmd: "pnpm --dir apps/worker typecheck", workdir: "/workspace/boltrig" },
      args_summary: { keys: ["cmd", "workdir"], count: 2 },
    },
    {
      type: "tool_result", run_id: "run-chat-direction-ui",
      call_id: "call-direction-command", status: "ok",
      output: { output: "Done in 1.2s", exit_code: 0 },
      result_summary: { keys: ["exit_code", "output"] },
    },
  ],
};

window.fetch = async (input) => {
  const resource = typeof input === "string"
    ? input
    : input instanceof URL ? input.href : input.url;
  const url = new URL(resource, window.location.href);
  const requestPath = `${url.pathname}${url.search}`;
  requestedPaths.push(requestPath);
  pendingRequests += 1;
  invalidateVisualReadiness();
  updateVisualDiagnostics();
  try {
    const runMatch = url.pathname.match(/^\/v1\/runs\/([^/]+)\/events$/);
    if (runMatch) {
      const events = runEventFixtures[decodeURIComponent(runMatch[1]!)];
      if (!events) {
        if (!fixtureMisses.includes(requestPath)) fixtureMisses.push(requestPath);
        return json({ status: "unavailable", reason: "No visual run fixture" }, 404);
      }
      return sse(events);
    }
    const routine = routines.find((item) => url.pathname === `/v1/workflows/${item.id}`);
    const value = routine ?? fixtures[url.pathname];
    if (value === undefined) {
      if (!fixtureMisses.includes(requestPath)) fixtureMisses.push(requestPath);
      return json({ status: "unavailable", reason: `No visual fixture for ${url.pathname}` }, 404);
    }
    return json(value);
  } finally {
    pendingRequests -= 1;
    updateVisualDiagnostics();
    queueMicrotask(evaluateVisualState);
  }
};

// Import client-owning modules only after fetch is replaced. BoltrigClient
// captures its fetcher during module evaluation, so this ordering keeps the
// visual fixture isolated from a real kernel without altering production auth.
const [{ App }, { WorkerGlobalContextProvider }] = await Promise.all([
  import("../../src/App"),
  import("../../src/components/WorkerGlobalContext"),
]);

const root = document.getElementById("root");
if (!root) throw new Error("root element #root not found");

ReactDOM.createRoot(root).render(
  <WorkerGlobalContextProvider>
    <App />
  </WorkerGlobalContextProvider>,
);

const visualObserver = new MutationObserver(() => {
  driveRequestedState();
  evaluateVisualState();
});
visualObserver.observe(document.body, {
  attributes: true,
  childList: true,
  subtree: true,
});
window.addEventListener("resize", evaluateVisualState);
driveRequestedState();
evaluateVisualState();

function driveRequestedState() {
  if (visualState.id !== "command-palette") return;
  if (document.querySelector('[data-screen-label="Command palette"]')) return;
  // The target palette belongs over the run-thread surface. Do not open it
  // until the real persisted conversation has reached the same truthful
  // completed state used by the chat-run capture.
  if (!runThreadSurfaceIsReady()) return;
  const open = document.querySelector<HTMLButtonElement>(
    'button[aria-label="Open command palette"]',
  );
  if (open && !paletteOpenRequested) {
    paletteOpenRequested = true;
    open.click();
  }
}

function evaluateVisualState() {
  latestMissingRequestPrefixes = visualState.required_request_prefixes.filter((prefix) => (
    !requestedPaths.some((requestPath) => requestPath.startsWith(prefix))
  ));
  latestContractMisses = visualContractMisses(visualState);
  if (latestContractMisses.length > 0) {
    document.documentElement.dataset.visualContractMisses = latestContractMisses.join("|");
  } else {
    delete document.documentElement.dataset.visualContractMisses;
  }
  if (
    pendingRequests !== 0
    || fixtureMisses.length !== 0
    || latestMissingRequestPrefixes.length !== 0
    || !surfaceIsReady(visualState.id)
    || latestContractMisses.length !== 0
    || document.fonts.status !== "loaded"
  ) {
    invalidateVisualReadiness();
    publishVisualCaptureContract();
    return;
  }

  const fingerprint = visualContractFingerprint(visualState);
  if (fingerprint !== visualStabilityFingerprint) {
    invalidateVisualReadiness();
    visualStabilityFingerprint = fingerprint;
  }
  scheduleVisualStabilityFrame();
  publishVisualCaptureContract();
}

function scheduleVisualStabilityFrame() {
  if (visualStabilityFrame !== null) return;
  visualStabilityFrame = window.requestAnimationFrame(() => {
    visualStabilityFrame = null;
    const missingRequestPrefixes = visualState.required_request_prefixes.filter((prefix) => (
      !requestedPaths.some((requestPath) => requestPath.startsWith(prefix))
    ));
    const contractMisses = visualContractMisses(visualState);
    const fingerprint = visualContractFingerprint(visualState);
    if (
      pendingRequests !== 0
      || fixtureMisses.length !== 0
      || missingRequestPrefixes.length !== 0
      || !surfaceIsReady(visualState.id)
      || contractMisses.length !== 0
      || document.fonts.status !== "loaded"
      || fingerprint !== visualStabilityFingerprint
    ) {
      evaluateVisualState();
      return;
    }

    visualStableFrames += 1;
    document.documentElement.dataset.visualStableFrames = String(visualStableFrames);
    if (visualStableFrames < 2) {
      scheduleVisualStabilityFrame();
      publishVisualCaptureContract();
      return;
    }
    document.documentElement.dataset.visualReady = visualState.id;
    document.documentElement.dataset.visualSettledAt = now;
    publishVisualCaptureContract();
  });
}

function invalidateVisualReadiness() {
  if (visualStabilityFrame !== null) {
    window.cancelAnimationFrame(visualStabilityFrame);
    visualStabilityFrame = null;
  }
  visualStabilityFingerprint = null;
  visualStableFrames = 0;
  delete document.documentElement.dataset.visualReady;
  delete document.documentElement.dataset.visualSettledAt;
  delete document.documentElement.dataset.visualStableFrames;
}

function visualContractFingerprint(state: SelectorAwareVisualState): string {
  const selectors = new Set<string>([
    ...(state.required_presence_selectors ?? []),
    ...(state.required_visible_selectors ?? []),
    ...(state.required_geometry ?? []).map((requirement) => requirement.selector),
    ...(state.required_computed_styles ?? []).map((requirement) => requirement.selector),
    ...(state.required_exact_text ?? []).map((requirement) => requirement.selector),
    ...(state.required_visible_counts ?? []).map((requirement) => requirement.selector),
  ]);
  const landmarks = [...selectors].map((selector) => ({
    selector,
    elements: Array.from(document.querySelectorAll<HTMLElement>(selector)).map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        x: roundContractNumber(rect.x),
        y: roundContractNumber(rect.y),
        width: roundContractNumber(rect.width),
        height: roundContractNumber(rect.height),
        text: normalizeContractText(element.textContent ?? ""),
      };
    }),
  }));
  return JSON.stringify({
    state: state.id,
    hash: window.location.hash,
    viewport: [window.innerWidth, window.innerHeight, window.devicePixelRatio],
    body: [document.body.scrollWidth, document.body.scrollHeight],
    landmarks,
  });
}

function roundContractNumber(value: number): number {
  return Math.round(value * 1_000) / 1_000;
}

function publishVisualCaptureContract() {
  visualWindow.__boltrigVisualCaptureContract = {
    schema: "boltrig-worker-visual-capture-contract.v1",
    state: visualState.id,
    expectedHash: visualState.hash,
    actualHash: window.location.hash,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    },
    output: "current_output" in visualState ? visualState.current_output ?? null : null,
    ready: document.documentElement.dataset.visualReady === visualState.id,
    settledAt: document.documentElement.dataset.visualSettledAt ?? null,
    stableFrames: visualStableFrames,
    pendingRequests,
    missingRequestPrefixes: [...latestMissingRequestPrefixes],
    fixtureMisses: [...fixtureMisses],
    contractMisses: [...latestContractMisses],
    requestedPaths: [...requestedPaths],
  };
}

function surfaceIsReady(id: VisualState["id"]): boolean {
  if (window.location.hash !== visualState.hash) return false;
  if (id === "new-chat") {
    return Boolean(
      window.location.hash === "#/chat"
      && document.querySelector(".new-chat-transcript .welcome h1")
      && document.querySelector(".new-chat-transcript .composer.new-context")
      && document.querySelector('.new-chat-transcript button[aria-label="Model"]')
      && document.querySelector(".voice-intro")
      && document.querySelectorAll(".shell-parity .session-row:not(.closed) .session-main").length === 4
      && bodyHas("What needs doing?")
      && bodyHas("Talk to Familiar")
    );
  }
  if (id === "chat-run") {
    return runThreadSurfaceIsReady();
  }
  if (id === "chat-direction") {
    return directionThreadSurfaceIsReady();
  }
  if (id === "agents") {
    return Boolean(
      document.querySelector('[aria-label="Permanent fleet topology"]')
      && document.querySelector(".fleet-canvas:not([data-loading=\"true\"])")
      && bodyHas("Chief of Staff"),
    );
  }
  if (id === "plugins") {
    return Boolean(
      document.querySelector(".plugins-groups")
      && bodyHas("Plugins")
      && bodyHas("Slack")
      && bodyHas("filesystem"),
    );
  }
  if (id === "command-palette") {
    return Boolean(
      runThreadSurfaceIsReady()
      && document.querySelector('[data-screen-label="Command palette"]')
      && document.querySelector('input[aria-label="Search Worker"]'),
    );
  }
  if (id === "call") {
    return Boolean(
      document.querySelector('[data-screen-label="Call"]')
      && document.querySelector(".voice-call-text")
      && document.querySelector(".voice-call-controls")
      && document.querySelector(
        '.voice-call-primary-familiar [data-renderer="webgl2"], '
        + '.voice-call-primary-familiar [data-renderer="badge"]',
      )
      && bodyHas("Leave")
      && bodyHas("Mute me")
      && bodyHas("Silence Familiar"),
    );
  }
  return Boolean(
    document.querySelector(".settings-head h1")
    && bodyHas("Reaching you")
    && bodyHas("Will Lilley")
    && bodyHas("Slack · Ops"),
  );
}

function runThreadSurfaceIsReady(): boolean {
  return Boolean(
    window.location.hash === "#/chat/run-thread"
    && document.querySelector("#shell-pinned-tasks")
    && document.querySelector("#shell-recent-tasks")
    && document.querySelector(".message.user")
    && document.querySelector(".message.assistant")
    && document.querySelector('.transcript-navigation[aria-label="Transcript navigation"]')
    && bodyHas("Renewal outreach, top 20 accounts")
    && bodyHas("Twenty accounts fall inside the renewal window.")
    && bodyHas("5 subagents"),
  );
}

function directionThreadSurfaceIsReady(): boolean {
  return Boolean(
    window.location.hash === "#/chat/direction-thread"
    && document.querySelector("#shell-pinned-tasks")
    && document.querySelector("#shell-recent-tasks")
    && document.querySelectorAll(".message.user").length === 2
    && document.querySelectorAll(".message.assistant").length === 2
    && document.querySelectorAll(".message-agent-label").length === 4
    && document.querySelector(".display-object-communication")
    && document.querySelector('.transcript-navigation[aria-label="Transcript navigation"]')
    && bodyHas("Desktop chat evidence")
    && bodyHas("The preview and inspection receipts completed without inventing live state.")
    && bodyHas("Draft update for #launch")
  );
}

function visualContractMisses(state: SelectorAwareVisualState): string[] {
  const misses: string[] = [];
  if (
    window.innerWidth !== manifest.viewport.width
    || window.innerHeight !== manifest.viewport.height
  ) {
    misses.push(
      `viewport:${window.innerWidth}x${window.innerHeight}`
      + `!=${manifest.viewport.width}x${manifest.viewport.height}`,
    );
  }
  for (const selector of state.required_presence_selectors ?? []) {
    if (!document.querySelector(selector)) misses.push(`missing:${selector}`);
  }
  for (const selector of state.required_absence_selectors ?? []) {
    if (document.querySelector(selector)) misses.push(`present:${selector}`);
  }
  for (const selector of state.required_visible_selectors ?? []) {
    const element = document.querySelector<HTMLElement>(selector);
    if (!element || !isVisiblyRendered(element)) misses.push(`not-visible:${selector}`);
  }
  for (const requirement of state.required_visible_counts ?? []) {
    const elements = Array.from(
      document.querySelectorAll<HTMLElement>(requirement.selector),
    );
    if (elements.length !== requirement.count) {
      misses.push(
        `visible-count:${requirement.selector}:${elements.length}!=${requirement.count}`,
      );
      continue;
    }
    if (elements.some((element) => !isVisiblyRendered(element))) {
      misses.push(`visible-count-clipped:${requirement.selector}`);
    }
  }
  for (const required of state.required_text ?? []) {
    if (!bodyHas(required)) misses.push(`missing-text:${required}`);
  }
  for (const requirement of state.required_exact_text ?? []) {
    const element = document.querySelector<HTMLElement>(requirement.selector);
    const actual = normalizeContractText(element?.textContent ?? "");
    if (!element || actual !== requirement.text) {
      misses.push(
        `exact-text:${requirement.selector}:${actual || "<missing>"}!=${requirement.text}`,
      );
    }
  }
  for (const prohibited of state.required_absent_text ?? []) {
    if (bodyHas(prohibited)) misses.push(`present-text:${prohibited}`);
  }
  for (const requirement of state.required_geometry ?? []) {
    const element = document.querySelector<HTMLElement>(requirement.selector);
    if (!element) {
      misses.push(`geometry-missing:${requirement.selector}`);
      continue;
    }
    const rect = element.getBoundingClientRect();
    const tolerance = requirement.tolerance ?? 1;
    for (const key of ["width", "height", "x", "y"] as const) {
      const expected = requirement[key];
      if (expected == null) continue;
      if (Math.abs(rect[key] - expected) > tolerance) {
        misses.push(`geometry:${requirement.selector}:${key}:${rect[key]}!=${expected}`);
      }
    }
  }
  for (const requirement of state.required_computed_styles ?? []) {
    const element = document.querySelector<HTMLElement>(requirement.selector);
    if (!element) {
      misses.push(`computed-style-missing:${requirement.selector}`);
      continue;
    }
    const actual = window.getComputedStyle(element)
      .getPropertyValue(requirement.property)
      .trim();
    if (actual !== requirement.value) {
      misses.push(
        `computed-style:${requirement.selector}:${requirement.property}`
        + `:${actual || "<missing>"}!=${requirement.value}`,
      );
    }
  }
  return misses;
}

function isVisiblyRendered(element: HTMLElement): boolean {
  const style = window.getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  if (
    style.display === "none"
    || style.visibility === "hidden"
    || Number.parseFloat(style.opacity || "1") <= 0
    || rect.width <= 4
    || rect.height <= 4
  ) return false;

  let left = Math.max(0, rect.left);
  let top = Math.max(0, rect.top);
  let right = Math.min(window.innerWidth, rect.right);
  let bottom = Math.min(window.innerHeight, rect.bottom);
  for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
    const ancestorStyle = window.getComputedStyle(ancestor);
    if (
      ancestorStyle.display === "none"
      || ancestorStyle.visibility === "hidden"
      || Number.parseFloat(ancestorStyle.opacity || "1") <= 0
    ) return false;
    const ancestorRect = ancestor.getBoundingClientRect();
    if (/(auto|hidden|clip|scroll)/.test(ancestorStyle.overflowX)) {
      left = Math.max(left, ancestorRect.left);
      right = Math.min(right, ancestorRect.right);
    }
    if (/(auto|hidden|clip|scroll)/.test(ancestorStyle.overflowY)) {
      top = Math.max(top, ancestorRect.top);
      bottom = Math.min(bottom, ancestorRect.bottom);
    }
  }
  // Required capture landmarks must be fully on-screen and outside clipped
  // ancestor regions. A one-pixel tolerance avoids fractional-layout noise.
  return left <= rect.left + 1
    && top <= rect.top + 1
    && right >= rect.right - 1
    && bottom >= rect.bottom - 1;
}

function bodyHas(text: string): boolean {
  return document.body.textContent?.includes(text) ?? false;
}

function normalizeContractText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function updateVisualDiagnostics() {
  document.documentElement.dataset.visualPendingRequests = String(pendingRequests);
  document.documentElement.dataset.visualRequests = requestedPaths.join("|");
  if (fixtureMisses.length > 0) {
    document.documentElement.dataset.visualFixtureMisses = fixtureMisses.join("|");
  } else {
    delete document.documentElement.dataset.visualFixtureMisses;
  }
}

function profile(name: string, label: string, skills: string[], depth: number, tier: string) {
  return {
    name, label, runtime: "codex", supported_skills: skills, max_depth: depth,
    is_ephemeral: false, cost_tier: tier, model_endpoint: null,
    vision_model_endpoint: null,
    familiar_genotype: familiarGenotype(name),
    source: "control-plane", is_active: true, status: "active",
  };
}

function head(name: string, routingId: string, skills: string[], depth: number, tier: string) {
  return {
    name, routing_id: routingId, purpose: name, brief: `${name} operating brief`,
    runtime: "codex", model_endpoint: null, supported_skills: skills,
    max_depth: depth, cost_tier: tier, budget: null,
    familiar_genotype: familiarGenotype(name),
  };
}

function integration(id: string, label: string, category: string, description: string, auth: string, certification: string) {
  return {
    id, label, category, description, transport: "rest", auth: [auth], certification,
    available: true, setup_supported: true, enabled_tools: [],
  };
}

function addon(id: string, label: string, runtime: string) {
  return {
    id, label, version: "1.0.0", installation: "installed", activation: "active",
    contributions: { harness: false, adapter: true, consequence_hint: false },
    configuration: { status: runtime === "ready" ? "ready" : "degraded", requirements: [] },
    runtime: { status: runtime, reason: runtime === "ready" ? null : "health_unverified" },
  };
}

function participant(id: string, label: string, kind: string, color: string) {
  return {
    id, label, kind,
    familiar_genotype: familiarGenotype(id, [color, "#18304a", "#f0c37b"]),
  };
}

function familiarGenotype(identity: string, palette = ["#0a84ff", "#29d3a1", "#9b7bff"]) {
  const key = identity.toLowerCase();
  const identityShape = key.includes("chief")
    ? { body: "cassini", markings: ["arc"], accessories: ["signal-pin"] }
    : key.includes("lyell")
      ? { body: "kepler", markings: ["orbit"], accessories: ["antenna"] }
      : key.includes("hutton")
        ? { body: "pioneer", markings: ["constellation"], accessories: ["signal-pin"] }
        : key.includes("noether")
          ? { body: "voyager", markings: ["halo"], accessories: ["orbit-ring"] }
          : key.includes("curie")
            ? { body: "cassini", markings: ["constellation"], accessories: [] }
            : key.includes("brunel")
              ? { body: "pioneer", markings: ["arc"], accessories: ["antenna"] }
              : { body: "voyager", markings: ["orbit"], accessories: [] };
  return {
    source: "agent_capability.name.v1",
    seed: [...identity].reduce((value, character) => (
      Math.imul(value, 31) + character.codePointAt(0)!
    ) >>> 0, 2166136261),
    palette,
    ...identityShape,
  };
}

function mcpServer(id: string, health: string, toolCount: number) {
  return {
    id, config_revision: 1, version: "1.0.0", source: "control-plane",
    state: "active", activated: true, runtime_loaded: true,
    endpoint: { origin: null, path_redacted: true, internal_egress_allowed: false },
    credential_configured: true, recorded_health: health,
    health: { status: health, source: "durable_probe", checked_at: now },
    operability: {
      status: health === "ok" ? "ready" : "degraded",
      reason: health === "ok" ? null : "probe_degraded",
    },
    last_probe: {
      checked_at: now, outcome: health === "ok" ? "succeeded" : "failed",
      failure_code: health === "ok" ? null : "transport_unavailable", tool_count: toolCount,
    },
    tool_snapshot: {
      status: "snapshot", observed_at: now, count: toolCount,
      publication_status: health === "ok" ? "published" : "drifted",
    },
    available_actions: ["probe", "deactivate", "update", "retire"],
  };
}

function workflow(
  id: string,
  actions: string[],
  intentTags: string[],
  source: "precreated" | "generated" | "learned",
  schedule: { cron: string; timezone: string } | null = null,
) {
  return {
    id,
    version: "1.0.0",
    source,
    intent_tags: intentTags,
    status: "active",
    schedule,
    definition: {
      steps: actions.map((action, index) => ({
        id: `step-${index + 1}`,
        action,
        parents: index === 0 ? [] : [`step-${index}`],
      })),
    },
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function sse(events: readonly unknown[]): Response {
  return new Response(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""), {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}
