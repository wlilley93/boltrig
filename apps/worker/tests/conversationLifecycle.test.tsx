// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  it("renders a closed row distinctly and restores it instead of opening it", async () => {
    api.restoreMyConversation.mockResolvedValue({
      status: "ok",
      id: "closed-a",
      conversation_status: "active",
    });
    const onConversation = vi.fn();
    const onConversationRestored = vi.fn();

    render(
      <Sidebar
        route="chat"
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

    expect(screen.getByText("Closed · retained during the recovery window")).toBeTruthy();
    expect(document.querySelector('[data-status="closed"]')).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => expect(api.restoreMyConversation).toHaveBeenCalledWith("closed-a"));
    expect(onConversation).not.toHaveBeenCalled();
    expect(onConversationRestored).toHaveBeenCalledWith("closed-a");
  });

  it("distinguishes an unavailable search from an authorized empty result and retries it", async () => {
    api.searchConversations
      .mockRejectedValueOnce(new Error("search unavailable"))
      .mockResolvedValueOnce({ results: [] });

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

    fireEvent.change(screen.getByRole("textbox", {
      name: "Search conversations",
    }), {
      target: { value: "missing task" },
    });

    expect(await screen.findByText("Conversation search is unavailable.")).toBeTruthy();
    expect(screen.queryByText("No matching conversations")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry search" }));

    expect(await screen.findByText("No matching conversations")).toBeTruthy();
    expect(api.searchConversations).toHaveBeenCalledTimes(2);
    expect(api.searchConversations).toHaveBeenLastCalledWith("missing task", 50);
  });
});
