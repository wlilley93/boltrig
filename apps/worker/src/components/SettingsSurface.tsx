import { useEffect, useState } from "react";
import type { BudgetItem } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import type { SettingsSection } from "../settingsSections";
import { ArchivedSection } from "./settings/ArchivedSection";
import {
  CompactAdvancedSection,
  CompactKnowledgeSection,
  CompactOrganisationSection,
  CompactYouSection,
} from "./settings/CompactSections";
import { HealthSection } from "./settings/HealthSection";
import { OvernightSection } from "./settings/OvernightSection";
import { SectionHead } from "./settings/SectionHead";
import { ShortcutsSection } from "./settings/ShortcutsSection";
import { SpendingSection } from "./settings/SpendingSection";
import { SettingsGroup, SettingsRow } from "./settings/rowKit";

// The settings pane, recast onto the typed row-control kit in
// ./settings/rowKit.tsx. Every section uses the same calm row idiom. Larger
// operational surfaces remain available from their dedicated app routes, but
// the settings route does not force most users through those dense dashboards.

// Re-exported so other surfaces (the Plugins pane shares this renderer) keep
// importing the row idiom from here.
export { SettingsGroup, SettingsRow };
export { SettingsSearchResults } from "./settings/SearchResults";

// --- Autonomy ---------------------------------------------------------------

function AutonomySection({ head = true }: { head?: boolean }) {
  const [budgets, setBudgets] = useState<BudgetItem[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    void client.budgets()
      .then((result) => { if (!cancelled) setBudgets(result.budgets); })
      .catch(() => { if (!cancelled) setBudgets([]); });
    return () => { cancelled = true; };
  }, []);

  const hardStops = (budgets ?? []).filter((budget) => budget.hard_stop).length;
  return (
    <>
      {head && <SectionHead section="autonomy" />}
      <SettingsGroup title="What stops a run">
        <SettingsRow
          title="Every consequential verb asks first"
          desc="Approval is decided by the kernel against the workspace policy, not by this client. Nothing here can widen it."
          tech="hitl"
        />
        <SettingsRow
          title="Ceilings that actually stop work"
          desc="A ceiling without a hard stop is recorded and reported, but it does not halt a run."
          control={(
            <span className="settings-value">
              {budgets === null ? "…" : `${hardStops} of ${budgets.length}`}
            </span>
          )}
        />
        <SettingsRow
          title="Credentials never reach this client"
          desc="Tools, credentials, memory and approvals stay server-side, so an autonomy setting here cannot leak one."
        />
      </SettingsGroup>
      {/* The decided target draws a three-way posture chooser here. This build
          has no posture to set: approval is policy-driven per verb, and drawing
          a chooser that wrote nothing would be a control that lies. */}
      <p className="console-foot">
        The decided target offers a three-way posture here. This build has no posture to set:
        what stops a run is decided per verb by workspace policy, so the honest thing to show is
        what that policy currently does.
      </p>
    </>
  );
}

export function SettingsSectionPane({ section, head = true }: {
  section: SettingsSection;
  /** The mobile surface draws its own head, so it suppresses this one. */
  head?: boolean;
}) {
  if (section === "spend") return <SpendingSection head={head} />;
  if (section === "autonomy") return <AutonomySection head={head} />;
  if (section === "health") return <HealthSection head={head} />;
  if (section === "shortcuts") return <ShortcutsSection head={head} />;
  if (section === "overnight") return <OvernightSection head={head} />;
  if (section === "archived") return <ArchivedSection head={head} />;
  if (section === "you") {
    return <>{head && <SectionHead section={section} />}<CompactYouSection /></>;
  }
  if (section === "organisation") {
    return <>{head && <SectionHead section={section} />}<CompactOrganisationSection /></>;
  }
  if (section === "knowledge") {
    return <>{head && <SectionHead section={section} />}<CompactKnowledgeSection /></>;
  }
  if (section === "advanced") {
    return <>{head && <SectionHead section={section} />}<CompactAdvancedSection /></>;
  }
  return null;
}
