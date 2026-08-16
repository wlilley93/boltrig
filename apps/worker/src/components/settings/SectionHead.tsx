import { settingsEntry, type SettingsSection } from "../../settingsSections";

// The static section head, read from the registry so the sidebar, the pane
// and the mobile detail screen can never disagree about a section's name or
// promise. Sections with a computed headline (Health, Overnight) draw their
// own head instead.
export function SectionHead({ section }: { section: SettingsSection }) {
  const entry = settingsEntry(section);
  return (
    <div className="settings-head">
      <h1>{entry.title}</h1>
      <p>{entry.lead}</p>
    </div>
  );
}
