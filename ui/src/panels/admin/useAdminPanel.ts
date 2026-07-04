import { useEffect, useState } from "react";

import { useIdentity } from "../../identity";
import { useRoute } from "../../router";
import { useAdminConfig, type AdminConfigState } from "./useAdminConfig";
import { useAdminSidebars, type AdminSidebarsState } from "./useAdminSidebars";
import { ADMIN_ROLES } from "./adminConstants";

export type AdminPanelState = {
  identity: ReturnType<typeof useIdentity>;
  isAdmin: boolean;
  view: string;
  setView: (view: string) => void;
} & AdminConfigState &
  AdminSidebarsState;

export function useAdminPanel(): AdminPanelState {
  const identity = useIdentity();
  const isAdmin = ADMIN_ROLES.has(identity.role);

  const route = useRoute();
  const routeView = route.segs[1] === "organisation" ? "organisation" : "config";
  const [view, setView] = useState<string>(routeView);
  useEffect(() => {
    setView(routeView);
  }, [routeView]);

  const config = useAdminConfig();
  const sidebars = useAdminSidebars();
  return { identity, isAdmin, view, setView, ...config, ...sidebars };
}
