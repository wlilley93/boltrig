// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  readiness: vi.fn(),
  budgets: vi.fn(),
  cost: vi.fn(),
  conversations: vi.fn(),
  restoreMyConversation: vi.fn(),
  searchConversations: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { Sidebar } from "../src/components/Shell";
import { SettingsSectionPane } from "../src/components/SettingsSurface";
import { SETTINGS_SECTIONS } from "../src/settingsSections";

beforeEach(() => {
  api.readiness.mockResolvedValue({ status: "ready", checks: {} });
  api.budgets.mockResolvedValue({ budgets: [], scope: "all" });
  api.cost.mockResolvedValue({ total_cost_micros: 0, by_actor: {}, scope: "all" });
  api.conversations.mockResolvedValue({ conversations: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("settings surface", () => {
  it("replaces the app nav with all ten settings sections while settings is open", () => {
    const onSettingsSection = vi.fn();
    render(
      <Sidebar
        route="settings"
        conversations={[]}
        conversationStatus="ready"
        selectedConversation={null}
        onRoute={vi.fn()}
        onConversation={vi.fn()}
        onConversationRestored={vi.fn()}
        onLoadMore={vi.fn()}
        hasMoreConversations={false}
        settingsSection="you"
        onSettingsSection={onSettingsSection}
      />,
    );

    expect(SETTINGS_SECTIONS.length).toBe(10);
    for (const entry of SETTINGS_SECTIONS) {
      expect(screen.getByRole("button", { name: entry.label })).toBeTruthy();
    }
    // The global nav is gone while settings is open, and the way back is named.
    expect(screen.queryByRole("button", { name: "Routines" })).toBeNull();
    expect(screen.getByRole("button", { name: "Back to app" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Health" }));
    expect(onSettingsSection).toHaveBeenCalledWith("health");
  });

  it("searches every setting rather than hiding one behind a head", () => {
    render(
      <Sidebar
        route="settings"
        conversations={[]}
        conversationStatus="ready"
        selectedConversation={null}
        onRoute={vi.fn()}
        onConversation={vi.fn()}
        onConversationRestored={vi.fn()}
        onLoadMore={vi.fn()}
        hasMoreConversations={false}
        settingsSection="you"
        onSettingsSection={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Search every setting" }), {
      target: { value: "archiv" },
    });
    expect(screen.getByRole("button", { name: "Archived chats" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Spending" })).toBeNull();
  });

  it("counts an ok check as healthy, not as a failure", async () => {
    // The kernel reports healthy as "ready" OR "ok". Treating only "ready" as
    // healthy painted an ok check red and counted it among the failures.
    api.readiness.mockResolvedValue({
      status: "not_ready",
      checks: {
        stack_tools: { status: "ok", required: true },
        postgres: { status: "disabled", required: false, reason: "not_configured" },
        control_plane: { status: "failed", required: true, reason: "unavailable" },
      },
    });
    render(<SettingsSectionPane section="health" />);

    await waitFor(() => {
      expect(screen.getByText("2 of 3 checks are not ready.")).toBeTruthy();
    });
    const ok = screen.getByText("ok");
    expect(ok.getAttribute("data-tone")).toBe("ok");
    expect(screen.getByText("failed").getAttribute("data-tone")).toBe("bad");
    // A switched-off check is not a failure, even though it is not ready.
    expect(screen.getByText("disabled").getAttribute("data-tone")).toBe("warn");
  });

  it("says no ceiling is set rather than implying spend is bounded", async () => {
    render(<SettingsSectionPane section="spend" />);
    await waitFor(() => {
      expect(screen.getByText("No ceiling is set")).toBeTruthy();
    });
    expect(screen.getByText(/Nothing stops spend/)).toBeTruthy();
  });

  it("states plainly that nothing runs overnight in this build", () => {
    render(<SettingsSectionPane section="overnight" />);
    expect(screen.getByText("Nothing runs overnight yet")).toBeTruthy();
  });
});
