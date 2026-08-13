import { useCallback, useEffect, useState } from "react";

import {
  conversationFromHash,
  navigate,
  routeFromHash,
  selectionFromHash,
  type WorkerRoute,
} from "../../routes";
import { isSettingsSection, type SettingsSection } from "../../settingsSections";
import { globalShortcutFor } from "../../shortcuts";

interface AppNavigationOptions {
  closeNavigation: () => void;
  refreshConversations: () => void;
}

export function useAppNavigation(options: AppNavigationOptions) {
  const [route, setRoute] = useState<WorkerRoute>(() => routeFromHash(window.location.hash));
  const [selectedConversation, setSelectedConversation] = useState<string | null>(
    () => conversationFromHash(window.location.hash),
  );
  const [settingsSection, setSettingsSection] = useState<SettingsSection>(settingsSectionFromHash);
  const [settingsQuery, setSettingsQuery] = useState("");

  useEffect(() => {
    if (route !== "settings") setSettingsQuery("");
  }, [route]);
  useEffect(() => mountHashNavigation({
    options,
    setRoute,
    setSelectedConversation,
    setSettingsSection,
  }), [options.refreshConversations]);

  const chooseDestination = useCallback((next: WorkerRoute, routeId: string | null) => {
    const boundedId = routeId && routeId.length <= 256 ? routeId : null;
    if (next === "settings" && boundedId && isSettingsSection(boundedId)) {
      setSettingsSection(boundedId);
    }
    navigate(next, boundedId);
    setRoute(next);
    options.closeNavigation();
    setSelectedConversation(next === "chat" ? boundedId : null);
  }, [options.closeNavigation]);
  const chooseRoute = useCallback((next: WorkerRoute) => {
    chooseDestination(next, null);
  }, [chooseDestination]);
  const chooseConversation = useCallback((id: string) => {
    chooseDestination("chat", id);
  }, [chooseDestination]);

  return {
    chooseConversation,
    chooseDestination,
    chooseRoute,
    route,
    selectedConversation,
    setSettingsQuery,
    setSettingsSection,
    settingsQuery,
    settingsSection,
  };
}

interface HashNavigationContext {
  options: AppNavigationOptions;
  setRoute: React.Dispatch<React.SetStateAction<WorkerRoute>>;
  setSelectedConversation: React.Dispatch<React.SetStateAction<string | null>>;
  setSettingsSection: React.Dispatch<React.SetStateAction<SettingsSection>>;
}

function mountHashNavigation(context: HashNavigationContext) {
  context.options.refreshConversations();
  const onHash = () => {
    const next = routeFromHash(window.location.hash);
    context.setRoute(next);
    context.setSelectedConversation(next === "chat" ? conversationFromHash(window.location.hash) : null);
    const section = selectionFromHash(window.location.hash, "settings");
    if (next === "settings" && section && isSettingsSection(section)) {
      context.setSettingsSection(section);
    }
  };
  window.addEventListener("hashchange", onHash);
  return () => window.removeEventListener("hashchange", onHash);
}

export function useCommandPalette(
  closeNavigation: () => void,
  chooseDestination: (route: WorkerRoute, id: string | null) => void,
) {
  const [open, setOpen] = useState(false);
  const openPalette = useCallback(() => {
    closeNavigation();
    setOpen(true);
  }, [closeNavigation]);
  const closePalette = useCallback(() => setOpen(false), []);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const hit = globalShortcutFor(event);
      if (!hit) return;
      event.preventDefault();
      if (hit.id === "command-palette") {
        closeNavigation();
        setOpen((current) => !current);
      } else if (hit.id === "new-chat") {
        setOpen(false);
        chooseDestination("chat", null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [chooseDestination, closeNavigation]);
  return { closePalette, open, openPalette };
}

function settingsSectionFromHash(): SettingsSection {
  const selection = selectionFromHash(window.location.hash, "settings");
  return selection && isSettingsSection(selection) ? selection : "you";
}
