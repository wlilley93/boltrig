import { useEffect, useState, type RefObject } from "react";
import type {
  ChatAttachment,
  ChatEvent,
  ChatMessage,
  NamedAgentView,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  consumePendingChatAgent,
  PENDING_CHAT_AGENT_EVENT,
} from "./pendingChatTarget";

export function useChatAgentSelection(selectedConversationRef: RefObject<string | null>) {
  const [namedAgents, setNamedAgents] = useState<NamedAgentView[]>([]);
  const [agentAddress, setAgentAddress] = useState("");
  const [catalogueLoaded, setCatalogueLoaded] = useState(false);

  useEffect(() => {
    if (typeof client.namedAgents !== "function") {
      setCatalogueLoaded(true);
      return;
    }
    let cancelled = false;
    void client.namedAgents().then((result) => {
      if (cancelled) return;
      setNamedAgents(result.named_agents);
      setAgentAddress((current) => current || defaultAgent(result.named_agents));
      setCatalogueLoaded(true);
    }).catch(() => { if (!cancelled) setCatalogueLoaded(true); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const applyPendingAgent = (event: Event) => {
      if (selectedConversationRef.current) return;
      const address = (event as CustomEvent<unknown>).detail;
      if (typeof address === "string") setAgentAddress(address);
    };
    window.addEventListener(PENDING_CHAT_AGENT_EVENT, applyPendingAgent);
    return () => window.removeEventListener(PENDING_CHAT_AGENT_EVENT, applyPendingAgent);
  }, [selectedConversationRef]);

  const ready = namedAgents.length === 0 || namedAgents.some(
    (agent) => agent.address === agentAddress && agent.enabled,
  );
  return {
    address: agentAddress,
    adopt: (address?: string | null) => setAgentAddress(
      (current) => address || current || defaultAgent(namedAgents),
    ),
    catalogueLoaded,
    composerProps: (locked: boolean) => ({
      agents: namedAgents,
      agentAddress,
      agentReady: !catalogueLoaded || ready,
      agentSelectionLocked: locked,
      onAgentAddress: setAgentAddress,
    }),
    label: (address?: string | null, prefix = "") => agentLabel(address, namedAgents, prefix),
    messageLabel: (message: ChatMessage) => message.role === "user"
      ? agentLabel(message.recipient_agent_address, namedAgents, "To")
      : agentLabel(message.author_agent_address, namedAgents, ""),
    namedAgents,
    observeEvent: (event: ChatEvent) => {
      if (event.type === "message_start" && event.agent_address) {
        setAgentAddress(event.agent_address);
      }
      return event;
    },
    queuedUserMessage: (
      id: string,
      content: string,
      attachments: ChatAttachment[],
      admittedAddress?: string | null,
    ) => queuedUserMessage(id, content, attachments, admittedAddress, agentAddress),
    ready,
    requestAddress: agentAddress || undefined,
    reset: (conversationId: string | null, ownsLiveStream: boolean) => {
      if (!ownsLiveStream) setAgentAddress(conversationId ? "" : consumePendingChatAgent());
    },
    select: setAgentAddress,
  };
}

export function chatSelectionError(
  agent: { catalogueLoaded: boolean; ready: boolean },
  input: {
  defaultModelAvailable: boolean;
  modelChoice: string;
  modelChoices: ReadonlyArray<{ id: string; available: boolean }>;
  modelChoicesLoaded: boolean;
  },
): string {
  const selectedModelAvailable = input.modelChoice
    ? input.modelChoices.some((choice) => choice.id === input.modelChoice && choice.available)
    : input.defaultModelAvailable;
  if (!input.modelChoicesLoaded || !selectedModelAvailable) {
    return "Choose an available model in the composer before sending.";
  }
  return agent.catalogueLoaded && !agent.ready
    ? "Choose an available agent in the composer before sending."
    : "";
}

function queuedUserMessage(
  id: string,
  content: string,
  attachments: ChatAttachment[],
  admittedAddress: string | null | undefined,
  selectedAddress: string,
): ChatMessage {
  return {
    id,
    role: "user",
    content,
    recipient_agent_address: (admittedAddress ?? selectedAddress) || undefined,
    attachments,
    created_at: new Date().toISOString(),
  };
}

function defaultAgent(agents: readonly NamedAgentView[]): string {
  return agents.find((agent) => agent.enabled && agent.default_for_intake)?.address ?? "";
}

function agentLabel(
  address: string | null | undefined,
  agents: readonly NamedAgentView[],
  prefix: string,
): string | undefined {
  if (!address) return undefined;
  const name = agents.find((agent) => agent.address === address)?.name
    ?? address.split("-").map((part) => part
      ? `${part[0]!.toUpperCase()}${part.slice(1)}`
      : part).join(" ");
  return prefix ? `${prefix} ${name}` : name;
}
