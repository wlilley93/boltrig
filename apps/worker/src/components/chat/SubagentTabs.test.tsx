// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SubagentEntry } from "@wlilley93/boltrig-web-sdk";

const api = vi.hoisted(() => ({
  auditTree: vi.fn(),
}));

vi.mock("../../client", () => ({ client: api }));

import { SubagentTabs } from "./SubagentTabs";

afterEach(cleanup);

const LYELL: SubagentEntry = {
  key: "sub-1",
  childRunId: "child-1",
  task: "Read health signals for 20 accounts",
  skills: ["crm.account.read", "crm.contact.read"],
  name: "Lyell",
  role: "researcher",
  stepCount: 3,
  status: "ok",
};

const NOETHER: SubagentEntry = {
  key: "sub-2",
  childRunId: "child-2",
  task: "Check three at-risk accounts against policy",
  skills: [],
};

function renderTabs(overrides: Partial<Parameters<typeof SubagentTabs>[0]> = {}) {
  const handlers = { onSelect: vi.fn(), onClose: vi.fn(), onCloseAll: vi.fn() };
  const view = render(
    <SubagentTabs
      subagents={[LYELL, NOETHER]}
      openKeys={["sub-1", "sub-2"]}
      activeKey="sub-1"
      parentRunId="run-parent"
      turnEnded={false}
      {...handlers}
      {...overrides}
    />,
  );
  return { view, handlers };
}

beforeEach(() => {
  api.auditTree.mockReset();
  api.auditTree.mockResolvedValue({
    root: {
      run_id: "run-parent",
      children: [
        { run_id: "child-1", actions: 3, tokens: 120, cost_micros: 420_000, total_cost_micros: 420_000 },
      ],
    },
  });
});

describe("subagent tabs", () => {
  it("draws one tab per open subagent and marks the active one", () => {
    renderTabs();
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    expect(tabs[1].getAttribute("aria-selected")).toBe("false");
    expect(tabs[0].textContent).toContain("Lyell");
    // The unnamed subagent renders its neutral fallback, not a minted name.
    expect(tabs[1].textContent).toContain("Subagent");
  });

  it("shows the instruction the parent gave and the settled state word", () => {
    renderTabs();
    expect(screen.getByText("Read health signals for 20 accounts")).toBeTruthy();
    expect(screen.getByText("finished")).toBeTruthy();
  });

  it("shows the honest step count, never a step list", () => {
    renderTabs();
    expect(screen.getByText(/3 steps recorded/)).toBeTruthy();
    // The design's fabricated per-step rows ("Read 20 account records", …)
    // must not appear; the stream exposes only the count it actually carries.
    expect(screen.queryByRole("link", { name: "Open full event stream" })).toBeNull();
  });

  it("fills the allowed-to-do card with real skills and real audit spend", async () => {
    renderTabs();
    expect(screen.getByText("crm.account.read, crm.contact.read")).toBeTruthy();
    await waitFor(() => {
      // Digits only: the currency symbol placement is locale-dependent.
      expect(screen.getByText(/3 actions · .*0\.42/)).toBeTruthy();
    });
    expect(api.auditTree).toHaveBeenCalledWith("run-parent");
  });

  it("reports spend honestly when the audit tree is unreachable", async () => {
    api.auditTree.mockRejectedValue(new Error("down"));
    renderTabs();
    await waitFor(() => {
      expect(screen.getByText("spend unavailable")).toBeTruthy();
    });
  });

  it("never renders a per-subagent composer or an invented result paragraph", () => {
    renderTabs();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(document.querySelector("form")).toBeNull();
  });

  it("keeps an unsettled subagent honest across the turn boundary", () => {
    // Live turn, no subagent_end yet: still working.
    const { view } = renderTabs({ activeKey: "sub-2" });
    expect(screen.getByText("still working")).toBeTruthy();
    view.unmount();
    // Turn over, still no settle frame: the kernel never reported completion,
    // so the pane must not claim it finished.
    renderTabs({ activeKey: "sub-2", turnEnded: true });
    expect(screen.getByText("no completion reported")).toBeTruthy();
  });

  it("wires select, close, and close-all to the caller", () => {
    const { handlers } = renderTabs();
    fireEvent.click(screen.getAllByRole("tab")[1]);
    expect(handlers.onSelect).toHaveBeenCalledWith("sub-2");
    fireEvent.click(screen.getByRole("button", { name: "Close Lyell tab" }));
    expect(handlers.onClose).toHaveBeenCalledWith("sub-1");
    fireEvent.click(screen.getByRole("button", { name: "Close all subagent tabs" }));
    expect(handlers.onCloseAll).toHaveBeenCalled();
  });

  it("renders nothing once every open key has left the turn", () => {
    const { view } = renderTabs({ openKeys: ["gone"] });
    expect(view.container.querySelector(".subtabs")).toBeNull();
  });
});
