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
    blurb:
      "Live governed routing for tagged spawns. The unique highest-priority match selects capability, adds reviewed skills, and may tighten depth.",
    list: true,
    schema: {
      type: "object",
      properties: {
        items: {
          type: "array",
          maxItems: 128,
          description:
            "Rules are validated as one policy revision. Equal-priority matches fail closed; list order never breaks a tie.",
          items: {
            type: "object",
            additionalProperties: false,
            properties: {
              name: { type: "string", description: "The rule's stable name." },
              priority: {
                type: "integer",
                minimum: 0,
                maximum: 1000,
                description:
                  "Explicit precedence. The unique highest matching value wins; ties are refused.",
              },
              match: {
                type: "object",
                additionalProperties: false,
                description:
                  "Closed all-of predicate evaluated against prefer.intent_tags at governed spawn intake.",
                properties: {
                  intent_tags: {
                    type: "array",
                    maxItems: 32,
                    items: {
                      type: "string",
                      pattern: "^[a-z0-9][a-z0-9._-]{0,63}$",
                    },
                    description:
                      "Every lower-case stable tag must be present for this rule to match.",
                  },
                },
                required: ["intent_tags"],
              },
              capability: {
                type: "string",
                description:
                  "Capability selected by the rule. A conflicting caller routing pin is refused.",
              },
              skills: {
                type: "array",
                maxItems: 32,
                items: { type: "string" },
                description:
                  "Reviewed skills added to the request. Their tool grants remain capped by caller authority.",
              },
              max_depth: {
                type: "integer",
                minimum: 1,
                maximum: 10,
                description:
                  "Optional additional ceiling; the lower of this and capability max depth is enforced.",
              },
            },
            required: ["name", "priority", "match", "capability"],
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
