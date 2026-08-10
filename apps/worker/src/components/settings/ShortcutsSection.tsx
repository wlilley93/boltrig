import { useState } from "react";

import { SHORTCUT_GROUPS } from "../../shortcuts";
import { SectionHead } from "./SectionHead";
import { SettingsGroup, SettingsRow } from "./rowKit";

// The shortcut reference, read from the shared registry in src/shortcuts.ts —
// the same table the keydown wiring reads, so this list cannot describe a key
// the build does not bind. (The old hand-written constant listed a ⌘B toggle
// no handler bound; the registry is how that class of defect stays fixed.)

export function ShortcutsSection({ head = true }: { head?: boolean }) {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const groups = SHORTCUT_GROUPS
    .map((group) => ({
      title: group.title,
      rows: group.rows.filter((row) => (
        !needle || `${row.label} ${row.desc}`.toLowerCase().includes(needle)
      )),
    }))
    .filter((group) => group.rows.length > 0);

  return (
    <>
      {head && <SectionHead section="shortcuts" />}

      <div className="settings-inline-search">
        <svg aria-hidden fill="none" height="14" stroke="var(--text-4)" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="14">
          <circle cx="11" cy="11" r="7" />
          <line x1="16.5" x2="21" y1="16.5" y2="21" />
        </svg>
        <input
          aria-label="Search shortcuts"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search shortcuts"
          value={query}
        />
      </div>

      {groups.map((group) => (
        <SettingsGroup eyebrow key={group.title} title={group.title}>
          {group.rows.map((row) => (
            <SettingsRow
              control={(
                <span className="settings-keys">
                  {row.keys.map((key) => <kbd className="settings-key" key={key}>{key}</kbd>)}
                </span>
              )}
              desc={row.desc || undefined}
              key={row.id}
              title={row.label}
            />
          ))}
        </SettingsGroup>
      ))}

      {groups.length === 0 && (
        <div className="settings-results-empty">Nothing matches that.</div>
      )}

      <p className="console-foot">
        Only the shortcuts this build actually binds are listed. An unassigned key is not shown as
        though it worked.
      </p>
    </>
  );
}
