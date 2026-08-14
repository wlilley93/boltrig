import { useEffect, useRef, useState } from "react";
import type {
  AiKeyLevel,
  ChatModelChoicesResponse,
  UserProfile,
} from "@wlilley93/boltrig-web-sdk";

import { submitWriteOnlyAiKey } from "../../aiKeyIntake";
import { client } from "../../client";

interface ProviderReadiness {
  models: ChatModelChoicesResponse | null;
  allowOwn: boolean;
  keyCount: number;
}

const ADMIN_ROLES = new Set(["admin", "org-admin", "owner", "superadmin"]);

export function useProviderSetup(profile: UserProfile) {
  const [readiness, setReadiness] = useState<ProviderReadiness | null>(null);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const apiKeyInput = useRef<HTMLInputElement>(null);
  const isAdmin = ADMIN_ROLES.has(profile.role ?? "");
  const canAddKey = Boolean(readiness?.allowOwn || isAdmin);
  const level: AiKeyLevel = readiness?.allowOwn ? "user" : "org";

  useEffect(() => {
    let active = true;
    void loadProviderReadiness().then((result) => {
      if (active) setReadiness(result);
    });
    return () => { active = false; };
  }, []);

  async function saveKey(event: React.FormEvent) {
    event.preventDefault();
    const input = apiKeyInput.current;
    if (!input?.value || !model.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await submitWriteOnlyAiKey(input, {
        level,
        provider: provider.trim(),
        model: model.trim(),
        base_url: baseUrl.trim() || undefined,
      });
      applyIntakeResult(result.status, result.reason);
    } catch {
      setMessage("The result is unavailable. The entered key was cleared and is not retained here.");
    } finally {
      setBusy(false);
    }
  }

  function applyIntakeResult(status: string, reason?: string) {
    if (status === "ok") {
      setReadiness((current) => current && { ...current, keyCount: current.keyCount + 1 });
      setMessage("Key sealed. Boltrig cannot retrieve or display it.");
    } else if (status === "pending_human") {
      setMessage("Key sealed and waiting for approval. You can finish setup now.");
    } else {
      setMessage(reason ?? "The key could not be installed.");
    }
  }

  return {
    apiKeyInput, baseUrl, busy, canAddKey, message, model, provider, readiness,
    saveKey, setBaseUrl, setModel, setProvider,
  };
}

async function loadProviderReadiness(): Promise<ProviderReadiness> {
  const [models, keys] = await Promise.all([
    client.chatModelChoices().catch(() => null),
    client.aiKeys().catch(() => null),
  ]);
  return {
    models,
    allowOwn: keys?.allow_own_ai_keys ?? false,
    keyCount: keys?.ai_keys?.length ?? 0,
  };
}
