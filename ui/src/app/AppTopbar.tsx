import { api } from "@/api/client";
import { useIdentity } from "@/identity";
import { navigate, useRoute } from "@/router";
import { useFetch } from "@/useFetch";
import {
  BUILD_NAV,
  itemForTab,
  OPERATE_NAV,
  visibleItems,
  zoneForTab,
} from "./navigation";

function openPalette() {
  window.dispatchEvent(new Event("boltrig:open-palette"));
}

function configuredEnvironment(): string | null {
  const configured = String(import.meta.env.VITE_ENVIRONMENT ?? "").trim();
  if (configured) return configured;
  return ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname)
    ? "local"
    : null;
}

export function AppTopbar() {
  const route = useRoute();
  const identity = useIdentity();
  const health = useFetch(() => api.health(), [], 30000);
  const zone = zoneForTab(route.tab);
  const current = itemForTab(route.tab, identity.role);
  const sectionItems =
    zone === "build"
      ? visibleItems(BUILD_NAV, identity.role)
      : zone === "operate"
        ? visibleItems(OPERATE_NAV, identity.role)
        : [];
  const environment = configuredEnvironment();
  const healthy = !health.error && health.data?.status === "ok";

  return (
    <header className="console-topbar">
      <div className="console-topbar__context">
        <div className="console-topbar__title">
          {(zone === "build" || zone === "operate") && route.tab !== zone && (
            <>
              <button className="console-topbar__crumb" onClick={() => navigate(`/${zone}`)}>
                {zone === "build" ? "Build" : "Operate"}
              </button>
              <span aria-hidden="true">/</span>
            </>
          )}
          <strong>{current?.label ?? (zone === "settings" ? "Settings" : "Boltrig")}</strong>
        </div>
        {sectionItems.length > 0 && (
          <nav className="console-subnav" aria-label={`${zone} sections`}>
            {sectionItems.map((item) => (
              <button
                key={item.id}
                className={route.tab === item.id ? "console-subnav__item is-active" : "console-subnav__item"}
                aria-current={route.tab === item.id ? "page" : undefined}
                onClick={() => navigate(item.path)}
              >
                {item.label}
              </button>
            ))}
          </nav>
        )}
      </div>

      <div className="console-topbar__actions">
        {environment && <span className="console-env">{environment}</span>}
        <button
          className="console-health"
          title={healthy ? "Kernel liveness is responding" : "Kernel liveness needs attention"}
          onClick={() => navigate("/health")}
        >
          <span className={healthy ? "console-health__dot is-ok" : "console-health__dot"} />
          <span>{health.loading && !health.data ? "Checking" : healthy ? "Live" : "Attention"}</span>
        </button>
        <button className="console-command" onClick={openPalette} aria-label="Open command palette">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="11" cy="11" r="6" /><path d="m16 16 4 4" /></svg>
          <span>Search</span>
          <kbd>⌘K</kbd>
        </button>
      </div>
    </header>
  );
}
