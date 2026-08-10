import { useEffect, useState } from "react";

import { SETTINGS_SECTIONS, settingsEntry, type SettingsSection } from "../settingsSections";
import { SettingsSearchResults, SettingsSectionPane } from "./SettingsSurface";

// Mobile Settings and its detail screen. The decided target draws these as an
// iOS list: a back control naming where it returns to, a large title, an
// identity row, a search over every setting row, then one grouped card of
// sections. The detail screen reuses the console pane's CONTENT — the same
// real readings of budgets, readiness and the archive — under a mobile head,
// so the two surfaces cannot drift apart on what they claim is true. While a
// query is live the results replace the section list, as the design's pane
// does.

function Chevron() {
  return (
    <svg className="m-chev" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.6" viewBox="0 0 24 24" width="15">
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
}

function BackBar({ label, onBack }: { label: string; onBack(): void }) {
  return (
    <div className="m-backbar">
      <button className="m-back" onClick={onBack} type="button">
        <svg fill="none" height="19" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4" viewBox="0 0 24 24" width="19">
          <polyline points="15 5 8 12 15 19" />
        </svg>
        <span>{label}</span>
      </button>
    </div>
  );
}

export function MobileSettings({
  user,
  role,
  initials,
  onLeave,
}: {
  user: string;
  role: string;
  initials: string;
  onLeave(): void;
}) {
  const [open, setOpen] = useState<SettingsSection | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    document.documentElement.dataset.mobileSurface = open ? "settings-detail" : "settings";
    return () => { delete document.documentElement.dataset.mobileSurface; };
  }, [open]);

  if (open) {
    const entry = settingsEntry(open);
    return (
      <div className="mobile-surface">
        <BackBar label="Settings" onBack={() => setOpen(null)} />
        <div className="m-settings-body">
          <div className="m-detail-head">
            <span className="m-big-title">{entry.title}</span>
            <span className="m-detail-lead">{entry.lead}</span>
          </div>
          <SettingsSectionPane head={false} section={open} />
        </div>
      </div>
    );
  }

  return (
    <div className="mobile-surface">
      <BackBar label="Today" onBack={onLeave} />
      <div className="m-settings-body">
        <span className="m-big-title">Settings</span>

        <div className="m-identity">
          <span className="m-identity-avatar">{initials}</span>
          <span className="m-identity-main">
            <span className="m-identity-name">{user || "Signed in"}</span>
            <span className="m-identity-sub">{role}</span>
          </span>
          <Chevron />
        </div>

        <div className="settings-inline-search">
          <svg aria-hidden fill="none" height="14" stroke="var(--text-4)" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="14">
            <circle cx="11" cy="11" r="7" />
            <line x1="16.5" x2="21" y1="16.5" y2="21" />
          </svg>
          <input
            aria-label="Search every setting"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search every setting"
            value={query}
          />
        </div>

        {query.trim() ? (
          <SettingsSearchResults
            onOpenSection={(section) => {
              setQuery("");
              setOpen(section);
            }}
            query={query}
          />
        ) : (
          <div className="m-card">
            {SETTINGS_SECTIONS.map((entry) => (
              <button className="m-settings-row" key={entry.id} onClick={() => setOpen(entry.id)} type="button">
                <span className="m-settings-label">{entry.label}</span>
                <Chevron />
              </button>
            ))}
          </div>
        )}

        <span className="m-settings-foot">
          Every setting is one search away. Nothing is hidden, only quiet.
        </span>
      </div>
    </div>
  );
}
