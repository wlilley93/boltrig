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
import {
  NotificationDefaultsList,
  PriceList,
  RoleMappingList,
  SkillsByRoleList,
} from "./editors";

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
const COST_TIER = ["cheap", "standard", "premium"];
const BUDGET_WINDOW = ["daily", "weekly", "monthly"];
const ENDPOINT_KIND = ["anthropic", "vllm", "openai"];
const DATA_CLASS = ["standard", "sensitive"];
const ADAPTER_RUNTIME = ["http", "sql", "script"];
const CREDENTIAL_KIND = ["oauth", "api_key", "basic"];
const RETRIEVAL_MODE = ["similarity", "graph_completion"];
const EVAL_TARGET_KIND = ["skill", "agent", "workflow"];

// The reusable budget sub-schema (a tier's spend cap): SchemaFormV2 renders it as
// a nested inset group wherever it appears (tier1 and each tier2 row).
const BUDGET_SCHEMA = {
  type: "object",
  description: "This tier's spend cap.",
  properties: {
    cost_limit_micros: {
      type: "integer",
      minimum: 0,
      maximum: 1000000000,
      description: "The spend ceiling in micros for the window.",
    },
    hard_stop: {
      type: "boolean",
      description: "When on, work halts at the cap; when off, it only alerts.",
    },
    window: {
      type: "string",
      enum: BUDGET_WINDOW,
      description: "The rolling window the cap applies over.",
    },
  },
};

// The agent-node shape shared by tier1 and each tier2 department head.
const AGENT_NODE_PROPERTIES = {
  name: { type: "string", description: "The agent's stable name." },
  department: { type: "string", description: "The department this agent heads (tier 2)." },
  runtime: { type: "string", description: "The runtime engine (e.g. hermes)." },
  model_endpoint: { type: "string", description: "The model endpoint id from Models." },
  max_depth: {
    type: "integer",
    minimum: 1,
    maximum: 10,
    description: "How deep this agent may spawn children.",
  },
  cost_tier: { type: "string", enum: COST_TIER, description: "The default cost tier." },
  supported_skills: {
    type: "array",
    items: { type: "string" },
    description: "Skill patterns this agent may run ('*' for all).",
  },
  budget: BUDGET_SCHEMA,
};

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
          // Dedicated typed editor: IdP-group field + role select + a structured
          // scope sub-editor (the generic array path cannot express the scope union).
          editor: RoleMappingList,
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
          properties: AGENT_NODE_PROPERTIES,
        },
        tier2: {
          type: "array",
          description:
            "The department heads under tier 1, each with its own runtime, skills and budget.",
          items: { type: "object", properties: AGENT_NODE_PROPERTIES },
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
          items: {
            type: "object",
            properties: {
              name: { type: "string", description: "The rule's stable name." },
              match: {
                type: "object",
                description: "The match predicate for inbound tasks.",
                properties: {
                  intent_tags: {
                    type: "array",
                    items: { type: "string" },
                    description: "Intent tags a task must carry for this rule to fire.",
                  },
                },
              },
              capability: {
                type: "string",
                description: "The ephemeral runtime (capability) this rule spawns.",
              },
              skills: {
                type: "array",
                items: { type: "string" },
                description: "The skills the spawned worker starts with.",
              },
              max_depth: {
                type: "integer",
                minimum: 1,
                maximum: 10,
                description: "The max spawn depth for this rule.",
              },
            },
          },
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
          items: {
            type: "object",
            properties: {
              id: { type: "string", description: "The adapter id (builtin id or project id)." },
              runtime: {
                type: "string",
                enum: ADAPTER_RUNTIME,
                description: "How the adapter is invoked.",
              },
              module_ref: {
                type: "string",
                description: "For a project adapter: the importable module:build ref.",
              },
              credential: {
                type: "object",
                description: "A credential REFERENCE (never the secret value).",
                properties: {
                  id: { type: "string", description: "The credential env-var reference id." },
                  store: {
                    type: "string",
                    enum: ["env"],
                    description: "Where the secret is held (env).",
                  },
                  kind: {
                    type: "string",
                    enum: CREDENTIAL_KIND,
                    description: "The credential kind.",
                  },
                },
              },
            },
          },
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
          items: {
            type: "object",
            properties: {
              name: { type: "string", description: "The runtime's stable name." },
              runtime: { type: "string", description: "The runtime engine (hermes, pi)." },
              model_endpoint: {
                type: "string",
                description: "The model endpoint id from Models.",
              },
              supported_skills: {
                type: "array",
                items: { type: "string" },
                description: "Skill patterns this runtime may run ('*' for all).",
              },
              max_depth: {
                type: "integer",
                minimum: 1,
                maximum: 10,
                description: "How deep this runtime may spawn children.",
              },
              cost_tier: {
                type: "string",
                enum: COST_TIER,
                description: "The default cost tier.",
              },
            },
          },
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
          properties: {
            enabled: { type: "boolean", description: "Whether the Pi sidecar runtime is active." },
            sidecar_url: { type: "string", description: "The Pi sidecar base URL." },
            model_endpoint: {
              type: "string",
              description: "The model endpoint id Pi reasons with.",
            },
            max_steps: {
              type: "integer",
              minimum: 1,
              maximum: 100,
              description: "Per-run reasoning/tool-call cap.",
            },
            sandbox: {
              type: "object",
              description: "The Pi sandbox policy.",
              properties: {
                network_allow: {
                  type: "array",
                  items: { type: "string" },
                  description: "Network targets Pi may reach (kernel_mcp, model_endpoint).",
                },
                native_tools: {
                  type: "boolean",
                  description: "Whether Pi's own filesystem/bash/network tools are enabled.",
                },
              },
            },
          },
        },
        gateway: {
          type: "object",
          description:
            "The model gateway for standard (non-sensitive) traffic: base_url and cache TTL. Empty base_url = off.",
          properties: {
            base_url: {
              type: "string",
              description: "The gateway base URL (blank = off).",
            },
            cache_ttl_seconds: {
              type: "integer",
              minimum: 0,
              maximum: 86400,
              description: "Prompt-cache TTL; sync to the gateway's own cache TTL.",
            },
          },
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
          properties: {
            enabled: {
              type: "boolean",
              description: "Expose this tenant's granted verbs as MCP tools.",
            },
          },
        },
        consume: {
          type: "array",
          description:
            "External MCP servers this tenant consumes (each registers inert until reviewed).",
          items: {
            type: "object",
            properties: {
              id: { type: "string", description: "The consumed server id." },
              url: { type: "string", description: "The server URL." },
              credential: {
                type: "string",
                description: "A credential reference (env-interpolated, held kernel-side).",
              },
            },
          },
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
          items: {
            type: "object",
            properties: {
              id: { type: "string", description: "The endpoint id (referenced elsewhere)." },
              kind: {
                type: "string",
                enum: ENDPOINT_KIND,
                description: "The back-end kind.",
              },
              model: { type: "string", description: "The model name served." },
              base_url: {
                type: "string",
                description: "The API base URL (for self-hosted back ends).",
              },
              data_class: {
                type: "string",
                enum: DATA_CLASS,
                description: "sensitive endpoints never egress.",
              },
            },
          },
        },
        prices: {
          type: "object",
          additionalProperties: true,
          description: "Per-model micros-per-token price table for budgets and cost true-up.",
          // Open key/value map (model -> micros): a typed key/value editor, not JSON.
          editor: PriceList,
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
          properties: {
            on_session_end: {
              type: "boolean",
              description: "Cognify a conversation when it closes.",
            },
            incremental: {
              type: "boolean",
              description: "Process only new/changed content.",
            },
            screen_content: {
              type: "boolean",
              description: "Run the anti-poisoning screen on ingested content.",
            },
            schedule: {
              type: "string",
              description: "Optional tz-aware cron for document corpora (blank = none).",
            },
          },
        },
        retrieval: {
          type: "object",
          description: "Retrieval policy: default_mode, max_hops, max_results.",
          properties: {
            default_mode: {
              type: "string",
              enum: RETRIEVAL_MODE,
              description: "similarity or graph_completion (multi-hop).",
            },
            max_hops: {
              type: "integer",
              minimum: 1,
              maximum: 10,
              description: "Max graph hops for multi-hop retrieval.",
            },
            max_results: {
              type: "integer",
              minimum: 1,
              maximum: 100,
              description: "Max results returned per retrieval.",
            },
          },
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
          // Open key/value map (role -> skills): a typed key/value editor, not JSON.
          editor: SkillsByRoleList,
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
          items: {
            type: "object",
            properties: {
              id: { type: "string", description: "The suite id." },
              target_kind: {
                type: "string",
                enum: EVAL_TARGET_KIND,
                description: "What the suite evaluates.",
              },
              target_ref: {
                type: "string",
                description: "The target ref/pattern (e.g. ops/*).",
              },
            },
          },
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
          // Open key/value map (event -> {channel}): a typed key/value editor, not JSON.
          editor: NotificationDefaultsList,
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
