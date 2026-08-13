// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  conversationsPage: vi.fn(),
  federatedSearch: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/ChatView", () => ({
  ChatView: ({ conversationId }: { conversationId: string | null }) => (
    <div aria-label="Selected conversation">{conversationId ?? "new task"}</div>
  ),
}));

import { App } from "../src/App";

beforeEach(() => {
  vi.useFakeTimers();
  window.location.hash = "#/chat";
  api.conversationsPage.mockResolvedValue({
    conversations: [],
    next_offset: null,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  window.location.hash = "";
});

describe("Worker federated result navigation", () => {
  it("opens a conversation result through its bounded durable route", async () => {
    api.federatedSearch.mockResolvedValue({
      query: "deep conversation",
      limit: 5,
      results: [{
        source: "conversations",
        id: "conversation/deep",
        title: "Deep conversation",
        preview: "Matched conversation content",
        route: "chat",
        route_id: "conversation/deep",
        metadata: {},
      }],
      sources: [{
        source: "conversations",
        status: "ok",
        count: 1,
        truncated: false,
      }],
    });

    render(<App />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "deep conversation" },
    });
    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });
    fireEvent.click(screen.getByRole("option", {
      name: /Deep conversation/,
    }));

    expect(window.location.hash).toBe("#/chat/conversation%2Fdeep");
    expect(screen.getByLabelText("Selected conversation").textContent).toBe(
      "conversation/deep",
    );
  });
});
