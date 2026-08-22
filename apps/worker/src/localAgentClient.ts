import { Channel, invoke } from "@tauri-apps/api/core";
import type {
  ApprovalPosture,
  ChatEvent,
  ChatMessage,
  ConversationSummary,
} from "@wlilley93/boltrig-web-sdk";

import { isDesktop } from "./desktop";

const STORAGE_KEY = "boltrig.local-conversations.v1";
const CHANGE_EVENT = "boltrig:local-conversations";
const LOCAL_PREFIX = "local:";
const MAX_STORED_BYTES = 8 * 1024 * 1024;
const MAX_CONVERSATIONS = 100;
const MAX_MESSAGES = 2_000;

export interface LocalAgentStatus {
  runtime: "local";
  state: "ready" | "unavailable";
  source: "bundled" | "development" | null;
  version: string | null;
  active: boolean;
  /** Whether the app-private runtime home holds a sign-in. A `ready` runtime
   * without one cannot start a local task. */
  signed_in: boolean;
  reason: string | null;
}

export type LocalAgentSignInEvent =
  | { type: "started" }
  | { type: "code"; url: string; code: string; opened: boolean }
  | { type: "completed" };

export interface LocalAgentSignInView {
  signed_in: boolean;
}

export type LocalAgentEvent =
  | { type: "message_start"; thread_id: string; turn_id: string; model: string }
  | { type: "text_delta"; delta: string }
  | { type: "reasoning_delta"; delta: string }
  | { type: "tool_started"; item_id: string; tool: string }
  | { type: "tool_completed"; item_id: string; tool: string; status: string }
  | { type: "approval_resolved"; item_id: string; decision: string }
  | { type: "message_end"; thread_id: string; turn_id: string; status: string }
  | { type: "cancelled"; thread_id: string | null; turn_id: string | null };

export interface LocalTurnOutcome {
  thread_id: string;
  turn_id: string;
  status: string;
  model: string;
}

export interface LocalAgentRoot {
  root_id: string;
}

export interface LocalAgentPosture {
  posture: ApprovalPosture;
}

export interface LocalConversation {
  id: string;
  thread_id: string;
  root_id: string;
  title: string;
  status: "active" | "closed";
  model: string;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
}

export async function localAgentStatus(): Promise<LocalAgentStatus> {
  if (!isDesktop) return unavailable("desktop_runtime_required");
  return invoke<LocalAgentStatus>("local_agent_status");
}

export async function localAgentRoots(): Promise<LocalAgentRoot[]> {
  if (!isDesktop) return [];
  return invoke<LocalAgentRoot[]>("local_agent_roots");
}

export async function localAgentPosture(): Promise<LocalAgentPosture> {
  if (!isDesktop) throw new Error("local_agent_requires_desktop");
  return invoke<LocalAgentPosture>("local_agent_posture");
}

export async function putLocalAgentPosture(
  posture: ApprovalPosture,
): Promise<LocalAgentPosture> {
  if (!isDesktop) throw new Error("local_agent_requires_desktop");
  return invoke<LocalAgentPosture>("put_local_agent_posture", {
    posture,
    confirm: posture === "full_access" ? "full_access" : null,
  });
}

export async function runLocalAgentTurn(
  input: {
    rootId: string;
    threadId?: string;
    message: string;
  },
  onEvent: (event: LocalAgentEvent) => void,
): Promise<LocalTurnOutcome> {
  if (!isDesktop) throw new Error("local_agent_requires_desktop");
  const channel = new Channel<LocalAgentEvent>();
  channel.onmessage = onEvent;
  return invoke<LocalTurnOutcome>("run_local_agent_turn", {
    request: {
      root_id: input.rootId,
      thread_id: input.threadId ?? null,
      message: input.message,
    },
    onEvent: channel,
  });
}

export async function stopLocalAgentTurn(): Promise<void> {
  if (!isDesktop) throw new Error("local_agent_requires_desktop");
  await invoke("stop_local_agent_turn");
}

export async function signInLocalAgent(
  onEvent: (event: LocalAgentSignInEvent) => void,
): Promise<LocalAgentSignInView> {
  if (!isDesktop) throw new Error("local_agent_requires_desktop");
  const channel = new Channel<LocalAgentSignInEvent>();
  channel.onmessage = onEvent;
  return invoke<LocalAgentSignInView>("local_agent_sign_in", { onEvent: channel });
}

export async function signOutLocalAgent(): Promise<LocalAgentSignInView> {
  if (!isDesktop) throw new Error("local_agent_requires_desktop");
  return invoke<LocalAgentSignInView>("local_agent_sign_out");
}

export function localConversationId(threadId: string): string {
  return `${LOCAL_PREFIX}${threadId}`;
}

export function localThreadId(conversationId: string | null): string | null {
  if (!conversationId?.startsWith(LOCAL_PREFIX)) return null;
  const threadId = conversationId.slice(LOCAL_PREFIX.length);
  return validId(threadId) ? threadId : null;
}

export function listLocalConversations(): ConversationSummary[] {
  return readStore().map(({ id, title, status, updated_at }) => ({
    id,
    title,
    status,
    updated_at,
  }));
}

export function loadLocalConversation(id: string): LocalConversation | null {
  return readStore().find((conversation) => conversation.id === id) ?? null;
}

export function saveLocalConversation(conversation: LocalConversation): void {
  if (!validConversation(conversation)) throw new Error("invalid_local_conversation");
  const current = readStore().filter((item) => item.id !== conversation.id);
  const next = [conversation, ...current]
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
    .slice(0, MAX_CONVERSATIONS);
  const encoded = JSON.stringify(next);
  if (encodedBytes(encoded) > MAX_STORED_BYTES) {
    throw new Error("local_conversation_store_full");
  }
  localStorage.setItem(STORAGE_KEY, encoded);
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function archiveLocalConversation(id: string): boolean {
  return setLocalConversationStatus(id, "closed");
}

export function restoreLocalConversation(id: string): boolean {
  return setLocalConversationStatus(id, "active");
}

function setLocalConversationStatus(
  id: string,
  status: LocalConversation["status"],
): boolean {
  if (!localThreadId(id)) return false;
  const current = readStore();
  const target = current.find((conversation) => conversation.id === id);
  if (!target || target.status === status) return false;
  const next = current.map((conversation) => conversation.id === id
    ? { ...conversation, status, updated_at: new Date().toISOString() }
    : conversation);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  window.dispatchEvent(new Event(CHANGE_EVENT));
  return true;
}

export function listenLocalConversations(handler: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, handler);
  return () => window.removeEventListener(CHANGE_EVENT, handler);
}

export function localEventToChatEvent(event: LocalAgentEvent): ChatEvent | null {
  return LOCAL_EVENT_PROJECTORS[event.type](event);
}

const LOCAL_EVENT_PROJECTORS: Record<
LocalAgentEvent["type"],
(event: LocalAgentEvent) => ChatEvent | null
> = {
  message_start: (event) => event.type === "message_start" ? {
      type: "message_start",
      conversation_id: localConversationId(event.thread_id),
      run_id: event.turn_id,
    } : null,
  text_delta: (event) => event.type === "text_delta"
    ? { type: "text_delta", delta: event.delta }
    : null,
  reasoning_delta: (event) => event.type === "reasoning_delta"
    ? { type: "reasoning_delta", delta: event.delta }
    : null,
  tool_started: (event) => event.type === "tool_started" ? {
      type: "tool_call",
      call_id: event.item_id,
      tool: event.tool,
      args_summary: { keys: [], count: 0 },
    } : null,
  tool_completed: (event) => event.type === "tool_completed" ? {
      type: "tool_result",
      call_id: event.item_id,
      verb: event.tool,
      status: event.status,
      result_summary: { keys: [], status: event.status },
    } : null,
  message_end: (event) => event.type === "message_end"
    ? { type: "message_end", run_id: event.turn_id }
    : null,
  cancelled: (event) => event.type === "cancelled" && event.turn_id
      ? { type: "cancelled", run_id: event.turn_id }
      : null,
  approval_resolved: () => null,
};

function readStore(): LocalConversation[] {
  let encoded: string | null;
  try {
    encoded = localStorage.getItem(STORAGE_KEY);
  } catch {
    return [];
  }
  if (!encoded || encodedBytes(encoded) > MAX_STORED_BYTES) return [];
  try {
    const parsed = JSON.parse(encoded) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(validConversation).slice(0, MAX_CONVERSATIONS);
  } catch {
    return [];
  }
}

function validConversation(value: unknown): value is LocalConversation {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return validConversationIdentity(candidate) && validConversationContent(candidate);
}

function validConversationIdentity(candidate: Record<string, unknown>): boolean {
  return typeof candidate.id === "string"
    && localThreadId(candidate.id) === candidate.thread_id
    && typeof candidate.thread_id === "string"
    && validId(candidate.thread_id)
    && typeof candidate.root_id === "string"
    && validId(candidate.root_id)
    && typeof candidate.title === "string"
    && candidate.title.length <= 240
    && (candidate.status === "active" || candidate.status === "closed");
}

function validConversationContent(candidate: Record<string, unknown>): boolean {
  return typeof candidate.model === "string"
    && candidate.model.length <= 180
    && Array.isArray(candidate.messages)
    && candidate.messages.length <= MAX_MESSAGES
    && candidate.messages.every(validMessage)
    && validDate(candidate.created_at)
    && validDate(candidate.updated_at);
}

function validMessage(value: unknown): value is ChatMessage {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.id === "string"
    && validId(candidate.id)
    && (candidate.role === "user" || candidate.role === "assistant")
    && typeof candidate.content === "string"
    && candidate.content.length <= 2 * 1024 * 1024
    && validDate(candidate.created_at)
    && (!candidate.run_id || validId(candidate.run_id))
    && (!candidate.events || (
      Array.isArray(candidate.events)
      && candidate.events.length <= 10_000
      && candidate.events.every(validStoredEvent)
    ));
}

function validStoredEvent(value: unknown): value is ChatEvent {
  if (!value || typeof value !== "object") return false;
  const event = value as Record<string, unknown>;
  if (typeof event.type !== "string") return false;
  return STORED_EVENT_VALIDATORS[event.type]?.(event) === true;
}

const STORED_EVENT_VALIDATORS: Record<
string,
(event: Record<string, unknown>) => boolean
> = {
  message_start: (event) => typeof event.conversation_id === "string"
    && localThreadId(event.conversation_id) !== null
    && validId(event.run_id),
  text_delta: validStoredDelta,
  reasoning_delta: validStoredDelta,
  tool_call: (event) => validId(event.call_id)
    && boundedLabel(event.tool, 180)
    && safeSummary(event.args_summary),
  tool_result: (event) => validId(event.call_id)
    && boundedLabel(event.verb, 180)
    && boundedLabel(event.status, 64)
    && safeSummary(event.result_summary),
  message_end: validStoredRunEvent,
  cancelled: validStoredRunEvent,
};

function validStoredDelta(event: Record<string, unknown>): boolean {
  return typeof event.delta === "string" && event.delta.length <= 256 * 1024;
}

function validStoredRunEvent(event: Record<string, unknown>): boolean {
  return validId(event.run_id);
}

function safeSummary(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const encoded = JSON.stringify(value);
  return encodedBytes(encoded) <= 4 * 1024;
}

function boundedLabel(value: unknown, max: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= max;
}

function validId(value: unknown): value is string {
  return typeof value === "string"
    && value.length > 0
    && value.length <= 180
    && /^[\x21-\x7e]+$/.test(value);
}

function validDate(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function encodedBytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function unavailable(reason: string): LocalAgentStatus {
  return {
    runtime: "local",
    state: "unavailable",
    source: null,
    version: null,
    active: false,
    signed_in: false,
    reason,
  };
}
