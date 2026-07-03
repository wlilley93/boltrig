// The app-chrome session controls (COUNTY 7 / 8): the org/workspace switcher and
// the logout control. They render ONLY on the real cookie-session auth path
// (hasSessionCookie): under the dev header resolver and the e2e smoke there is
// no session cookie, so this is inert there and the chat smoke is unaffected.

import { useState } from "react";

import { api } from "../api/client";
import {
  hasSessionCookie,
  markUnauthenticated,
  setActiveWorkspace,
  useAuth,
} from "../auth";
import { useFetch } from "../useFetch";

function WorkspaceSwitcher() {
  const { activeWorkspaceId } = useAuth();
  const workspaces = useFetch(() => api.workspaces(), []);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const list = workspaces.data?.workspaces ?? [];
  // With zero or one workspace there is nothing to switch between; keep the
  // chrome quiet (this is also why the dev/e2e caller, with no memberships,
  // renders nothing here).
  if (list.length < 2) return null;

  async function onSwitch(id: string) {
    if (!id || id === activeWorkspaceId || switching) return;
    setSwitching(true);
    setError(null);
    try {
      const res = await api.switchActiveContext(id);
      if (res.status === "ok" && res.workspace_id) {
        setActiveWorkspace(res.workspace_id);
        // The active workspace narrows effective grants server-side, so re-fetch
        // app state under the new context. A full reload is the honest, complete
        // refresh (every panel re-queries) since panels fetch independently.
        window.location.reload();
        return;
      }
      setError(res.reason ?? "Could not switch workspace.");
    } catch {
      setError("Could not switch workspace.");
    } finally {
      setSwitching(false);
    }
  }

  return (
    <div className="chrome-switcher" role="group" aria-label="Active workspace">
      <label className="chrome-switcher__label" htmlFor="chrome-workspace">
        Workspace
      </label>
      <select
        id="chrome-workspace"
        className="chrome-switcher__select"
        value={activeWorkspaceId ?? ""}
        disabled={switching}
        onChange={(e) => void onSwitch(e.target.value)}
      >
        {activeWorkspaceId === null && (
          <option value="" disabled>
            Select a workspace
          </option>
        )}
        {list.map((w) => (
          <option key={w.id} value={w.id}>
            {w.name}
          </option>
        ))}
      </select>
      {error && (
        <span className="chrome-switcher__error error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

function LogoutButton() {
  const [busy, setBusy] = useState(false);
  async function logout() {
    if (busy) return;
    setBusy(true);
    try {
      // Revoke the session server-side; the response also clears the cookies.
      await api.logout();
    } catch {
      // even if the call fails, drop the client to the gate (fail-safe logout).
    } finally {
      markUnauthenticated();
    }
  }
  return (
    <button
      type="button"
      className="btn btn--ghost btn--sm chrome-logout"
      title="Sign out of your Boltrig session"
      disabled={busy}
      onClick={() => void logout()}
    >
      {busy ? "Signing out..." : "Sign out"}
    </button>
  );
}

export function SessionControls() {
  // Only meaningful for a real cookie session; inert on the dev header path.
  if (!hasSessionCookie()) return null;
  return (
    <div className="chrome-session">
      <WorkspaceSwitcher />
      <LogoutButton />
    </div>
  );
}
