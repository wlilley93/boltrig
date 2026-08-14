import { lazy, Suspense } from "react";

import type { SettingsSection } from "../../settingsSections";
import type { WorkerRoute } from "../../routes";
import { hasDesktopRuntime } from "../../desktop";
import { MobileToday } from "../MobileToday";
import type { WorkerIdentity } from "../WorkerGlobalContext";

const AgentsView = lazyNamed(() => import("../ParityViews"), "AgentsView");
const ChatView = lazyNamed(() => import("../ChatView"), "ChatView");
const LocalChatView = lazyNamed(() => import("../LocalChatView"), "LocalChatView");
const AutomationsView = lazyNamed(() => import("../AutomationView"), "AutomationsView");
const BuildView = lazyNamed(() => import("../BuildView"), "BuildView");
const ChannelsView = lazyNamed(() => import("../ChannelsView"), "ChannelsView");
const EvaluationsView = lazyNamed(() => import("../EvaluationsView"), "EvaluationsView");
const HomeView = lazyNamed(() => import("../OperationsView"), "HomeView");
const IntegrationsView = lazyNamed(() => import("../IntegrationsView"), "IntegrationsView");
const KnowledgeView = lazyNamed(() => import("../ParityViews"), "KnowledgeView");
const MemoryView = lazyNamed(() => import("../ParityViews"), "MemoryView");
const MobileSettings = lazyNamed(() => import("../MobileSettings"), "MobileSettings");
const OrganisationView = lazyNamed(() => import("../OrganisationView"), "OrganisationView");
const RunsView = lazyNamed(() => import("../ParityViews"), "RunsView");
const SettingsView = lazyNamed(() => import("../Views"), "SettingsView");
const SettingsSearchResults = lazyNamed(
  () => import("../settings/SearchResults"),
  "SettingsSearchResults",
);
const WorkView = lazyNamed(() => import("../ParityViews"), "WorkView");

interface AppRouteSurfaceProps {
  identity: WorkerIdentity | null;
  onChanged: () => void;
  onCommandPalette: () => void;
  onConversation: (id: string) => void;
  onDestination: (route: WorkerRoute, id: string | null) => void;
  onRoute: (route: WorkerRoute) => void;
  onSettingsSection: (section: SettingsSection) => void;
  onSettingsQuery: (query: string) => void;
  onWorkingChange: (id: string, working: boolean) => void;
  phone: boolean;
  route: WorkerRoute;
  selectedConversation: string | null;
  settingsQuery: string;
  settingsSection: SettingsSection;
}

export function AppRouteSurface(props: AppRouteSurfaceProps) {
  return (
    <Suspense fallback={<div className="route-loading" role="status">Loading Worker surface…</div>}>
      <RouteContent {...props} />
    </Suspense>
  );
}

function RouteContent(props: AppRouteSurfaceProps) {
  if (CORE_ROUTES.has(props.route)) return <CoreRoute {...props} />;
  return <SupportingRoute {...props} />;
}

const CORE_ROUTES = new Set<WorkerRoute>([
  "home", "chat", "automations", "channels", "build", "evaluations", "integrations",
]);

function CoreRoute(props: AppRouteSurfaceProps) {
  switch (props.route) {
    case "home": return <HomeRoute {...props} />;
    case "chat": return hasDesktopRuntime() ? <LocalChatView
      conversationId={props.selectedConversation}
      onCommandPalette={props.onCommandPalette}
      onConversation={props.onConversation}
      onChanged={props.onChanged}
      onWorkingChange={props.onWorkingChange}
    /> : <ChatView
        conversationId={props.selectedConversation}
        onCommandPalette={props.onCommandPalette}
        onConversation={props.onConversation}
        onChanged={props.onChanged}
        onWorkingChange={props.onWorkingChange}
      />;
    case "automations": return <AutomationsView />;
    case "channels": return <ChannelsView />;
    case "build": return <BuildView />;
    case "evaluations": return <EvaluationsView />;
    case "integrations": return <IntegrationsView />;
    default: return null;
  }
}

function SupportingRoute(props: AppRouteSurfaceProps) {
  switch (props.route) {
    case "organisation": return <OrganisationView />;
    case "settings": return <SettingsRoute {...props} />;
    case "account": return <SettingsView section="you" />;
    case "runs": return <RunsView />;
    case "work": return <WorkView />;
    case "agents": return <AgentsView />;
    case "knowledge": return <KnowledgeView />;
    case "memory": return <MemoryView />;
    default: return null;
  }
}

function HomeRoute(props: AppRouteSurfaceProps) {
  if (!props.phone) {
    return <HomeView onRoute={props.onRoute} onSettingsSection={props.onSettingsSection} />;
  }
  return (
    <MobileToday
      initials={initialsOf(props.identity?.user)}
      onNewChat={() => props.onRoute("chat")}
      onOpenConversation={props.onConversation}
      onSettings={() => props.onRoute("settings")}
      workspace={props.identity
        ? `${props.identity.organisation} · ${props.identity.workspace}`
        : ""}
    />
  );
}

function SettingsRoute(props: AppRouteSurfaceProps) {
  if (props.phone) {
    return (
      <MobileSettings
        initials={initialsOf(props.identity?.user)}
        onLeave={() => props.onRoute("home")}
        role={props.identity?.role ?? ""}
        user={props.identity?.user ?? ""}
      />
    );
  }
  if (!props.settingsQuery.trim()) return <SettingsView section={props.settingsSection} />;
  return (
    <div className="page">
      <div className="page-content narrow">
        <SettingsSearchResults
          onOpenSection={(section) => {
            props.onDestination("settings", section);
            props.onSettingsQuery("");
          }}
          query={props.settingsQuery}
        />
      </div>
    </div>
  );
}

function initialsOf(user?: string): string {
  const parts = (user ?? "").split(/[\s@._-]+/).filter(Boolean).slice(0, 2);
  return parts.map((part) => part[0]!.toUpperCase()).join("") || "—";
}

function lazyNamed<
  Module extends Record<Key, React.ComponentType<any>>,
  Key extends keyof Module,
>(loader: () => Promise<Module>, key: Key) {
  return lazy(async () => ({ default: (await loader())[key] }));
}
