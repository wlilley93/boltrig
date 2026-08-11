// @vitest-environment happy-dom

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  deleteMyConversation: vi.fn(),
  readiness: vi.fn(),
  restoreMyConversation: vi.fn(),
  searchConversations: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { Sidebar } from "../src/components/Shell";
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
  localStorage.removeItem("boltrig-worker-pinned-conversations");
  vi.clearAllMocks();
});

describe("console sidebar", () => {
  it("scopes the Codex glass/density override to Chat and New chat", () => {
    const chat = renderSidebar();
    expect(chat.container.querySelector(".sidebar")?.classList.contains("shell-parity"))
      .toBe(true);
    chat.unmount();
    const agents = renderSidebar(vi.fn(), vi.fn(), "agents");
    expect(agents.container.querySelector(".sidebar")?.classList.contains("shell-parity"))
      .toBe(false);
  });

  it("keeps conversation search on Chat and cancels it when another route opens", async () => {
    api.searchConversations.mockResolvedValue({ results: [] });
    const onRoute = vi.fn();
    const onSettingsSection = vi.fn();
    const view = renderSidebar(onRoute, onSettingsSection, "chat");
    fireEvent.change(screen.getByRole("textbox", { name: "Search conversations" }), {
      target: { value: "renewal" },
    });

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

    expect(screen.queryByRole("textbox", { name: "Search conversations" })).toBeNull();
    await new Promise((resolve) => window.setTimeout(resolve, 300));
    expect(api.searchConversations).not.toHaveBeenCalled();
  });

  it.each<WorkerRoute>(["agents", "integrations", "automations"])(
    "does not render conversation search on %s",
    (route) => {
      renderSidebar(vi.fn(), vi.fn(), route);
      expect(screen.queryByRole("textbox", { name: "Search conversations" })).toBeNull();
    },
  );

  it("maps the console nav onto the real Worker routes", () => {
    api.readiness.mockResolvedValue({ status: "ready", checks: {} });
    const { onRoute } = renderSidebar();

    // The decided target's sidebar carries four surfaces and no second group.
    const expectations: Array<[string, WorkerRoute]> = [
      ["New chat", "chat"],
      ["Agents", "agents"],
      ["Plugins", "integrations"],
      ["Routines", "automations"],
    ];
    for (const [label, route] of expectations) {
      fireEvent.click(screen.getByRole("button", { name: label }));
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
    expect(screen.getByText("›").getAttribute("aria-hidden")).not.toBeNull();
    expect(screen.getByText("⌘,").getAttribute("aria-hidden")).not.toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Home" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Open Operator" })).toBeNull();
  });

  it("uses truthful workspace and help destinations", () => {
    api.readiness.mockResolvedValue({ status: "ready", checks: {} });
    const { onRoute, onSettingsSection } = renderSidebar();

    fireEvent.click(screen.getByTitle("Open organisation and workspace administration"));
    expect(onRoute).toHaveBeenLastCalledWith("organisation");

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
    expect(navigation.querySelectorAll("button")).toHaveLength(10);
    expect(container.querySelectorAll(".settings-side-head")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Archived chats" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Account menu/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Help and shortcuts" })).toBeNull();
    expect(screen.getByText("Every setting is one search away. Nothing is hidden, only quiet."))
      .toBeTruthy();
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
    expect(container.querySelector(".shell-recent-meta")).toBeTruthy();
    expect(container.querySelector(".session-row.active .session-actions")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Pin Integrate EMEET Pixy with Boltrig" }));
    expect(screen.getByRole("button", { name: "Unpin Integrate EMEET Pixy with Boltrig" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Archive Integrate EMEET Pixy with Boltrig" }));
    await waitFor(() => expect(api.deleteMyConversation).toHaveBeenCalledWith("pixy"));
  });

  it("keeps the rail glassy and recent rows bounded without hiding actions", () => {
    expect(shellParityCss).toContain(".sidebar.shell-parity");
    expect(shellParityCss).toMatch(/\.sidebar\.shell-parity\s*\{[\s\S]*?border-right:\s*0/);
    expect(shellParityCss).toContain("color-mix(in srgb, var(--side) 82%, transparent)");
    expect(shellParityCss).toContain("backdrop-filter: blur(22px)");
    expect(shellParityCss).toContain(".shell-parity .session-row {");
    expect(shellParityCss).toContain("max-height: 44px");
    expect(shellParityCss).toContain(".shell-parity .session-row.active .session-main");
    expect(shellParityCss).toMatch(/time\.shell-recent-meta\s*\{[\s\S]*?display:\s*inline/);
    expect(shellParityCss).toMatch(/session-row\.active \.session-actions\s*\{[\s\S]*?opacity:\s*1/);
    expect(shellParityCss).toContain(".shell-parity .session-row:hover .session-actions");
    expect(workerStylesCss).toMatch(/\.conversation-search\s*\{[\s\S]*?height:\s*31px/);
    expect(workerStylesCss).toMatch(/\.conversation-search\s*\{[\s\S]*?position:\s*static/);
    expect(shellParityCss).toMatch(/\.shell-parity \.conversation-search\s*\{[\s\S]*?border-color:\s*#262626/);
    expect(shellParityCss).toMatch(/\.shell-parity \.conversation-search\s*\{[\s\S]*?background:\s*#171717/);
    expect(shellParityCss).toMatch(/\.shell-parity \.session-actions\s*\{[\s\S]*?right:\s*12px/);
    expect(shellParityCss).toMatch(/\.shell-parity \.session-actions\s*\{[\s\S]*?background:\s*transparent/);
    expect(shellParityCss).toMatch(/\.shell-parity \.session-row\.pinned \.session-main,[\s\S]*?padding-right:\s*61px/);
  });

  it("computes a 31px search, 44px selected row, visible time and compact ordinary row", () => {
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

    const search = screen.getByRole("textbox", { name: "Search conversations" });
    expect(getComputedStyle(search).position).toBe("static");
    expect(getComputedStyle(search).height).toBe("31px");
    expect(getComputedStyle(search).marginBottom).toBe("7px");

    const selected = screen.getByText("Selected renewal").closest(".session-row")!;
    const ordinary = screen.getByText("Ordinary renewal").closest(".session-row")!;
    const pinned = screen.getByText("Pinned renewal").closest(".session-row")!;
    expect(getComputedStyle(selected).height).toBe("44px");
    expect(getComputedStyle(selected.querySelector(".session-main")!).height).toBe("44px");
    expect(getComputedStyle(selected.querySelector(".session-actions")!).opacity).toBe("1");
    expect(getComputedStyle(selected.querySelector(".shell-recent-meta")!).display).toBe("inline");
    expect(getComputedStyle(ordinary.querySelector(".session-main")!).height).toBe("31px");
    expect(getComputedStyle(ordinary.querySelector(".session-actions")!).opacity).toBe("0");
    expect(getComputedStyle(pinned.querySelector(".session-main")!).paddingRight).toBe("61px");
    expect(getComputedStyle(pinned.querySelector(".session-actions")!).opacity).toBe("1");
    expect(ordinary.querySelector("time")?.getAttribute("datetime"))
      .toBe("2026-08-11T08:00:00Z");
  });
});
