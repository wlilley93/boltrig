import { useEffect, useState } from "react";
import type {
  MyOrganisationView,
  WorkspaceView,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

/**
 * The workspaces and organisations this session may bind to, and the act of
 * binding to one.
 *
 * A CONTEXT SWITCH IS A SESSION REBINDING, SO THE WHOLE SURFACE IS RELOADED.
 * Since agent rosters and companions became per-workspace, at least four things
 * change when a switch succeeds: the caller's grants, the agent roster, the
 * main-character companion, and which canonical capabilities are offered.
 * Nothing in the shell re-reads any of them, and the `onChanged` callback has
 * never been supplied by any caller, so before this the page kept rendering the
 * previous workspace's answers until something else happened to reload it.
 *
 * A reload rather than a refresh of each surface, for the same reason sign-out
 * reloads: a partial refresh that misses one of the four is a page showing two
 * workspaces at once, and the one it misses is the one nobody thought of.
 *
 * A FAILED switch never reloads. The session is still bound to the old
 * workspace, and reloading would present the unchanged context as though the
 * switch had taken effect.
 */
export function useActiveContext(onChanged?: () => void) {
  const [workspaces, setWorkspaces] = useState<WorkspaceView[]>([]);
  const [organisations, setOrganisations] = useState<MyOrganisationView[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [orgId, setOrgId] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    void Promise.all([
      client.workspaces(),
      client.currentOrg(),
      client.myOrganisations(),
      // The session's active workspace, the same source the shell reads.
      client.consoleOverview(1).catch(() => null),
    ])
      .then(([workspaceResult, orgResult, orgsResult, overviewResult]) => {
        const activeWorkspaceId = overviewResult?.workspace_id ?? "";
        setWorkspaces(workspaceResult.workspaces);
        setOrganisations(orgsResult.organisations);
        setWorkspaceId(
          workspaceResult.workspaces.some((item) => item.id === activeWorkspaceId)
            ? activeWorkspaceId
            : workspaceResult.workspaces[0]?.id ?? "",
        );
        setOrgId(orgResult.organisation.id);
      })
      .catch(() => setMessage("Active context is unavailable."));
  }, []);

  function reloadIntoNewContext() {
    onChanged?.();
    window.location.reload();
  }

  async function switchWorkspace() {
    try {
      const result = await client.switchActiveContext(workspaceId);
      setMessage(result.status === "ok"
        ? "Workspace context changed."
        : result.reason ?? result.status);
      if (result.status === "ok") reloadIntoNewContext();
    } catch {
      setMessage("The workspace context could not be changed.");
    }
  }

  async function switchOrg() {
    try {
      const result = await client.switchActiveOrg(orgId.trim());
      setMessage(result.status === "ok"
        ? "Organisation context changed."
        : result.reason ?? result.status);
      // An org switch also moves the active workspace: the resolver picks a
      // default in the new org, so everything above applies here too.
      if (result.status === "ok") reloadIntoNewContext();
    } catch {
      setMessage("The organisation context could not be changed.");
    }
  }

  return {
    message,
    orgId,
    organisations,
    setOrgId,
    setWorkspaceId,
    switchOrg,
    switchWorkspace,
    workspaceId,
    workspaces,
  };
}
