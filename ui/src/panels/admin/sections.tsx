// The admin console section register (Beat 5 chunk 3, the settings/admin
// retrofit). The manifest stays the source of truth (C1); this descriptor names
// the manifest sections an org-admin may edit and gives each one a typed
// SchemaFormV2 schema so a section renders as structured controls (switches,
// segmented, steppers, chip pickers), never a raw JSON blob.
//
// Two rails carried here:
//  - Fail-closed partial edit: control.config.upsert REPLACES the whole section
//    value, so a schema is an ALLOWLIST of editable fields, not the full shape.
//    toFormValue seeds the known fields over the loaded value so any key the UI
//    does not expose (operator-only wiring such as the OIDC issuer/audience/JWKS
//    under identity) survives untouched and is sent back on save.
//  - Deploy-time env stays out (ports, secrets, OIDC endpoints, backups): those
//    are operator-only and never appear as a section here.
//
// A section whose manifest value is a top-level LIST (spawn_rules, adapters,
// ephemeral_runtimes) sets list:true; the array is wrapped under `items` so the
// object-shaped SchemaFormV2 can render it as one labelled, validated field
// (fail-closed via onValidity), and fromFormValue unwraps it back to the array.

import { schemaDefaults } from "../uxForm";

export interface AdminSection {
  key: string;
  label: string;
  blurb: string;
  // SchemaFormV2 schema (the JSON-schema subset it renders). Only these keys are
  // editable; everything else in the loaded section value is preserved.
  schema: Record<string, unknown>;
  // true when the section value is a top-level array (wrapped under `items`).
  list?: boolean;
  // a one-line note about operator-only keys intentionally kept out of the form.
  preserves?: string;
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// Section value (as the server stores it) -> the object SchemaFormV2 edits.
// List sections wrap the array; object sections seed defaults under the loaded
// value so no known field opens blank while unknown keys are preserved.
export function toFormValue(
  section: AdminSection,
  loaded: unknown,
): Record<string, unknown> {
  if (section.list) {
    return { items: Array.isArray(loaded) ? loaded : [] };
  }
  return { ...schemaDefaults(section.schema), ...(isObject(loaded) ? loaded : {}) };
}

// The SchemaFormV2 object -> the section value the server persists. List
// sections unwrap back to the bare array; object sections send the whole object
// (preserved unknown keys included).
export function fromFormValue(section: AdminSection, form: Record<string, unknown>): unknown {
  if (section.list) {
    const items = form.items;
    return Array.isArray(items) ? items : [];
  }
  return form;
}

// A stable structural compare for the dirty check (key order independent enough
// for a form whose keys come from a fixed schema + a preserved loaded object).
export function stableKey(value: unknown): string {
  return JSON.stringify(value);
}

const RESIDENCY = ["eu", "us", "global"];
const CHANNELS = ["teams", "email", "slack"];

export const ADMIN_SECTIONS: ReadonlyArray<AdminSection> = [
  {
    key: "identity",
    label: "Identity & roles",
    blurb: "IdP group to role and scope mappings - the RBAC source of truth.",
    preserves:
      "OIDC endpoints (issuer, audience, JWKS) are deploy-time wiring and stay operator-only; they are preserved untouched.",
    schema: {
      type: "object",
      properties: {
        provider: {
          type: "string",
          enum: ["oidc"],
          description: "The identity provider protocol.",
        },
        role_mappings: {
          type: "array",
          description:
            "Each entry maps an IdP group to a role and a permission scope (all / departments / nouns / verbs). This is the RBAC source of truth.",
          items: {
            type: "object",
            properties: {
              idp_group: { type: "string" },
              role: { type: "string" },
              scope: { type: "object" },
            },
          },
        },
      },
    },
  },
  {
    key: "hierarchy",
    label: "Org hierarchy & budgets",
    blurb: "The durable agent org chart and each tier's spend budget.",
    schema: {
      type: "object",
      properties: {
        tier1: {
          type: "object",
          description: "The single top-tier agent (chief of staff).",
          properties: {
            name: { type: "string" },
            runtime: { type: "string" },
            model_endpoint: { type: "string" },
            department: { type: "string" },
            max_depth: { type: "integer", minimum: 1, maximum: 10 },
            cost_tier: { type: "string", enum: ["cheap", "standard", "premium"] },
            supported_skills: { type: "array", items: { type: "string" } },
            budget: {
              type: "object",
              description:
                "cost_limit_micros, hard_stop and window for this tier's spend cap.",
            },
          },
        },
        tier2: {
          type: "array",
          description:
            "The department heads under tier 1, each with its own runtime, skills and budget.",
          items: { type: "object" },
        },
      },
    },
  },
  {
    key: "spawn_rules",
    label: "Spawn rules",
    blurb: "How an inbound task is matched to a runtime and a skill set.",
    list: true,
    schema: {
      type: "object",
      properties: {
        items: {
          type: "array",
          description:
            "Each rule matches intent tags to a capability, a skill set and a max depth.",
          items: { type: "object" },
        },
      },
      required: ["items"],
    },
  },
  {
    key: "adapters",
    label: "Adapters",
    blurb: "The integrations this tenant uses and their credential references.",
    list: true,
    schema: {
      type: "object",
      properties: {
        items: {
          type: "array",
          description:
            "Each adapter names its id, runtime and (by reference) its credential. Secret values are never edited here.",
          items: { type: "object" },
        },
      },
      required: ["items"],
    },
  },
  {
    key: "ephemeral_runtimes",
    label: "Ephemeral runtimes",
    blurb: "Short-lived child-agent runtimes the fleet spawns on demand.",
    list: true,
    schema: {
      type: "object",
      properties: {
        items: {
          type: "array",
          description:
            "Each runtime pins a runtime engine, a model endpoint, its skills, a max depth and a cost tier.",
          items: { type: "object" },
        },
      },
      required: ["items"],
    },
  },
  {
    key: "runtimes",
    label: "Runtime sidecars & gateway",
    blurb: "The Pi reasoning sidecar and the model gateway routing.",
    schema: {
      type: "object",
      properties: {
        pi: {
          type: "object",
          description:
            "The sandboxed Pi reasoning runtime: enabled, model endpoint, step cap and sandbox policy.",
        },
        gateway: {
          type: "object",
          description:
            "The model gateway for standard (non-sensitive) traffic: base_url and cache TTL. Empty base_url = off.",
        },
      },
    },
  },
  {
    key: "mcp",
    label: "MCP",
    blurb: "Expose the kernel as an MCP server, and consumed external servers.",
    preserves:
      "Consumed servers register inert and are activated only on the human-review route; credentials are never edited here.",
    schema: {
      type: "object",
      properties: {
        server: {
          type: "object",
          description: "Whether granted verbs are exposed as MCP tools.",
        },
        consume: {
          type: "array",
          description:
            "External MCP servers this tenant consumes (each registers inert until reviewed).",
          items: { type: "object" },
        },
      },
    },
  },
  {
    key: "models",
    label: "Models",
    blurb: "Inference back ends, default routing and the price table.",
    schema: {
      type: "object",
      properties: {
        default: {
          type: "string",
          description: "The default model endpoint id.",
        },
        sensitive_endpoint: {
          type: "string",
          description: "The on-box endpoint sensitive data is routed to (never egresses).",
        },
        endpoints: {
          type: "array",
          description: "Each endpoint's id, kind, model, base_url and data class.",
          items: { type: "object" },
        },
        prices: {
          type: "object",
          additionalProperties: true,
          description: "Per-model micros-per-token price table for budgets and cost true-up.",
        },
      },
    },
  },
  {
    key: "hitl",
    label: "Approvals (HITL)",
    blurb: "Where approvals route and which verbs always pause for a human.",
    schema: {
      type: "object",
      properties: {
        primary_channel: {
          type: "string",
          enum: CHANNELS,
          description: "The channel approval requests are sent to first.",
        },
        notify_via: {
          type: "array",
          items: { type: "string", enum: CHANNELS },
          description: "The channels approval notifications are delivered on.",
        },
        approval_timeout_seconds: {
          type: "integer",
          minimum: 0,
          maximum: 86400,
          description: "How long an approval request waits before it times out.",
        },
        escalation_chain: {
          type: "array",
          items: { type: "string" },
          description: "The agents an unanswered approval escalates through, in order.",
        },
        blocking_verbs: {
          type: "array",
          items: { type: "string" },
          description: "Verbs the kernel gates for human approval regardless of consequence.",
        },
      },
    },
  },
  {
    key: "network",
    label: "Network",
    blurb: "Outbound egress posture for adapter calls.",
    schema: {
      type: "object",
      properties: {
        air_gapped: {
          type: "boolean",
          description: "When on, no outbound network calls are permitted.",
        },
        https_proxy: { type: "string", description: "Outbound HTTPS proxy URL (blank = none)." },
        ca_bundle: { type: "string", description: "Path to a custom CA bundle (blank = system)." },
        allowed_domains: {
          type: "array",
          items: { type: "string" },
          description: "Domains adapters may reach.",
        },
        blocked_domains: {
          type: "array",
          items: { type: "string" },
          description: "Domains explicitly denied.",
        },
      },
    },
  },
  {
    key: "privacy",
    label: "Privacy & data",
    blurb: "Data-handling posture: redaction, residency and retention.",
    schema: {
      type: "object",
      properties: {
        pii_redaction: {
          type: "boolean",
          description: "Redact detected PII before it reaches a model or an adapter.",
        },
        data_residency: {
          type: "string",
          enum: RESIDENCY,
          description: "Where this tenant's data may be processed and stored.",
        },
        retention_days: {
          type: "integer",
          minimum: 0,
          maximum: 3650,
          description: "Days to retain conversation and work data.",
        },
        redact_fields: {
          type: "array",
          items: { type: "string" },
          description: "Field names always redacted (email, phone, ...).",
        },
      },
    },
  },
  {
    key: "memory",
    label: "Memory",
    blurb: "The memory subsystem: engine, scopes, residency and retrieval.",
    schema: {
      type: "object",
      properties: {
        enabled: { type: "boolean", description: "Whether memory is active for this tenant." },
        engine: {
          type: "string",
          enum: ["local", "cognee"],
          description: "local is the dev/offline reference; cognee is the production engine.",
        },
        store: { type: "string", enum: ["postgres"], description: "The backing store." },
        embedding_endpoint: { type: "string", description: "The embedding model endpoint." },
        extraction_endpoint: {
          type: "string",
          description: "The entity/relationship extraction endpoint.",
        },
        local_endpoints: {
          type: "array",
          items: { type: "string" },
          description: "Endpoints treated as on-box for residency.",
        },
        default_owner_scope: {
          type: "string",
          enum: ["user", "department", "org"],
          description: "The default ownership scope for new memories.",
        },
        cross_scope_edges: {
          type: "string",
          enum: ["forbidden", "governed"],
          description: "Whether memory edges may cross ownership scopes.",
        },
        retention_days: {
          type: "integer",
          minimum: 0,
          maximum: 3650,
          description: "Days to retain memory.",
        },
        ingest: {
          type: "object",
          description: "Ingestion policy: on_session_end, incremental, screen_content, schedule.",
        },
        retrieval: {
          type: "object",
          description: "Retrieval policy: default_mode, max_hops, max_results.",
        },
      },
    },
  },
  {
    key: "chat",
    label: "Chat",
    blurb: "The conversational layer and per-role bare-turn authority.",
    schema: {
      type: "object",
      properties: {
        enabled: { type: "boolean", description: "Whether the chat surface is active." },
        transport: {
          type: "string",
          enum: ["sse", "websocket"],
          description: "The streaming transport.",
        },
        retention_days: {
          type: "integer",
          minimum: 0,
          maximum: 3650,
          description: "Days to retain conversations.",
        },
        panel: { type: "boolean", description: "Show the Chat panel in the UI." },
        continuity: {
          type: "boolean",
          description: "Compose prior turns into the prompt for continuity.",
        },
        default_skills: {
          type: "array",
          items: { type: "string" },
          description: "Skills a bare chat turn spawns with for an unmapped role.",
        },
        skills_by_role: {
          type: "object",
          additionalProperties: true,
          description:
            "Per-role skill sets a bare chat turn spawns with (intersected with the caller's grants, so it can only reduce authority).",
        },
      },
    },
  },
  {
    key: "evaluation",
    label: "Evaluation",
    blurb: "The eval harness and its suites.",
    schema: {
      type: "object",
      properties: {
        enabled: { type: "boolean", description: "Whether the eval harness is active." },
        suites: {
          type: "array",
          description: "Each suite's id, target kind and target ref.",
          items: { type: "object" },
        },
      },
    },
  },
  {
    key: "notifications",
    label: "Notifications",
    blurb: "Default channel routing per notification event.",
    schema: {
      type: "object",
      properties: {
        defaults: {
          type: "object",
          additionalProperties: true,
          description: "Per-event default channel routing (approval, escalation, budget_alert).",
        },
      },
    },
  },
  {
    key: "personal_agents",
    label: "Personal agents",
    blurb: "Org-level defaults for users' delegated personal agents.",
    schema: {
      type: "object",
      properties: {
        enabled: { type: "boolean", description: "Whether personal agents are available." },
        default_runtime: {
          type: "string",
          description: "The runtime a new personal agent uses by default.",
        },
        default_skills: {
          type: "array",
          items: { type: "string" },
          description: "The skills a new personal agent starts with.",
        },
      },
    },
  },
];

export const ADMIN_SECTION_OPTIONS = ADMIN_SECTIONS.map((s) => ({
  value: s.key,
  label: s.label,
}));
