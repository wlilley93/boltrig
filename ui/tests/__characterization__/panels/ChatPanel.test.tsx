import { afterEach, describe, it, expect } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChatPanel } from "@/panels/ChatPanel";
import ChatPanelDefault from "@/panels/ChatPanel";
import { clearApiMocks, mockApi } from "../helpers";

describe("ChatPanel", () => {
  afterEach(() => {
    cleanup();
    clearApiMocks();
  });

  it("renders without crashing", () => {
    mockApi({
      listConversations: { conversations: [], next_offset: null },
      searchConversations: { results: [], next_offset: null },
      conversation: { messages: [] },
    });
    render(<ChatPanel />);
  });

  it("shows the empty chat start, composer and header when no conversation is active", () => {
    mockApi({
      listConversations: { conversations: [], next_offset: null },
      searchConversations: { results: [], next_offset: null },
      conversation: { messages: [] },
    });
    render(<ChatPanel />);

    // Header
    expect(screen.getByRole("button", { name: "Toggle chat sidebar" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Chat tabs" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Chat" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Activity" })).toBeTruthy();

    // Empty state greeting
    expect(screen.getByRole("heading", { level: 1 })).toBeTruthy();

    // Composer
    expect(screen.getByPlaceholderText("Type a message")).toBeTruthy();
  });

  it("opens the agent rail and shows an empty conversation list", async () => {
    mockApi({
      listConversations: { conversations: [], next_offset: null },
      searchConversations: { results: [], next_offset: null },
      conversation: { messages: [] },
    });
    render(<ChatPanel />);

    const toggle = screen.getByRole("button", { name: "Toggle chat sidebar" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");

    // The sidebar label and empty list copy
    await waitFor(() => expect(screen.getByText("No conversations yet.")).toBeTruthy());
  });

  it("preserves the public named and default export", () => {
    expect(typeof ChatPanel).toBe("function");
    expect(ChatPanelDefault).toBe(ChatPanel);
  });
});
