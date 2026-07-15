import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { api } from "@/api/client";
import type { RunRow } from "@/api/types";
import { RunsPanel } from "@/panels/RunsPanel";
import {
  ownerFilterValue,
  statusFilterValue,
} from "@/panels/runsPanel/model";
import { clearApiMocks, mockApi } from "../helpers";

const RUNS: RunRow[] = [
  {
    run_id: "run-invoice",
    work_item: "work-101",
    intent: "Process the invoice",
    status: "in_flight",
    owner: "ops.agent",
  },
  {
    run_id: "run-refund",
    work_item: "work-102",
    intent: "Refund the customer",
    status: "awaiting_human",
    owner: "support.agent",
  },
  {
    run_id: null,
    work_item: "work-103",
    intent: "Reconcile inventory",
    status: "failed",
    owner: null,
  },
  {
    run_id: "run-sync",
    work_item: "work-104",
    intent: "Sync the catalogue",
    status: "failed",
    owner: "ops.agent",
  },
];

afterEach(() => {
  cleanup();
  clearApiMocks();
  window.location.hash = "";
});

describe("RunsPanel", () => {
  it("renders only truthful run fields, a real status summary, and drawer links", async () => {
    mockApi({ runs: { runs: RUNS } });
    render(<RunsPanel />);

    await screen.findByText("Process the invoice");
    expect(screen.getByText("4 total")).toBeTruthy();
    expect(screen.getByLabelText("failed: 2")).toBeTruthy();
    expect(screen.getByText("No run ID")).toBeTruthy();
    expect(within(screen.getByRole("table")).getByText("No owner")).toBeTruthy();

    const headers = within(screen.getByRole("table"))
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual(["Run", "Intent", "Work item", "Status", "Owner"]);

    fireEvent.click(screen.getByRole("button", { name: "run-invoice" }));
    expect(window.location.hash).toContain("run=run-invoice");
  });

  it("filters by intent, run ID, work item, status, and owner", async () => {
    mockApi({ runs: { runs: RUNS } });
    render(<RunsPanel />);
    await screen.findByText("Process the invoice");

    const search = screen.getByLabelText("Search");
    fireEvent.change(search, { target: { value: "invoice" } });
    expect(screen.getByText("Process the invoice")).toBeTruthy();
    expect(screen.queryByText("Refund the customer")).toBeNull();

    fireEvent.change(search, { target: { value: "run-refund" } });
    expect(screen.getByText("Refund the customer")).toBeTruthy();
    expect(screen.queryByText("Process the invoice")).toBeNull();

    fireEvent.change(search, { target: { value: "work-104" } });
    expect(screen.getByText("Sync the catalogue")).toBeTruthy();
    expect(screen.queryByText("Refund the customer")).toBeNull();

    fireEvent.change(search, { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: statusFilterValue("failed") },
    });
    expect(screen.getByText("Reconcile inventory")).toBeTruthy();
    expect(screen.getByText("Sync the catalogue")).toBeTruthy();
    expect(screen.queryByText("Process the invoice")).toBeNull();

    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "all-statuses" },
    });
    fireEvent.change(screen.getByLabelText("Owner"), {
      target: { value: ownerFilterValue("ops.agent") },
    });
    expect(screen.getByText("Process the invoice")).toBeTruthy();
    expect(screen.getByText("Sync the catalogue")).toBeTruthy();
    expect(screen.queryByText("Refund the customer")).toBeNull();
  });

  it("refreshes from the same scoped endpoint", async () => {
    mockApi({ runs: { runs: RUNS } });
    render(<RunsPanel />);
    await screen.findByText("Process the invoice");
    expect(api.runs).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(api.runs).toHaveBeenCalledTimes(2));
  });
});
