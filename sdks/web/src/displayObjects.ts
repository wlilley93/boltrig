/** Closed, versioned visual objects that may appear inside a chat turn.
 *
 * Models never return JSX, HTML or JavaScript. They select one reviewed
 * template, fill bounded JSON data, and optionally compose `custom.card` from
 * the primitives below. Hosts validate the envelope again before rendering.
 */

export const DISPLAY_OBJECT_SCHEMA = "boltrig.display.v1" as const;

export const DISPLAY_OBJECT_TEMPLATES = [
  // Content and evidence.
  { kind: "content.markdown", family: "content", label: "Markdown" },
  { kind: "content.code", family: "content", label: "Code" },
  { kind: "content.image", family: "content", label: "Image" },
  { kind: "content.file", family: "content", label: "File" },
  { kind: "content.sources", family: "content", label: "Sources" },
  { kind: "content.gallery", family: "content", label: "Gallery" },
  { kind: "artifact.card", family: "content", label: "Artifact" },
  // Activity and system state.
  { kind: "status.notice", family: "status", label: "Notice" },
  { kind: "status.progress", family: "status", label: "Progress" },
  { kind: "status.steps", family: "status", label: "Steps" },
  { kind: "status.system", family: "status", label: "System state" },
  { kind: "status.feedback", family: "status", label: "Feedback" },
  { kind: "status.tool_receipt", family: "status", label: "Tool receipt" },
  { kind: "status.coordination", family: "status", label: "Coordination" },
  { kind: "status.execution_target", family: "status", label: "Execution target" },
  { kind: "status.screen_context", family: "status", label: "Screen context" },
  { kind: "status.computer_batch", family: "status", label: "Computer actions" },
  // Questions, forms, confirmation and approval presentation.
  { kind: "question.text", family: "question", label: "Question" },
  { kind: "question.single_select", family: "question", label: "Single choice" },
  { kind: "question.multi_select", family: "question", label: "Multiple choice" },
  { kind: "question.date", family: "question", label: "Date question" },
  { kind: "question.datetime", family: "question", label: "Date and time" },
  { kind: "question.person", family: "question", label: "Person picker" },
  { kind: "question.agent", family: "question", label: "Agent picker" },
  { kind: "question.connection", family: "question", label: "Connection picker" },
  { kind: "question.recipient", family: "question", label: "Recipient picker" },
  { kind: "question.file", family: "question", label: "File question" },
  { kind: "question.form", family: "question", label: "Form" },
  { kind: "question.rank", family: "question", label: "Ranking" },
  { kind: "confirmation.simple", family: "confirmation", label: "Confirmation" },
  { kind: "confirmation.destructive", family: "confirmation", label: "Destructive confirmation" },
  { kind: "confirmation.typed", family: "confirmation", label: "Typed confirmation" },
  { kind: "approval.action", family: "confirmation", label: "Approval summary" },
  // Structured data and visuals.
  { kind: "data.table", family: "data", label: "Table" },
  { kind: "data.key_value", family: "data", label: "Details" },
  { kind: "data.metrics", family: "data", label: "Metrics" },
  { kind: "data.chart", family: "data", label: "Chart" },
  { kind: "data.timeline", family: "data", label: "Timeline" },
  { kind: "data.map", family: "data", label: "Map" },
  { kind: "data.place", family: "data", label: "Place" },
  { kind: "data.diff", family: "data", label: "Comparison" },
  // Editable outbound communication and immutable receipts.
  { kind: "email.draft", family: "communication", label: "Email draft" },
  { kind: "email.sent", family: "communication", label: "Email" },
  { kind: "slack.message.draft", family: "communication", label: "Slack draft" },
  { kind: "slack.message.sent", family: "communication", label: "Slack message" },
  { kind: "teams.message.draft", family: "communication", label: "Teams draft" },
  { kind: "teams.message.sent", family: "communication", label: "Teams message" },
  { kind: "whatsapp.message.draft", family: "communication", label: "WhatsApp draft" },
  { kind: "whatsapp.message.sent", family: "communication", label: "WhatsApp message" },
  { kind: "telegram.message.draft", family: "communication", label: "Telegram draft" },
  { kind: "telegram.message.sent", family: "communication", label: "Telegram message" },
  { kind: "webhook.request.draft", family: "communication", label: "Webhook draft" },
  { kind: "webhook.request.sent", family: "communication", label: "Webhook request" },
  // Work and connected records.
  { kind: "ticket.issue", family: "record", label: "Issue" },
  { kind: "ticket.draft", family: "record", label: "Issue draft" },
  { kind: "calendar.event", family: "record", label: "Calendar event" },
  { kind: "calendar.event.draft", family: "record", label: "Calendar draft" },
  { kind: "contact.card", family: "record", label: "Contact" },
  { kind: "document.card", family: "record", label: "Document" },
  { kind: "opbox.entity", family: "record", label: "Opbox object" },
  { kind: "opbox.action", family: "record", label: "Opbox action" },
  { kind: "task.card", family: "record", label: "Task" },
  { kind: "routine.card", family: "record", label: "Routine" },
  // Safe novel composition.
  { kind: "custom.card", family: "custom", label: "Custom card" },
] as const;

export type DisplayObjectTemplate = typeof DISPLAY_OBJECT_TEMPLATES[number];
export type DisplayObjectKind = DisplayObjectTemplate["kind"];
export type DisplayObjectFamily = DisplayObjectTemplate["family"];

export type DisplayObjectStatus =
  | "draft" | "ready" | "pending" | "sending" | "sent"
  | "done" | "failed" | "cancelled" | "informational";

export type DisplayActionIntent =
  | "edit" | "change_recipient" | "send" | "discard"
  | "reply" | "submit" | "confirm" | "cancel"
  | "approve" | "reject" | "retry" | "open"
  | "download" | "copy";

export interface DisplayObjectAction {
  id: string;
  label: string;
  intent: DisplayActionIntent;
  style?: "primary" | "secondary" | "danger";
  requires_confirmation?: boolean;
}

export interface DisplayObjectProvenance {
  run_id?: string;
  agent_address?: string;
  provider?: string;
  connection_label?: string;
  source_label?: string;
}

export type DisplayFieldType =
  | "text" | "textarea" | "number" | "date" | "datetime"
  | "select" | "multi_select" | "person" | "agent"
  | "connection" | "recipient" | "checkbox" | "file";

export interface DisplayFieldOption {
  label: string;
  value: string;
}

export interface DisplayField {
  id: string;
  label: string;
  type: DisplayFieldType;
  value?: string | number | boolean | string[];
  options?: DisplayFieldOption[];
  placeholder?: string;
  required?: boolean;
  help?: string;
}

export type DisplayBlock =
  | { type: "text" | "markdown"; text: string }
  | { type: "code"; code: string; language?: string }
  | { type: "notice"; text: string; tone?: "neutral" | "info" | "warning" | "danger" | "success" }
  | { type: "divider" }
  | { type: "key_value"; items: Array<{ label: string; value: string }> }
  | { type: "metrics"; items: Array<{ label: string; value: string; change?: string }> }
  | { type: "table"; columns: string[]; rows: string[][] }
  | { type: "progress"; value: number; max?: number; label?: string }
  | { type: "steps"; items: Array<{ label: string; status?: string }> }
  | { type: "timeline"; items: Array<{ label: string; detail?: string; time?: string; status?: string }> }
  | { type: "chart"; chart?: "bar" | "line" | "donut"; series: Array<{ label: string; value: number; color?: string }> }
  | { type: "image"; url: string; alt: string; caption?: string }
  | { type: "gallery"; items: Array<{ url: string; alt: string; caption?: string }> }
  | { type: "diff"; before: string; after: string; label?: string }
  | { type: "source"; label: string; url?: string }
  | { type: "map"; latitude: number; longitude: number; label: string; zoom?: number };

export type DisplayJSON =
  | null | boolean | number | string | DisplayJSON[]
  | { [key: string]: DisplayJSON };

export interface DisplayObjectEnvelope {
  schema: typeof DISPLAY_OBJECT_SCHEMA;
  id: string;
  kind: DisplayObjectKind;
  title: string;
  subtitle?: string;
  status?: DisplayObjectStatus;
  revision?: number;
  data: Record<string, DisplayJSON>;
  fields?: DisplayField[];
  blocks?: DisplayBlock[];
  actions?: DisplayObjectAction[];
  provenance?: DisplayObjectProvenance;
}

const TEMPLATE_BY_KIND = new Map(
  DISPLAY_OBJECT_TEMPLATES.map((template) => [template.kind, template]),
);

export function displayObjectTemplate(kind: DisplayObjectKind): DisplayObjectTemplate {
  return TEMPLATE_BY_KIND.get(kind)!;
}

export function isDisplayObjectKind(value: unknown): value is DisplayObjectKind {
  return typeof value === "string" && TEMPLATE_BY_KIND.has(value as DisplayObjectKind);
}
