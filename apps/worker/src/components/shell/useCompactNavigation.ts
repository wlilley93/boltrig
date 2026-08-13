import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

export function useCompactNavigation(compactNavigation: boolean) {
  const [railOpen, setRailOpen] = useState(false);
  const mobileMenuRef = useRef<HTMLButtonElement>(null);
  const sidebarWrapRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLElement>(null);
  const compactRef = useRef(compactNavigation);
  const previousCompactRef = useRef(compactNavigation);
  compactRef.current = compactNavigation;

  const closeNavigation = useCallback(() => setRailOpen(false), []);
  const openNavigation = useCallback(() => setRailOpen(true), []);

  useEffect(() => {
    const wasCompact = previousCompactRef.current;
    previousCompactRef.current = compactNavigation;
    if (wasCompact === compactNavigation) return;

    const surface = surfaceRef.current;
    const sidebar = sidebarWrapRef.current?.querySelector<HTMLElement>(".sidebar") ?? null;
    const activeElement = document.activeElement;
    if (!compactNavigation) {
      if (surface) revealSurface(surface);
      if (railOpen) closeNavigation();
      if (!sidebar?.contains(activeElement)) {
        const destination = sidebar?.querySelector<HTMLElement>(
          '.session-main[aria-current="page"], .nav-row.active',
        ) ?? (sidebar ? focusableElements(sidebar)[0] ?? null : null);
        destination?.focus();
      }
      return;
    }
    if (!railOpen && sidebarWrapRef.current?.contains(activeElement)) {
      mobileMenuRef.current?.focus();
    }
  }, [closeNavigation, compactNavigation, railOpen]);

  useEffect(() => {
    return mountNavigationModal({
      closeNavigation,
      compactNavigation,
      compactRef,
      mobileMenuRef,
      railOpen,
      sidebarWrapRef,
      surfaceRef,
    });
  }, [closeNavigation, compactNavigation, railOpen]);

  return {
    closeNavigation,
    mobileMenuRef,
    openNavigation,
    railOpen,
    sidebarWrapRef,
    surfaceRef,
  };
}

interface NavigationModalContext {
  closeNavigation: () => void;
  compactNavigation: boolean;
  compactRef: RefObject<boolean>;
  mobileMenuRef: RefObject<HTMLButtonElement | null>;
  railOpen: boolean;
  sidebarWrapRef: RefObject<HTMLDivElement | null>;
  surfaceRef: RefObject<HTMLElement | null>;
}

function mountNavigationModal(context: NavigationModalContext) {
  const surface = context.surfaceRef.current;
  if (!context.railOpen || !context.compactNavigation) {
    if (surface) revealSurface(surface);
    return;
  }
  if (surface) concealSurface(surface);
  const sidebar = context.sidebarWrapRef.current?.querySelector<HTMLElement>(".sidebar") ?? null;
  focusableElements(sidebar)[0]?.focus();
  const onKeyDown = (event: KeyboardEvent) => {
    trapNavigationKey(event, context.sidebarWrapRef.current, context.closeNavigation);
  };
  window.addEventListener("keydown", onKeyDown);
  return () => {
    window.removeEventListener("keydown", onKeyDown);
    if (surface) revealSurface(surface);
    if (context.compactRef.current) context.mobileMenuRef.current?.focus();
  };
}

function trapNavigationKey(
  event: KeyboardEvent,
  navigation: HTMLDivElement | null,
  closeNavigation: () => void,
) {
  if (event.key === "Escape") {
    event.preventDefault();
    closeNavigation();
    return;
  }
  if (event.key !== "Tab" || !navigation) return;
  const destination = tabWrapDestination(event, navigation);
  if (destination === undefined) return;
  event.preventDefault();
  destination?.focus();
}

function tabWrapDestination(
  event: KeyboardEvent,
  navigation: HTMLDivElement,
): HTMLElement | null | undefined {
  const elements = focusableElements(navigation);
  if (elements.length === 0) return null;
  const first = elements[0]!;
  const last = elements[elements.length - 1]!;
  const active = document.activeElement;
  const outside = !navigation.contains(active);
  if (event.shiftKey) return active === first || outside ? last : undefined;
  return active === last || outside ? first : undefined;
}

function concealSurface(surface: HTMLElement) {
  surface.inert = true;
  surface.setAttribute("aria-hidden", "true");
}

function revealSurface(surface: HTMLElement) {
  surface.inert = false;
  surface.removeAttribute("aria-hidden");
}

function focusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  return Array.from(container.querySelectorAll<HTMLElement>(
    'input, button:not([disabled]), a[href], select, textarea, [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.hasAttribute("hidden"));
}
