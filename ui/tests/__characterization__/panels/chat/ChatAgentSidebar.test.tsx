import { afterEach, describe, it, expect, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ChatAgentSidebar } from "@/panels/chat/ChatAgentSidebar";
import { CHAT_AGENTS } from "@/panels/chat/constants";
import type { ConversationSearchResult } from "@/api/types";
import type { RailState } from "@/panels/chat/types";

describe("ChatAgentSidebar", () => {
  afterEach(() => {
    cleanup();
  });

  const railState: RailState = {
    mode: "list",
    items: [],
    nextOffset: null,
    loading: false,
    loadingMore: false,
    error: null,
    errorStatus: null,
  };

  const railItems: ConversationSearchResult[] = [
    { id: "conv-1", title: "First conversation", status: "active", updated_at: "2024-01-01T00:00:00Z", snippet: null },
    { id: "conv-2", title: "Second conversation", status: "active", updated_at: "2024-01-02T00:00:00Z", snippet: "match" },
  ];

  function renderSidebar(overrides: Partial<Parameters<typeof ChatAgentSidebar>[0]> = {}) {
    const props = {
      open: true,
      agents: CHAT_AGENTS,
      activeAgent: CHAT_AGENTS[0],
      railItems,
      railTerm: "",
      railState,
      onNew: vi.fn(),
      onSelectAgent: vi.fn(),
      onSelectConversation: vi.fn(),
      onDeleted: vi.fn(),
      onRenamed: vi.fn(),
      loadMore: vi.fn(),
      onRailTerm: vi.fn(),
      ...overrides,
    };
    return {
      ...render(<ChatAgentSidebar {...props} />),
      props,
    };
  }

  it("renders nothing when closed", () => {
    const { container } = renderSidebar({ open: false });
    expect(container.firstChild).toBeNull();
  });

  it("renders the rail header, search toggle and new chat button", () => {
    renderSidebar();
    expect(screen.getByText("Chat")).toBeTruthy();
    expect(screen.getByTitle("Search conversations")).toBeTruthy();
    expect(screen.getByTitle("New chat")).toBeTruthy();
  });

  it("toggles the search input", () => {
    renderSidebar();
    const toggle = screen.getByTitle("Search conversations");
    expect(screen.queryByLabelText("Search conversations")).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByLabelText("Search conversations")).toBeTruthy();
    fireEvent.click(toggle);
    expect(screen.queryByLabelText("Search conversations")).toBeNull();
  });

  it("calls onNew when the new chat button is clicked", () => {
    const { props } = renderSidebar();
    fireEvent.click(screen.getByTitle("New chat"));
    expect(props.onNew).toHaveBeenCalledTimes(1);
  });

  it("calls onSelectAgent when an agent row is clicked", () => {
    const { props } = renderSidebar();
    fireEvent.click(screen.getByText(CHAT_AGENTS[0].name));
    expect(props.onSelectAgent).toHaveBeenCalledWith(CHAT_AGENTS[0]);
  });

  it("calls onSelectConversation when a conversation is clicked", () => {
    const { props } = renderSidebar({ railState: { ...railState, nextOffset: null } });
    fireEvent.click(screen.getByText("First conversation"));
    expect(props.onSelectConversation).toHaveBeenCalledWith("conv-1");
  });

  it("calls onRailTerm when the search input changes", () => {
    const { props } = renderSidebar();
    fireEvent.click(screen.getByTitle("Search conversations"));
    const input = screen.getByLabelText("Search conversations");
    fireEvent.change(input, { target: { value: "hello" } });
    expect(props.onRailTerm).toHaveBeenCalledWith("hello");
  });

  it("calls loadMore when the load more button is present", () => {
    const { props } = renderSidebar({
      railState: { ...railState, nextOffset: 2 },
    });
    const button = screen.getByText("Load more");
    expect(button).toBeTruthy();
    fireEvent.click(button);
    expect(props.loadMore).toHaveBeenCalledTimes(1);
  });

  it("shows empty state when there are no conversations", () => {
    renderSidebar({ railItems: [] });
    expect(screen.getByText("No conversations yet.")).toBeTruthy();
  });

  it("preserves the public export shape", () => {
    expect(typeof ChatAgentSidebar).toBe("function");
  });
});
