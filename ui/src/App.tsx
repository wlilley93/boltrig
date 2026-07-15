import { useEffect, useMemo, useState } from "react";

import { applyAppearance, loadAppearance } from "@/appearance";
import { Deck } from "@/deck/Deck";
import { buildRows, routeToCell } from "@/deck/deckMap";
import { useIdentity } from "@/identity";
import { useRoute } from "@/router";
import { useAgentDeckCols } from "@/panels/AgentsSlide";
import { useAutomationDeckCols } from "@/panels/AutomationsSlide";
import { CommandPalette } from "@/panels/CommandPalette";
import { RunView } from "@/panels/RunView";
import { SettingsPage } from "@/panels/SettingsPage";
import { AppSidebar } from "@/app/AppSidebar";
import { AppTopbar } from "@/app/AppTopbar";
import { IdentityBar } from "@/app/IdentityBar";
import { renderCell } from "@/app/renderCell";

// The role gates live with the deck row model now; App re-exports them so the
// existing `import { AUTHOR_ROLES } from "../App"` call sites keep working.
export { ADMIN_ROLES, AUTHOR_ROLES } from "@/deck/deckMap";

// The chat anchor keeps its React state (an in-flight SSE stream included)
// once visited, even when it is no longer a neighbour of the active cell.
const KEEP_ALIVE = ["chat:chat"];

export function App() {
  const identity = useIdentity();
  // The URL hash drives everything: the deck cell via routeToCell, and the Run
  // drawer via route.runId; navigate() writes the hash, useRoute reads it.
  const route = useRoute();

  // Visible rows derive from the CURRENT role each render (the dev IdentityBar
  // changes role live); the deck addresses cells by id, never a stored index.
  const agentCols = useAgentDeckCols();
  const automationCols = useAutomationDeckCols();
  const rows = useMemo(
    () => buildRows(identity.role, agentCols, automationCols),
    [identity.role, agentCols, automationCols],
  );
  const active = routeToCell(route, rows);
  const settingsActive = route.tab === "settings";

  // The dev sign-in is collapsed behind the identity chip by default; expanding it
  // reveals the editable identity bar (the dev auth mechanism).
  const [identityOpen, setIdentityOpen] = useState(false);
  // Labels are the discoverable desktop default. The responsive shell turns
  // this into an icon rail on narrow screens, and the user can collapse it at
  // any width without changing navigation state.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Apply the persisted appearance (theme / density / contrast / font scale /
  // reduced motion) to the document root on first load, before any panel paints,
  // so the saved choice takes effect with no flash. The Settings panel keeps it
  // in sync with the server thereafter.
  useEffect(() => {
    applyAppearance(loadAppearance());
  }, []);

  return (
    <div className="app app--shell">
      <AppSidebar
        identityOpen={identityOpen}
        collapsed={sidebarCollapsed}
        onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
        onToggleIdentity={() => setIdentityOpen((v) => !v)}
      />

      <div className="app__body">
        {identityOpen && <IdentityBar />}
        {route.tab !== "chat" && <AppTopbar />}
        <main className="app__main app__main--deck">
          {/* The Deck stays mounted (so keep-alive chat state survives) but is
              hidden when Settings is the active page - settings renders as its
              own full-width page outside the deck. */}
          <div className={settingsActive ? "app__deck app__deck--hidden" : "app__deck"}>
            <Deck
              rows={rows}
              active={active}
              render={renderCell}
              keepAlive={KEEP_ALIVE}
            />
          </div>
          {settingsActive && <SettingsPage />}
        </main>
      </div>

      {/* The global Run drawer: any surface can raise it via openRun(runId).
          It is position:fixed, so it must stay OUTSIDE the transformed deck. */}
      <RunView />

      {/* Cmd/Ctrl-K jump-to-anything palette - also outside the deck. */}
      <CommandPalette />
    </div>
  );
}
