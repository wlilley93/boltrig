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
import { providerApiBaseUrl, providerKeyOptional, providerNeedsBaseUrl } from "./providerCatalogue";

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
  modality: "text" | "vision";
  model: string;
  proposal: AiKeyProposalView | null;
  provider: string;
  readiness: ProviderReadiness | null;
  userId: string;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setKeyPresent: Dispatch<SetStateAction<boolean>>;
  setMessage: Dispatch<SetStateAction<string>>;
  setProposal: Dispatch<SetStateAction<AiKeyProposalView | null>>;
  setReadiness: Dispatch<SetStateAction<ProviderReadiness | null>>;
}

export function useProviderSetup(
  profile: UserProfile,
  modality: "text" | "vision" = "text",
) {
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
    void loadProviderReadiness(profile.id, modality).then((result) => {
      if (active) setReadiness(result);
    });
    return () => { active = false; };
  }, [profile.id, modality]);

  const completionContext: ProviderCompletionContext = {
    apiKeyInput, baseUrl, keyPresent, level, modality, model, proposal, provider, readiness,
    userId: profile.id,
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
      modality: context.modality,
      // A typed base URL always wins. Failing that, a non-native provider
      // submits the catalogue's published URL: the kernel binds it as an
      // OpenAI-compatible custom provider and cannot do so without an address.
      base_url: context.baseUrl.trim()
        || providerApiBaseUrl(context.provider.trim())
        || undefined,
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

/**
 * Confirm the key the kernel just accepted can actually reach its provider.
 *
 * A WRITE THAT SUCCEEDED IS NOT A PROVIDER THAT WORKS, and this step exists
 * because we shipped the version that assumed otherwise. Intake returning `ok`
 * means the secret was sealed, approved and stored - it says nothing about the
 * endpoint answering. A key saved on 2026-08-18 with base_url
 * `https://mac-mini-m1:11434` reported "Provider connected." and was dead:
 * Ollama serves plain HTTP on that port, so every request died in the TLS
 * handshake. The onboarding said connected, the model list stayed empty, and
 * nothing anywhere named the scheme.
 *
 * `gateway_ready` on /v1/ai-keys is the kernel asking Bifrost whether the
 * binding is usable, which is the question the user is actually asking. Read it
 * back and say which of the two things happened.
 *
 * A failed re-read is NOT reported as a dead provider: not knowing and knowing
 * it is broken are different answers, and only one of them should send someone
 * to check their endpoint. So an unreachable re-read lets the step pass, and
 * only a kernel that positively says `gateway_ready: false` holds it.
 *
 * Holding the step is the point. Returning true here would advance the wizard,
 * and OnboardingGate only renders this message while the step is on screen, so
 * a warning on the success path is a warning nobody reads. The instruction is
 * spelled out because the recovery needs the key typed again: the address is
 * part of the sealed intake, so changing it is a resubmit, not a retry.
 */
async function confirmGatewayReady(context: ProviderCompletionContext): Promise<boolean> {
  const refreshed = await loadProviderReadiness(context.userId, context.modality)
    .catch(() => null);
  if (!refreshed) {
    context.setMessage("Provider saved. We couldn't confirm it is reachable.");
    return true;
  }
  context.setReadiness(refreshed);
  if (refreshed.existingKey && !refreshed.existingKey.gateway_ready) {
    context.setMessage(
      "Provider saved, but it did not answer. Check the API address - a "
      + "self-hosted endpoint is usually http, not https - then re-enter your "
      + "key and select Continue.",
    );
    return false;
  }
  context.setMessage("Provider connected.");
  return true;
}

async function applyIntakeResult(context: ProviderCompletionContext, result: {
  status: string;
  reason?: string;
  proposal?: AiKeyProposalView;
}): Promise<boolean> {
  if (result.status === "ok") return confirmGatewayReady(context);
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
      return await confirmGatewayReady(context);
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
    // Was `setReadiness(... gateway_ready: true)`: the client asserting the very
    // fact it is supposed to be reading. Ask the kernel instead.
    return await confirmGatewayReady(context);
  } catch {
    context.setMessage("We couldn't connect the saved provider. Try again.");
    return false;
  } finally {
    context.setBusy(false);
  }
}

async function loadProviderReadiness(
  userId: string,
  modality: "text" | "vision",
): Promise<ProviderReadiness> {
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
      && (key.modality ?? "text") === modality
    )) ?? null,
  };
}
