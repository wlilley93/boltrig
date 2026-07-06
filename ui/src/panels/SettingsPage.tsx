import { navigate, useRoute } from "@/router";
import { SETTINGS_COLS } from "@/deck/deckMap";
import { SETTINGS_PANELS } from "@/app/renderCell";
import { useIdentity } from "@/identity";

// Settings renders as its own full-width page (outside the Deck): a left
// section rail + the active section's panel. The section comes from the route
// (#/settings/<section>); with no section, the first one is shown.
export function SettingsPage(): JSX.Element {
  const route = useRoute();
  const identity = useIdentity();
  const cols = SETTINGS_COLS.filter((c) => !c.gate || c.gate(identity.role));
  const section =
    route.param && SETTINGS_PANELS[route.param]
      ? route.param
      : cols[0]?.key ?? "account";
  const panel = SETTINGS_PANELS[section] ?? SETTINGS_PANELS.account;

  return (
    <div className="settings-page">
      <aside className="settings-page__nav" aria-label="Settings sections">
        <h2 className="settings-page__title">Settings</h2>
        {cols.map((c) => (
          <button
            key={c.key}
            className={`settings-nav-item${c.key === section ? " settings-nav-item--active" : ""}`}
            onClick={() => navigate(`/settings/${c.key}`)}
          >
            {c.label}
          </button>
        ))}
      </aside>
      <div className="settings-page__content">{panel()}</div>
    </div>
  );
}
