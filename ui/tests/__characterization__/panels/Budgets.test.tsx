import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "@/api/client";
import { Budgets } from "@/panels/insightPanel/Budgets";
import { clearApiMocks, mockApi } from "../helpers";

const BUDGET = {
  id: "default",
  scope_type: "tenant" as const,
  window: "monthly" as const,
  hard_stop: true,
  token_limit: 1000,
  spent_tokens: 250,
  cost_limit_micros: 5_000_000,
  spent_micros: 1_000_000,
};

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("Budgets", () => {
  it("submits a typed high-consequence policy mutation", async () => {
    mockApi({
      budgets: { budgets: [BUDGET], scope: "all" },
      invoke: { status: "ok", output: { budget: BUDGET } },
    });
    render(<Budgets />);

    await screen.findByText("Budget policy");
    expect(screen.getByText(/Workflow scope and window values are policy metadata/)).toBeTruthy();
    expect(screen.getByText(/Realtime voice and direct paid-adapter usage are not debited/)).toBeTruthy();
    expect(screen.getByText("monthly tag · manual reset")).toBeTruthy();
    expect(screen.getByText("spawned-work hard stop")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Token limit"), {
      target: { value: "2000" },
    });
    fireEvent.change(screen.getByLabelText("Cost limit (USD)"), {
      target: { value: "7.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request policy change" }));

    await waitFor(() => {
      expect(api.invoke).toHaveBeenCalledWith({
        noun: "control",
        verb: "control.budget.upsert",
        params: {
          scope_type: "tenant",
          scope_id: "default",
          token_limit: 2000,
          cost_limit_micros: 7_500_000,
          hard_stop: true,
          window: "monthly",
        },
      });
    });
  });

  it("arms usage reset before requesting the governed reset", async () => {
    mockApi({
      budgets: { budgets: [BUDGET], scope: "all" },
      invoke: { status: "pending_human", hitl_request_id: "hitl-budget" },
      hitl: { requests: [{ id: "hitl-budget" }] },
    });
    render(<Budgets />);

    await screen.findByText("default");
    fireEvent.click(screen.getByRole("button", { name: "Reset usage" }));
    expect(screen.getByText(/Reset both usage counters/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm reset" }));

    await screen.findByText("Paused for approval");
    expect(api.invoke).toHaveBeenCalledWith({
      noun: "control",
      verb: "control.budget.reset",
      params: {
        scope_type: "tenant",
        scope_id: "default",
        reason: "Operator reset from browser console",
        reset_tokens: true,
        reset_cost: true,
      },
    });
  });

  it("labels an existing workflow budget as stored rather than enforced", async () => {
    mockApi({
      budgets: {
        budgets: [{ ...BUDGET, id: "wf-support", scope_type: "workflow" }],
        scope: "all",
      },
    });
    render(<Budgets />);

    await screen.findByText("wf-support");
    expect(screen.getByText("stored only")).toBeTruthy();
    expect(screen.queryByText("spawned-work hard stop")).toBeNull();
  });
});
