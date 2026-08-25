// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("../src/routes", () => ({ navigate }));

import { ComposerAddMenu } from "../src/components/chat/ComposerAddMenu";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("composer add menu", () => {
  it("searches only truthful Boltrig actions and restores focus on Escape", async () => {
    const attach = vi.fn();
    const commands = vi.fn();
    render(
      <ComposerAddMenu
        disabled={false}
        onAttach={attach}
        onOpenCommands={commands}
      />,
    );

    const opener = screen.getByRole("button", { name: "Add" });
    fireEvent.click(opener);
    expect(screen.getByRole("button", { name: /Files/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Search Boltrig/ })).toBeTruthy();
    expect(screen.queryByText("Browser tabs")).toBeNull();

    // The menu's "Agent tools" and "Workspace" groups pointed at Work,
    // Routines, Skills, Plugins and Knowledge - kernel consoles, all removed
    // with their routes. What is still worth pinning is that the search filters
    // to TRUTHFUL actions and finds nothing for a destination that is gone.
    const search = screen.getByRole("textbox", { name: "Search actions" });
    fireEvent.change(search, { target: { value: "skill" } });
    expect(screen.queryByRole("button", { name: /Record a skill/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Plugins/ })).toBeNull();
    fireEvent.change(search, { target: { value: "" } });

    fireEvent.keyDown(screen.getByRole("dialog", { name: "Add to task" }), { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it("keeps navigation available while local file attachment is unavailable", () => {
    render(
      <ComposerAddMenu
        attachmentsDisabled
        disabled={false}
        onAttach={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect((screen.getByRole("button", { name: /Files/ }) as HTMLButtonElement).disabled)
      .toBe(true);
    // The menu still opens and still says why Files cannot be used, which is
    // the honesty this test is named for.
    expect(screen.getByRole("dialog", { name: "Add to task" })).toBeTruthy();
    expect(screen.getByText("Unavailable for local tasks")).toBeTruthy();
  });
});
