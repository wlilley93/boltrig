// @vitest-environment happy-dom

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
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

import { CommandPalette, workerCommands } from "../src/components/CommandPalette";
import { SETTINGS_SECTIONS } from "../src/settingsSections";

const commandPaletteCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/components/CommandPalette.css"),
  "utf8",
);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("Worker command palette", () => {
  it("pins the 1440px CURRENT SOURCE panel geometry without breaking narrow layouts", () => {
    expect(commandPaletteCss).toMatch(/padding:\s*15vh 5vw 0/);
    expect(commandPaletteCss).toMatch(/transform:\s*translateX\(220px\)/);
    expect(commandPaletteCss).toMatch(/width:\s*min\(560px, 90vw\)/);
    expect(commandPaletteCss).toMatch(/max-width:\s*960px[\s\S]*transform:\s*none/);
  });

  it("matches the target command surface vocabulary and bounded opening list", () => {
    render(<CommandPalette open onClose={vi.fn()} onNavigate={vi.fn()} />);

    const dialog = screen.getByRole("dialog", { name: "Worker commands" });
    expect(dialog.getAttribute("data-screen-label")).toBe("Command palette");
    expect(screen.getByPlaceholderText("Go anywhere, change anything")).toBeTruthy();
    expect(screen.getByText("esc")).toBeTruthy();
    expect(screen.queryByText("Commands")).toBeNull();
    // Agents, Plugins and Routines were kernel consoles and went with their
    // routes, so the opening list is New chat plus settings destinations. The
    // assertion still pins that the list is BOUNDED and starts with the task.
    const options = screen.getAllByRole("option");
    expect(options.length).toBeLessThanOrEqual(8);
    expect(options[0]?.textContent).toContain("New chat");
    expect(options.map((option) => option.textContent).join(" "))
      .not.toMatch(/Agents|Plugins|Routines/);
  });

  it("uses the canonical icon for each settings destination", () => {
    render(<CommandPalette open onClose={vi.fn()} onNavigate={vi.fn()} />);
    const input = screen.getByRole("combobox");
    const firstPath = (label: string) => {
      fireEvent.change(input, { target: { value: label } });
      return screen.getByRole("option", { name: new RegExp(label, "i") })
        .querySelector("path")
        ?.getAttribute("d");
    };

    expect(firstPath("You settings")).toBe(
      "M12 4.6a3.4 3.4 0 1 1 0 6.8 3.4 3.4 0 0 1 0-6.8z",
    );
    expect(firstPath("Autonomy settings")).toBe(
      "M12 3l7 3v5.5c0 4.6-3 7.2-7 8.5-4-1.3-7-3.9-7-8.5V6z",
    );
    expect(firstPath("Spending settings")).toBe(
      "M12 3.5a8.5 8.5 0 1 0 8.5 8.5",
    );
    expect(firstPath("Keyboard shortcuts settings")).toBe(
      "M3.5 6.5h17v11h-17z",
    );
  });

  it("keeps every canonical settings section reachable from search", () => {
    for (const { id } of SETTINGS_SECTIONS) {
      expect(workerCommands).toContainEqual(expect.objectContaining({
        route: "settings",
        routeId: id,
      }));
    }

    const onNavigate = vi.fn();
    render(<CommandPalette open onClose={vi.fn()} onNavigate={onNavigate} />);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "models" },
    });
    fireEvent.click(screen.getByRole("option", { name: /Models settings/ }));
    expect(onNavigate).toHaveBeenCalledWith("settings", "models");
  });

  it("finds capability destinations without implying content-wide search", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} onNavigate={onNavigate} />);

    fireEvent.change(screen.getByLabelText("Search Worker"), {
      target: { value: "budget" },
    });
    // "budget" is a keyword of the Spending settings entry. The routes this
    // test used to drive - Routines, Memory - were kernel consoles and are
    // gone; what it proves is that a keyword match navigates and closes.
    fireEvent.click(screen.getByRole("option", { name: /Spending/ }));

    expect(onNavigate).toHaveBeenCalledWith("settings", "spend");
    expect(onClose).toHaveBeenCalled();
  });

  it("supports keyboard selection and dismissal", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} onNavigate={onNavigate} />);
    const input = screen.getByLabelText("Search Worker");

    fireEvent.change(input, { target: { value: "keyboard" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("settings", "shortcuts");

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

  it("keeps keyboard-selected results inside the scrolling result well", () => {
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    try {
      render(<CommandPalette open onClose={vi.fn()} onNavigate={vi.fn()} />);
      const input = screen.getByRole("combobox", { name: "Search Worker" });
      const options = screen.getAllByRole("option");
      scrollIntoView.mockClear();

      fireEvent.keyDown(input, { key: "End" });

      expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
      expect(scrollIntoView.mock.instances.at(-1)).toBe(options.at(-1));
    } finally {
      if (originalScrollIntoView) {
        Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
          configurable: true,
          value: originalScrollIntoView,
        });
      } else {
        delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView;
      }
    }
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

    fireEvent.change(input, { target: { value: "archive" } });
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    expect(onNavigate).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("settings", "archived");
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

    // Escape from a focused option, not just the input: Tab puts focus on the
    // rows, and the registry promises Escape closes what is open.
    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(options.at(-1));
    fireEvent.keyDown(options.at(-1)!, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(opener);
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("makes only background siblings inert and restores them before opener focus", () => {
    const openerFocusState = vi.fn();

    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button
            onClick={() => setOpen(true)}
            onFocus={() => {
              const background = document.querySelector<HTMLElement>(
                '[data-testid="command-background"]',
              );
              openerFocusState({
                ariaHidden: background?.getAttribute("aria-hidden") ?? null,
                inert: background?.inert ?? false,
              });
            }}
            type="button"
          >
            Open commands
          </button>
          <section aria-hidden="false" data-testid="command-background">
            <button data-testid="background-action" type="button">
              Background action
            </button>
          </section>
          <aside
            aria-hidden="true"
            data-testid="already-inert"
            ref={(element) => {
              if (element) element.inert = true;
            }}
          >
            Existing modal background
          </aside>
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
    const background = screen.getByTestId("command-background");
    const backgroundAction = screen.getByTestId("background-action");
    const alreadyInert = screen.getByTestId("already-inert");
    opener.focus();
    openerFocusState.mockClear();
    fireEvent.click(opener);

    const paletteSurface = document.querySelector<HTMLElement>(
      "[data-command-surface]",
    );
    expect(paletteSurface?.inert).toBe(false);
    expect(paletteSurface?.hasAttribute("aria-hidden")).toBe(false);
    expect(opener.inert).toBe(true);
    expect(opener.getAttribute("aria-hidden")).toBe("true");
    expect(background.inert).toBe(true);
    expect(background.getAttribute("aria-hidden")).toBe("true");
    expect(alreadyInert.inert).toBe(true);
    expect(alreadyInert.getAttribute("aria-hidden")).toBe("true");
    expect(screen.queryByRole("button", { name: "Background action" })).toBeNull();
    expect(backgroundAction.closest("[inert]")).toBe(background);

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener.inert).toBe(false);
    expect(opener.hasAttribute("aria-hidden")).toBe(false);
    expect(background.inert).toBe(false);
    expect(background.getAttribute("aria-hidden")).toBe("false");
    expect(alreadyInert.inert).toBe(true);
    expect(alreadyInert.getAttribute("aria-hidden")).toBe("true");
    expect(openerFocusState).toHaveBeenLastCalledWith({
      ariaHidden: "false",
      inert: false,
    });
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
    // A federated hit for a surface this build no longer routes to opens the
    // conversation surface rather than a dead hash.
    expect(onNavigate).toHaveBeenCalledWith("chat", null);
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

    fireEvent.change(input, { target: { value: "archive" } });
    await act(async () => {
      vi.advanceTimersByTime(249);
    });
    expect(api.federatedSearch).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
    });

    const options = screen.getAllByRole("option");
    // The command row is now a settings destination rather than the Memory
    // console; what this test proves is that a command and a content hit sit in
    // one list and the keyboard crosses between them.
    expect(options[0].textContent).toContain("settings");
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

    fireEvent.change(input, { target: { value: "archive" } });
    await flushDebounce();

    expect(screen.getByRole("alert").textContent).toContain(
      "Content search is unavailable",
    );
    fireEvent.click(screen.getAllByRole("option")[0]!);
    expect(onNavigate).toHaveBeenCalledWith("settings", "archived");
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

    // Both are content hits for surfaces this build no longer routes to, so
    // both open the conversation surface. The point the test still makes is
    // that neither invents a detail link: the absent id and the 257-character
    // one both arrive as null rather than as a hash nothing can open.
    expect(onNavigate).toHaveBeenNthCalledWith(1, "chat", null);
    expect(onNavigate).toHaveBeenNthCalledWith(2, "chat", null);
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
