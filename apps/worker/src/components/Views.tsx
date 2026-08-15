import { DeviceSettings } from "./DeviceSettings";
import { DesktopUpdater } from "./DesktopUpdater";
import { SettingsSectionPane } from "./SettingsSurface";
import type { SettingsSection } from "../settingsSections";
import { hasDesktopRuntime } from "../desktop";

export function SettingsView({ section = "you" }: { section?: SettingsSection }) {
  // Settings uses one calm row-based surface. The larger legacy account,
  // organisation and knowledge dashboards are still available from their
  // dedicated app routes where they are needed, but are not the default
  // settings experience.
  if (section === "advanced") {
    return (
      <div className="page">
        <div className="page-content">
          <div className="narrow"><SettingsSectionPane section={section} /></div>
          <div className="settings-grid">
            {hasDesktopRuntime() && <DesktopUpdater />}
            <DeviceSettings />
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="page">
      <div className="page-content narrow">
        <SettingsSectionPane section={section} />
      </div>
    </div>
  );
}
