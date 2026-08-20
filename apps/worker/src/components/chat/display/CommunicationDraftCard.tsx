import { useEffect, useRef, useState } from "react";
import type { DisplayObjectEnvelope } from "@wlilley93/boltrig-web-sdk";

import { DisplayObjectHeader, type DisplayObjectReply } from "./DecisionDisplayCards";
import { displayStrings, displayText } from "./displayObjectData";

interface CommunicationDraft {
  provider: string;
  channelId: string;
  workspace: string;
  recipient: string;
  cc: string;
  subject: string;
  body: string;
  from: string;
  thread: string;
}

type DraftPhase = "draft" | "submitting" | "submitted" | "discarded" | "failed";

export function CommunicationReceiptCard({ object }: { object: DisplayObjectEnvelope }) {
  const draft = draftFrom(object);
  return <section className="display-object-card display-object-communication" data-phase="receipt">
    <DisplayObjectHeader object={object} eyebrow={`${draft.provider} message`} />
    <div className="display-object-body">
      <CommunicationFields draft={draft} editing={false} onChange={() => undefined}
        recipientRef={{ current: null }} />
      <p className="display-object-governance">This is a presentation receipt. Delivery truth comes from the recorded provider/tool status.</p>
    </div>
  </section>;
}

export function CommunicationDraftCard({ object, settled, onReply }: {
  object: DisplayObjectEnvelope;
  settled: boolean;
  onReply?: DisplayObjectReply;
}) {
  const [draft, setDraft] = useState(() => draftFrom(object));
  const [editing, setEditing] = useState(false);
  const [focusRecipient, setFocusRecipient] = useState(false);
  const [phase, setPhase] = useState<DraftPhase>("draft");
  const recipientRef = useRef<HTMLInputElement>(null);
  const intents = new Set((object.actions ?? []).map((action) => action.intent));

  useEffect(() => {
    if (!focusRecipient) return;
    recipientRef.current?.focus();
    recipientRef.current?.select();
    setFocusRecipient(false);
  }, [focusRecipient]);

  async function submit() {
    if (!onReply || !settled || !draft.recipient.trim() || !draft.body.trim()) return;
    setPhase("submitting");
    try {
      const restore = await onReply(sendInstruction(object, draft));
      setPhase(restore ? "failed" : "submitted");
    } catch {
      setPhase("failed");
    }
  }

  if (phase === "discarded") return <section className="display-object-card" data-phase="discarded">
    <DisplayObjectHeader object={object} eyebrow={`${draft.provider} draft`} />
    <p className="display-object-discarded">Discarded locally. No message was sent.</p>
  </section>;

  return <section className="display-object-card display-object-communication" data-phase={phase}>
    <DisplayObjectHeader object={object} eyebrow={`${draft.provider} draft`} />
    <div className="display-object-body">
      <CommunicationFields draft={draft} editing={editing} onChange={setDraft} recipientRef={recipientRef} />
      <CommunicationDraftActions draft={draft} editing={editing} hasReply={Boolean(onReply)}
        intents={intents} onDiscard={() => setPhase("discarded")} onEdit={() => setEditing((value) => !value)}
        onRecipient={() => { setEditing(true); setFocusRecipient(true); }} onSubmit={() => void submit()}
        phase={phase} settled={settled} />
      <DraftNotices phase={phase} settled={settled} />
      <p className="display-object-governance">Send creates an exact new turn; the agent must use the ordinary governed provider tool and any required approval.</p>
    </div>
  </section>;
}

function CommunicationDraftActions({
  draft, editing, hasReply, intents, onDiscard, onEdit, onRecipient, onSubmit, phase, settled,
}: {
  draft: CommunicationDraft; editing: boolean; hasReply: boolean; intents: Set<string>;
  onDiscard(): void; onEdit(): void; onRecipient(): void; onSubmit(): void;
  phase: DraftPhase; settled: boolean;
}) {
  const sendDisabled = !settled || !hasReply || phase === "submitting" || phase === "submitted"
    || !draft.recipient.trim() || !draft.body.trim();
  return <div className="display-object-actions">
    {intents.has("edit") && <button className="secondary-button" onClick={onEdit} type="button">
      {editing ? "Preview" : "Edit"}
    </button>}
    {intents.has("change_recipient") && <button className="secondary-button"
      onClick={onRecipient} type="button">Change recipient</button>}
    {intents.has("send") && <button className="primary-button" disabled={sendDisabled}
      onClick={onSubmit} type="button">{phase === "submitting" ? "Submitting…" : "Send"}</button>}
    {intents.has("discard") && <button className="secondary-button"
      disabled={phase === "submitting" || phase === "submitted"} onClick={onDiscard} type="button">Discard</button>}
  </div>;
}

function DraftNotices({ phase, settled }: { phase: DraftPhase; settled: boolean }) {
  return <>
    {!settled && <p className="muted small">Actions unlock when this response finishes.</p>}
    {phase === "submitted" && <p className="display-object-result" role="status">
      Send request added as a new turn. Delivery is not claimed until the governed provider receipt arrives.
    </p>}
    {phase === "failed" && <p className="notice" role="alert">
      The send request was not added. Review the draft and retry.
    </p>}
  </>;
}

function CommunicationFields({ draft, editing, onChange, recipientRef }: {
  draft: CommunicationDraft;
  editing: boolean;
  onChange(value: CommunicationDraft): void;
  recipientRef: React.RefObject<HTMLInputElement | null>;
}) {
  if (!editing) return <div className="display-object-message-preview">
    <dl>
      {draft.workspace && <div><dt>Workspace</dt><dd>{draft.workspace}</dd></div>}
      {draft.from && <div><dt>From</dt><dd>{draft.from}</dd></div>}
      <div><dt>To</dt><dd>{draft.recipient}</dd></div>
      {draft.cc && <div><dt>Cc</dt><dd>{draft.cc}</dd></div>}
      {draft.subject && <div><dt>Subject</dt><dd>{draft.subject}</dd></div>}
      {draft.thread && <div><dt>Thread</dt><dd>{draft.thread}</dd></div>}
    </dl>
    <p>{draft.body}</p>
  </div>;
  return <div className="display-object-fields display-object-draft-fields">
    <label><span>Recipient</span><input ref={recipientRef} maxLength={2_000} value={draft.recipient}
      onChange={(event) => onChange({ ...draft, recipient: event.target.value })} /></label>
    {draft.provider === "Email" && <>
      <label><span>Cc</span><input maxLength={2_000} value={draft.cc}
        onChange={(event) => onChange({ ...draft, cc: event.target.value })} /></label>
      <label><span>Subject</span><input maxLength={500} value={draft.subject}
        onChange={(event) => onChange({ ...draft, subject: event.target.value })} /></label>
    </>}
    <label><span>Message</span><textarea maxLength={32_768} rows={8} value={draft.body}
      onChange={(event) => onChange({ ...draft, body: event.target.value })} /></label>
  </div>;
}

function draftFrom(object: DisplayObjectEnvelope): CommunicationDraft {
  const data = object.data;
  return {
    provider: providerName(object.kind),
    channelId: displayText(data, "channel_id", "connection_id"),
    workspace: displayText(data, "workspace_label", "workspace"),
    recipient: displayStrings(data.to).join(", ") || displayText(data, "recipient", "target", "to"),
    cc: displayStrings(data.cc).join(", "),
    subject: displayText(data, "subject"),
    body: displayText(data, "body", "text"),
    from: displayText(data, "from", "from_user"),
    thread: displayText(data, "thread_label", "thread"),
  };
}

function providerName(kind: DisplayObjectEnvelope["kind"]): string {
  if (kind.startsWith("email.")) return "Email";
  if (kind.startsWith("slack.")) return "Slack";
  if (kind.startsWith("teams.")) return "Teams";
  if (kind.startsWith("whatsapp.")) return "WhatsApp";
  if (kind.startsWith("telegram.")) return "Telegram";
  if (kind.startsWith("webhook.")) return "Webhook";
  return "Message";
}

function sendInstruction(object: DisplayObjectEnvelope, draft: CommunicationDraft): string {
  const lines = [
    `Send this exact ${draft.provider} draft (display object ${object.id}, revision ${object.revision ?? 1}).`,
    draft.channelId ? `Connection/channel id: ${draft.channelId}` : "",
    draft.workspace ? `Workspace: ${draft.workspace}` : "",
    draft.from ? `From: ${draft.from}` : "",
    `Recipient: ${draft.recipient}`,
    draft.cc ? `Cc: ${draft.cc}` : "",
    draft.subject ? `Subject: ${draft.subject}` : "",
    draft.thread ? `Thread: ${draft.thread}` : "",
    "Message body:", draft.body,
    "Use the normal governed provider tool. Do not claim delivery without its receipt.",
  ];
  return lines.filter(Boolean).join("\n");
}
