import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { api } from "@/api/client";
import { AuditSearchForm } from "@/panels/insightPanel/AuditSearchForm";
import { downloadAuditExport } from "@/panels/insightPanel/useInsightActions";
import { useInsightState } from "@/panels/insightPanel/useInsightState";
import { clearApiMocks, mockApi } from "../helpers";

function Harness() {
  return <AuditSearchForm s={useInsightState()} />;
}

afterEach(() => {
  cleanup();
  clearApiMocks();
  vi.restoreAllMocks();
});

describe("Audit search", () => {
  it("sends the richer server filters and renders inspectable security metadata", async () => {
    mockApi({
      cost: { total_cost_micros: 0, by_actor: { eve: 0 }, by_status: {} },
      runs: { runs: [] },
      capabilities: { verbs: [] },
      auditSearch: {
        stream: "security",
        scope: "all",
        results: [{
          seq: 7,
          ts: "2026-07-15T10:00:00Z",
          actor: "eve",
          event_type: "login_failure",
          reason: "invalid credentials",
          resource: "auth.login",
        }],
      },
    });
    render(<Harness />);

    await screen.findByRole("option", { name: "eve" });
    fireEvent.change(screen.getByLabelText("Stream"), { target: { value: "security" } });
    fireEvent.change(screen.getByLabelText("Actor"), { target: { value: "eve" } });
    fireEvent.change(screen.getByLabelText("Resource"), { target: { value: "auth.login" } });
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-07-01" } });
    fireEvent.change(screen.getByLabelText("Through"), { target: { value: "2026-07-15" } });
    fireEvent.change(screen.getByLabelText("Event type"), { target: { value: "login_failure" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(api.auditSearch).toHaveBeenCalledWith(expect.objectContaining({
      actor: "eve",
      resource: "auth.login",
      since: "2026-07-01",
      until: "2026-07-15",
      security: true,
      eventType: "login_failure",
    })));
    expect(await screen.findByText("login_failure")).toBeTruthy();
    expect(screen.getByText("Inspect")).toBeTruthy();
  });

  it("downloads export JSON with a deterministic descriptive filename", () => {
    const createObjectURL = vi.fn(() => "blob:audit");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    const filename = downloadAuditExport(
      { count: 1, events: [{ seq: 1 }] },
      new Date("2026-07-15T12:00:00Z"),
    );

    expect(filename).toBe("boltrig-audit-2026-07-15.json");
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:audit");
  });
});
