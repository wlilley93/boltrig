import { client } from "../client";
import { isDesktop } from "../desktop";
import { DeviceSettings } from "./DeviceSettings";
import { CameraDiscoverySettings } from "./CameraDiscoverySettings";
import { DesktopUpdater } from "./DesktopUpdater";
import { Unavailable } from "./Shell";
import { SettingsSectionPane } from "./SettingsSurface";
import { DeveloperDetailsRow } from "./settings/rowKit";
import type { SettingsSection } from "../settingsSections";

export function SettingsView({ section = "you" }: { section?: SettingsSection }) {
  // Settings uses one calm row-based surface. The larger legacy account,
  // organisation and knowledge dashboards are still available from their
  // dedicated app routes where they are needed, but are not the default
  // settings experience.
  if (section === "you" || section === "organisation" || section === "knowledge") {
    return (
      <div className="page">
        <div className="page-content narrow">
          <SettingsSectionPane section={section} />
        </div>
      </div>
    );
  }
  if (section === "advanced") {
    return (
      <div className="page">
        <div className="page-content">
          <div className="settings-head">
            <h1>Advanced</h1>
            <p>The device this client runs on, and the controls that are only safe when you know why you want them.</p>
          </div>
          <div className="settings-grid">
            <section className="settings-card">
              <p className="eyebrow">Desktop device</p>
              <h2>{isDesktop ? "This Worker is running in Tauri" : "Browser session"}</h2>
              <p>
                User sign-in uses the same secure browser session cookie in desktop
                and web builds. A separately enrolled background device agent keeps
                its rotating session in the OS keychain. The shell runs no Python
                agent server.
              </p>
            </section>
            <DesktopUpdater />
            <DeviceSettings />
            <CameraDiscoverySettings />
            <section className="settings-card">
              <p className="eyebrow">Security defaults</p>
              <ul>
                <li>Available only while online and unlocked</li>
                <li>Commands disabled until enabled per root</li>
                <li>Every command requires per-invocation approval</li>
                <li>Artifact saves use a native user dialog</li>
              </ul>
            </section>
            <section className="settings-card">
              <p className="eyebrow">Presentation</p>
              <h2>Developer details</h2>
              <p>
                Shows the technical register everywhere it exists: verb chips,
                raw model ids, run identifiers. The plain-language reading stays
                the default.
              </p>
              <DeveloperDetailsRow />
            </section>
            <section className="settings-card">
              <p className="eyebrow">Session</p>
              <h2>Signed in to Boltrig</h2>
              <p>Signing out revokes the current browser session cookie. Other sessions remain visible and revocable under You.</p>
              <button className="secondary-button" onClick={() => void client.logout().finally(() => window.location.reload())}>Sign out</button>
            </section>
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
