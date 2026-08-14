// @vitest-environment happy-dom

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  deleteMyConversation: vi.fn(),
  putMeSettings: vi.fn(),
  readiness: vi.fn(),
  restoreMyConversation: vi.fn(),
  searchConversations: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/components/WorkerGlobalContext", () => ({
  useWorkerGlobalContext: () => ({
    identity: {
      user: "Will Lilley",
      role: "org-admin",
      organisation: "acme",
      workspace: "production",
    },
    identityStatus: "ready",
  }),
}));

import { Sidebar } from "../src/components/Shell";
import { SETTINGS_SECTIONS } from "../src/settingsSections";
import type { WorkerRoute } from "../src/routes";

const shellParityCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/components/ShellParity.css"),
  "utf-8",
);
const workerStylesCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/styles.css"),
  "utf-8",
);

function installShellStyles() {
  const style = document.createElement("style");
  style.dataset.testShellStyles = "true";
  style.textContent = `${workerStylesCss}\n${shellParityCss}`;
  document.head.append(style);
}

function renderSidebar(
  onRoute = vi.fn(),
  onSettingsSection = vi.fn(),
  route: WorkerRoute = "chat",
) {
  const view = render(
    <Sidebar
      route={route}
      conversations={[]}
      conversationStatus="ready"
      selectedConversation={null}
      onRoute={onRoute}
      onConversation={vi.fn()}
      onConversationRestored={vi.fn()}
      onLoadMore={vi.fn()}
      hasMoreConversations={false}
      onCommandPalette={vi.fn()}
      onSettingsSection={onSettingsSection}
    />,
  );
  return { ...view, onRoute, onSettingsSection };
}

afterEach(() => {
  cleanup();
  document.querySelectorAll("style[data-test-shell-styles]").forEach((style) => style.remove());
  localStorage.removeItem("boltrig.shell-preferences.v1");
  localStorage.removeItem("boltrig-worker-pinned-conversations");
  localStorage.removeItem("boltrig.character");
  delete document.documentElement.dataset.character;
  vi.clearAllMocks();
});

describe("console sidebar", () => {
  it("keeps shell navigation and task history behind explicit boundaries", () => {
    const chat = renderSidebar();
    expect(chat.container.querySelector(".sidebar")?.classList.contains("shell-parity"))
      .toBe(true);
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    expect(chat.container.querySelector(".shell-task-list")).toBeTruthy();
    chat.unmount();
    const agents = renderSidebar(vi.fn(), vi.fn(), "agents");
    expect(agents.container.querySelector(".sidebar")?.classList.contains("shell-parity"))
      .toBe(true);
  });

  it("uses the top search control without a second recents search or workspace line", () => {
    renderSidebar();
    expect(screen.getByRole("button", { name: "Open command palette" })).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Search conversations" })).toBeNull();
    expect(document.querySelector(".conversation-search")).toBeNull();
    expect(document.querySelector(".side-workspace")).toBeNull();
    expect(screen.queryByText(/acme\s*[·.]\s*production/i)).toBeNull();
    const account = screen.getByRole("button", { name: /Signed in as/i });
    expect(account.getAttribute("aria-label")).not.toMatch(/acme|production/i);
    expect(account.getAttribute("title")).toBeNull();
    expect(api.searchConversations).not.toHaveBeenCalled();
  });

  it("uses the real companion preference as the shell identity", async () => {
    api.putMeSettings.mockResolvedValue({ status: "ok", settings: {} });
    const { container } = renderSidebar();

    const trigger = screen.getByRole("button", { name: "Companion: Familiar" });
    expect(container.querySelector(".side-brand")).toBeNull();
    fireEvent.click(trigger);

    const menu = screen.getByRole("menu", { name: "Companion" });
    const familiar = within(menu).getByRole("menuitemradio", { name: /Familiar/ });
    const jarvis = within(menu).getByRole("menuitemradio", { name: /Jarvis/ });
    expect(familiar.getAttribute("aria-checked")).toBe("true");
    expect(jarvis.getAttribute("aria-checked")).toBe("false");
    expect(within(menu).getByText("A living body with a private inner life of its own."))
      .toBeTruthy();
    expect(within(menu).getByText("An instrument that displays the machine's measured state."))
      .toBeTruthy();

    fireEvent.click(jarvis);
    await waitFor(() => {
      expect(api.putMeSettings).toHaveBeenCalledWith({
        settings: { "agent.character": "jarvis" },
      });
      expect(screen.getByRole("button", { name: "Companion: Jarvis" })).toBeTruthy();
    });
    expect(screen.queryByRole("menu", { name: "Companion" })).toBeNull();
  });

  it("rolls the companion switcher back when the saved preference is refused", async () => {
    api.putMeSettings.mockResolvedValue({ status: "degraded", reason: "Settings unavailable." });
    renderSidebar();

    fireEvent.click(screen.getByRole("button", { name: "Companion: Familiar" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /Jarvis/ }));

    expect((await screen.findByRole("alert")).textContent).toBe("Settings unavailable.");
    expect(screen.getByRole("button", { name: "Companion: Familiar" })).toBeTruthy();
    expect(screen.getByRole("menuitemradio", { name: /Familiar/ }).getAttribute("aria-checked"))
      .toBe("true");
  });

  it("keeps companion selection keyboard-operable and returns to shell order", () => {
    renderSidebar();

    const trigger = screen.getByRole("button", { name: "Companion: Familiar" });
    const search = screen.getByRole("button", { name: "Open command palette" });
    fireEvent.click(trigger);
    const items = screen.getAllByRole("menuitemradio");
    expect(document.activeElement).toBe(items[0]);
    expect(items.every((item) => item.tabIndex === -1)).toBe(true);

    fireEvent.keyDown(items[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[1]);
    fireEvent.keyDown(items[1]!, { key: "Tab" });
    expect(screen.queryByRole("menu", { name: "Companion" })).toBeNull();
    expect(document.activeElement).toBe(search);

    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getAllByRole("menuitemradio")[0]!, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Companion" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("maps the console nav onto the real Worker routes", () => {
    api.readiness.mockResolvedValue({ status: "ready", checks: {} });
    const { onRoute } = renderSidebar();

    // The decided target's sidebar carries four surfaces and no second group.
    const expectations: Array<[string, WorkerRoute, string, number, number]> = [
      ["New chat", "chat", "0 0 20 20", 1, 0],
      ["Agents", "agents", "0 0 20 20", 2, 3],
      ["Plugins", "integrations", "0 0 20 20", 1, 0],
      ["Routines", "automations", "0 0 18 18", 1, 0],
    ];
    for (const [label, route, viewBox, pathCount, circleCount] of expectations) {
      const button = screen.getByRole("button", { name: label });
      const icon = button.querySelector("svg")!;
      expect(icon.getAttribute("viewBox")).toBe(viewBox);
      expect(icon.querySelectorAll("path")).toHaveLength(pathCount);
      expect(icon.querySelectorAll("circle")).toHaveLength(circleCount);
      fireEvent.click(button);
      expect(onRoute).toHaveBeenLastCalledWith(route);
    }
  });

  it("keeps the account menu small and canonical", () => {
    api.readiness.mockResolvedValue({ status: "ready", checks: {} });
    const { onRoute, onSettingsSection } = renderSidebar();

    const expectations: Array<[string, WorkerRoute]> = [
      ["Spend remaining", "settings"],
      ["Invite someone", "organisation"],
      ["Settings", "settings"],
    ];
    for (const [label, route] of expectations) {
      fireEvent.click(screen.getByRole("button", { name: /Account menu/ }));
      fireEvent.click(screen.getByRole("menuitem", { name: label }));
      expect(onRoute).toHaveBeenLastCalledWith(route);
    }
    expect(onSettingsSection).toHaveBeenCalledWith("spend");
    expect(onSettingsSection).toHaveBeenCalledWith("you");
    fireEvent.click(screen.getByRole("button", { name: /Account menu/ }));
    expect(screen.getByRole("menuitem", { name: "Log out" })).toBeTruthy();
    expect(screen.getByText("org-admin")).toBeTruthy();
    expect(screen.getByText("›").getAttribute("aria-hidden")).not.toBeNull();
    expect(screen.getByText("⌘,").getAttribute("aria-hidden")).not.toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Home" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Open Operator" })).toBeNull();
  });

  it("uses truthful help destinations without a redundant workspace shortcut", () => {
    api.readiness.mockResolvedValue({ status: "ready", checks: {} });
    const { onRoute, onSettingsSection } = renderSidebar();

    expect(screen.queryByTitle("Open organisation and workspace administration")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Help and shortcuts" }));
    expect(screen.getByRole("menu", { name: "Help" })).toBeTruthy();
    expect(screen.queryByText("What's new")).toBeNull();
    expect(screen.queryByText("Set up on another machine")).toBeNull();

    fireEvent.click(screen.getByRole("menuitem", { name: "Keyboard shortcuts" }));
    expect(onSettingsSection).toHaveBeenLastCalledWith("shortcuts");
    expect(onRoute).toHaveBeenLastCalledWith("settings");

    fireEvent.click(screen.getByRole("button", { name: "Help and shortcuts" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Health and diagnostics" }));
    expect(onSettingsSection).toHaveBeenLastCalledWith("health");
    expect(onRoute).toHaveBeenLastCalledWith("settings");
  });

  it("moves focus through account and help menus and returns it on Escape", () => {
    renderSidebar();

    const accountTrigger = screen.getByRole("button", { name: /Account menu/ });
    fireEvent.click(accountTrigger);
    const accountItems = screen.getAllByRole("menuitem");
    expect(document.activeElement).toBe(accountItems[0]);

    fireEvent.keyDown(accountItems[0]!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(accountItems.at(-1));
    fireEvent.keyDown(accountItems.at(-1)!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(accountItems[0]);
    fireEvent.keyDown(accountItems[0]!, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Account" })).toBeNull();
    expect(document.activeElement).toBe(accountTrigger);

    const helpTrigger = screen.getByRole("button", { name: "Help and shortcuts" });
    fireEvent.click(helpTrigger);
    const helpItems = screen.getAllByRole("menuitem");
    expect(document.activeElement).toBe(helpItems[0]);

    fireEvent.keyDown(helpItems[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(helpItems[1]);
    fireEvent.keyDown(helpItems[1]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(helpItems[0]);
    fireEvent.keyDown(helpItems[0]!, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Help" })).toBeNull();
    expect(document.activeElement).toBe(helpTrigger);
  });

  it("closes menus on Tab without adding scrims or menuitems to ordinary Tab order", () => {
    renderSidebar();

    const accountTrigger = screen.getByRole("button", { name: /Account menu/ });
    const helpTrigger = screen.getByRole("button", { name: "Help and shortcuts" });
    fireEvent.click(accountTrigger);
    const accountItems = screen.getAllByRole("menuitem");
    expect(accountItems.every((item) => item.tabIndex === -1)).toBe(true);
    expect(screen.getByRole("button", { name: "Close account menu" }).tabIndex).toBe(-1);
    expect(document.activeElement).toBe(accountItems[0]);

    fireEvent.keyDown(accountItems[0]!, { key: "Tab" });
    expect(screen.queryByRole("menu", { name: "Account" })).toBeNull();
    expect(document.activeElement).toBe(helpTrigger);

    fireEvent.click(helpTrigger);
    const helpItems = screen.getAllByRole("menuitem");
    expect(helpItems.every((item) => item.tabIndex === -1)).toBe(true);
    expect(screen.getByRole("button", { name: "Close help menu" }).tabIndex).toBe(-1);
    expect(document.activeElement).toBe(helpItems[0]);

    fireEvent.keyDown(helpItems[0]!, { key: "Tab", shiftKey: true });
    expect(screen.queryByRole("menu", { name: "Help" })).toBeNull();
    expect(document.activeElement).toBe(accountTrigger);
  });

  it("does not carry an overlay menu onto a newly selected route", () => {
    const onRoute = vi.fn();
    const onSettingsSection = vi.fn();
    const view = renderSidebar(onRoute, onSettingsSection, "chat");
    fireEvent.click(screen.getByRole("button", { name: /Account menu/ }));
    expect(screen.getByRole("menu", { name: "Account" })).toBeTruthy();

    view.rerender(
      <Sidebar
        route="agents"
        conversations={[]}
        conversationStatus="ready"
        selectedConversation={null}
        onRoute={onRoute}
        onConversation={vi.fn()}
        onConversationRestored={vi.fn()}
        onLoadMore={vi.fn()}
        hasMoreConversations={false}
        onCommandPalette={vi.fn()}
        onSettingsSection={onSettingsSection}
      />,
    );
    expect(screen.queryByRole("menu", { name: "Account" })).toBeNull();
    const accountTrigger = screen.getByRole("button", { name: /Account menu/ });
    expect(accountTrigger.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(accountTrigger);

    fireEvent.click(screen.getByRole("button", { name: "Help and shortcuts" }));
    expect(screen.getByRole("menu", { name: "Help" })).toBeTruthy();
    view.rerender(
      <Sidebar
        route="integrations"
        conversations={[]}
        conversationStatus="ready"
        selectedConversation={null}
        onRoute={onRoute}
        onConversation={vi.fn()}
        onConversationRestored={vi.fn()}
        onLoadMore={vi.fn()}
        hasMoreConversations={false}
        onCommandPalette={vi.fn()}
        onSettingsSection={onSettingsSection}
      />,
    );
    expect(screen.queryByRole("menu", { name: "Help" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Help and shortcuts" }));
  });

  it("keeps every settings section and group head visible during search", () => {
    api.readiness.mockResolvedValue({ status: "ready", checks: {} });
    const { container } = render(
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
        settingsQuery="health"
        onSettingsQuery={vi.fn()}
        onSettingsSection={vi.fn()}
      />,
    );

    const navigation = screen.getByRole("navigation", { name: "Settings sections" });
    expect(navigation.querySelectorAll("button")).toHaveLength(SETTINGS_SECTIONS.length);
    expect(container.querySelectorAll(".settings-side-head")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Archived chats" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Account menu/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Help and shortcuts" })).toBeNull();
    expect(screen.queryByText("Every setting is one search away. Nothing is hidden, only quiet."))
      .toBeNull();
    expect(container.querySelector(".settings-side-foot")).toBeNull();
  });

  it("omits the readiness/status row and does not poll it from navigation", () => {
    api.readiness.mockResolvedValue({
      status: "not_ready",
      checks: {
        store: { status: "ok" },
        engine: { status: "failed" },
      },
    });
    renderSidebar();

    expect(document.querySelector(".side-status")).toBeNull();
    expect(document.querySelector(".side-status-dot")).toBeNull();
    expect(screen.queryByText(/check.*not ready/i)).toBeNull();
    expect(api.readiness).not.toHaveBeenCalled();
  });

  it("reveals pin and archive actions on a conversation row", async () => {
    api.readiness.mockResolvedValue({ status: "ready", checks: {} });
    api.deleteMyConversation.mockResolvedValue({ status: "ok", conversation_status: "closed" });
    const { container } = render(
      <Sidebar
        route="chat"
        conversations={[{
          id: "pixy",
          title: "Integrate EMEET Pixy with Boltrig",
          status: "active",
          updated_at: "2026-08-10T23:20:00Z",
        }]}
        conversationStatus="ready"
        selectedConversation="pixy"
        onRoute={vi.fn()}
        onConversation={vi.fn()}
        onConversationRestored={vi.fn()}
        onConversationArchived={vi.fn()}
        workingConversationIds={["pixy"]}
        onLoadMore={vi.fn()}
        hasMoreConversations={false}
        onCommandPalette={vi.fn()}
      />,
    );

    expect(screen.getByRole("status", { name: "Working on this chat" })).toBeTruthy();
    expect(container.querySelector(".shell-parity .session-main")?.getAttribute("aria-current"))
      .toBe("page");
    expect(container.querySelector(".shell-recent-meta")).toBeNull();
    expect(container.querySelector(".session-row.active .session-actions")).toBeTruthy();
    const pinButton = screen.getByRole("button", { name: "Pin Integrate EMEET Pixy with Boltrig" });
    const archiveButton = screen.getByRole("button", {
      name: "Archive Integrate EMEET Pixy with Boltrig",
    });
    for (const button of [pinButton, archiveButton]) {
      const icon = button.querySelector("svg")!;
      expect(icon.getAttribute("viewBox")).toBe("0 0 20 20");
      expect(icon.getAttribute("fill")).toBe("currentColor");
      expect(icon.getAttribute("stroke")).toBeNull();
    }
    expect(pinButton.querySelectorAll("path")).toHaveLength(1);
    expect(archiveButton.querySelectorAll("path")).toHaveLength(2);

    fireEvent.click(pinButton);
    expect(screen.getByRole("button", { name: "Unpin Integrate EMEET Pixy with Boltrig" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Archive Integrate EMEET Pixy with Boltrig",
    }));
    await waitFor(() => expect(api.deleteMyConversation).toHaveBeenCalledWith("pixy"));
  });

  it("renders pinned tasks as a distinct group and moves rows between groups", () => {
    localStorage.setItem("boltrig-worker-pinned-conversations", JSON.stringify(["pinned"]));
    render(
      <Sidebar
        route="chat"
        conversations={[
          {
            id: "recent",
            title: "Recent task",
            status: "active",
            updated_at: "2026-08-11T09:00:00Z",
          },
          {
            id: "pinned",
            title: "Pinned task",
            status: "active",
            updated_at: "2026-08-11T08:00:00Z",
          },
        ]}
        conversationStatus="ready"
        selectedConversation={null}
        onRoute={vi.fn()}
        onConversation={vi.fn()}
        onLoadMore={vi.fn()}
        hasMoreConversations={false}
      />,
    );

    const pinnedGroup = screen.getByRole("region", { name: "Pinned" });
    const recentGroup = screen.getByRole("region", { name: "Recents" });
    expect(within(pinnedGroup).getByText("Pinned task")).toBeTruthy();
    expect(within(pinnedGroup).queryByText("Recent task")).toBeNull();
    expect(within(recentGroup).getByText("Recent task")).toBeTruthy();
    expect(within(recentGroup).queryByText("Pinned task")).toBeNull();

    fireEvent.click(within(recentGroup).getByRole("button", { name: "Pin Recent task" }));
    expect(within(screen.getByRole("region", { name: "Pinned" })).getByText("Recent task"))
      .toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Recents" })).queryByText("Recent task"))
      .toBeNull();
  });

  it("keeps the rail glassy and recent rows bounded without redundant chrome", () => {
    expect(shellParityCss).toContain(".sidebar.shell-parity");
    expect(shellParityCss).toMatch(/\.sidebar\.shell-parity\s*\{[\s\S]*?border-right:\s*0/);
    expect(shellParityCss).toContain("--shell-rail-glass: color-mix(in srgb, var(--side) 82%, transparent)");
    expect(shellParityCss).toMatch(/:root\[data-theme="dark"\] \.sidebar\.shell-parity\s*\{[\s\S]*?--shell-rail-glass:\s*rgb\(32 36 29 \/ 96%\)/);
    expect(shellParityCss).toMatch(/prefers-reduced-transparency:[\s\S]*?data-theme="dark"[\s\S]*?background:\s*#20231d/);
    expect(shellParityCss).toContain("backdrop-filter: blur(22px)");
    expect(shellParityCss).toMatch(/\.worker-shell:has\(\.sidebar\.shell-parity\)\s*\{[\s\S]*?grid-template-columns:\s*266px/);
    expect(shellParityCss).toMatch(/\.sidebar\.shell-parity\s*\{[\s\S]*?width:\s*266px/);
    expect(shellParityCss).toMatch(/\.shell-parity \.nav-row\s*\{[\s\S]*?height:\s*32px[\s\S]*?font-size:\s*14px/);
    expect(shellParityCss).toMatch(/\.shell-parity \.nav-row:focus-visible\s*\{[\s\S]*?outline:\s*2px[\s\S]*?outline-offset:\s*-2px/);
    expect(shellParityCss).toMatch(/\.shell-task-list\s*\{[\s\S]*?padding-top:\s*20px/);
    expect(shellParityCss).toMatch(/\.shell-task-group \+ \.shell-task-group\s*\{[\s\S]*?margin-top:\s*20px/);
    expect(shellParityCss).toMatch(/\.shell-task-group-label\s*\{[\s\S]*?font-size:\s*13\.5px/);
    expect(shellParityCss).toContain(".shell-task-group-label");
    expect(shellParityCss).toContain(".shell-task-rows");
    expect(shellParityCss).toContain(".shell-parity .session-row {");
    expect(shellParityCss).toContain("max-height: 31px");
    expect(shellParityCss).toContain(".shell-parity .session-row.active .session-main");
    expect(shellParityCss).toMatch(/time\.shell-recent-meta\s*\{[\s\S]*?display:\s*none/);
    expect(shellParityCss).toMatch(/session-row\.active \.session-actions\s*\{[\s\S]*?opacity:\s*0/);
    expect(shellParityCss).toContain(".shell-parity .session-row:hover .session-actions");
    expect(shellParityCss).toMatch(/\.session-working-indicator\s*\{[\s\S]*?width:\s*12px[\s\S]*?border-top-color:\s*var\(--text-2\)/);
    expect(shellParityCss).toContain("animation: shell-task-working-spin 800ms linear infinite");
    expect(workerStylesCss).not.toContain(".conversation-search");
    expect(workerStylesCss).not.toContain(".side-workspace");
    expect(shellParityCss).not.toContain(".conversation-search");
    expect(shellParityCss).toMatch(/\.shell-parity \.session-actions\s*\{[\s\S]*?right:\s*12px/);
    expect(shellParityCss).toMatch(/\.shell-parity \.session-actions\s*\{[\s\S]*?background:\s*transparent/);
    expect(shellParityCss).toMatch(/\.shell-parity \.session-row:hover \.session-main,[\s\S]*?padding-right:\s*61px/);
  });

  it("keeps selected, pinned and ordinary task rows equally compact at rest", () => {
    installShellStyles();
    localStorage.setItem("boltrig-worker-pinned-conversations", JSON.stringify(["pinned"]));
    render(
      <Sidebar
        route="chat"
        conversations={[
          {
            id: "selected",
            title: "Selected renewal",
            status: "active",
            updated_at: "2026-08-11T09:00:00Z",
          },
          {
            id: "ordinary",
            title: "Ordinary renewal",
            status: "active",
            updated_at: "2026-08-11T08:00:00Z",
          },
          {
            id: "pinned",
            title: "Pinned renewal",
            status: "active",
            updated_at: "2026-08-11T07:00:00Z",
          },
        ]}
        conversationStatus="ready"
        selectedConversation="selected"
        onRoute={vi.fn()}
        onConversation={vi.fn()}
        onConversationRestored={vi.fn()}
        onLoadMore={vi.fn()}
        hasMoreConversations={false}
        onCommandPalette={vi.fn()}
      />,
    );

    const selected = screen.getByText("Selected renewal").closest(".session-row")!;
    const ordinary = screen.getByText("Ordinary renewal").closest(".session-row")!;
    const pinned = screen.getByText("Pinned renewal").closest(".session-row")!;
    expect(getComputedStyle(selected).height).toBe("31px");
    expect(getComputedStyle(selected.querySelector(".session-main")!).height).toBe("31px");
    expect(getComputedStyle(selected.querySelector(".session-actions")!).opacity).toBe("0");
    expect(selected.querySelector(".shell-recent-meta")).toBeNull();
    expect(getComputedStyle(ordinary.querySelector(".session-main")!).height).toBe("31px");
    expect(getComputedStyle(ordinary.querySelector(".session-actions")!).opacity).toBe("0");
    expect(getComputedStyle(pinned.querySelector(".session-main")!).height).toBe("31px");
    expect(getComputedStyle(pinned.querySelector(".session-actions")!).opacity).toBe("0");
    expect(ordinary.querySelector("time")).toBeNull();
  });
});
