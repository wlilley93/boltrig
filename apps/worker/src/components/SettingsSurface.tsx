import { useEffect, useState } from "react";
import type { BudgetItem } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import type { SettingsSection } from "../settingsSections";
import { hasDesktopRuntime } from "../desktop";
import { ArchivedSection } from "./settings/ArchivedSection";
import {
  CompactAdvancedSection,
  CompactKnowledgeSection,
  CompactOrganisationSection,
  CompactYouSection,
} from "./settings/CompactSections";
import { HealthSection } from "./settings/HealthSection";
import { ModelSettingsSection } from "./settings/ModelSettingsSection";
import { OperationsSettingsSection } from "./settings/OperationsSettingsSection";
import { OvernightSection } from "./settings/OvernightSection";
import { SectionHead } from "./settings/SectionHead";
import { ShortcutsSection } from "./settings/ShortcutsSection";
import { SpendingSection } from "./settings/SpendingSection";
import { SettingsGroup, SettingsRow } from "./settings/rowKit";
import { ApprovalPostureSettings } from "./ApprovalPostureControl";
import "./settings/settings-you.css";

// The settings pane, recast onto the typed row-control kit in
// ./settings/rowKit.tsx. Every section uses the same calm row idiom. Larger
// the operations evidence surface lives here as well, so settings is the single
// place for workspace posture, audit evidence and budget controls.

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
  const localAgent = hasDesktopRuntime();
  return (
    <>
      {head && <SectionHead section="autonomy" />}
      <SettingsGroup title="What stops a run">
        <SettingsRow
          title="Agent tool approvals"
          desc={localAgent
            ? "Choose how this computer approves local files, commands and network access. Cloud tool grants stay separate."
            : "Choose how cloud tools use the authority you already granted."}
          control={<ApprovalPostureSettings runtime={localAgent ? "local" : "cloud"} />}
          tech="agentic.approval_posture"
        />
        <SettingsRow
          title="Hard-stop ceilings"
          desc="A ceiling without a hard stop is recorded and reported, but it does not halt a run."
          control={(
            <span className="settings-value">
              {budgets === null ? "…" : `${hardStops} of ${budgets.length}`}
            </span>
          )}
        />
        <SettingsRow
          title={localAgent ? "Boltrig credentials stay server-side" : "Credentials stay server-side"}
          desc={localAgent
            ? "The local agent receives no Boltrig provider credentials. Local files remain governed by the posture above."
            : "Cloud tools can use credentials without exposing them to this device."}
        />
      </SettingsGroup>
    </>
  );
}

export function SettingsSectionPane({ section, head = true }: {
  section: SettingsSection;
  /** The mobile surface draws its own head, so it suppresses this one. */
  head?: boolean;
}) {
  const Pane = SETTINGS_PANES[section];
  return Pane ? <Pane head={head} /> : null;
}

type SettingsPane = (props: { head?: boolean }) => React.ReactNode;

const SETTINGS_PANES: Record<SettingsSection, SettingsPane> = {
  advanced: AdvancedSettingsPane,
  archived: ArchivedSection,
  autonomy: AutonomySection,
  health: HealthSection,
  knowledge: KnowledgeSettingsPane,
  models: ModelSettingsSection,
  operations: OperationsSettingsSection,
  organisation: OrganisationSettingsPane,
  overnight: OvernightSection,
  shortcuts: ShortcutsSection,
  spend: SpendingSection,
  you: YouSettingsPane,
};

function YouSettingsPane({ head = true }: { head?: boolean }) {
  return (
    <div className="settings-you-pane">
      {head && <SectionHead section="you" />}
      <CompactYouSection />
    </div>
  );
}

function OrganisationSettingsPane({ head = true }: { head?: boolean }) {
  return <>{head && <SectionHead section="organisation" />}<CompactOrganisationSection /></>;
}

function KnowledgeSettingsPane({ head = true }: { head?: boolean }) {
  return <>{head && <SectionHead section="knowledge" />}<CompactKnowledgeSection /></>;
}

function AdvancedSettingsPane({ head = true }: { head?: boolean }) {
  return <>{head && <SectionHead section="advanced" />}<CompactAdvancedSection /></>;
}
