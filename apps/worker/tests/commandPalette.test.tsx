// @vitest-environment happy-dom

import { useState } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  federatedSearch: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { CommandPalette } from "../src/components/CommandPalette";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("Worker command palette", () => {
  it("finds capability destinations without implying content-wide search", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} onNavigate={onNavigate} />);

    fireEvent.change(screen.getByLabelText("Search Worker"), {
      target: { value: "hatchet" },
    });
    // "hatchet" is a keyword of the Routines entry, which the sidebar's
    // decided-target vocabulary renamed from "Automations".
    fireEvent.click(screen.getByRole("option", { name: /Routines/ }));

    expect(onNavigate).toHaveBeenCalledWith("automations", null);
    expect(onClose).toHaveBeenCalled();
  });

  it("supports keyboard selection and dismissal", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} onNavigate={onNavigate} />);
    const input = screen.getByLabelText("Search Worker");

    fireEvent.change(input, { target: { value: "durable memory" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("memory", null);

    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("exposes the active option through combobox and listbox semantics", () => {
    render(<CommandPalette open onClose={vi.fn()} onNavigate={vi.fn()} />);
    const input = screen.getByRole("combobox", {
      name: "Search Worker",
    });
    const listbox = screen.getByRole("listbox", {
      name: "Worker command results",
    });
    const options = screen.getAllByRole("option");

    expect(input.getAttribute("aria-controls")).toBe(listbox.id);
    expect(input.getAttribute("aria-activedescendant")).toBe(options[0].id);
    expect(options[0].getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("status").textContent).toBe(
      `${options.length} results available.`,
    );

    fireEvent.keyDown(input, { key: "End" });
    expect(input.getAttribute("aria-activedescendant")).toBe(options.at(-1)?.id);
    expect(options.at(-1)?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(input, { key: "Home" });
    expect(input.getAttribute("aria-activedescendant")).toBe(options[0].id);
  });

  it("keeps zero-result navigation bounded and ignores IME composition", () => {
    const onNavigate = vi.fn();
    render(<CommandPalette open onClose={vi.fn()} onNavigate={onNavigate} />);
    const input = screen.getByRole("combobox");

    fireEvent.change(input, { target: { value: "no-such-capability" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Home" });
    fireEvent.keyDown(input, { key: "End" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(input.hasAttribute("aria-activedescendant")).toBe(false);
    expect(screen.getByRole("status").textContent).toContain("0 results available.");
    expect(onNavigate).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "memory" } });
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    expect(onNavigate).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("memory", null);
  });

  it("traps focus and restores it to the opener when dismissed", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Open commands</button>
          <CommandPalette
            open={open}
            onClose={() => setOpen(false)}
            onNavigate={vi.fn()}
          />
        </>
      );
    }

    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open commands" });
    opener.focus();
    fireEvent.click(opener);
    const input = screen.getByRole("combobox");
    const options = screen.getAllByRole("option");
    expect(document.activeElement).toBe(input);

    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(options.at(-1));
    fireEvent.keyDown(options.at(-1)!, { key: "Tab" });
    expect(document.activeElement).toBe(input);

    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("renders canonical results in source order with honest partial states", async () => {
    vi.useFakeTimers();
    api.federatedSearch.mockResolvedValue({
      query: "quarterly incident",
      limit: 5,
      results: [{
        source: "executions",
        id: "run-a",
        title: "Quarterly incident run",
        preview: "Failed during validation",
        route: "runs",
        route_id: "run/a",
        metadata: {},
      }],
      sources: [
        { source: "executions", status: "ok", count: 2, truncated: true },
        { source: "knowledge", status: "denied", count: 0, truncated: false },
        { source: "conversations", status: "unavailable", count: 0, truncated: false },
      ],
    });
    const onNavigate = vi.fn();
    render(<CommandPalette open onClose={vi.fn()} onNavigate={onNavigate} />);
    const input = screen.getByRole("combobox");

    fireEvent.change(input, { target: { value: "quarterly incident" } });
    await flushDebounce();

    expect(api.federatedSearch).toHaveBeenCalledWith({
      query: "quarterly incident",
      limit: 5,
    });
    const groups = screen.getAllByRole("group");
    expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual([
      "Runs and work search results",
      "Knowledge search results",
      "Conversations search results",
    ]);
    expect(within(groups[0]).getByText("2 results · more available")).toBeTruthy();
    expect(within(groups[1]).getByText("Restricted")).toBeTruthy();
    expect(within(groups[2]).getByText("Unavailable")).toBeTruthy();
    const result = within(groups[0]).getByRole("option", {
      name: /Quarterly incident run/,
    });
    expect(input.getAttribute("aria-activedescendant")).toBe(result.id);
    fireEvent.click(result);
    expect(onNavigate).toHaveBeenCalledWith("runs", "run/a");
  });

  it("waits for a substantive query and moves the keyboard across both result kinds", async () => {
    vi.useFakeTimers();
    api.federatedSearch.mockResolvedValue(searchResponse(
      "memory",
      "Memory planning conversation",
    ));
    const onNavigate = vi.fn();
    render(<CommandPalette open onClose={vi.fn()} onNavigate={onNavigate} />);
    const input = screen.getByRole("combobox");

    fireEvent.change(input, { target: { value: "m" } });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(api.federatedSearch).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "memory" } });
    await act(async () => {
      vi.advanceTimersByTime(249);
    });
    expect(api.federatedSearch).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
    });

    const options = screen.getAllByRole("option");
    expect(options[0].textContent).toContain("Memory");
    expect(options[1].textContent).toContain("Memory planning conversation");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toBe(options[1].id);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("chat", "conversation-memory");
  });

  it("keeps navigation available when the federated API is unavailable", async () => {
    vi.useFakeTimers();
    api.federatedSearch.mockRejectedValue(new Error("offline"));
    const onNavigate = vi.fn();
    render(<CommandPalette open onClose={vi.fn()} onNavigate={onNavigate} />);
    const input = screen.getByRole("combobox");

    fireEvent.change(input, { target: { value: "memory" } });
    await flushDebounce();

    expect(screen.getByRole("alert").textContent).toContain(
      "Content search is unavailable",
    );
    fireEvent.click(screen.getByRole("option", { name: /Memory/ }));
    expect(onNavigate).toHaveBeenCalledWith("memory", null);
  });

  it("ignores a stale response after the query changes", async () => {
    vi.useFakeTimers();
    const first = deferred<ReturnType<typeof searchResponse>>();
    api.federatedSearch
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(searchResponse("second", "Second result"));
    render(<CommandPalette open onClose={vi.fn()} onNavigate={vi.fn()} />);
    const input = screen.getByRole("combobox");

    fireEvent.change(input, { target: { value: "first" } });
    await flushDebounce();
    fireEvent.change(input, { target: { value: "second" } });
    await flushDebounce();
    expect(screen.getByText("Second result")).toBeTruthy();

    await act(async () => {
      first.resolve(searchResponse("first", "Stale result"));
      await Promise.resolve();
    });
    expect(screen.queryByText("Stale result")).toBeNull();
    expect(screen.getByText("Second result")).toBeTruthy();
  });

  it("drops absent and overlong route ids instead of inventing detail links", async () => {
    vi.useFakeTimers();
    api.federatedSearch.mockResolvedValue({
      query: "history",
      limit: 5,
      results: [
        {
          source: "memory",
          id: "fact-a",
          title: "Remembered decision",
          preview: null,
          route: "memory",
          route_id: null,
          metadata: {},
        },
        {
          source: "audit",
          id: "audit-a",
          title: "Audit event",
          preview: null,
          route: "operate",
          route_id: "a".repeat(257),
          metadata: {},
        },
      ],
      sources: [
        { source: "memory", status: "ok", count: 1, truncated: false },
        { source: "audit", status: "ok", count: 1, truncated: false },
      ],
    });
    const onNavigate = vi.fn();
    render(<CommandPalette open onClose={vi.fn()} onNavigate={onNavigate} />);

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "history" },
    });
    await flushDebounce();
    fireEvent.click(screen.getByRole("option", { name: /Remembered decision/ }));
    fireEvent.click(screen.getByRole("option", { name: /Audit event/ }));

    expect(onNavigate).toHaveBeenNthCalledWith(1, "memory", null);
    expect(onNavigate).toHaveBeenNthCalledWith(2, "operate", null);
  });
});

async function flushDebounce() {
  await act(async () => {
    vi.advanceTimersByTime(250);
    await Promise.resolve();
  });
}

function searchResponse(query: string, title: string) {
  return {
    query,
    limit: 5,
    results: [{
      source: "conversations" as const,
      id: `conversation-${query}`,
      title,
      preview: null,
      route: "chat" as const,
      route_id: `conversation-${query}`,
      metadata: {},
    }],
    sources: [{
      source: "conversations" as const,
      status: "ok" as const,
      count: 1,
      truncated: false,
    }],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
