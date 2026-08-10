// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  readiness: vi.fn(),
  health: vi.fn(),
  hitl: vi.fn(),
  budgets: vi.fn(),
  cost: vi.fn(),
  conversations: vi.fn(),
  restoreMyConversation: vi.fn(),
  searchConversations: vi.fn(),
  auditSearch: vi.fn(),
  meSettings: vi.fn(),
  putMeSettings: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { Sidebar } from "../src/components/Shell";
import { SettingsSearchResults, SettingsSectionPane } from "../src/components/SettingsSurface";
import { SETTINGS_SECTIONS } from "../src/settingsSections";
import { SHORTCUTS } from "../src/shortcuts";

beforeEach(() => {
  api.readiness.mockResolvedValue({ status: "ready", checks: {} });
  api.health.mockResolvedValue({ status: "ok", adapters: {} });
  api.hitl.mockResolvedValue({ requests: [] });
  api.budgets.mockResolvedValue({ budgets: [], scope: "all" });
  api.cost.mockResolvedValue({ total_cost_micros: 0, by_actor: {}, scope: "all" });
  api.conversations.mockResolvedValue({ conversations: [] });
  api.auditSearch.mockResolvedValue({ results: [], scope: "all", limit: 50, offset: 0, next_offset: null });
  api.meSettings.mockResolvedValue({ profile: { id: "u" }, settings: {} });
  api.putMeSettings.mockResolvedValue({ status: "ok" });
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

  it("humanises checks without repainting kernel semantics", async () => {
    // The kernel reports healthy as "ready" OR "ok", and a switched-off check
    // as "disabled". The humanised rows must keep those distinctions: an ok
    // check is fine, a disabled optional check is not a failure, and only a
    // failing required check reads as not working.
    api.readiness.mockResolvedValue({
      status: "not_ready",
      checks: {
        stack_tools: { status: "ok", required: true },
        postgres: { status: "disabled", required: false, reason: "not_configured" },
        control_plane: { status: "failed", required: true, reason: "unavailable" },
      },
    });
    api.health.mockResolvedValue({ status: "ok", adapters: { "acme/jira": "degraded" } });
    render(<SettingsSectionPane section="health" />);

    await waitFor(() => {
      expect(screen.getByText("1 essential check is not working")).toBeTruthy();
    });
    // Humanised titles for known checks; tone words carry the reading.
    expect(screen.getByText("Acting in your systems")).toBeTruthy();
    expect(screen.getByText("fine").getAttribute("data-tone")).toBe("green");
    expect(screen.getByText("not working").getAttribute("data-tone")).toBe("red");
    expect(screen.getByText("switched off").getAttribute("data-tone")).toBe("unknown");
    // The stat card counts healthy checks, required and optional together.
    expect(screen.getByText("1 of 3")).toBeTruthy();
    // Adapter health from /healthz joins the same card.
    expect(screen.getByText("jira adapter")).toBeTruthy();
    expect(screen.getByText("struggling").getAttribute("data-tone")).toBe("amber");
    // Every boundary listed is a limit of THIS build.
    expect(screen.getByText("What boltrig does not do yet")).toBeTruthy();
    expect(screen.getByText("Weekly spending windows")).toBeTruthy();
  });

  it("says no ceiling is set rather than implying spend is bounded", async () => {
    render(<SettingsSectionPane section="spend" />);
    await waitFor(() => {
      expect(screen.getByText("No ceiling is set")).toBeTruthy();
    });
    expect(screen.getByText(/Nothing stops spend/)).toBeTruthy();
  });

  it("draws a labelled meter per money ceiling, honest about soft stops", async () => {
    api.budgets.mockResolvedValue({
      budgets: [{
        id: "b1",
        scope_type: "tenant",
        window: "daily",
        hard_stop: false,
        token_limit: null,
        spent_tokens: 0,
        cost_limit_micros: 40_000_000,
        spent_micros: 12_400_000,
        usage_state: "current",
        window_key: null,
        window_started_at: null,
        window_ends_at: "2026-08-11T00:00:00Z",
      }],
      scope: "all",
    });
    render(<SettingsSectionPane section="spend" />);
    await waitFor(() => {
      expect(screen.getByText("Today")).toBeTruthy();
    });
    expect(screen.getByText("$12.40")).toBeTruthy();
    expect(screen.getByText("of $40.00")).toBeTruthy();
    // A soft ceiling never claims to stop work, and the reset date is drawn
    // from window_ends_at (exact day depends on the runner's timezone).
    expect(screen.getByText(/does not stop work · Resets \d+ Aug/)).toBeTruthy();
  });

  it("tells the truth about a workspace where no night has run", async () => {
    render(<SettingsSectionPane section="overnight" />);
    await waitFor(() => {
      expect(screen.getByText("No night has run here yet")).toBeTruthy();
    });
    // The mechanism is described, never scored: no invented pass/fail words.
    expect(screen.getByText("What a night has to prove")).toBeTruthy();
    expect(screen.getByText("The rules it works under")).toBeTruthy();
    expect(screen.queryByText("passed")).toBeNull();
  });

  it("reads a held night from the gate receipt, not from demo data", async () => {
    api.auditSearch.mockResolvedValue({
      results: [{
        seq: 7,
        ts: "2026-08-09T03:00:00Z",
        actor: "distill",
        verb: "distill.gate",
        status: "distill_gate_hold",
        run_id: "run_1",
      }],
      scope: "all",
      limit: 50,
      offset: 0,
      next_offset: null,
    });
    render(<SettingsSectionPane section="overnight" />);
    await waitFor(() => {
      expect(screen.getByText("The last practice was held back")).toBeTruthy();
    });
    expect(screen.getByText("held back").getAttribute("data-tone")).toBe("amber");
  });

  it("lists only shortcuts the build binds, from the shared registry", () => {
    render(<SettingsSectionPane section="shortcuts" />);
    for (const shortcut of SHORTCUTS) {
      expect(screen.getByText(shortcut.label)).toBeTruthy();
    }
    // The old hand-written list claimed a ⌘B sidebar toggle no handler bound.
    expect(screen.queryByText("Show or hide the sidebar")).toBeNull();
    expect(screen.queryByText("⌘B")).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "Search shortcuts" }), {
      target: { value: "palette" },
    });
    expect(screen.getByText("Close what is open")).toBeTruthy();
    expect(screen.queryByText("New chat")).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "Search shortcuts" }), {
      target: { value: "zzz" },
    });
    expect(screen.getByText("Nothing matches that.")).toBeTruthy();
  });

  it("shows each archived chat on one line with its last-activity date", async () => {
    api.conversations.mockResolvedValue({
      conversations: [
        { id: "c1", title: "Enable maax in Codex", status: "closed", updated_at: "2026-08-09T10:00:00Z" },
        { id: "c2", title: "Live one", status: "active", updated_at: "2026-08-10T10:00:00Z" },
      ],
    });
    render(<SettingsSectionPane section="archived" />);
    await waitFor(() => {
      expect(screen.getByText("Enable maax in Codex")).toBeTruthy();
    });
    expect(screen.getByText("All chats · 1 chat")).toBeTruthy();
    expect(screen.getByText(/\d+ Aug/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Bring back" })).toBeTruthy();
    // The date is honestly labelled as activity, not archive time.
    expect(screen.getByText(/last activity, not the moment of archiving/)).toBeTruthy();
    expect(screen.queryByText("Live one")).toBeNull();
  });

  it("hides tech identifiers until the persisted Developer-details switch is on", async () => {
    render(<SettingsSectionPane section="autonomy" />);
    await waitFor(() => {
      expect(screen.getByText("Every consequential verb asks first")).toBeTruthy();
    });
    // The blob has no developer_details flag, so no monospace chip renders.
    expect(screen.queryByText("hitl")).toBeNull();
  });

  it("answers a settings query with grouped rows across every section", () => {
    const onOpenSection = vi.fn();
    render(<SettingsSearchResults onOpenSection={onOpenSection} query="two-factor" />);
    expect(screen.getByText("Two-factor authentication")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Two-factor authentication/ }));
    expect(onOpenSection).toHaveBeenCalledWith("you");

    cleanup();
    render(<SettingsSearchResults onOpenSection={vi.fn()} query="qqqqqq" />);
    expect(screen.getByText(/Nothing matches that/)).toBeTruthy();
  });
});
