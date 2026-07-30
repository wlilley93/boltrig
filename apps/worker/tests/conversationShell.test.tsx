// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  conversationsPage: vi.fn(),
  restoreMyConversation: vi.fn(),
  searchConversations: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/ChatView", () => ({
  ChatView: ({ onChanged }: { onChanged(): void }) => (
    <main>
      <p>Chat surface</p>
      <button onClick={onChanged}>Refresh conversations from Chat</button>
    </main>
  ),
}));

import { App } from "../src/App";

const conversation = {
  id: "conversation-a",
  title: "Previously loaded task",
  status: "active",
  updated_at: "2026-07-29T12:00:00Z",
};

beforeEach(() => {
  window.location.hash = "#/chat";
  api.searchConversations.mockResolvedValue({ results: [] });
  api.restoreMyConversation.mockResolvedValue({
    status: "ok",
    id: conversation.id,
    conversation_status: "active",
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = "";
});

describe("Worker conversation shell truthfulness", () => {
  it("distinguishes initial loading from a canonical empty response", async () => {
    let resolve!: (value: { conversations: never[]; next_offset: null }) => void;
    api.conversationsPage.mockReturnValue(new Promise((done) => {
      resolve = done;
    }));

    render(<App />);

    expect(screen.getByText("Loading conversations…")).toBeTruthy();
    expect(screen.queryByText("No conversations yet")).toBeNull();

    await act(async () => {
      resolve({ conversations: [], next_offset: null });
      await Promise.resolve();
    });

    expect(await screen.findByText("No conversations yet")).toBeTruthy();
    expect(screen.queryByText("Loading conversations…")).toBeNull();
  });

  it("retains authorized rows on refresh failure and retries without losing truth", async () => {
    api.conversationsPage
      .mockResolvedValueOnce({
        conversations: [conversation],
        next_offset: 25,
      })
      .mockRejectedValueOnce(new Error("network unavailable"))
      .mockResolvedValueOnce({
        conversations: [],
        next_offset: null,
      });

    render(<App />);

    expect(await screen.findByText("Previously loaded task")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Refresh conversations from Chat",
    }));

    expect(await screen.findByText(
      "Conversation refresh is unavailable. Previously loaded conversations may be stale.",
    )).toBeTruthy();
    expect(screen.getByText("Previously loaded task")).toBeTruthy();
    expect(screen.queryByText("No conversations yet")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry conversations" }));
    await waitFor(() => expect(api.conversationsPage).toHaveBeenCalledTimes(3));
    expect(await screen.findByText("No conversations yet")).toBeTruthy();
    expect(screen.queryByText("Previously loaded task")).toBeNull();
  });

  it("keeps conversation pagination additive and uses the opaque next offset", async () => {
    api.conversationsPage
      .mockResolvedValueOnce({
        conversations: [conversation],
        next_offset: 25,
      })
      .mockResolvedValueOnce({
        conversations: [{
          ...conversation,
          id: "conversation-b",
          title: "Next page task",
        }],
        next_offset: null,
      });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", {
      name: "Load more conversations",
    }));
    expect(await screen.findByText("Next page task")).toBeTruthy();
    expect(screen.getByText("Previously loaded task")).toBeTruthy();
    expect(api.conversationsPage).toHaveBeenLastCalledWith(25, 25);
    expect(screen.queryByRole("button", {
      name: "Load more conversations",
    })).toBeNull();
  });

  it("makes the mobile navigation modal to keyboard focus and restores its opener", async () => {
    api.conversationsPage.mockResolvedValue({
      conversations: [],
      next_offset: null,
    });
    render(<App />);
    await screen.findByText("No conversations yet");

    const opener = screen.getByRole("button", { name: "Open navigation" });
    const surface = document.querySelector<HTMLElement>(".surface")!;
    fireEvent.click(opener);

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole("button", {
        name: "Home",
      }));
    });
    expect(opener.getAttribute("aria-expanded")).toBe("true");
    expect(surface.getAttribute("aria-hidden")).toBe("true");
    expect(surface.inert).toBe(true);

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(opener));
    expect(opener.getAttribute("aria-expanded")).toBe("false");
    expect(surface.hasAttribute("aria-hidden")).toBe(false);
    expect(surface.inert).toBe(false);

    fireEvent.click(opener);
    fireEvent.click(screen.getByRole("button", { name: "Close navigation" }));
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});
