import { useEffect, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from "react";
import type {
  AiKeyLevel,
  AiKeyProposalView,
  AiKeyView,
  ChatModelChoicesResponse,
  UserProfile,
} from "@wlilley93/boltrig-web-sdk";

import { submitWriteOnlyAiKey } from "../../aiKeyIntake";
import { client } from "../../client";
import { providerKeyOptional, providerNeedsBaseUrl } from "./providerCatalogue";

interface ProviderReadiness {
  models: ChatModelChoicesResponse | null;
  allowOwn: boolean;
  keyCount: number;
  existingKey: AiKeyView | null;
}

const ADMIN_ROLES = new Set(["admin", "org-admin", "owner", "superadmin"]);

interface ProviderCompletionContext {
  apiKeyInput: RefObject<HTMLInputElement | null>;
  baseUrl: string;
  keyPresent: boolean;
  level: AiKeyLevel;
  model: string;
  proposal: AiKeyProposalView | null;
  provider: string;
  readiness: ProviderReadiness | null;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setKeyPresent: Dispatch<SetStateAction<boolean>>;
  setMessage: Dispatch<SetStateAction<string>>;
  setProposal: Dispatch<SetStateAction<AiKeyProposalView | null>>;
  setReadiness: Dispatch<SetStateAction<ProviderReadiness | null>>;
}

export function useProviderSetup(profile: UserProfile) {
  const [readiness, setReadiness] = useState<ProviderReadiness | null>(null);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [keyPresent, setKeyPresent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [proposal, setProposal] = useState<AiKeyProposalView | null>(null);
  const apiKeyInput = useRef<HTMLInputElement>(null);
  const isAdmin = ADMIN_ROLES.has(profile.role ?? "");
  const canAddKey = Boolean(readiness && (readiness.allowOwn || isAdmin));
  const level: AiKeyLevel = readiness?.allowOwn ? "user" : "org";

  useEffect(() => {
    let active = true;
    void loadProviderReadiness(profile.id).then((result) => {
      if (active) setReadiness(result);
    });
    return () => { active = false; };
  }, [profile.id]);

  const completionContext: ProviderCompletionContext = {
    apiKeyInput, baseUrl, keyPresent, level, model, proposal, provider, readiness,
    setBusy, setKeyPresent, setMessage, setProposal, setReadiness,
  };

  return {
    apiKeyInput, baseUrl, busy, canAddKey, keyPresent, message, model, provider, readiness,
    complete: () => completeProvider(completionContext),
    setBaseUrl, setKeyPresent, setModel, setProvider,
  };
}

async function completeProvider(context: ProviderCompletionContext): Promise<boolean> {
  if (context.proposal) return approveAndConnect(context, context.proposal);
  if (!context.keyPresent && !context.model.trim()) {
    const existing = context.readiness?.existingKey;
    return existing && !existing.gateway_ready ? activateExisting(context, existing) : true;
  }
  if (!providerInputIsComplete(context)) {
    context.setMessage("Choose a provider, add its key and pick a model to continue.");
    return false;
  }
  const input = context.apiKeyInput.current;
  if (!input || (!input.value && !providerKeyOptional(context.provider))) {
    context.setMessage("Add your API key to continue.");
    return false;
  }
  context.setBusy(true);
  context.setMessage("");
  try {
    const submission = submitWriteOnlyAiKey(input, {
      level: context.level,
      provider: context.provider.trim(),
      model: context.model.trim(),
      modality: "text",
      base_url: context.baseUrl.trim() || undefined,
    });
    context.setKeyPresent(false);
    return applyIntakeResult(context, await submission);
  } catch {
    context.setMessage("We couldn't connect that provider. Check the details and try again.");
    return false;
  } finally {
    context.setBusy(false);
  }
}

function providerInputIsComplete(context: ProviderCompletionContext): boolean {
  const keySatisfied = context.keyPresent || providerKeyOptional(context.provider);
  return keySatisfied
    && Boolean(context.model.trim())
    && (
      (context.provider !== "custom" && !providerNeedsBaseUrl(context.provider))
      || Boolean(context.baseUrl.trim())
    );
}

function applyIntakeResult(context: ProviderCompletionContext, result: {
  status: string;
  reason?: string;
  proposal?: AiKeyProposalView;
}): boolean {
  if (result.status === "ok") {
    context.setReadiness((current) => current && { ...current, keyCount: current.keyCount + 1 });
    context.setMessage("Provider connected.");
    return true;
  }
  if (result.status === "pending_human" && result.proposal) {
    context.setProposal(result.proposal);
    context.setMessage("Select Continue again to approve this provider and model.");
    return false;
  }
  context.setMessage(result.reason ?? "We couldn't connect that provider.");
  return false;
}

async function approveAndConnect(
  context: ProviderCompletionContext,
  current: AiKeyProposalView,
): Promise<boolean> {
  context.setBusy(true);
  context.setMessage("");
  try {
    const result = await client.approveAiKeyProposal(current.id);
    if (result.status === "ok") {
      context.setProposal(null);
      context.setReadiness((value) => value && { ...value, keyCount: value.keyCount + 1 });
      context.setMessage("Provider connected.");
      return true;
    }
    if (result.proposal) context.setProposal(result.proposal);
    context.setMessage(result.reason ?? "This provider connection still needs approval.");
    return false;
  } catch {
    context.setMessage("We couldn't finish connecting that provider. Try again.");
    return false;
  } finally {
    context.setBusy(false);
  }
}

async function activateExisting(
  context: ProviderCompletionContext,
  existing: AiKeyView,
): Promise<boolean> {
  context.setBusy(true);
  context.setMessage("");
  try {
    const result = await client.activateAiKey({
      level: existing.level,
      scope_id: existing.scope_id,
      modality: existing.modality ?? "text",
    });
    if (result.status !== "ok") {
      context.setMessage(result.reason ?? "We couldn't connect the saved provider.");
      return false;
    }
    context.setReadiness((value) => value && {
      ...value,
      existingKey: value.existingKey && { ...value.existingKey, gateway_ready: true },
    });
    context.setMessage("Provider connected.");
    return true;
  } catch {
    context.setMessage("We couldn't connect the saved provider. Try again.");
    return false;
  } finally {
    context.setBusy(false);
  }
}

async function loadProviderReadiness(userId: string): Promise<ProviderReadiness> {
  const [models, keys] = await Promise.all([
    client.chatModelChoices().catch(() => null),
    client.aiKeys().catch(() => null),
  ]);
  return {
    models,
    allowOwn: keys?.allow_own_ai_keys ?? false,
    keyCount: keys?.ai_keys?.length ?? 0,
    existingKey: keys?.ai_keys?.find((key) => (
      key.level === "user"
      && key.scope_id === userId
      && (key.modality ?? "text") === "text"
    )) ?? null,
  };
}
