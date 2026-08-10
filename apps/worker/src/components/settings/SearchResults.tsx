import { useDeveloperDetails } from "./devDetails";
import { searchSettings } from "./searchRegistry";
import type { SettingsSection } from "../../settingsSections";
import "./settings-kit.css";

// The row-level results pane the design renders while a settings query is
// live: matches grouped by section, capped per section, with a dashed empty
// state. The mobile surface renders this above its section list; the desktop
// shell can render it in place of the section pane once it lifts its query.

export function SettingsSearchResults({ query, onOpenSection }: {
  query: string;
  onOpenSection(section: SettingsSection): void;
}) {
  const showTech = useDeveloperDetails();
  const groups = searchSettings(query);
  if (!query.trim()) return null;
  if (groups.length === 0) {
    return <div className="settings-results-empty">Nothing matches that. Try a plainer word.</div>;
  }
  return (
    <>
      {groups.map((group) => (
        <div className="settings-group" key={group.section}>
          <div className="console-section-title">{group.label}</div>
          <div className="console-table">
            {group.rows.map((row) => (
              <button
                className="settings-result-row"
                key={`${group.section}:${row.title}`}
                onClick={() => onOpenSection(group.section)}
                type="button"
              >
                <span className="settings-row-main">
                  <span className="console-row-title">
                    <span>{row.title}</span>
                    {row.tech && showTech && <span className="console-tech">{row.tech}</span>}
                  </span>
                  {row.desc && <span className="settings-row-desc">{row.desc}</span>}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
