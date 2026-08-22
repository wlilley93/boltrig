import { useEffect, useState } from "react";
import type { NamedAgentView, WorkspaceView } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

/** Best-effort catalogues for alternate sidebar projections. */
export function useDirectoryMetadata() {
  const [projects, setProjects] = useState<WorkspaceView[]>([]);
  const [namedAgents, setNamedAgents] = useState<NamedAgentView[]>([]);

  useEffect(() => {
    let cancelled = false;
    const workspaces = typeof client.workspaces === "function"
      ? client.workspaces()
      : Promise.reject(new Error("workspace catalogue unavailable"));
    const agents = typeof client.namedAgents === "function"
      ? client.namedAgents()
      : Promise.reject(new Error("named-agent catalogue unavailable"));
    void Promise.allSettled([workspaces, agents]).then(([workspaceResult, agentResult]) => {
      if (cancelled) return;
      if (workspaceResult.status === "fulfilled") {
        setProjects(workspaceResult.value.workspaces.filter((item) => item.status === "active"));
      }
      if (agentResult.status === "fulfilled") setNamedAgents(agentResult.value.named_agents);
    });
    return () => { cancelled = true; };
  }, []);

  return { namedAgents, projects };
}
