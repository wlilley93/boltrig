// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  readiness: vi.fn(),
  restoreMyConversation: vi.fn(),
  searchConversations: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { Sidebar } from "../src/components/Shell";
import type { WorkerRoute } from "../src/routes";

function renderSidebar(onRoute = vi.fn()) {
  render(
    <Sidebar
      route="chat"
      conversations={[]}
      conversationStatus="ready"
      selectedConversation={null}
      onRoute={onRoute}
      onConversation={vi.fn()}
      onConversationRestored={vi.fn()}
      onLoadMore={vi.fn()}
      hasMoreConversations={false}
      onCommandPalette={vi.fn()}
    />,
  );
  return onRoute;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("console sidebar", () => {
  it("maps the console nav onto the real Worker routes", () => {
    api.readiness.mockResolvedValue({ status: "ready", checks: {} });
    const onRoute = renderSidebar();

    const expectations: Array<[string, WorkerRoute]> = [
      ["Chat", "chat"],
      ["Inbox", "inbox"],
      ["Agents", "agents"],
      ["Integrations", "integrations"],
      ["Automations", "automations"],
      ["Runs", "runs"],
      ["Work", "work"],
      ["Knowledge", "knowledge"],
      ["Memory", "memory"],
      ["New chat ⌘N", "chat"],
    ];
    for (const [label, route] of expectations) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(onRoute).toHaveBeenLastCalledWith(route);
    }
  });

  it("keeps every quiet surface reachable from the account menu", () => {
    api.readiness.mockResolvedValue({ status: "ready", checks: {} });
    const onRoute = renderSidebar();

    const expectations: Array<[string, WorkerRoute]> = [
      ["Home", "home"],
      ["Build", "build"],
      ["Evaluations", "evaluations"],
      ["Channels", "channels"],
      ["Operate", "operate"],
      ["Account", "account"],
      ["Organisation", "organisation"],
      ["Settings", "settings"],
    ];
    for (const [label, route] of expectations) {
      fireEvent.click(screen.getByRole("button", { name: /Account menu/ }));
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(onRoute).toHaveBeenLastCalledWith(route);
    }
    // The Operator handoff stays a plain visible link, never a re-implemented
    // surface (WORKER-PARITY.md) - and exactly one, so role queries stay strict.
    expect(screen.getByRole("link", { name: "Open Operator" })
      .getAttribute("href")).toBe("/operator/");
  });

  it("reports measured readiness on the status line and degrades honestly", async () => {
    api.readiness.mockResolvedValue({
      status: "not_ready",
      checks: {
        store: { status: "ok" },
        engine: { status: "failed" },
      },
    });
    const onRoute = renderSidebar();

    const status = await screen.findByRole("button", { name: /1 check not ready/ });
    fireEvent.click(status);
    expect(onRoute).toHaveBeenLastCalledWith("operate");
  });

  it("says health is unavailable rather than inventing a green dot", async () => {
    api.readiness.mockRejectedValue(new Error("network unavailable"));
    renderSidebar();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Health unavailable/ })).toBeTruthy();
    });
  });
});
