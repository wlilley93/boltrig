// Settings anchor (#/settings): the settings map. A directory, not a form -
// one card per section, clicking navigates right to that section's column
// (settings-retrofit spec section 1.1; fact lines are deferred, the anchor
// makes no reads of its own). Reuses the wfpick card-grid idiom the
// automations anchor already established.

import { SETTINGS_COLS } from "../../deck/deckMap";
import { useIdentity } from "../../identity";
import { navigate } from "../../router";
import { PageIntro } from "../ux";

// One-line description per section, in the spec's 1.1 card copy.
const SECTION_BLURB: Record<string, string> = {
  account: "Name, locale and timezone.",
  appearance: "Theme, density, text size, motion and contrast.",
  notifications: "What reaches you, and where.",
  developer: "Personal access tokens and how to connect clients.",
  agent: "The assistant that runs as you.",
  privacy: "Export your data; manage your conversations.",
  security: "Active sessions, tokens, your own activity.",
  organisation: "The user directory and invitations.",
};

export function SettingsAnchorSlide() {
  const identity = useIdentity();
  const visible = SETTINGS_COLS.filter(
    (c) => !c.gate || c.gate(identity.role),
  );

  return (
    <section className="panel">
      <PageIntro
        title="Settings"
        lead="Your account, security, and how Boltrig looks and reaches you."
        how="Pick a section to open it. Org-admins also manage the directory and invitations here."
        actions={<span className="muted">{visible.length} sections</span>}
      />

      <div className="wfpick">
        {visible.map((c) => (
          <button
            key={c.key}
            className="wfpick__card"
            title={`Open ${c.label}`}
            onClick={() => navigate(`/settings/${c.key}`)}
          >
            <span className="wfpick__id">
              <strong>{c.label}</strong>
            </span>
            <span className="muted">{SECTION_BLURB[c.key]}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
