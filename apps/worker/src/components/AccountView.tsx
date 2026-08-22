import { useEffect, useState } from "react";
import type { MeSettingsResponse } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { AiKeyManagement } from "./AiKeyManagement";
import { Topbar, Unavailable } from "./Shell";
import {
  NotificationPreferences,
  PersonalAgentLifecycle,
} from "./AccountAutomationSections";
import {
  ActivityAndExport,
  PrivacyPolicyEvidence,
  ProfileSettings,
} from "./AccountProfileSections";
import { ActiveContext } from "./account/ActiveContext";
import {
  DeveloperTokens,
  PasswordSecurity,
  SecuritySessions,
  TwoFactorSecurity,
} from "./AccountSecuritySections";
import { ConnectionInstructions } from "./ConnectionInstructions";

type AccountTab = "profile" | "access" | "notifications" | "agent";

export function AccountView({ onContextChanged }: { onContextChanged?(): void }) {
  const [account, setAccount] = useState<MeSettingsResponse | null>(null);
  const [tab, setTab] = useState<AccountTab>("profile");
  const [error, setError] = useState("");

  function refresh() {
    setError("");
    void client.meSettings()
      .then(setAccount)
      .catch(() => setError("Your account settings are unavailable."));
  }

  useEffect(refresh, []);

  return (
    <div className="page">
      <Topbar title="Account" status={account?.profile.role ?? "Signed in"} />
      <div className="page-content">
        <div className="page-intro">
          <div>
            <h2>Your Boltrig account</h2>
            <p>Preferences, activity, sessions, developer access and delegated automation.</p>
          </div>
        </div>
        <nav className="tabs" aria-label="Account sections">
          {([
            ["profile", "Profile"],
            ["access", "Access"],
            ["notifications", "Notifications"],
            ["agent", "Personal agent"],
          ] as const).map(([id, label]) => (
            <button
              className={tab === id ? "active" : ""}
              key={id}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>
        {error && (
          <Unavailable title="Account unavailable">{error}</Unavailable>
        )}
        {!error && !account && <p className="muted">Loading account…</p>}
        {account && tab === "profile" && (
          <div className="settings-grid">
            <ProfileSettings account={account} onSaved={refresh} />
            <ActivityAndExport />
            <PrivacyPolicyEvidence />
          </div>
        )}
        {account && tab === "access" && (
          <div className="settings-grid">
            <DeveloperTokens />
            <ConnectionInstructions />
            <AiKeyManagement />
            <PasswordSecurity />
            <TwoFactorSecurity />
            <SecuritySessions />
            <ActiveContext onChanged={onContextChanged} />
          </div>
        )}
        {account && tab === "notifications" && (
          <div className="settings-grid"><NotificationPreferences /></div>
        )}
        {account && tab === "agent" && (
          <div className="settings-grid"><PersonalAgentLifecycle /></div>
        )}
      </div>
    </div>
  );
}
