import { useState } from "react";

import { api } from "../../api/client";
import type { CredentialRef } from "../../api/types";
import { errText } from "../shared";

export interface AdminSidebarsState {
  exported: unknown;
  exportError: string | null;
  creds: CredentialRef[] | null;
  credsError: string | null;
  exportManifest: () => Promise<void>;
  loadCredentials: () => Promise<void>;
}

export function useAdminSidebars(): AdminSidebarsState {
  const [exported, setExported] = useState<unknown>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [creds, setCreds] = useState<CredentialRef[] | null>(null);
  const [credsError, setCredsError] = useState<string | null>(null);

  async function exportManifest() {
    setExportError(null);
    setExported(null);
    try {
      const res = await api.configExport();
      if (res.error) setExportError(res.error);
      else setExported(res.manifest ?? {});
    } catch (err) {
      setExportError(errText(err));
    }
  }

  async function loadCredentials() {
    setCredsError(null);
    setCreds(null);
    try {
      const res = await api.adminCredentials();
      if (res.error) setCredsError(res.error);
      else setCreds(res.credentials ?? []);
    } catch (err) {
      setCredsError(errText(err));
    }
  }

  return { exported, exportError, creds, credsError, exportManifest, loadCredentials };
}
