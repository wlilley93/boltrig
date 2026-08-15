import { useCallback, useEffect, useState } from "react";
import type {
  GovernedRouteResponse,
  OrganisationView,
  UpdateOrgResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { useExactApprovalFinalizer } from "../ExactApprovalFinalizer";

const OVERNIGHT_SETTING = "behaviour.overnight.enabled";

interface OvernightChange {
  enabled: boolean;
  expectedUpdatedAt: string | null;
  settings: Record<string, unknown>;
}

function useOrganisationSettings() {
  const [organisation, setOrganisation] = useState<OrganisationView | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const refresh = useCallback(async () => {
    try {
      const result = await client.currentOrg();
      setOrganisation(result.organisation);
      setState("ready");
    } catch {
      setState("unavailable");
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return { organisation, refresh, setOrganisation, state };
}

function useOvernightApproval(
  organisation: OrganisationView | null,
  refresh: () => Promise<void>,
  setMessage: (message: string) => void,
) {
  return useExactApprovalFinalizer<
    OvernightChange,
    GovernedRouteResponse<UpdateOrgResponse>
  >({
    isCurrent: (input) => Boolean(
      organisation
      && (organisation.updated_at ?? null) === input.expectedUpdatedAt
      && organisation.settings[OVERNIGHT_SETTING] !== input.enabled
    ),
    replay: (input, approvalId) => client.updateCurrentOrg(
      { settings: input.settings }, approvalId,
    ),
    isApplied: (result) => result.status === "ok" && "organisation" in result,
    onApplied: async () => { setMessage("Overnight updated."); await refresh(); },
    onRefused: (result) => setMessage(
      "reason" in result && result.reason
        ? result.reason
        : "The approved overnight change was not applied.",
    ),
    onUncertain: refresh,
  });
}

function useOvernightMutation(
  organisation: OrganisationView | null,
  setOrganisation: (value: OrganisationView) => void,
  finalizer: ReturnType<typeof useOvernightApproval>,
  setMessage: (message: string) => void,
) {
  const [busy, setBusy] = useState(false);
  const change = async (enabled: boolean) => {
    if (!organisation || busy) return;
    const input: OvernightChange = {
      enabled,
      expectedUpdatedAt: organisation.updated_at ?? null,
      settings: { ...organisation.settings, [OVERNIGHT_SETTING]: enabled },
    };
    setBusy(true);
    setMessage("");
    finalizer.invalidate();
    try {
      const result = await client.updateCurrentOrg({ settings: input.settings });
      if (finalizer.begin(input, result, "Overnight behaviour change")) {
        setMessage("Waiting for approval in the originating chat.");
      } else if (result.status === "ok" && "organisation" in result && result.organisation) {
        setOrganisation(result.organisation);
        setMessage("Overnight updated.");
      } else {
        setMessage("reason" in result && result.reason
          ? result.reason : "Overnight could not be changed.");
      }
    } catch {
      setMessage("Overnight could not be changed. Its last state is unchanged.");
    } finally {
      setBusy(false);
    }
  };
  return { busy, change };
}

export function useOvernightBehaviour() {
  const source = useOrganisationSettings();
  const [message, setMessage] = useState("");
  const finalizer = useOvernightApproval(source.organisation, source.refresh, setMessage);
  const mutation = useOvernightMutation(
    source.organisation, source.setOrganisation, finalizer, setMessage,
  );
  return {
    ...source,
    ...mutation,
    enabled: source.organisation?.settings[OVERNIGHT_SETTING] === true,
    finalizer,
    message,
  };
}
