import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { api } from "@/api/client";
import type { RunRow } from "@/api/types";
import { RunsPanel } from "@/panels/RunsPanel";
import {
  channelFilterValue,
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
    external_ref: "opbox",
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
    external_ref: "opbox",
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
    expect(headers).toEqual([
      "Run",
      "Intent",
      "Work item",
      "Status",
      "Owner",
      "Channel",
    ]);

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

describe("RunsPanel channel attribution", () => {
  it("shows which surface each run arrived through, and names the absent case", async () => {
    // One conversation can span an Opbox spotlight and this UI. The channel was
    // RECORDED by the kernel from v0.4.21 and displayed nowhere: `external_ref`
    // appeared in no UI source at all, so the answer existed and no one could see
    // it. A run typed into boltrig itself carries no channel, and that is the
    // ordinary case rather than a gap - it reads as "Direct", not as blank.
    mockApi({ runs: { runs: RUNS } });
    render(<RunsPanel />);
    const table = await waitFor(() => screen.getByRole("table"));
    expect(within(table).getAllByText("opbox").length).toBe(2);
    expect(within(table).getAllByText("Direct").length).toBe(2);
  });

  it("filters to one channel, and the filter is independent of the others", async () => {
    mockApi({ runs: { runs: RUNS } });
    render(<RunsPanel />);
    await waitFor(() => screen.getByRole("table"));

    fireEvent.change(screen.getByLabelText("Channel"), {
      target: { value: channelFilterValue("opbox") },
    });
    await waitFor(() => {
      const rows = within(screen.getByRole("table")).getAllByRole("row");
      // header + the two opbox runs
      expect(rows.length).toBe(3);
    });
    expect(screen.getByText("Process the invoice")).toBeTruthy();
    expect(screen.queryByText("Refund the customer")).toBeNull();

    // Narrowing by owner on top must INTERSECT, not replace: both opbox runs are
    // ops.agent, so adding support.agent leaves nothing. An empty result drops the
    // table for the empty state, so the absence of the table IS the assertion -
    // asking for rows here would fail on a missing element rather than on a count.
    fireEvent.change(screen.getByLabelText("Owner"), {
      target: { value: ownerFilterValue("support.agent") },
    });
    await waitFor(() => {
      expect(screen.queryByRole("table")).toBeNull();
    });
    expect(screen.queryByText("Process the invoice")).toBeNull();
    expect(screen.queryByText("Refund the customer")).toBeNull();
  });
});
