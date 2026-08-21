import { useState } from "react";
import {
  displayObjectTemplate,
  type DisplayObjectEnvelope,
} from "@wlilley93/boltrig-web-sdk";

import {
  CommunicationDraftCard,
  CommunicationReceiptCard,
} from "./CommunicationDraftCard";
import {
  DisplayConfirmationCard,
  DisplayObjectHeader,
  DisplayQuestionCard,
  type DisplayObjectReply,
} from "./DecisionDisplayCards";
import { DisplayObjectBlocks } from "./DisplayObjectBlocks";
import { blocksForObject, displayText } from "./displayObjectData";

export function DisplayObjectCard({ object, settled, onReply }: {
  object: DisplayObjectEnvelope;
  settled: boolean;
  onReply?: DisplayObjectReply;
}) {
  const template = displayObjectTemplate(object.kind);
  if (template.family === "communication") {
    return object.kind.endsWith(".draft")
      ? <CommunicationDraftCard object={object} onReply={onReply} settled={settled} />
      : <CommunicationReceiptCard object={object} />;
  }
  if (template.family === "question") {
    return <DisplayQuestionCard object={object} onReply={onReply} settled={settled} />;
  }
  if (template.family === "confirmation") {
    return <DisplayConfirmationCard object={object} onReply={onReply} settled={settled} />;
  }
  return <GenericDisplayCard object={object} onReply={onReply} settled={settled} />;
}

function GenericDisplayCard({ object, settled, onReply }: {
  object: DisplayObjectEnvelope;
  settled: boolean;
  onReply?: DisplayObjectReply;
}) {
  const [notice, setNotice] = useState("");
  const template = displayObjectTemplate(object.kind);
  const blocks = blocksForObject(object);
  const actions = (object.actions ?? []).filter((action) => (
    action.intent === "copy" || action.intent === "open" || action.intent === "reply" || action.intent === "retry"
  ));

  async function act(intent: "copy" | "open" | "reply" | "retry") {
    if (intent === "copy") {
      try {
        await navigator.clipboard.writeText(copyText(object));
        setNotice("Copied.");
      } catch {
        setNotice("Copy was not available.");
      }
      return;
    }
    if (intent === "open") return;
    if (!onReply || !settled) return;
    setNotice("Adding a new turn…");
    const restore = await onReply(`${intent === "retry" ? "Retry" : "Continue with"} “${object.title}” (display object ${object.id}, revision ${object.revision ?? 1}).`);
    setNotice(restore ? "The new turn was not added." : "Added as a new turn.");
  }

  return <section className="display-object-card" data-family={template.family}>
    <DisplayObjectHeader object={object} eyebrow={template.label} />
    <div className="display-object-body">
      <DisplayObjectBlocks blocks={blocks} />
      {blocks.length === 0 && <p className="muted small">No displayable fields were supplied.</p>}
      {actions.length > 0 && <div className="display-object-actions">{actions.map((action) => {
        const url = action.intent === "open" ? displayText(object.data, "url", "href") : "";
        if (action.intent === "open" && url) return <a className="secondary-button" href={url}
          key={action.id} rel="noreferrer" target="_blank">{action.label}</a>;
        return <button className={action.style === "primary" ? "primary-button" : "secondary-button"}
          disabled={(action.intent === "reply" || action.intent === "retry") && (!settled || !onReply)}
          key={action.id} onClick={() => void act(action.intent as "copy" | "reply" | "retry")}
          type="button">{action.label}</button>;
      })}</div>}
      {notice && <p className="muted small" role="status">{notice}</p>}
      {object.provenance && <details className="display-object-provenance">
        <summary>Source</summary>
        <p>{[
          object.provenance.provider,
          object.provenance.connection_label,
          object.provenance.source_label,
          object.provenance.agent_address ? `Agent ${object.provenance.agent_address}` : "",
        ].filter(Boolean).join(" · ") || "Recorded run context"}</p>
      </details>}
    </div>
  </section>;
}

function copyText(object: DisplayObjectEnvelope): string {
  const summary = displayText(object.data, "summary", "message", "text", "body");
  return summary ? `${object.title}\n${summary}` : object.title;
}
