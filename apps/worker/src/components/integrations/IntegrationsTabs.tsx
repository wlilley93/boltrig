import { useRouteSelection } from "../../useRouteSelection";
import {
  CAPABILITY_TABS,
  INTEGRATIONS_ROUTE,
  selectionForTab,
  tabFromSelection,
} from "./capabilityTabs";

/**
 * The Integrations page's tab strip, owning its own selection.
 *
 * Self-contained rather than driven by a prop, for a measured reason:
 * IntegrationsView's structural baseline pins it at ZERO parameters and the
 * trusted-baseline check refuses growth in any per-function metric, so passing
 * the strip in would have been a ratchet raise. It reads the hash itself, both
 * places that render it get the same strip, and there is no state to keep in
 * step.
 *
 * It renders inside the page heading, which is inside the pane. A strip wrapped
 * around the whole route lands at x=266 against a pane at x=435, which the
 * visual contract calls what it is: a different page.
 */
export function IntegrationsTabs() {
  const [selection, select] = useRouteSelection(INTEGRATIONS_ROUTE);
  const active = tabFromSelection(selection);
  return (
    <nav aria-label="Integrations views" className="plugins-tabs" role="tablist">
      {CAPABILITY_TABS.map((tab) => (
        <button
          aria-selected={active === tab.id}
          className={`plugins-tab ${active === tab.id ? "active" : ""}`}
          data-active={active === tab.id}
          key={tab.id}
          onClick={() => select(selectionForTab(tab.id))}
          role="tab"
          type="button"
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
