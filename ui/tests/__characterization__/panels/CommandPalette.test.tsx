import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { consumeDevInvokePrefill, peekDevInvokePrefill } from "@/devInvokePrefill";
import { CommandPalette } from "@/panels/CommandPalette";
import { usePaletteCommands } from "@/panels/commandPalette/usePaletteCommands";
import { clearApiMocks, mockApi } from "../helpers";

function PaletteHarness() {
  return (
    <>
      <button
        type="button"
        onClick={() => window.dispatchEvent(new Event("boltrig:open-palette"))}
      >
        Open palette
      </button>
      <CommandPalette />
    </>
  );
}

describe("command palette commands", () => {
  beforeEach(() => {
    const pending = peekDevInvokePrefill();
    if (pending) consumeDevInvokePrefill(pending);
    window.location.hash = "#/home";
  });

  afterEach(() => {
    cleanup();
    clearApiMocks();
  });

  it("opens workflow entities at their real canvas route", () => {
    const { result } = renderHook(() =>
      usePaletteCommands(
        { verbs: [] },
        { workflows: [{ id: "refund.flow", version: "3", source: "generated", intent_tags: [] }] },
        { runs: [] },
        "org-admin",
        "refund",
      ),
    );
    const workflow = result.current.filtered.find((command) => command.id === "workflow:refund.flow");
    act(() => workflow?.run());
    expect(window.location.hash).toBe("#/automations/refund.flow");
  });

  it("carries the exact scoped noun and verb into the Dev console", () => {
    const { result } = renderHook(() =>
      usePaletteCommands(
        { verbs: [{ id: "ticket.create", noun: "ticket" }] },
        { workflows: [] },
        { runs: [] },
        "org-admin",
        "ticket.create",
      ),
    );
    const verb = result.current.filtered.find((command) => command.id === "verb:ticket.create");
    act(() => verb?.run());
    expect(peekDevInvokePrefill()).toEqual({ noun: "ticket", verb: "ticket.create" });
    expect(window.location.hash).toBe("#/dev");
  });

  it("finds workflow navigation for run and trigger language without mutating", () => {
    const { result } = renderHook(() =>
      usePaletteCommands(
        { verbs: [] },
        {
          workflows: [
            {
              id: "refund.flow",
              version: "3",
              source: "generated",
              intent_tags: ["refund"],
            },
          ],
        },
        { runs: [] },
        "org-admin",
        "trigger refund",
        "workflow",
      ),
    );

    expect(result.current.filtered.map((command) => command.id)).toEqual([
      "workflow:refund.flow",
    ]);
    expect(result.current.filtered[0]?.hint).toMatch(/open to review and run/i);
  });

  it("filters command kinds, wraps keyboard selection, and restores opener focus", async () => {
    mockApi({
      capabilities: { verbs: [] },
      workflows: {
        workflows: [
          {
            id: "refund.flow",
            version: "3",
            source: "generated",
            intent_tags: [],
          },
        ],
      },
      runs: { runs: [] },
    });
    render(<PaletteHarness />);
    const opener = screen.getByRole("button", { name: "Open palette" });
    opener.focus();
    fireEvent.click(opener);

    const input = await screen.findByRole("combobox", {
      name: "Command palette search",
    });
    await waitFor(() => expect(document.activeElement).toBe(input));
    const optionCount = screen.getAllByRole("option").length;

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input.getAttribute("aria-activedescendant")).toBe(
      `cmdk-opt-${optionCount - 1}`,
    );
    fireEvent.keyDown(input, { key: "Home" });
    expect(input.getAttribute("aria-activedescendant")).toBe("cmdk-opt-0");
    fireEvent.keyDown(input, { key: "End" });
    expect(input.getAttribute("aria-activedescendant")).toBe(
      `cmdk-opt-${optionCount - 1}`,
    );

    fireEvent.click(screen.getByRole("button", { name: "Workflows" }));
    expect(
      await screen.findByRole("option", { name: /refund\.flow/i }),
    ).toBeTruthy();
    expect(screen.getAllByRole("option")).toHaveLength(1);

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Command palette" })).toBeNull(),
    );
    expect(document.activeElement).toBe(opener);
  });
});
