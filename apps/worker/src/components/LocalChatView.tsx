import { useEffect, useRef, useState } from "react";
import {
  normalizeEvents,
  type ChatAttachmentLimits,
} from "@wlilley93/boltrig-web-sdk";

import {
  type LocalAgentRoot,
  type LocalAgentStatus,
} from "../localAgentClient";
import { Message, LiveTurn } from "./chat/ChatMessages";
import { Composer } from "./chat/Composer";
import { ThemeToggle } from "./chat/ThemeToggle";
import { TranscriptNavigation } from "./chat/TranscriptNavigation";
import {
  useLocalChatController,
  type LocalChatController,
  type LocalChatControllerProps,
} from "./chat/useLocalChatController";
import { useTranscriptViewport } from "./chat/useTranscriptViewport";
import { useReplySpeech } from "./chat/useReplySpeech";
import { Welcome } from "./chat/Welcome";
import "./chat/chat.css";
import "./chat/ChatViewParity.css";
import "./chat/LocalChatView.css";

const LOCAL_ATTACHMENT_LIMITS: ChatAttachmentLimits = {
  max_count: 0,
  max_bytes: 0,
  max_total_bytes: 0,
  model_readable_media_types: [],
};

interface LocalChatViewProps extends LocalChatControllerProps {
  onCommandPalette?(): void;
}

export function LocalChatView(props: LocalChatViewProps) {
  const [speechError, setSpeechError] = useState("");
  const replySpeech = useReplySpeech({
    conversationKey: props.conversationId,
    onActivity: () => undefined,
    onError: setSpeechError,
  });
  const controller = useLocalChatController({
    ...props,
    onReplyCompleted: replySpeech.readReply,
  });
  useEffect(() => setSpeechError(""), [props.conversationId]);
  const newTask = !props.conversationId;
  return <div className="chat-layout local-chat-layout" data-rail-collapsed="true">
    <main className="chat-main">
      {!newTask && <LocalChatHeader controller={controller} />}
      <LocalChatContent
        controller={controller}
        conversationId={props.conversationId}
        newTask={newTask}
        onCommandPalette={props.onCommandPalette}
        onPrimeSpeech={replySpeech.prime}
        speechError={speechError}
      />
    </main>
  </div>;
}

function LocalChatContent({
  controller,
  conversationId,
  newTask,
  onCommandPalette,
  onPrimeSpeech,
  speechError,
}: {
  controller: LocalChatController;
  conversationId: string | null;
  newTask: boolean;
  onCommandPalette?: () => void;
  onPrimeSpeech(): void;
  speechError: string;
}) {
  const live = normalizeEvents(controller.events);
  const transcript = useTranscriptViewport({
    conversationKey: conversationId,
    contentRevision: `${controller.messages.length}:${controller.events.length}:${live.text.length}:${controller.error}`,
  });
  const composer = <LocalComposer
    controller={controller}
    conversationId={conversationId}
    newTask={newTask}
    onCommandPalette={onCommandPalette}
    onPrimeSpeech={onPrimeSpeech}
  />;
  return <>
    <div
      aria-label="Local conversation transcript"
      className={newTask ? "transcript new-chat-transcript" : "transcript"}
      id="worker-local-conversation-transcript"
      onScroll={transcript.onTranscriptScroll}
      ref={transcript.transcriptRef}
      role="region"
      tabIndex={0}
    >
      {newTask && <Welcome>
        <LocalWorkspacePicker
          roots={controller.roots}
          rootId={controller.rootId}
          onRoot={controller.setRootId}
        />
        {composer}
      </Welcome>}
      {controller.messages.map((message) => (
        <Message key={message.id} message={message} tech={false}
          onDisplayReply={(text) => controller.send(text, [])} />
      ))}
      {controller.events.length > 0 && <LiveTurn
        events={controller.events}
        turn={live}
        tech={false}
        startedAt={null}
        onDisplayReply={(text) => controller.send(text, [])}
      />}
      {controller.error && <p className="notice" role="alert">{controller.error}</p>}
      {speechError && <p className="notice" role="status">{speechError}</p>}
    </div>
    {!newTask && <TranscriptNavigation
      model={transcript.navigation}
      transcriptId="worker-local-conversation-transcript"
    />}
    {!newTask && composer}
  </>;
}

function LocalComposer({
  controller,
  conversationId,
  newTask,
  onCommandPalette,
  onPrimeSpeech,
}: {
  controller: LocalChatController;
  conversationId: string | null;
  newTask: boolean;
  onCommandPalette?: () => void;
  onPrimeSpeech(): void;
}) {
  const draftRef = useRef<HTMLTextAreaElement>(null);
  return <Composer
    attachmentLimits={LOCAL_ATTACHMENT_LIMITS}
    attachmentsDisabled
    agentRuntime="local"
    agents={[]}
    agentAddress=""
    agentReady
    agentSelectionLocked
    busy={controller.busy}
    closed={false}
    conversationKey={conversationId}
    defaultModelAvailable={controller.ready}
    defaultModelUnavailableReason={localUnavailableReason(controller.status, controller.roots)}
    disabled={!controller.ready || Boolean(conversationId && !controller.conversation)}
    disabledPlaceholder={localDisabledPlaceholder(controller.status, controller.roots)}
    modelChoice=""
    modelChoices={[]}
    modelChoicesLoaded={controller.status !== null}
    modelSelectionLocked
    newContext={newTask}
    onChange={controller.setDraft}
    onCommandPalette={onCommandPalette}
    onModelChoice={() => undefined}
    onAgentAddress={() => undefined}
    onSend={(message, attachments) => {
      onPrimeSpeech();
      return controller.send(message, attachments);
    }}
    onStop={controller.stop}
    inputRef={draftRef}
    value={controller.draft}
  />;
}

function LocalChatHeader({ controller }: { controller: LocalChatController }) {
  return <header className="chat-header local-chat-header">
    <div className="agent-heading">
      <h1>{controller.conversation?.title ?? "Local task"}</h1>
      <span className="chat-header-sub">
        Local · {controller.conversation?.model || "Codex"}
      </span>
    </div>
    <ThemeToggle />
  </header>;
}

function LocalWorkspacePicker({ roots, rootId, onRoot }: {
  roots: LocalAgentRoot[];
  rootId: string;
  onRoot(value: string): void;
}) {
  if (roots.length === 0) return <p className="notice local-workspace-notice">
    Bind a read/write workspace with local commands enabled in Settings → Advanced.
  </p>;
  return <label className="local-workspace-picker">
    <span>Runs locally in</span>
    <select value={rootId} onChange={(event) => onRoot(event.target.value)}>
      {roots.map((root) => <option key={root.root_id} value={root.root_id}>
        Workspace · {root.root_id.slice(0, 12)}
      </option>)}
    </select>
  </label>;
}

function localUnavailableReason(
  status: LocalAgentStatus | null,
  roots: LocalAgentRoot[],
): string {
  if (!status) return "Checking the local agent";
  if (status.state !== "ready") return localStatusReason(status.reason);
  if (!status.signed_in) return "Sign in to the local runtime in Settings → Advanced";
  if (roots.length === 0) return "Bind a local workspace in Settings → Advanced";
  return "";
}

function localDisabledPlaceholder(
  status: LocalAgentStatus | null,
  roots: LocalAgentRoot[],
): string {
  if (!status) return "Checking the local agent…";
  return localUnavailableReason(status, roots) || "Loading local task…";
}

function localStatusReason(reason: string | null): string {
  if (reason === "local_agent_binary_not_bundled") {
    return "Local Codex is not included in this development build";
  }
  if (reason === "local_agent_binary_unavailable") {
    return "Local Codex could not be opened on this computer";
  }
  return reason ?? "Local agent unavailable";
}
