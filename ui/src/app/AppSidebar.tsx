import { navigate } from "@/router";
import { SessionControls } from "@/panels/SessionControls";
import type { DeckRow } from "@/deck/Deck";
import { BoltMark } from "./BoltMark";
import { IdentityChip } from "./IdentityChip";
import { OpsGroup } from "./OpsGroup";
import { ZoneGroup } from "./ZoneGroup";

interface AppSidebarProps {
  rows: DeckRow[];
  active: { rowId: string; colKey: string };
  identityOpen: boolean;
  collapsed: boolean;
  onToggleSidebar: () => void;
  onToggleIdentity: () => void;
}

// The icon rail (collapsed) or labelled rail (expanded). Collapse state is owned
// by App so it survives re-renders; the toggle lives in the brand row.
export function AppSidebar({
  rows,
  active,
  identityOpen,
  collapsed,
  onToggleSidebar,
  onToggleIdentity,
}: AppSidebarProps) {
  const zoneRows = rows.filter((r) => r.id !== "ops");
  const opsCols = rows.find((r) => r.id === "ops")?.cols ?? [];
  return (
    <aside
      className="side"
      data-collapsed={collapsed ? "true" : "false"}
      aria-label="Primary navigation"
    >
      <div className="side__brand">
        <BoltMark />
        <span className="side__word">boltrig</span>
        <button
          className="side__collapse"
          onClick={onToggleSidebar}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            {collapsed ? (
              <path d="M9 6l6 6-6 6" />
            ) : (
              <path d="M15 6l-6 6 6 6" />
            )}
          </svg>
        </button>
      </div>

      <nav className="side__nav" aria-label="Panels">
        <ZoneGroup rows={zoneRows} active={active} />
        <OpsGroup cols={opsCols} active={active} />
      </nav>

      <div className="side__foot">
        <SessionControls />
        <button
          className="side__settings"
          title="Settings"
          aria-label="Settings"
          onClick={() => navigate("/settings")}
        >
          <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" opacity="0.85">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.26.6.77 1.02 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
        <IdentityChip
          expanded={identityOpen}
          onToggle={onToggleIdentity}
        />
      </div>
    </aside>
  );
}
