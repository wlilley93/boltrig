import { client } from "../client";
import { isDesktop } from "../desktop";
import type { WorkerRoute } from "../routes";
import { DeviceSettings } from "./DeviceSettings";
import { DesktopUpdater } from "./DesktopUpdater";
import { InboxQueue } from "./InboxHitl";
import { Topbar, Unavailable } from "./Shell";
import { SettingsSectionPane } from "./SettingsSurface";
import { AccountView } from "./AccountView";
import { OrganisationView } from "./OrganisationView";
import { KnowledgeView } from "./ParityViews";
import type { SettingsSection } from "../settingsSections";

export function InboxView() {
  return <InboxQueue />;
}

export function SettingsView({
  section = "you",
  onContextChanged,
}: {
  section?: SettingsSection;
  onContextChanged?(): void;
}) {
  // Four sections already have a working surface, so settings routes to them
  // rather than redrawing a credential, roster or knowledge view to change its
  // frame. The other six are drawn here on the console idiom.
  if (section === "you") return <AccountView onContextChanged={onContextChanged} />;
  if (section === "organisation") return <OrganisationView />;
  if (section === "knowledge") return <KnowledgeView />;
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

const advancedCopy: Record<Exclude<WorkerRoute, "home" | "chat" | "inbox" | "automations" | "integrations" | "channels" | "build" | "evaluations" | "operate" | "account" | "organisation" | "settings">, { title: string; body: string; operator: string }> = {
  runs: { title: "Runs", body: "Inspect execution trees, structured events, tools, costs, checkpoints, and child runs.", operator: "runs" },
  work: { title: "Work", body: "Track canonical work items and the workflow state projected from Boltrig.", operator: "work" },
  agents: { title: "Agents", body: "Author profiles, skill selection, grant ceilings, and Familiar identity.", operator: "agents" },
  knowledge: { title: "Knowledge", body: "Browse governed assets, revisions, citations, provider health, and erasure state.", operator: "knowledge" },
  memory: { title: "Memory", body: "Recall with provenance, remember, inspect ingestion, and forget exact sources.", operator: "memory" },
};

export function AdvancedView({ route }: { route: keyof typeof advancedCopy }) {
  const copy = advancedCopy[route];
  return (
    <div className="page">
      <Topbar title={copy.title} />
      <div className="page-content narrow">
        <Unavailable title={`${copy.title} is available in Operator`}>
          {copy.body}
        </Unavailable>
        <a className="primary-button centered" href={`/operator/#/${copy.operator}`}>Open {copy.title} in Operator</a>
      </div>
    </div>
  );
}
