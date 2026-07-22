import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { InsightPanel } from "@/panels/InsightPanel";
import { clearApiMocks, mockApi } from "../helpers";

afterEach(() => {
  cleanup();
  clearApiMocks();
});

describe("InsightPanel task modes", () => {
  it("keeps one primary action in each operator mode", () => {
    mockApi({
      cost: { total_cost_micros: 0, by_actor: {}, by_status: {}, scope: "all" },
      runs: { runs: [] },
      capabilities: { verbs: [] },
      budgets: { budgets: [], scope: "all" },
    });
    const { container } = render(<InsightPanel />);

    expect(screen.getByRole("button", { name: "Refresh overview" })).toBeTruthy();
    expect(container.querySelectorAll(".btn--primary")).toHaveLength(1);

    fireEvent.click(screen.getByRole("radio", { name: "Audit" }));
    expect(screen.getByRole("button", { name: "Search" })).toBeTruthy();
    expect(container.querySelectorAll(".btn--primary")).toHaveLength(1);

    fireEvent.click(screen.getByRole("radio", { name: "Budgets" }));
    expect(screen.getByRole("button", { name: "Request policy change" })).toBeTruthy();
    expect(container.querySelectorAll(".btn--primary")).toHaveLength(1);
  });
});
