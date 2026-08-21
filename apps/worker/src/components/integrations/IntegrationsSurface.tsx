import { IntegrationsView } from "../IntegrationsView";
import { useRouteSelection } from "../../useRouteSelection";
import { CapabilityCataloguePanel } from "./CapabilityCataloguePanel";
import { CapabilityReviewPanel } from "./CapabilityReviewPanel";
import { PluginPageHeading } from "./PluginPicker";
import { RoutingRulesPanel } from "./RoutingRulesPanel";
import {
  INTEGRATIONS_ROUTE,
  tabFromSelection,
  type CapabilityTabId,
} from "./capabilityTabs";

/**
 * The Integrations page: the connections list it has always been, plus the
 * three capability-layer views that had routes and no reader.
 *
 * A WRAPPER rather than three more sections inside IntegrationsView. That file
 * carries a structural-debt pin and a 707-line component; growing it to add
 * tabs would have meant raising a ratchet to make room for the thing the
 * ratchet exists to discourage. The strip itself lives in the shared page
 * heading (see IntegrationsTabs), which is inside the pane: a strip wrapped
 * around the whole route renders at x=266 against a pane at x=435, and the
 * visual contract calls that what it is.
 *
 * The tab is the hash SELECTION, so it survives a reload and can be linked. The
 * default clears the segment, because a bare `#/integrations` has always meant
 * the connections list and rewriting it on load would break saved links.
 */
export function IntegrationsSurface() {
  const [selection] = useRouteSelection(INTEGRATIONS_ROUTE);
  const active = tabFromSelection(selection);
  // The connections tab IS IntegrationsView, unchanged. The strip it shows
  // comes from the shared page heading, so this branch chooses a body and
  // nothing else.
  if (active === "connections") return <IntegrationsView />;
  return (
    <div className="plugins-page">
      <main className="plugins-pane">
        <PluginPageHeading />
        <div className="plugins-wrap">
          <CapabilityPanel tab={active} />
        </div>
      </main>
    </div>
  );
}

function CapabilityPanel({ tab }: { tab: CapabilityTabId }) {
  if (tab === "capabilities") return <CapabilityCataloguePanel />;
  if (tab === "rules") return <RoutingRulesPanel />;
  return <CapabilityReviewPanel />;
}
