import { useMemo, useState } from "react";
import type {
  DisplayField,
  DisplayObjectEnvelope,
} from "@wlilley93/boltrig-web-sdk";

import { DisplayFields, initialFieldValues, type DisplayFieldValue } from "./DisplayFields";
import { DisplayObjectBlocks } from "./DisplayObjectBlocks";
import { displayStrings, displayText } from "./displayObjectData";

export type DisplayObjectReply = (message: string) => Promise<boolean>;

export function DisplayQuestionCard({ object, settled, onReply }: {
  object: DisplayObjectEnvelope;
  settled: boolean;
  onReply?: DisplayObjectReply;
}) {
  const fields = useMemo(() => questionFields(object), [object]);
  const [values, setValues] = useState(() => initialFieldValues(fields));
  const [phase, setPhase] = useState<"open" | "sending" | "sent" | "cancelled" | "failed">("open");
  const prompt = displayText(object.data, "prompt", "summary") || object.title;
  const canReply = settled && Boolean(onReply) && phase !== "sending" && phase !== "sent";

  async function submit() {
    if (!onReply || !canReply || !validFields(fields, values)) return;
    setPhase("sending");
    try {
      const restore = await onReply(questionReply(object, prompt, fields, values));
      setPhase(restore ? "failed" : "sent");
    } catch {
      setPhase("failed");
    }
  }

  return <section className="display-object-card display-object-decision" data-phase={phase}>
    <DisplayObjectHeader object={object} eyebrow="Question" />
    <div className="display-object-body">
      <p>{prompt}</p>
      {object.blocks?.length ? <DisplayObjectBlocks blocks={object.blocks} /> : null}
      {phase !== "cancelled" && <DisplayFields
        disabled={!canReply}
        fields={fields}
        onChange={(id, value) => setValues((current) => ({ ...current, [id]: value }))}
        values={values}
      />}
      {phase === "open" || phase === "failed" ? <div className="display-object-actions">
        <button className="primary-button" disabled={!canReply || !validFields(fields, values)}
          onClick={() => void submit()} type="button">Reply</button>
        <button className="secondary-button"
          onClick={() => setPhase("cancelled")} type="button">Cancel</button>
      </div> : null}
      <DecisionState phase={phase} settled={settled} />
    </div>
  </section>;
}

export function DisplayConfirmationCard({ object, settled, onReply }: {
  object: DisplayObjectEnvelope;
  settled: boolean;
  onReply?: DisplayObjectReply;
}) {
  const [typed, setTyped] = useState("");
  const [phase, setPhase] = useState<"open" | "sending" | "sent" | "cancelled" | "failed">("open");
  const summary = displayText(object.data, "summary", "message");
  const phrase = object.kind === "confirmation.typed" ? displayText(object.data, "phrase") : "";
  const canConfirm = settled && Boolean(onReply) && (!phrase || typed === phrase);

  async function confirm() {
    if (!onReply || !canConfirm) return;
    setPhase("sending");
    try {
      const restore = await onReply(confirmationReply(object, summary));
      setPhase(restore ? "failed" : "sent");
    } catch {
      setPhase("failed");
    }
  }

  return <section className="display-object-card display-object-decision" data-tone={
    object.kind === "confirmation.destructive" ? "danger" : "neutral"
  } data-phase={phase}>
    <DisplayObjectHeader object={object} eyebrow="Confirmation" />
    <div className="display-object-body">
      {summary && <p>{summary}</p>}
      {object.blocks?.length ? <DisplayObjectBlocks blocks={object.blocks} /> : null}
      {phrase && phase === "open" && <label className="display-object-typed">
        <span>Type <strong>{phrase}</strong> to continue</span>
        <input maxLength={200} onChange={(event) => setTyped(event.target.value)} value={typed} />
      </label>}
      {phase === "open" || phase === "failed" ? <div className="display-object-actions">
        <button className={object.kind === "confirmation.destructive" ? "danger-button" : "primary-button"}
          disabled={!canConfirm} onClick={() => void confirm()} type="button">Confirm</button>
        <button className="secondary-button" onClick={() => setPhase("cancelled")} type="button">Cancel</button>
      </div> : null}
      <DecisionState phase={phase} settled={settled} />
      <p className="display-object-governance">This records a new chat turn. Any consequential action still follows kernel policy and approval.</p>
    </div>
  </section>;
}

export function DisplayObjectHeader({ object, eyebrow }: {
  object: DisplayObjectEnvelope; eyebrow: string;
}) {
  return <header className="display-object-header">
    <div><span>{eyebrow}</span><strong>{object.title}</strong>
      {object.subtitle && <small>{object.subtitle}</small>}
    </div>
    {object.status && <span className="display-object-status" data-status={object.status}>{object.status}</span>}
  </header>;
}

function questionFields(object: DisplayObjectEnvelope): DisplayField[] {
  if (object.fields?.length) return object.fields;
  const options = displayStrings(object.data.options ?? object.data.choices)
    .map((value) => ({ label: value, value }));
  const preferred = QUESTION_FIELD_TYPES[object.kind] ?? "textarea";
  const type = options.length > 0 && preferred === "textarea" ? "select" : preferred;
  return [{ id: "answer", label: "Your answer", type, options, required: true }];
}

const QUESTION_FIELD_TYPES: Partial<Record<DisplayObjectEnvelope["kind"], DisplayField["type"]>> = {
  "question.single_select": "select",
  "question.multi_select": "multi_select",
  "question.date": "date",
  "question.datetime": "datetime",
  "question.person": "person",
  "question.agent": "agent",
  "question.connection": "connection",
  "question.recipient": "recipient",
  "question.file": "file",
};

function validFields(fields: DisplayField[], values: Record<string, DisplayFieldValue>): boolean {
  return fields.every((field) => !field.required || present(values[field.id]));
}

function present(value: DisplayFieldValue | undefined): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "string") return value.trim().length > 0;
  return value !== undefined && value !== false;
}

function questionReply(
  object: DisplayObjectEnvelope,
  prompt: string,
  fields: DisplayField[],
  values: Record<string, DisplayFieldValue>,
): string {
  const answers = fields.map((field) => `${field.label}: ${formatValue(values[field.id])}`).join("\n");
  return `Response to “${prompt}” (display object ${object.id}, revision ${object.revision ?? 1}):\n${answers}`;
}

function confirmationReply(object: DisplayObjectEnvelope, summary: string): string {
  return `I confirm “${object.title}” (display object ${object.id}, revision ${object.revision ?? 1}).${
    summary ? `\nReviewed summary: ${summary}` : ""
  }`;
}

function formatValue(value: DisplayFieldValue | undefined): string {
  return Array.isArray(value) ? value.join(", ") : String(value ?? "");
}

function DecisionState({ phase, settled }: {
  phase: "open" | "sending" | "sent" | "cancelled" | "failed"; settled: boolean;
}) {
  if (!settled && phase === "open") return <p className="muted small">Available when this response finishes.</p>;
  if (phase === "sending") return <p role="status">Adding your response…</p>;
  if (phase === "sent") return <p role="status">Response added as a new turn.</p>;
  if (phase === "cancelled") return <p className="muted small" role="status">Cancelled locally; nothing was sent.</p>;
  if (phase === "failed") return <p className="notice" role="alert">The response was not added. Review it and retry.</p>;
  return null;
}
