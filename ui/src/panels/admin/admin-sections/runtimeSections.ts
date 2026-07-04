// Runtime sidecar, MCP and model-endpoint sections of the admin console
// register. These configure the engines the fleet uses and the inference back
// ends it routes to.
import { PriceList } from "@/panels/admin/editors";
import {
  DATA_CLASS,
  ENDPOINT_KIND,
} from "@/panels/admin/admin-sections/schemaConstants";
import type { AdminSection } from "@/panels/admin/admin-sections/types";

export const runtimeSections: ReadonlyArray<AdminSection> = [
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
];
