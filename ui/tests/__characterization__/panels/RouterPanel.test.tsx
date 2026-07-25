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
    // Wait for the OPTION, not just the verb row. Firing `change` at a <select>
    // that has no matching <option> is a silent no-op: the DOM snaps the value
    // back to "" and React reports onChange(""), so the filter never reaches the
    // server and the assertion below can never pass. The panel now commits the
    // options with the verbs, so this is belt and braces - but a test whose
    // arrange step can silently not-happen is a test that reports timing as a
    // product failure.
    await screen.findByRole("option", { name: "ticket" });

    fireEvent.change(screen.getByLabelText("Filter capabilities by noun"), {
      target: { value: "ticket" },
    });
    // Called WITH the noun, not LAST called with it. The property under test is
    // that the filter reaches the server rather than being applied to an
    // already-downloaded list; it says nothing about what settles afterwards.
    // toHaveBeenLastCalledWith additionally asserted an ordering the component
    // never promised, so it passed alone and failed under full-suite timing.
    await waitFor(() => expect(api.capabilities).toHaveBeenCalledWith("ticket"));
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
