import { useEffect, useState } from "react";
import type { KnowledgeMutationResponse, KnowledgeProvider } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  ExactApprovalFinalizer,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import {
  SettingsGroup,
  SettingsInfo,
  SettingsRow,
  SettingsToggle,
  StateWord,
  type Tone,
} from "./rowKit";

function providerTone(provider: KnowledgeProvider): { tone: Tone; state: string } {
  if (!provider.enabled) return { tone: "unknown", state: "off" };
  if (provider.health === "ok") return { tone: "green", state: "fine" };
  if (provider.health === "degraded") return { tone: "amber", state: "needs a model" };
  if (provider.health === "down") return { tone: "red", state: "down" };
  return { tone: "unknown", state: provider.health || "unknown" };
}

function providerDescription(provider: KnowledgeProvider): string | undefined {
  if (provider.health === "ok") return undefined;
  if (provider.id === "cognee" && provider.health === "degraded") {
    return "Cognee needs an AI model before it can enrich your knowledge.";
  }
  return provider.id === "cognee"
    ? "Builds useful links and context from your knowledge."
    : provider.role;
}

function useKnowledgeProviders() {
  const [providers, setProviders] = useState<KnowledgeProvider[] | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const refresh = async () => {
    try {
      const result = await client.knowledgeProviders();
      setProviders(result.providers ?? []);
      setState("ready");
    } catch {
      setState("unavailable");
    }
  };
  useEffect(() => { void refresh(); }, []);
  return { providers, refresh, setProviders, state };
}

export function KnowledgeToggle() {
  const source = useKnowledgeProviders();
  const [message, setMessage] = useState("");
  const finalizer = useExactApprovalFinalizer<
    { providerId: string; enabled: boolean },
    KnowledgeMutationResponse
  >({
    isCurrent: (input) => source.providers?.some((provider) => (
      provider.id === input.providerId && provider.enabled !== input.enabled
    )) ?? false,
    replay: (input, approvalId) => client.setKnowledgeProvider(
      input.providerId, input.enabled, approvalId,
    ),
    onApplied: async (_result, input) => {
      setMessage(`Provider ${input.enabled ? "enabled" : "disabled"}.`);
      await source.refresh();
    },
    onRefused: (result) => setMessage(
      result.reason ?? "The approved Knowledge provider change was not applied.",
    ),
    onUncertain: source.refresh,
  });
  return <KnowledgeToggleView
    finalizer={finalizer}
    message={message}
    providers={source.providers}
    refresh={source.refresh}
    setMessage={setMessage}
    state={source.state}
  />;
}

function KnowledgeToggleView(props: {
  finalizer: ReturnType<typeof useExactApprovalFinalizer<
    { providerId: string; enabled: boolean }, KnowledgeMutationResponse
  >>;
  message: string;
  providers: KnowledgeProvider[] | null;
  refresh(): Promise<void>;
  setMessage(message: string): void;
  state: "loading" | "ready" | "unavailable";
}) {
  if (props.state === "loading") return <p className="muted small">Reading memory…</p>;
  if (props.state === "unavailable" || props.providers === null) {
    return <p className="notice">Memory could not be read.</p>;
  }
  return (
    <>
      {props.message && <p className="console-foot" role="status">{props.message}</p>}
      <ExactApprovalFinalizer controller={props.finalizer} />
      <SettingsGroup>
        {props.providers.length === 0
          ? <SettingsRow title="Nothing configured" desc="Cognee is unavailable." />
          : props.providers.map((provider) => (
            <KnowledgeProviderRow key={provider.id} provider={provider} {...props} />
          ))}
      </SettingsGroup>
    </>
  );
}

function KnowledgeProviderRow(props: {
  provider: KnowledgeProvider;
  finalizer: ReturnType<typeof useExactApprovalFinalizer<
    { providerId: string; enabled: boolean }, KnowledgeMutationResponse
  >>;
  refresh(): Promise<void>;
  setMessage(message: string): void;
}) {
  const { provider } = props;
  const tone = providerTone(provider);
  const change = async (enabled: boolean) => {
    if (provider.status === "unavailable") return;
    props.setMessage("");
    props.finalizer.invalidate();
    const input = { providerId: provider.id, enabled };
    try {
      const result = await client.setKnowledgeProvider(provider.id, enabled);
      if (props.finalizer.begin(input, result, "Knowledge provider change")) {
        props.setMessage("Waiting for approval in the originating chat.");
      } else {
        props.setMessage(result.reason ?? `Provider ${enabled ? "enabled" : "disabled"}.`);
        if (result.status === "ok") await props.refresh();
      }
    } catch {
      props.setMessage(`${provider.display_name} could not be changed; the last reported state is unchanged.`);
    }
  };
  return <SettingsRow
    control={<div className="settings-status">
      <StateWord tone={tone.tone}>{tone.state}</StateWord>
      <SettingsInfo
        label={`About ${provider.display_name}`}
        text="Cognee connects related knowledge so Boltrig can recall it later. It uses the same server-side AI connection as chat; no key enters this page."
      />
      <SettingsToggle
        disabled={provider.status === "unavailable"}
        label={`${provider.enabled ? "Disable" : "Enable"} ${provider.display_name}`}
        on={provider.enabled}
        onToggle={(enabled) => void change(enabled)}
      />
    </div>}
    desc={providerDescription(provider)}
    title={provider.display_name}
  />;
}
