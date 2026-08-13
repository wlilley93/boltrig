import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { client } from "../client";
import { characterFromSettings, saveCharacterLocal } from "../character";

const CONTEXT_CHANGED_EVENT = "boltrig:worker-context-changed";

type LoadStatus = "loading" | "ready" | "unavailable";

export interface WorkerIdentity {
  user: string;
  role: string | null;
  organisation: string;
  workspace: string;
}

interface WorkerGlobalContextValue {
  identity: WorkerIdentity | null;
  identityStatus: LoadStatus;
}

const fallbackContext: WorkerGlobalContextValue = {
  identity: null,
  identityStatus: "loading",
};

const WorkerGlobalContext = createContext<WorkerGlobalContextValue>(fallbackContext);

export function WorkerGlobalContextProvider({ children }: { children: React.ReactNode }) {
  const [identity, setIdentity] = useState<WorkerIdentity | null>(null);
  const [identityStatus, setIdentityStatus] = useState<LoadStatus>("loading");

  const refreshIdentity = useCallback(async () => {
    const [meResult, orgResult, workspaceResult, overviewResult] = await Promise.allSettled([
      client.meSettings(),
      client.currentOrg(),
      client.workspaces(),
      client.consoleOverview(1),
    ]);

    if (meResult.status !== "fulfilled") {
      setIdentity(null);
      setIdentityStatus("unavailable");
      return;
    }

    // Covers authentication transitions that enter the private tree without
    // AuthGate's initial session probe. This consumes the existing identity
    // read and does not add another settings request.
    saveCharacterLocal(characterFromSettings(meResult.value.settings));
    const profile = meResult.value.profile;
    const organisation = orgResult.status === "fulfilled"
      ? orgResult.value.organisation.name
      : "Organisation unavailable";
    const workspaces = workspaceResult.status === "fulfilled"
      ? workspaceResult.value.workspaces
      : [];
    const workspaceId = overviewResult.status === "fulfilled"
      ? overviewResult.value.workspace_id
      : undefined;
    let workspace = "Workspace unavailable";
    if (overviewResult.status === "fulfilled" && !workspaceId) {
      workspace = "Organisation-wide";
    } else if (workspaceId) {
      workspace = workspaces.find((item) => item.id === workspaceId)?.name ?? workspaceId;
    } else if (workspaces.length === 1) {
      workspace = workspaces[0].name;
    }

    setIdentity({
      user: profile.display_name?.trim() || profile.email?.trim() || profile.id,
      role: profile.role?.trim() || null,
      organisation,
      workspace,
    });
    setIdentityStatus(
      orgResult.status === "fulfilled"
        && workspaceResult.status === "fulfilled"
        && (overviewResult.status === "fulfilled" || workspaces.length === 1)
        ? "ready"
        : "unavailable",
    );
  }, []);

  useEffect(() => {
    void refreshIdentity();
    const refresh = () => {
      void refreshIdentity();
    };
    window.addEventListener(CONTEXT_CHANGED_EVENT, refresh);
    return () => {
      window.removeEventListener(CONTEXT_CHANGED_EVENT, refresh);
    };
  }, [refreshIdentity]);

  const value = useMemo<WorkerGlobalContextValue>(() => ({
    identity,
    identityStatus,
  }), [identity, identityStatus]);

  return (
    <WorkerGlobalContext.Provider value={value}>
      {children}
    </WorkerGlobalContext.Provider>
  );
}

export function useWorkerGlobalContext(): WorkerGlobalContextValue {
  return useContext(WorkerGlobalContext);
}

export function notifyWorkerContextChanged(): void {
  window.dispatchEvent(new Event(CONTEXT_CHANGED_EVENT));
}
