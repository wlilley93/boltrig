import { lazy, Suspense } from "react";

import type { SettingsSection } from "../../settingsSections";
import type { WorkerRoute } from "../../routes";
import { hasDesktopRuntime } from "../../desktop";
import type { WorkerIdentity } from "../WorkerGlobalContext";

const ChatView = lazyNamed(() => import("../ChatView"), "ChatView");
const LocalChatView = lazyNamed(() => import("../LocalChatView"), "LocalChatView");
const MobileSettings = lazyNamed(() => import("../MobileSettings"), "MobileSettings");
const SettingsView = lazyNamed(() => import("../Views"), "SettingsView");
const SettingsSearchResults = lazyNamed(
  () => import("../settings/SearchResults"),
  "SettingsSearchResults",
);

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
  switch (props.route) {
    case "chat":
      return hasDesktopRuntime()
        ? <LocalChatView
            conversationId={props.selectedConversation}
            onChanged={props.onChanged}
            onCommandPalette={props.onCommandPalette}
            onConversation={props.onConversation}
            onWorkingChange={props.onWorkingChange}
          />
        : <ChatView
            conversationId={props.selectedConversation}
            onChanged={props.onChanged}
            onCommandPalette={props.onCommandPalette}
            onConversation={props.onConversation}
            onWorkingChange={props.onWorkingChange}
          />;
    case "settings":
      return <SettingsRoute {...props} />;
    case "account":
      return <SettingsView section="you" />;
    default:
      return null;
  }
}

function SettingsRoute(props: AppRouteSurfaceProps) {
  if (props.phone) {
    return (
      <MobileSettings
        initials={mobileInitials(props.identity?.user)}
        onLeave={() => props.onRoute("chat")}
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

function mobileInitials(user?: string): string {
  const parts = (user ?? "").split(/[\s@._-]+/).filter(Boolean).slice(0, 2);
  return parts.map((part) => part[0]!.toUpperCase()).join("") || "—";
}

function lazyNamed<
  Module extends Record<Key, React.ComponentType<any>>,
  Key extends keyof Module,
>(loader: () => Promise<Module>, key: Key) {
  return lazy(async () => ({ default: (await loader())[key] }));
}
