import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import type { ConversationSummary } from "@wlilley93/boltrig-web-sdk";

import { client } from "./client";
import type { SettingsSection } from "./settingsSections";
import { useMediaQuery } from "./useMediaQuery";
import { MobileSettings } from "./components/MobileSettings";
import { MobileToday } from "./components/MobileToday";
import { useWorkerGlobalContext } from "./components/WorkerGlobalContext";

import { ChatView } from "./components/ChatView";
import { CommandPalette } from "./components/CommandPalette";
import { Sidebar } from "./components/Shell";
import { globalShortcutFor } from "./shortcuts";
import {
  conversationFromHash,
  navigate,
  routeFromHash,
  type WorkerRoute,
} from "./routes";

const AgentsView = lazyNamed(() => import("./components/ParityViews"), "AgentsView");
const AutomationsView = lazyNamed(() => import("./components/AutomationView"), "AutomationsView");
const BuildView = lazyNamed(() => import("./components/BuildView"), "BuildView");
const ChannelsView = lazyNamed(() => import("./components/ChannelsView"), "ChannelsView");
const EvaluationsView = lazyNamed(() => import("./components/EvaluationsView"), "EvaluationsView");
const HomeView = lazyNamed(() => import("./components/OperationsView"), "HomeView");
const InboxView = lazyNamed(() => import("./components/Views"), "InboxView");
const IntegrationsView = lazyNamed(() => import("./components/IntegrationsView"), "IntegrationsView");
const KnowledgeView = lazyNamed(() => import("./components/ParityViews"), "KnowledgeView");
const MemoryView = lazyNamed(() => import("./components/ParityViews"), "MemoryView");
const OperateView = lazyNamed(() => import("./components/OperationsView"), "OperateView");
const OrganisationView = lazyNamed(() => import("./components/OrganisationView"), "OrganisationView");
const RunsView = lazyNamed(() => import("./components/ParityViews"), "RunsView");
const SettingsView = lazyNamed(() => import("./components/Views"), "SettingsView");
const SettingsSearchResults = lazyNamed(() => import("./components/SettingsSurface"), "SettingsSearchResults");
const WorkView = lazyNamed(() => import("./components/ParityViews"), "WorkView");

// Two initials from whatever the identity gives us — an email, a handle or a
// name — so the mobile avatar never renders a raw address.
function initialsOf(user?: string): string {
  const parts = (user ?? "").split(/[\s@._-]+/).filter(Boolean).slice(0, 2);
  return parts.map((part) => part[0]!.toUpperCase()).join("") || "—";
}

export function App() {
  const [route, setRoute] = useState<WorkerRoute>(() => routeFromHash(window.location.hash));
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationOffset, setConversationOffset] = useState<number | null>(0);
  const [selectedConversation, setSelectedConversation] = useState<string | null>(
    () => conversationFromHash(window.location.hash),
  );
  const [conversationStatus, setConversationStatus] = useState<
    "loading" | "ready" | "unavailable"
  >("loading");
  const [railOpen, setRailOpen] = useState(false);
  // Which settings section is open. The sidebar and the pane both read it, so
  // it lives above them rather than inside either.
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("you");
  // The settings search query lives here too: the sidebar input feeds it and
  // the page swaps the section pane for row-level results while it is set.
  const [settingsQuery, setSettingsQuery] = useState("");
  useEffect(() => {
    if (route !== "settings") setSettingsQuery("");
  }, [route]);
  const phone = useMediaQuery("(max-width: 640px)");
  const { identity } = useWorkerGlobalContext();
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const mobileMenuRef = useRef<HTMLButtonElement>(null);
  const sidebarWrapRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLElement>(null);

  const refreshConversations = useCallback(() => {
    setConversationStatus("loading");
    void client.conversationsPage(25, 0)
      .then((result) => {
        setConversations(result.conversations);
        setConversationOffset(result.next_offset);
        setConversationStatus("ready");
      })
      .catch(() => {
        setConversationStatus("unavailable");
      });
  }, []);

  const loadMoreConversations = useCallback(() => {
    if (conversationOffset === null) return;
    setConversationStatus("loading");
    void client.conversationsPage(25, conversationOffset)
      .then((result) => {
        setConversations((current) => [
          ...current,
          ...result.conversations.filter(
            (conversation) => !current.some((item) => item.id === conversation.id),
          ),
        ]);
        setConversationOffset(result.next_offset);
        setConversationStatus("ready");
      })
      .catch(() => setConversationStatus("unavailable"));
  }, [conversationOffset]);

  useEffect(() => {
    refreshConversations();
    const onHash = () => {
      const next = routeFromHash(window.location.hash);
      setRoute(next);
      setSelectedConversation(
        next === "chat" ? conversationFromHash(window.location.hash) : null,
      );
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [refreshConversations]);

  useEffect(() => {
    // Global bindings come from the shortcut registry so the Shortcuts
    // screen and the behaviour cannot disagree.
    const onKeyDown = (event: KeyboardEvent) => {
      const hit = globalShortcutFor(event);
      if (!hit) return;
      if (hit.id === "command-palette") {
        event.preventDefault();
        setCommandPaletteOpen((current) => !current);
      }
      // Best effort: browsers may reserve Cmd/Ctrl-N for a new window, but
      // the desktop shell and permissive browsers land on a fresh chat.
      if (hit.id === "new-chat") {
        event.preventDefault();
        // Every other palette navigation closes it; this one must too, or the
        // modal is left open over results for a surface that has moved on.
        setCommandPaletteOpen(false);
        chooseDestination("chat", null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!railOpen) {
      if (surface) {
        surface.inert = false;
        surface.removeAttribute("aria-hidden");
      }
      return;
    }

    if (surface) {
      surface.inert = true;
      surface.setAttribute("aria-hidden", "true");
    }
    const navigation = sidebarWrapRef.current?.querySelector<HTMLElement>(".sidebar");
    const initial = navigation ? focusableElements(navigation)[0] : null;
    initial?.focus();

    const onNavigationKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setRailOpen(false);
        return;
      }
      if (event.key !== "Tab" || !sidebarWrapRef.current) return;
      const focusable = focusableElements(sidebarWrapRef.current);
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (
        document.activeElement === first
        || !sidebarWrapRef.current.contains(document.activeElement)
      )) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (
        document.activeElement === last
        || !sidebarWrapRef.current.contains(document.activeElement)
      )) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onNavigationKeyDown);
    return () => {
      window.removeEventListener("keydown", onNavigationKeyDown);
      if (surface) {
        surface.inert = false;
        surface.removeAttribute("aria-hidden");
      }
      mobileMenuRef.current?.focus();
    };
  }, [railOpen]);

  function chooseRoute(next: WorkerRoute) {
    chooseDestination(next, null);
  }

  function chooseDestination(next: WorkerRoute, routeId: string | null) {
    const boundedId = routeId && routeId.length <= 256 ? routeId : null;
    navigate(next, boundedId);
    setRoute(next);
    setRailOpen(false);
    setSelectedConversation(next === "chat" ? boundedId : null);
  }

  function chooseConversation(id: string) {
    setSelectedConversation(id);
    navigate("chat", id);
    setRoute("chat");
    setRailOpen(false);
  }

  return (
    <div className="worker-shell">
      <button
        aria-controls="worker-navigation"
        aria-expanded={railOpen}
        aria-label="Open navigation"
        className="mobile-menu"
        onClick={() => setRailOpen(true)}
        ref={mobileMenuRef}
        type="button"
      >
        ☰
      </button>
      <div
        className={railOpen ? "sidebar-wrap open" : "sidebar-wrap"}
        id="worker-navigation"
        ref={sidebarWrapRef}
      >
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setRailOpen(false)}
          type="button"
        />
        <Sidebar
          route={route}
          conversations={conversations}
          conversationStatus={conversationStatus}
          selectedConversation={selectedConversation}
          onRoute={chooseRoute}
          onConversation={chooseConversation}
          onConversationRestored={() => refreshConversations()}
          onLoadMore={loadMoreConversations}
          onRetryConversations={refreshConversations}
          hasMoreConversations={conversationOffset !== null}
          onCommandPalette={() => setCommandPaletteOpen(true)}
          onSettingsSection={(section) => {
            setSettingsSection(section);
            setSettingsQuery("");
          }}
          settingsSection={settingsSection}
          settingsQuery={settingsQuery}
          onSettingsQuery={setSettingsQuery}
        />
      </div>
      <section className="surface" ref={surfaceRef}>
        <Suspense fallback={<div className="route-loading" role="status">Loading Worker surface…</div>}>
        {/* Today is the phone's home. It lives on the `home` route rather than
            standing in for an empty chat, so the conversation surface — and the
            task-details trigger that must survive a breakpoint flip — stays
            exactly where it was at every width. */}
        {route === "home" && (phone
          ? (
            <MobileToday
              initials={initialsOf(identity?.user)}
              onNewChat={() => chooseRoute("chat")}
              onOpenConversation={chooseConversation}
              onSettings={() => chooseRoute("settings")}
              workspace={identity ? `${identity.organisation} · ${identity.workspace}` : ""}
            />
          )
          : <HomeView onRoute={chooseRoute} />)}
        {route === "chat" && (
          <ChatView
            conversationId={selectedConversation}
            onConversation={chooseConversation}
            onChanged={refreshConversations}
          />
        )}
        {route === "inbox" && <InboxView />}
        {route === "automations" && <AutomationsView />}
        {route === "channels" && <ChannelsView />}
        {route === "build" && <BuildView />}
        {route === "evaluations" && <EvaluationsView />}
        {route === "integrations" && <IntegrationsView />}
        {route === "operate" && <OperateView />}
        {route === "organisation" && <OrganisationView />}
        {route === "settings" && (phone
          ? (
            <MobileSettings
              initials={initialsOf(identity?.user)}
              onLeave={() => chooseRoute("home")}
              role={identity?.role ?? ""}
              user={identity?.user ?? ""}
            />
          )
          : settingsQuery.trim()
            ? (
              <div className="page">
                <div className="page-content narrow">
                  <SettingsSearchResults
                    onOpenSection={(section) => {
                      setSettingsSection(section);
                      setSettingsQuery("");
                    }}
                    query={settingsQuery}
                  />
                </div>
              </div>
            )
            : <SettingsView section={settingsSection} />)}
        {route === "account" && <SettingsView section="you" />}
        {route === "runs" && <RunsView />}
        {route === "work" && <WorkView />}
        {route === "agents" && <AgentsView />}
        {route === "knowledge" && <KnowledgeView />}
        {route === "memory" && <MemoryView />}
        </Suspense>
      </section>
      <CommandPalette
        open={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={chooseDestination}
      />
    </div>
  );
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(
    'input, button:not([disabled]), a[href], select, textarea, [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.hasAttribute("hidden"));
}

function lazyNamed<
  Module extends Record<Key, React.ComponentType<any>>,
  Key extends keyof Module,
>(loader: () => Promise<Module>, key: Key) {
  return lazy(async () => ({ default: (await loader())[key] }));
}
