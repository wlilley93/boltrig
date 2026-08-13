// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  approvalPosture: vi.fn(),
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
  meNotifications: vi.fn(),
  putMeSettings: vi.fn(),
  putApprovalPosture: vi.fn(),
  knowledgeProviders: vi.fn(),
  setKnowledgeProvider: vi.fn(),
  invokeApprovalState: vi.fn(),
}));
const desktop = vi.hoisted(() => ({ runtime: false }));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/desktop", async (importOriginal) => ({
  ...await importOriginal<typeof import("../src/desktop")>(),
  hasDesktopRuntime: () => desktop.runtime,
}));

import { Sidebar } from "../src/components/Shell";
import { SettingsSearchResults, SettingsSectionPane } from "../src/components/SettingsSurface";
import { registerCharacter } from "../src/components/characters";
import { loadLocalConversation, saveLocalConversation } from "../src/localAgentClient";
import { SETTINGS_SECTIONS } from "../src/settingsSections";
import { SHORTCUTS } from "../src/shortcuts";

beforeEach(() => {
  desktop.runtime = false;
  api.approvalPosture.mockResolvedValue({
    posture: "risk_based",
    source: "safe_default",
    enforcement: {
      applies_to: "delegated_agent_adapter_calls",
      workspace_blocking_verbs_remain: true,
      control_plane_approvals_remain: true,
      direct_human_consequence_gate_remains: true,
      authority_is_never_widened: true,
    },
  });
  api.readiness.mockResolvedValue({ status: "ready", checks: {} });
  api.health.mockResolvedValue({ status: "ok", adapters: {} });
  api.hitl.mockResolvedValue({ requests: [] });
  api.budgets.mockResolvedValue({ budgets: [], scope: "all" });
  api.cost.mockResolvedValue({ total_cost_micros: 0, by_actor: {}, scope: "all" });
  api.conversations.mockResolvedValue({ conversations: [] });
  api.auditSearch.mockResolvedValue({ results: [], scope: "all", limit: 50, offset: 0, next_offset: null });
  api.meSettings.mockResolvedValue({
    profile: { id: "u", email: "will@acme.co", role: "org-admin" },
    settings: {
      theme: "system",
      density: "comfortable",
      font_scale: "1",
      "a11y.reduced_motion": false,
      "a11y.high_contrast": false,
    },
  });
  api.meNotifications.mockResolvedValue({
    prefs: [{
      id: "notification-1",
      event_type: "approval",
      channel: "slack",
      target: "ops",
      enabled: true,
      deliverable: true,
    }],
    catalogue: {
      events: [
        { id: "approval", label: "Approvals", description: "Needs you" },
        { id: "escalation", label: "Escalations", description: "Needs authority" },
        { id: "work_status", label: "Work status", description: "Lane changes" },
      ],
      transports: [{
        id: "slack",
        platform: "slack",
        label: "Slack",
        delivery_mode: "durable_outbox",
        targets: [{ id: "ops", label: "Ops" }],
      }],
    },
  });
  api.putMeSettings.mockResolvedValue({ status: "ok" });
  api.putApprovalPosture.mockResolvedValue({
    status: "ok",
    posture: "full_access",
    source: "user_override",
    enforcement: {
      applies_to: "delegated_agent_adapter_calls",
      workspace_blocking_verbs_remain: true,
      control_plane_approvals_remain: true,
      direct_human_consequence_gate_remains: true,
      authority_is_never_widened: true,
    },
  });
  api.knowledgeProviders.mockResolvedValue({ providers: [] });
  api.setKnowledgeProvider.mockResolvedValue({ status: "ok" });
  api.invokeApprovalState.mockResolvedValue({ status: "pending" });
  localStorage.clear();
  document.documentElement.classList.remove("reduce-motion");
  document.documentElement.style.removeProperty("--font-scale");
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.themePreference;
  delete document.documentElement.dataset.character;
  delete document.documentElement.dataset.density;
  delete document.documentElement.dataset.contrast;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
});

describe("settings surface", () => {
  it("replaces the app nav with every canonical settings section while settings is open", () => {
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

    expect(SETTINGS_SECTIONS.length).toBe(12);
    for (const entry of SETTINGS_SECTIONS) {
      expect(screen.getByRole("button", { name: entry.label })).toBeTruthy();
    }
    // The global nav is gone while settings is open, and the way back is named.
    expect(screen.queryByRole("button", { name: "Routines" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Operations" })).toBeNull();
    expect(screen.getByRole("button", { name: "Back to app" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Health" }));
    expect(onSettingsSection).toHaveBeenCalledWith("health");
  });

  it("searches every setting while leaving the full settings navigation visible", () => {
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
    expect(screen.getByRole("button", { name: "Spending" })).toBeTruthy();
  });

  it("applies and persists every supported appearance axis from the target Look group", async () => {
    render(<SettingsSectionPane section="you" />);

    await screen.findByText("Look");
    const pane = document.querySelector(".settings-you-pane") as HTMLElement;
    const groups = Array.from(pane.children).filter((child) => (
      child.classList.contains("settings-group")
    ));
    expect(pane.firstElementChild?.classList.contains("settings-head")).toBe(true);
    expect(groups.map((group) => group.querySelector(".console-section-title")?.textContent))
      .toEqual(["Look", "Reaching you", "Talking to it", "You"]);

    const themeRow = screen.getByText("Theme").closest(".settings-row") as HTMLElement;
    expect(within(themeRow).getAllByRole("button").map((button) => button.textContent))
      .toEqual(["System", "Dark", "Light"]);
    expect(screen.getByText("Density")).toBeTruthy();
    expect(screen.getByText("Text size")).toBeTruthy();
    expect(screen.queryByText("Companion")).toBeNull();
    const lookGroup = groups[0] as HTMLElement;
    expect(within(lookGroup).getByRole("button", { name: /3 more, for when you need them/ }))
      .toBeTruthy();

    fireEvent.click(within(themeRow).getByRole("button", { name: "Dark" }));
    await waitFor(() => expect(api.putMeSettings).toHaveBeenCalledWith({
      settings: {
        theme: "dark",
        density: "comfortable",
        font_scale: "1",
        "a11y.reduced_motion": false,
        "a11y.high_contrast": false,
        // Character is saved independently so this appearance write cannot
        // overwrite the selected Stage body.
      },
    }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(JSON.parse(localStorage.getItem("boltrig.appearance") ?? "{}").theme).toBe("dark");

    fireEvent.click(screen.getAllByRole("button", { name: /3 more, for when you need them/ })[0]);
    const reducedMotion = screen.getByRole("switch", { name: "Reduced motion" });
    fireEvent.click(reducedMotion);
    await waitFor(() => expect(document.documentElement.classList.contains("reduce-motion"))
      .toBe(true));
    expect(document.documentElement.style.getPropertyValue("--font-scale")).toBe("1");
  });

  it("reads real delivery routes and marks unsupported reach and voice controls unavailable", async () => {
    render(<SettingsSectionPane section="you" />);

    await screen.findByText("Reaching you");
    const approval = screen.getByRole("switch", { name: "When something needs approving" });
    await waitFor(() => expect(approval.getAttribute("aria-checked")).toBe("true"));
    expect((approval as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect(
      (screen.getByLabelText("Send approval notifications to") as HTMLSelectElement).value,
    ).toBe("Slack · Ops"));
    expect(screen.getByText("Quiet hours are not available.")).toBeTruthy();

    const takeCalls = screen.getByRole("switch", { name: "Take calls" });
    const holdAtGate = screen.getByRole("switch", { name: "Hold the line at a gate" });
    expect(takeCalls.getAttribute("aria-checked")).toBe("false");
    expect((takeCalls as HTMLButtonElement).disabled).toBe(true);
    expect(holdAtGate.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText(/Calls wait for approval/)).toBeTruthy();
  });

  it("renders a searched Theme as the live control under Results", async () => {
    render(<SettingsSearchResults query="theme" onOpenSection={vi.fn()} />);

    expect(screen.getByRole("heading", { level: 1, name: "Results" })).toBeTruthy();
    await screen.findByText("Look");
    expect(document.querySelector(".settings-result-row")).toBeNull();
    const themeRow = screen.getByText("Theme").closest(".settings-row") as HTMLElement;
    fireEvent.click(within(themeRow).getByRole("button", { name: "Light" }));
    await waitFor(() => expect(api.putMeSettings).toHaveBeenCalledWith({
      settings: expect.objectContaining({ theme: "light" }),
    }));
  });

  it("finds and saves Companion through its independent character key", async () => {
    render(<SettingsSearchResults query="agent.character" onOpenSection={vi.fn()} />);

    await screen.findByText("Look");
    const companionRow = screen.getByText("Companion").closest(".settings-row") as HTMLElement;
    expect(within(companionRow).getByText(/visualises measured runtime state/i)).toBeTruthy();
    fireEvent.click(within(companionRow).getByRole("button", { name: "Jarvis" }));

    await waitFor(() => expect(api.putMeSettings).toHaveBeenCalledWith({
      settings: { "agent.character": "jarvis" },
    }));
    expect(document.documentElement.dataset.character).toBe("jarvis");
    expect(localStorage.getItem("boltrig.character")).toBe("jarvis");
  });

  it("updates Companion choices when a validated plugin registers after Settings mounts", async () => {
    render(<SettingsSearchResults query="agent.character" onOpenSection={vi.fn()} />);

    await screen.findByText("Companion");
    expect(screen.queryByRole("button", { name: "Late Character" })).toBeNull();
    act(() => registerCharacter({
      id: "late-character",
      name: "Late Character",
      readsPhenotype: false,
      blurb: "Registered after the settings surface mounted.",
      render: () => null,
    }));

    fireEvent.click(await screen.findByRole("button", { name: "Late Character" }));
    await waitFor(() => expect(api.putMeSettings).toHaveBeenCalledWith({
      settings: { "agent.character": "late-character" },
    }));
    expect(document.documentElement.dataset.character).toBe("late-character");
  });

  it("keeps unavailable Knowledge providers visible but not actionable", async () => {
    api.knowledgeProviders.mockResolvedValue({
      providers: [{
        id: "supermemory",
        display_name: "Supermemory",
        role: "managed_context",
        enabled: false,
        bundled: false,
        health: "unavailable",
        status: "unavailable",
        last_error: "Credential-backed projection adapter is not implemented in this build.",
      }],
    });

    render(<SettingsSectionPane section="knowledge" />);

    const providerSwitch = await screen.findByRole("switch", { name: "Enable Supermemory" });
    expect((providerSwitch as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText(/Credential-backed projection adapter is not implemented/)).toBeNull();
    expect(screen.getByText("managed_context")).toBeTruthy();
    expect(api.setKnowledgeProvider).not.toHaveBeenCalled();
  });

  it("replays only the exact approved Knowledge provider change from Settings", async () => {
    const disabledProvider = {
      id: "cognee",
      display_name: "Cognee",
      role: "graph",
      enabled: false,
      bundled: true,
      health: "unknown",
      status: "available",
    };
    api.knowledgeProviders
      .mockResolvedValueOnce({ providers: [disabledProvider] })
      .mockResolvedValueOnce({
        providers: [{ ...disabledProvider, enabled: true, status: "enabled" }],
      });
    api.setKnowledgeProvider
      .mockResolvedValueOnce({
        status: "pending_human",
        hitl_request_id: "approval-provider",
      })
      .mockResolvedValueOnce({
        status: "ok",
        provider: { ...disabledProvider, enabled: true, status: "enabled" },
      });
    api.invokeApprovalState.mockResolvedValue({ status: "approved" });

    render(<SettingsSectionPane section="knowledge" />);
    fireEvent.click(await screen.findByRole("switch", { name: "Enable Cognee" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Check approval and apply exact change",
    }));

    await waitFor(() => expect(api.setKnowledgeProvider).toHaveBeenLastCalledWith(
      "cognee",
      true,
      "approval-provider",
    ));
    expect(await screen.findByText("Provider enabled.")).toBeTruthy();
  });

  it("keeps the last reported Knowledge state when a provider mutation fails", async () => {
    api.knowledgeProviders.mockResolvedValue({
      providers: [{
        id: "cognee",
        display_name: "Cognee",
        role: "graph",
        enabled: false,
        bundled: true,
        health: "unknown",
        status: "available",
      }],
    });
    api.setKnowledgeProvider.mockRejectedValue(new Error("network unavailable"));

    render(<SettingsSectionPane section="knowledge" />);
    const providerSwitch = await screen.findByRole("switch", { name: "Enable Cognee" });
    fireEvent.click(providerSwitch);

    expect(await screen.findByText(/Cognee could not be changed/)).toBeTruthy();
    expect(screen.getByText(/last reported state is unchanged/)).toBeTruthy();
    expect(providerSwitch.getAttribute("aria-checked")).toBe("false");
    expect(api.knowledgeProviders).toHaveBeenCalledTimes(1);
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
        codex_runtime: {
          status: "test_only",
          required: false,
          reason: "production_gate_closed",
        },
        hitl_expiry_janitor: {
          status: "unknown",
          required: false,
          reason: "attempt_evidence_not_observed",
        },
        future_service_probe: {
          status: "failed",
          required: false,
          reason: "internal_reason_token",
        },
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
    expect(screen.getByText("1 of 6")).toBeTruthy();
    expect(screen.getByText("Cloud agent runtime")).toBeTruthy();
    expect(screen.getByText("development only")).toBeTruthy();
    expect(screen.getByText("Expired decisions")).toBeTruthy();
    expect(screen.getByText("not observed")).toBeTruthy();
    expect(screen.getByText("Future Service Probe")).toBeTruthy();
    expect(screen.getByText("Optional service check")).toBeTruthy();
    expect(screen.queryByText("production_gate_closed")).toBeNull();
    expect(screen.queryByText("attempt_evidence_not_observed")).toBeNull();
    expect(screen.queryByText("internal_reason_token")).toBeNull();
    // Adapter health from /healthz joins the same card.
    const jiraRow = screen.getByText("jira adapter").closest(".settings-tone-row") as HTMLElement;
    expect(jiraRow).toBeTruthy();
    expect(within(jiraRow).getByText("struggling").getAttribute("data-tone")).toBe("amber");
    // Every boundary listed is a limit of THIS build.
    expect(screen.getByText("Current limits")).toBeTruthy();
    expect(screen.getByText("Weekly spending windows")).toBeTruthy();
  });

  it("says no ceiling is set rather than implying spend is bounded", async () => {
    render(<SettingsSectionPane section="spend" />);
    await waitFor(() => {
      expect(screen.getByText("No ceiling is set")).toBeTruthy();
    });
    expect(screen.getByText(/Nothing stops spend/)).toBeTruthy();
  });

  it("does not render implementation commentary in Autonomy", async () => {
    render(<SettingsSectionPane section="autonomy" />);

    await screen.findByText("What stops a run");
    expect(screen.getByText("Agent tool approvals")).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Approve for me/ }).getAttribute("aria-checked"))
      .toBe("true");
    expect(screen.queryByText(/decided target|this build has no posture|honest thing to show/i))
      .toBeNull();
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
    expect(screen.getByText("Dates show each chat's last activity.")).toBeTruthy();
    expect(screen.queryByText("Live one")).toBeNull();
  });

  it("restores desktop-local tasks without calling the cloud conversation lifecycle", async () => {
    desktop.runtime = true;
    saveLocalConversation({
      id: "local:thread-settings",
      thread_id: "thread-settings",
      root_id: "root-1",
      title: "Local workspace review",
      status: "closed",
      model: "gpt-5.6-sol",
      messages: [],
      created_at: "2026-08-13T10:00:00.000Z",
      updated_at: "2026-08-13T10:00:00.000Z",
    });

    render(<SettingsSectionPane section="archived" />);
    expect(await screen.findByText("Local workspace review")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Bring back" }));
    await waitFor(() => {
      expect(loadLocalConversation("local:thread-settings")?.status).toBe("active");
    });
    expect(api.restoreMyConversation).not.toHaveBeenCalled();
    expect(screen.queryByText("Local workspace review")).toBeNull();
  });

  it("hides tech identifiers until the persisted Developer-details switch is on", async () => {
    render(<SettingsSectionPane section="autonomy" />);
    await waitFor(() => {
      expect(screen.getByText("Agent tool approvals")).toBeTruthy();
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
