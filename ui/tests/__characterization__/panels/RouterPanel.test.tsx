import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "@/api/client";
import { resetIdentity, updateIdentity } from "@/identity";
import { RouterPanel } from "@/panels/RouterPanel";
import { clearApiMocks, mockApi } from "../helpers";

const CAPABILITIES = {
  verbs: [
    { id: "ticket.read", noun: "ticket", consequence: "low" },
    { id: "memory.recall", noun: "memory", consequence: "low" },
  ],
};

afterEach(() => {
  cleanup();
  clearApiMocks();
  resetIdentity();
});

describe("RouterPanel", () => {
  it("uses the server noun filter instead of only filtering a downloaded list", async () => {
    mockApi({
      capabilities: CAPABILITIES,
      health: { status: "ok", adapters: {} },
      capabilityChangelog: { changes: [] },
    });
    render(<RouterPanel />);
    await screen.findByText("ticket.read");

    fireEvent.change(screen.getByLabelText("Filter capabilities by noun"), {
      target: { value: "ticket" },
    });
    await waitFor(() => expect(api.capabilities).toHaveBeenLastCalledWith("ticket"));
  });

  it("does not request the author-only changelog for an agent role", async () => {
    updateIdentity({ role: "agent", grants: "ticket.read" });
    mockApi({ capabilities: CAPABILITIES, health: { status: "ok", adapters: {} } });
    render(<RouterPanel />);
    await screen.findByText("ticket.read");

    expect(api.capabilityChangelog).not.toHaveBeenCalled();
    expect(screen.queryByText("Recent capability changes")).toBeNull();
  });
});
