// @vitest-environment happy-dom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  restoreMyConversation: vi.fn(),
  searchConversations: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { Sidebar } from "../src/components/Shell";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Worker closed-conversation lifecycle", () => {
  it.each(["chat", "agents", "integrations", "automations"] as const)(
    "keeps closed tasks out of %s Recents because recovery lives in Archived chats",
    (route) => {
      const onConversation = vi.fn();
      const onConversationRestored = vi.fn();

      render(
        <Sidebar
          route={route}
          conversations={[{
            id: "closed-a",
            title: "Closed task",
            status: "closed",
            updated_at: "2026-01-01T00:00:00Z",
          }]}
          selectedConversation={null}
          onRoute={vi.fn()}
          onConversation={onConversation}
          onConversationRestored={onConversationRestored}
          onLoadMore={vi.fn()}
          hasMoreConversations={false}
        />,
      );

      expect(screen.queryByText("Closed task")).toBeNull();
      expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
      expect(screen.getByText("No recent conversations")).toBeTruthy();
      expect(document.querySelector('[data-status="closed"]')).toBeNull();
      expect(api.restoreMyConversation).not.toHaveBeenCalled();
      expect(onConversation).not.toHaveBeenCalled();
      expect(onConversationRestored).not.toHaveBeenCalled();
    },
  );

  it("does not retain the removed recents search path", () => {
    render(
      <Sidebar
        route="chat"
        conversations={[]}
        selectedConversation={null}
        onRoute={vi.fn()}
        onConversation={vi.fn()}
        onConversationRestored={vi.fn()}
        onLoadMore={vi.fn()}
        hasMoreConversations={false}
      />,
    );

    expect(screen.queryByRole("textbox", { name: "Search conversations" })).toBeNull();
    expect(document.querySelector(".conversation-search")).toBeNull();
    expect(screen.queryByText("No matching conversations")).toBeNull();
    expect(api.searchConversations).not.toHaveBeenCalled();
  });
});
