// Adapter and spawn-rule sections of the admin console register. These describe
// how inbound tasks are matched to ephemeral runtimes and which integrations a
// tenant consumes.
import {
  ADAPTER_RUNTIME,
  COST_TIER,
  CREDENTIAL_KIND,
} from "@/panels/admin/admin-sections/schemaConstants";
import type { AdminSection } from "@/panels/admin/admin-sections/types";

export const integrationSections: ReadonlyArray<AdminSection> = [
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
];
