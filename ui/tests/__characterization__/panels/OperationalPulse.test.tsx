import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { OperationalPulse } from "@/panels/home/OperationalPulse";
import { clearApiMocks, mockApi } from "../helpers";

const OVERVIEW = {
  generated_at: "2026-07-15T10:00:00Z",
  tenant_id: "acme",
  workspace_id: "prod",
  scope: "all",
  platform: {
    components: [{ id: "postgres", kind: "database", status: "ok", metadata: {} }],
    runtimes: [{ id: "pi", kind: "runtime", status: "degraded", metadata: {} }],
  },
  models: [{
    provider: "cerebras",
    model: "qwen-3-coder",
    runtime: "opencode",
    calls: 2,
    tokens: 125,
    cost_micros: 250000,
    avg_latency_ms: 80,
    last_seen: "2026-07-15T10:00:00Z",
    statuses: { ok: 1, degraded: 1 },
  }],
  cost: {
    total_cost_micros: 2500000,
    by_actor: { worker: 2500000 },
    by_status: { ok: 4, failed: 2, degraded: 1 },
  },
  budgets: [{
    id: "tenant",
    scope_type: "tenant",
    window: "monthly",
    hard_stop: true,
    token_limit: 1000,
    spent_tokens: 1000,
    cost_limit_micros: 5000000,
    spent_micros: 2500000,
  }],
  recent_runs: [],
  approvals: [],
  counts: { visible_events: 7, recent_runs: 7, pending_approvals: 3 },
};

afterEach(() => {
  cleanup();
  clearApiMocks();
  window.location.hash = "";
});

describe("OperationalPulse", () => {
  it("renders only real overview posture and links to the operational surfaces", async () => {
    mockApi({ consoleOverview: OVERVIEW });
    render(<OperationalPulse />);

    await screen.findByText("postgres");
    expect(screen.getByText("pi")).toBeTruthy();
    expect(screen.getByText("Hard stop reached")).toBeTruthy();
    expect(screen.getByText("cerebras / qwen-3-coder")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText("Failed events").previousElementSibling?.textContent).toBe("2");

    fireEvent.click(screen.getByRole("button", { name: /Open health/ }));
    expect(window.location.hash).toContain("/health");
  });

  it("stays honest when no status provider or budget exists", async () => {
    mockApi({
      consoleOverview: {
        ...OVERVIEW,
        platform: { components: [], runtimes: [] },
        budgets: [],
        models: [],
      },
    });
    render(<OperationalPulse />);

    expect(await screen.findByText("No runtime status provider is configured.")).toBeTruthy();
    expect(screen.getByText("No scoped budgets are configured.")).toBeTruthy();
  });
});
