// @vitest-environment happy-dom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  hitlPolicy: vi.fn(),
  verbs: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { ActionsTable } from "../src/components/build/ActionsTable";

const VERBS = [
  { id: "crm.account.read", noun: "crm", description: "Read an account", consequence: "low", status: "active", noun_status: "active", is_active: true, binding: { target_ref: "crm", target_type: "adapter" } },
  { id: "ticket.create", noun: "ticket", description: "Open a ticket", consequence: "high", status: "active", noun_status: "active", is_active: true, binding: { target_ref: "jira", target_type: "adapter" } },
];

beforeEach(() => {
  api.verbs.mockResolvedValue({ verbs: VERBS });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("Actions table needs-you column", () => {
  it("adds asking from deployment policy, not consequence alone", async () => {
    // blocking_verbs gates a LOW verb at the kernel regardless of consequence,
    // so a table reading consequence alone would print a flat, wrong "no".
    api.hitlPolicy.mockResolvedValue({
      policy: { blocking_verbs: ["crm.account.read"] },
    });

    render(<ActionsTable onOpen={vi.fn()} />);

    const low = await screen.findByText("crm.account.read");
    const lowRow = low.closest(".console-row")!;
    expect(lowRow.querySelector(".console-state")!.textContent).toBe("always");

    const high = screen.getByText("ticket.create").closest(".console-row")!;
    expect(high.querySelector(".console-state")!.textContent).toBe("always");
  });

  it("says no only when the policy was actually read", async () => {
    api.hitlPolicy.mockResolvedValue({ policy: { blocking_verbs: [] } });

    render(<ActionsTable onOpen={vi.fn()} />);

    const row = (await screen.findByText("crm.account.read")).closest(".console-row")!;
    expect(row.querySelector(".console-state")!.textContent).toBe("no");
  });

  it("says the gate is not known when the policy cannot be read", async () => {
    api.hitlPolicy.mockRejectedValue(new Error("not an author"));

    render(<ActionsTable onOpen={vi.fn()} />);

    const row = (await screen.findByText("crm.account.read")).closest(".console-row")!;
    expect(row.querySelector(".console-state")!.textContent).toBe("not known");
    // A high-consequence verb still asks: that half needs no policy read.
    const high = screen.getByText("ticket.create").closest(".console-row")!;
    expect(high.querySelector(".console-state")!.textContent).toBe("always");
    expect(screen.getByText(/policy could not be read/)).toBeTruthy();
  });
});
