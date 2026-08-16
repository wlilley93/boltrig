import {
  useCallback, useEffect, useRef, useState,
  type Dispatch, type SetStateAction,
} from "react";
import type {
  IntegrationCatalogueEntry,
  IntegrationConnection,
  IntegrationSecretFieldContract,
  UserProfile,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { voiceCatalogueEntries } from "./voiceProviderCatalogue";

const ADMIN_ROLES = new Set(["admin", "org-admin", "owner", "superadmin"]);

interface VoiceReadiness {
  entries: IntegrationCatalogueEntry[];
  connections: IntegrationConnection[];
}

interface VoiceCompletionContext {
  canConfigure: boolean;
  fields: Map<string, HTMLInputElement>;
  provider: string;
  readiness: VoiceReadiness | null;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setMessage: Dispatch<SetStateAction<string>>;
  setReadiness: Dispatch<SetStateAction<VoiceReadiness | null>>;
  started: boolean;
}

export function useVoiceSetup(profile: UserProfile) {
  const [readiness, setReadiness] = useState<VoiceReadiness | null>(null);
  const [provider, setProvider] = useState("");
  const [started, setStarted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const fields = useRef(new Map<string, HTMLInputElement>());
  const canConfigure = ADMIN_ROLES.has(profile.role ?? "");

  useEffect(() => {
    let active = true;
    void Promise.all([
      client.integrationCatalogue(),
      client.integrationConnections(),
    ]).then(([catalogue, connections]) => {
      if (!active) return;
      const entries = voiceCatalogueEntries(catalogue.integrations);
      setReadiness({ entries, connections: connections.connections });
      const existing = connections.connections.find((connection) => (
        connection.health !== "revoked"
        && entries.some((entry) => entry.id === connection.integration_id)
      ));
      const first = entries.find((entry) => entry.setup_supported) ?? entries[0];
      setProvider(existing?.integration_id ?? first?.id ?? "");
    }).catch(() => {
      if (active) setReadiness({ entries: [], connections: [] });
    });
    return () => { active = false; };
  }, []);

  const attachField = useCallback((name: string, element: HTMLInputElement | null) => {
    if (element) fields.current.set(name, element);
    else fields.current.delete(name);
  }, []);

  const selectProvider = useCallback((id: string) => {
    setProvider(id);
    setStarted(false);
    setMessage("");
    fields.current.clear();
  }, []);

  const completionContext: VoiceCompletionContext = {
    canConfigure, fields: fields.current, provider, readiness, setBusy, setMessage, setReadiness, started,
  };
  const complete = useCallback(
    () => completeVoiceSetup(completionContext),
    [canConfigure, provider, readiness, started],
  );

  const selected = readiness?.entries.find((entry) => entry.id === provider) ?? null;
  const connected = Boolean(readiness?.connections.some((connection) => (
    connection.integration_id === provider && connection.health !== "revoked"
  )));

  return {
    attachField,
    busy,
    canConfigure,
    complete,
    connected,
    message,
    provider,
    readiness,
    selectProvider,
    selected,
    setStarted,
    started,
  };
}

async function completeVoiceSetup(context: VoiceCompletionContext): Promise<boolean> {
  if (!context.started || !context.canConfigure) return true;
  const current = context.readiness;
  const entry = current?.entries.find((candidate) => candidate.id === context.provider);
  const contract = entry?.setup_contract;
  if (!current || !entry || !entry.setup_supported || contract?.kind !== "manual_secret") {
    context.setMessage("That voice service is not available on this Boltrig server.");
    return false;
  }
  if (current.connections.some((connection) => (
    connection.integration_id === context.provider && connection.health !== "revoked"
  ))) return true;

  const submitted = collectVoiceFields(contract.fields, context.fields, context.setMessage);
  if (!submitted) return false;
  clearSecretFields(contract.fields, context.fields);
  return saveVoiceEntry(context, entry, submitted);
}

function collectVoiceFields(
  contractFields: readonly IntegrationSecretFieldContract[],
  inputs: Map<string, HTMLInputElement>,
  setMessage: (message: string) => void,
): Record<string, string> | null {
  const submitted: Record<string, string> = {};
  for (const field of contractFields) {
    const input = inputs.get(field.name);
    const value = field.secret ? (input?.value ?? "") : (input?.value.trim() ?? "");
    if (field.required && !value) {
      setMessage(`Add ${field.label.toLocaleLowerCase()} or skip voice for now.`);
      return null;
    }
    if (value) submitted[field.name] = value;
  }
  return submitted;
}

function clearSecretFields(
  contractFields: readonly IntegrationSecretFieldContract[],
  inputs: Map<string, HTMLInputElement>,
) {
  for (const field of contractFields) {
    const input = inputs.get(field.name);
    if (field.secret && input) input.value = "";
  }
}

async function saveVoiceEntry(
  context: VoiceCompletionContext,
  entry: IntegrationCatalogueEntry,
  fields: Record<string, string>,
): Promise<boolean> {
  context.setBusy(true);
  context.setMessage("");
  try {
    const result = await client.submitIntegrationSecret(entry.id, { fields, label: entry.label });
    context.setReadiness((current) => current && {
      ...current,
      connections: [
        ...current.connections.filter((connection) => connection.id !== result.connection.id),
        result.connection,
      ],
    });
    context.setMessage(`${entry.label} saved.`);
    return true;
  } catch {
    context.setMessage("That voice service could not be saved. Check the details or skip for now.");
    return false;
  } finally {
    context.setBusy(false);
  }
}
