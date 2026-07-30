// Human-in-the-loop, network, privacy and memory sections of the admin console
// register. These shape trust boundaries, data handling and the memory subsystem.
import {
  CHANNELS,
  RESIDENCY,
  RETRIEVAL_MODE,
} from "@/panels/admin/admin-sections/schemaConstants";
import type { AdminSection } from "@/panels/admin/admin-sections/types";

export const governanceSections: ReadonlyArray<AdminSection> = [
  {
    key: "hitl",
    label: "Approvals (HITL)",
    blurb:
      "Approval timeout and blocking verbs are enforced. Channel and escalation routing remain stored policy.",
    schema: {
      type: "object",
      properties: {
        primary_channel: {
          type: "string",
          enum: CHANNELS,
          description:
            "Stored preferred channel. It does not currently deliver approval requests.",
        },
        notify_via: {
          type: "array",
          items: { type: "string", enum: CHANNELS },
          description:
            "Stored notification preferences. They are not currently consumed by the HITL gate.",
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
          description:
            "Stored ordered escalation targets. Timed-out approvals do not traverse this chain yet.",
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
    blurb:
      "Conversation deletion retention is enforced. PII redaction fields and residency labels remain stored policy.",
    schema: {
      type: "object",
      properties: {
        pii_redaction: {
          type: "boolean",
          description:
            "Stored policy flag. Automatic model/adapter-boundary PII redaction is not wired yet.",
        },
        data_residency: {
          type: "string",
          enum: RESIDENCY,
          description:
            "Stored residency label. It does not currently constrain processing or storage.",
        },
        retention_days: {
          type: "integer",
          minimum: 1,
          maximum: 3650,
          description:
            "Days after a conversation is closed before the fleet janitor hard-erases it. Open conversations, work, memory and audit use separate lifecycles.",
        },
        redact_fields: {
          type: "array",
          items: { type: "string" },
          description:
            "Stored field names. They are not currently applied to model or adapter payloads.",
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
];
