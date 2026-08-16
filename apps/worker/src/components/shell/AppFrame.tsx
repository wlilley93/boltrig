import { lazy, Suspense } from "react";

import type { WorkerIdentity } from "../WorkerGlobalContext";
import { Sidebar } from "../Shell";
import { AppRouteSurface } from "./AppRouteSurface";
import type { useAppNavigation, useCommandPalette } from "./useAppNavigation";
import type { useCompactNavigation } from "./useCompactNavigation";
import type { useConversationDirectory } from "./useConversationDirectory";

const CommandPalette = lazyNamed(() => import("../CommandPalette"), "CommandPalette");

interface AppFrameProps {
  directory: ReturnType<typeof useConversationDirectory>;
  identity: WorkerIdentity | null;
  navigation: ReturnType<typeof useAppNavigation>;
  palette: ReturnType<typeof useCommandPalette>;
  phone: boolean;
  rail: ReturnType<typeof useCompactNavigation>;
}

export function AppFrame(props: AppFrameProps) {
  return (
    <div className="worker-shell">
      <NavigationRail {...props} />
      <section className="surface" ref={props.rail.surfaceRef}>
        <AppRouteSurface
          identity={props.identity}
          onChanged={props.directory.refresh}
          onCommandPalette={props.palette.openPalette}
          onConversation={props.navigation.chooseConversation}
          onDestination={props.navigation.chooseDestination}
          onRoute={props.navigation.chooseRoute}
          onSettingsQuery={props.navigation.setSettingsQuery}
          onSettingsSection={props.navigation.setSettingsSection}
          onWorkingChange={props.directory.setWorking}
          phone={props.phone}
          route={props.navigation.route}
          selectedConversation={props.navigation.selectedConversation}
          settingsQuery={props.navigation.settingsQuery}
          settingsSection={props.navigation.settingsSection}
        />
      </section>
      {props.palette.open && (
        <Suspense fallback={null}>
          <CommandPalette
            open
            onClose={props.palette.closePalette}
            onNavigate={props.navigation.chooseDestination}
          />
        </Suspense>
      )}
    </div>
  );
}

function NavigationRail(props: AppFrameProps) {
  const archived = (id: string) => {
    props.directory.remove(id);
    if (props.navigation.selectedConversation === id) {
      props.navigation.chooseDestination("chat", null);
    }
  };
  return <>
    <button
      aria-controls="worker-navigation"
      aria-expanded={props.rail.railOpen}
      aria-label="Open navigation"
      className="mobile-menu"
      onClick={props.rail.openNavigation}
      ref={props.rail.mobileMenuRef}
      type="button"
    >☰</button>
    <div
      className={props.rail.railOpen ? "sidebar-wrap open" : "sidebar-wrap"}
      id="worker-navigation"
      ref={props.rail.sidebarWrapRef}
    >
      <button className="sidebar-scrim" aria-label="Close navigation"
        onClick={props.rail.closeNavigation} type="button" />
      <Sidebar
        route={props.navigation.route}
        conversations={props.directory.conversations}
        conversationStatus={props.directory.conversationStatus}
        selectedConversation={props.navigation.selectedConversation}
        onRoute={props.navigation.chooseRoute}
        onConversation={props.navigation.chooseConversation}
        onConversationRestored={props.directory.refresh}
        workingConversationIds={props.directory.workingConversationIds}
        onConversationArchived={archived}
        onLoadMore={props.directory.loadMore}
        onRetryConversations={props.directory.refresh}
        hasMoreConversations={props.directory.hasMore}
        onCommandPalette={props.palette.openPalette}
        onSettingsSection={(section) => {
          props.navigation.chooseDestination("settings", section);
          props.navigation.setSettingsQuery("");
        }}
        settingsSection={props.navigation.settingsSection}
        settingsQuery={props.navigation.settingsQuery}
        onSettingsQuery={props.navigation.setSettingsQuery}
      />
    </div>
  </>;
}

function lazyNamed<
  Module extends Record<Key, React.ComponentType<any>>,
  Key extends keyof Module,
>(loader: () => Promise<Module>, key: Key) {
  return lazy(async () => ({ default: (await loader())[key] }));
}
