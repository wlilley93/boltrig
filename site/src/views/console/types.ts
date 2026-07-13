export type ConsoleComponent = {
  id: string;
  kind: string;
  status: "ok" | "degraded" | "down" | "unknown";
  message: string;
  updated_at: string;
  metadata: Record<string, unknown>;
};

export type ConsoleModel = {
  provider: string;
  model: string;
  runtime: string;
  profile?: string;
  calls: number;
  tokens: number;
  cost_micros: number;
  avg_latency_ms: number | null;
  last_seen: string;
  statuses: Record<string, number>;
};

export type ConsoleBudget = {
  id: string;
  scope_type: string;
  window: string;
  hard_stop: boolean;
  token_limit: number | null;
  spent_tokens: number;
  cost_limit_micros: number | null;
  spent_micros: number;
};

export type ConsoleRun = {
  seq: number | null;
  ts: string;
  run_id: string | null;
  parent_run_id: string | null;
  workspace_id: string | null;
  actor: string;
  action_type: string;
  verb: string | null;
  status: string;
  tokens_used: number;
  cost_micros: number;
  latency_ms: number | null;
};

export type ConsoleApproval = {
  id: string;
  run_id: string;
  work_item_id: string | null;
  type: string;
  urgency: string;
  status: string;
  question: string;
  options: string[];
  assignee: string | null;
  timeout_at: string | null;
};

export type ConsoleOverview = {
  generated_at: string;
  tenant_id: string;
  workspace_id: string | null;
  scope: string | string[];
  platform: {
    components: ConsoleComponent[];
    runtimes: ConsoleComponent[];
  };
  models: ConsoleModel[];
  cost: {
    total_cost_micros: number;
    by_actor: Record<string, number>;
    by_status: Record<string, number>;
  };
  budgets: ConsoleBudget[];
  recent_runs: ConsoleRun[];
  approvals: ConsoleApproval[];
  counts: {
    visible_events: number;
    recent_runs: number;
    pending_approvals: number;
  };
};

export type ConsoleSettings = {
  apiBase: string;
  bearerToken: string;
};
