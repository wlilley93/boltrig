// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  conversations: vi.fn(),
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
  vi.unstubAllGlobals();
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

  it("shows server-owned ongoing work without exposing a run identifier", async () => {
    api.conversationsPage
      .mockResolvedValueOnce({
        conversations: [{ ...conversation, working: true }],
        next_offset: null,
      })
      .mockResolvedValueOnce({
        conversations: [{ ...conversation, working: false }],
        next_offset: null,
      });
    api.conversations.mockResolvedValue({
      conversations: [{ ...conversation, working: true }],
    });

    render(<App />);

    expect(await screen.findByRole("status", { name: "Working on this chat" })).toBeTruthy();
    expect(screen.queryByText("run-active")).toBeNull();

    fireEvent.click(screen.getByRole("button", {
      name: "Refresh conversations from Chat",
    }));
    await waitFor(() => expect(screen.queryByRole("status", {
      name: "Working on this chat",
    })).toBeNull());
  });

  it("does not append a stale page into a newer conversation refresh", async () => {
    let resolveStalePage!: (value: {
      conversations: Array<typeof conversation>;
      next_offset: number | null;
    }) => void;
    api.conversationsPage
      .mockResolvedValueOnce({
        conversations: [conversation],
        next_offset: 25,
      })
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveStalePage = resolve;
      }))
      .mockResolvedValueOnce({
        conversations: [{
          ...conversation,
          id: "conversation-current",
          title: "Current refreshed task",
        }],
        next_offset: null,
      });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", {
      name: "Load more conversations",
    }));
    fireEvent.click(screen.getByRole("button", {
      name: "Refresh conversations from Chat",
    }));

    expect(await screen.findByText("Current refreshed task")).toBeTruthy();
    await act(async () => {
      resolveStalePage({
        conversations: [{
          ...conversation,
          id: "conversation-stale",
          title: "Stale paginated task",
        }],
        next_offset: 50,
      });
      await Promise.resolve();
    });

    expect(screen.queryByText("Previously loaded task")).toBeNull();
    expect(screen.queryByText("Stale paginated task")).toBeNull();
    expect(screen.getByText("Current refreshed task")).toBeTruthy();
    expect(screen.queryByRole("button", {
      name: "Load more conversations",
    })).toBeNull();
    expect(api.conversationsPage.mock.calls[1]).toEqual([25, 25]);
    expect(api.conversationsPage.mock.calls[2]).toEqual([25, 0]);
  });

  it("makes the mobile navigation modal to keyboard focus and restores its opener", async () => {
    stubNavigationViewport(true);
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
        name: "Companion: Familiar",
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

  it("hands compact-drawer modality to the command palette without stacking focus traps", async () => {
    stubNavigationViewport(true);
    api.conversationsPage.mockResolvedValue({
      conversations: [],
      next_offset: null,
    });
    render(<App />);
    await screen.findByText("No conversations yet");

    const navigationOpener = screen.getByRole("button", { name: "Open navigation" });
    fireEvent.click(navigationOpener);
    const paletteOpener = await screen.findByRole("button", {
      name: "Open command palette",
    });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", {
      name: "Companion: Familiar",
    })));

    fireEvent.click(paletteOpener);

    const dialog = await screen.findByRole("dialog", { name: "Worker commands" });
    const input = within(dialog).getByRole("combobox", { name: "Search Worker" });
    const options = within(dialog).getAllByRole("option");
    await waitFor(() => expect(document.activeElement).toBe(input));
    expect(navigationOpener.getAttribute("aria-expanded")).toBe("false");
    expect(document.querySelector(".sidebar-wrap.open")).toBeNull();

    const lastOption = options.at(-1)!;
    lastOption.focus();
    fireEvent.keyDown(lastOption, { key: "Tab" });
    expect(document.activeElement).toBe(input);

    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(lastOption);

    fireEvent.keyDown(lastOption, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(navigationOpener.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(navigationOpener);
  });

  it("releases the main surface when an open navigation drawer crosses to desktop", async () => {
    const viewport = stubNavigationViewport(true);
    api.conversationsPage.mockResolvedValue({
      conversations: [],
      next_offset: null,
    });
    render(<App />);
    await screen.findByText("No conversations yet");

    const opener = screen.getByRole("button", { name: "Open navigation" });
    const surface = document.querySelector<HTMLElement>(".surface")!;
    fireEvent.click(opener);
    await waitFor(() => expect(surface.inert).toBe(true));
    expect(surface.getAttribute("aria-hidden")).toBe("true");
    const scrim = screen.getByRole("button", { name: "Close navigation" });
    scrim.focus();
    expect(document.activeElement).toBe(scrim);

    act(() => viewport.setCompact(false));

    await waitFor(() => expect(opener.getAttribute("aria-expanded")).toBe("false"));
    expect(surface.inert).toBe(false);
    expect(surface.hasAttribute("aria-hidden")).toBe(false);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "New chat" }));
  });

  it("moves desktop-sidebar focus to the visible opener when navigation becomes compact", async () => {
    const viewport = stubNavigationViewport(false);
    api.conversationsPage.mockResolvedValue({
      conversations: [],
      next_offset: null,
    });
    render(<App />);
    await screen.findByText("No conversations yet");

    const desktopDestination = screen.getByRole("button", { name: "New chat" });
    const opener = screen.getByRole("button", { name: "Open navigation" });
    const surface = document.querySelector<HTMLElement>(".surface")!;
    desktopDestination.focus();
    expect(document.activeElement).toBe(desktopDestination);

    act(() => viewport.setCompact(true));

    await waitFor(() => expect(document.activeElement).toBe(opener));
    expect(opener.getAttribute("aria-expanded")).toBe("false");
    expect(surface.inert).toBe(false);
    expect(surface.hasAttribute("aria-hidden")).toBe(false);
  });
});

function stubNavigationViewport(initialCompact: boolean) {
  const compactListeners = new Set<(event: MediaQueryListEvent) => void>();
  const compactMedia = {
    matches: initialCompact,
    media: "(max-width: 760px)",
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      compactListeners.add(listener);
    },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      compactListeners.delete(listener);
    },
    dispatchEvent: vi.fn(),
  };
  const phoneMedia = {
    matches: false,
    media: "(max-width: 640px)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  };
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => (
    query === compactMedia.media ? compactMedia : phoneMedia
  )));
  return {
    setCompact(matches: boolean) {
      compactMedia.matches = matches;
      for (const listener of compactListeners) {
        listener({ matches, media: compactMedia.media } as MediaQueryListEvent);
      }
    },
  };
}
