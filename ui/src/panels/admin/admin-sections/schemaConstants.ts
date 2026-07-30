// Shared enum lists and sub-schemas used by multiple admin section definitions.
// Keeping them in one place keeps the per-section files data-only and avoids
// repeating the budget/agent-node shapes across the registry.

export const RESIDENCY = ["eu", "us", "global"];
export const CHANNELS = ["teams", "email", "slack"];
export const COST_TIER = ["cheap", "standard", "expensive"];
export const BUDGET_WINDOW = ["daily", "weekly", "monthly"];
export const ENDPOINT_KIND = ["anthropic", "vllm", "openai"];
export const DATA_CLASS = ["standard", "sensitive"];
export const ADAPTER_RUNTIME = ["http", "sql", "script"];
export const CREDENTIAL_KIND = ["oauth", "api_key", "basic"];
export const RETRIEVAL_MODE = ["similarity", "graph_completion"];
export const EVAL_TARGET_KIND = ["skill", "workflow"];

// The reusable budget sub-schema (a tier's spend cap): SchemaFormV2 renders it as
// a nested inset group wherever it appears (tier1 and each tier2 row).
export const BUDGET_SCHEMA = {
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
export const AGENT_NODE_PROPERTIES = {
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
