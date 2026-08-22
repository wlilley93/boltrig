import {
  DISPLAY_OBJECT_SCHEMA,
  type DisplayActionIntent,
  type DisplayBlock,
  type DisplayField,
  type DisplayJSON,
  type DisplayObjectAction,
  type DisplayObjectEnvelope,
  type DisplayObjectProvenance,
  isDisplayObjectKind,
} from "./displayObjects.js";

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const ACTIONS = new Set<DisplayActionIntent>([
  "edit", "change_recipient", "send", "discard", "reply", "submit",
  "confirm", "cancel", "approve", "reject", "retry", "open",
  "download", "copy",
]);
const STATUSES = new Set([
  "draft", "ready", "pending", "sending", "sent", "done", "failed",
  "cancelled", "informational",
]);
const FIELD_TYPES = new Set([
  "text", "textarea", "number", "date", "datetime", "select",
  "multi_select", "person", "agent", "connection", "recipient",
  "checkbox", "file",
]);
const BLOCK_TYPES = new Set([
  "text", "markdown", "code", "notice", "divider", "key_value",
  "metrics", "table", "progress", "steps", "image", "source", "map",
  "timeline", "chart", "gallery", "diff",
]);
const MAX_BYTES = 65_536;

/** Parse untrusted JSON into the exact public display-object contract. */
export function parseDisplayObject(value: unknown): DisplayObjectEnvelope | null {
  if (!record(value) || value.schema !== DISPLAY_OBJECT_SCHEMA) return null;
  if (!ID.test(text(value.id, 128)) || !isDisplayObjectKind(value.kind)) return null;
  const title = text(value.title, 200);
  if (!title || !record(value.data) || !safeJSON(value.data)) return null;
  if (encodedBytes(value) > MAX_BYTES || !kindShape(value.kind, value.data)) return null;
  const subtitle = optionalText(value.subtitle, 400);
  const status = typeof value.status === "string" && STATUSES.has(value.status)
    ? value.status as DisplayObjectEnvelope["status"] : undefined;
  if (value.status !== undefined && !status) return null;
  const revision = integer(value.revision, 1, 1_000_000);
  if (value.revision !== undefined && revision === undefined) return null;
  const actions = optionalArray(value.actions, action, 8);
  const fields = optionalArray(value.fields, field, 24);
  const blocks = optionalArray(value.blocks, block, 32);
  const provenance = value.provenance === undefined
    ? undefined : provenanceOf(value.provenance);
  if (
    (value.actions !== undefined && !actions)
    || (value.fields !== undefined && !fields)
    || (value.blocks !== undefined && !blocks)
    || (value.provenance !== undefined && !provenance)
  ) return null;
  const result: DisplayObjectEnvelope = {
    schema: DISPLAY_OBJECT_SCHEMA,
    id: value.id as string,
    kind: value.kind,
    title,
    data: value.data as Record<string, DisplayJSON>,
  };
  if (subtitle) result.subtitle = subtitle;
  if (status) result.status = status;
  if (revision !== undefined) result.revision = revision;
  if (actions) result.actions = actions;
  if (fields) result.fields = fields;
  if (blocks) result.blocks = blocks;
  if (provenance) result.provenance = provenance;
  return result;
}

function action(value: unknown): DisplayObjectAction | null {
  if (!record(value)) return null;
  const id = text(value.id, 64);
  const label = text(value.label, 100);
  const intent = value.intent;
  if (!ID.test(id) || !label || typeof intent !== "string" || !ACTIONS.has(intent as DisplayActionIntent)) {
    return null;
  }
  const style = value.style;
  if (style !== undefined && !["primary", "secondary", "danger"].includes(String(style))) {
    return null;
  }
  if (value.requires_confirmation !== undefined && typeof value.requires_confirmation !== "boolean") {
    return null;
  }
  return {
    id, label, intent: intent as DisplayActionIntent,
    ...(style ? { style: style as DisplayObjectAction["style"] } : {}),
    ...(value.requires_confirmation === true ? { requires_confirmation: true } : {}),
  };
}

function field(value: unknown): DisplayField | null {
  if (!record(value)) return null;
  const id = text(value.id, 64);
  const label = text(value.label, 120);
  if (!ID.test(id) || !label || typeof value.type !== "string" || !FIELD_TYPES.has(value.type)) {
    return null;
  }
  if (value.required !== undefined && typeof value.required !== "boolean") return null;
  const raw = value.value;
  if (raw !== undefined && !fieldValue(raw)) return null;
  const options = value.options === undefined ? undefined
    : optionalArray(value.options, fieldOption, 50);
  if (value.options !== undefined && !options) return null;
  return {
    id, label, type: value.type as DisplayField["type"],
    ...(raw !== undefined ? { value: raw as DisplayField["value"] } : {}),
    ...(options ? { options } : {}),
    ...(optionalText(value.placeholder, 200) ? { placeholder: String(value.placeholder) } : {}),
    ...(value.required === true ? { required: true } : {}),
    ...(optionalText(value.help, 300) ? { help: String(value.help) } : {}),
  };
}

function fieldOption(value: unknown): { label: string; value: string } | null {
  if (!record(value)) return null;
  const label = text(value.label, 120);
  const optionValue = text(value.value, 200);
  return label && optionValue ? { label, value: optionValue } : null;
}

function block(value: unknown): DisplayBlock | null {
  if (!record(value) || typeof value.type !== "string" || !BLOCK_TYPES.has(value.type)) {
    return null;
  }
  if (!safeJSON(value) || !safeUrls(value) || !safeCoordinates(value) || !blockShape(value)) {
    return null;
  }
  return value as unknown as DisplayBlock;
}

function blockShape(value: Record<string, unknown>): boolean {
  switch (value.type) {
    case "text": case "markdown":
      return requiredDataText(value.text, 32_768);
    case "code":
      return requiredDataText(value.code, 32_768) && optionalDataText(value.language, 80);
    case "notice":
      return requiredDataText(value.text, 4_000)
        && optionalChoice(value.tone, ["neutral", "info", "warning", "danger", "success"]);
    case "divider":
      return true;
    case "key_value":
      return objectRows(value.items, 40, (item) => boundedText(item.label, 200)
        && boundedText(item.value, 4_000));
    case "metrics":
      return objectRows(value.items, 24, (item) => boundedText(item.label, 200)
        && boundedText(item.value, 1_000) && optionalDataText(item.change, 200));
    case "table":
      return stringRows(value.columns, 12, 200)
        && tableRows(value.rows, Array.isArray(value.columns) ? value.columns.length : 0);
    case "progress":
      return finite(value.value) && optionalPositive(value.max) && optionalDataText(value.label, 200);
    case "steps":
      return objectRows(value.items, 50, (item) => boundedText(item.label, 500)
        && optionalDataText(item.status, 80));
    case "timeline":
      return objectRows(value.items, 50, (item) => boundedText(item.label, 500)
        && optionalDataText(item.detail, 4_000) && optionalDataText(item.time, 120)
        && optionalDataText(item.status, 80));
    case "chart":
      return optionalChoice(value.chart, ["bar", "line", "donut"])
        && objectRows(value.series, 50, (item) => boundedText(item.label, 200)
          && finite(item.value) && optionalDataText(item.color, 80));
    case "image":
      return boundedText(value.url, 2_048) && boundedText(value.alt, 500)
        && optionalDataText(value.caption, 1_000);
    case "gallery":
      return objectRows(value.items, 24, (item) => boundedText(item.url, 2_048)
        && boundedText(item.alt, 500) && optionalDataText(item.caption, 1_000));
    case "diff":
      return fieldValueText(value.before, 32_768) && fieldValueText(value.after, 32_768)
        && optionalDataText(value.label, 200);
    case "source":
      return boundedText(value.label, 500) && optionalDataText(value.url, 2_048);
    case "map":
      return coordinate(value.latitude, -90, 90) && coordinate(value.longitude, -180, 180)
        && boundedText(value.label, 500) && optionalInteger(value.zoom, 0, 22);
    default:
      return false;
  }
}

function objectRows(
  value: unknown,
  max: number,
  validate: (item: Record<string, unknown>) => boolean,
): boolean {
  return Array.isArray(value) && value.length <= max
    && value.every((item) => record(item) && validate(item));
}

function stringRows(value: unknown, max: number, textMax: number): boolean {
  return Array.isArray(value) && value.length > 0 && value.length <= max
    && value.every((item) => boundedText(item, textMax));
}

function tableRows(value: unknown, columns: number): boolean {
  return Array.isArray(value) && value.length <= 100 && value.every((row) => (
    Array.isArray(row) && row.length <= columns && row.every((cell) => fieldValueText(cell, 4_000))
  ));
}

function optionalChoice(value: unknown, choices: readonly string[]): boolean {
  return value === undefined || (typeof value === "string" && choices.includes(value));
}

function optionalPositive(value: unknown): boolean {
  return value === undefined || (finite(value) && Number(value) > 0);
}

function optionalInteger(value: unknown, min: number, max: number): boolean {
  return value === undefined || integer(value, min, max) !== undefined;
}

function boundedText(value: unknown, max: number): boolean {
  return typeof value === "string" && value.length > 0 && value.length <= max;
}

function finite(value: unknown): boolean {
  return typeof value === "number" && Number.isFinite(value);
}

function provenanceOf(value: unknown): DisplayObjectProvenance | null {
  if (!record(value)) return null;
  const out: DisplayObjectProvenance = {};
  for (const [key, max] of [
    ["run_id", 128], ["agent_address", 128], ["provider", 80],
    ["connection_label", 160], ["source_label", 240],
  ] as const) {
    const item = optionalText(value[key], max);
    if (value[key] !== undefined && !item) return null;
    if (item) out[key] = item;
  }
  return out;
}

function kindShape(kind: DisplayObjectEnvelope["kind"], data: Record<string, unknown>): boolean {
  if (!safeUrls(data) || !safeCoordinates(data)) return false;
  if (kind === "email.draft") {
    return stringList(data.to, 50) && optionalDataText(data.subject, 500)
      && requiredDataText(data.body, 32_768);
  }
  if (kind.endsWith(".message.draft")) return requiredDataText(data.body ?? data.text, 32_768);
  if (kind.startsWith("question.")) return requiredDataText(data.prompt ?? data.summary, 4_000);
  if (kind.startsWith("confirmation.") || kind === "approval.action") {
    return requiredDataText(data.summary ?? data.message, 4_000)
      && (kind !== "confirmation.typed" || requiredDataText(data.phrase, 200));
  }
  if (kind === "data.map" || kind === "data.place") {
    return coordinate(data.latitude, -90, 90) && coordinate(data.longitude, -180, 180);
  }
  return true;
}

function safeJSON(value: unknown, depth = 0): value is DisplayJSON {
  if (value === null || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") return value.length <= 32_768;
  if (depth >= 6) return false;
  if (Array.isArray(value)) return value.length <= 100 && value.every((item) => safeJSON(item, depth + 1));
  if (!record(value) || Object.keys(value).length > 64) return false;
  return Object.entries(value).every(([key, item]) => key.length <= 80 && safeJSON(item, depth + 1));
}

function safeUrls(value: unknown): boolean {
  if (Array.isArray(value)) return value.every(safeUrls);
  if (!record(value)) return true;
  return Object.entries(value).every(([key, item]) => {
    if (/^(url|href|image_url)$/i.test(key) && typeof item === "string") {
      try {
        const parsed = new URL(item);
        return parsed.protocol === "https:" && Boolean(parsed.hostname)
          && !parsed.username && !parsed.password;
      } catch { return false; }
    }
    return safeUrls(item);
  });
}

function safeCoordinates(value: unknown): boolean {
  if (Array.isArray(value)) return value.every(safeCoordinates);
  if (!record(value)) return true;
  for (const [key, item] of Object.entries(value)) {
    if (/^(lat|latitude)$/i.test(key) && !coordinate(item, -90, 90)) return false;
    if (/^(lng|lon|longitude)$/i.test(key) && !coordinate(item, -180, 180)) return false;
    if (!safeCoordinates(item)) return false;
  }
  return true;
}

function optionalArray<T>(value: unknown, parse: (item: unknown) => T | null, max: number): T[] | null {
  if (!Array.isArray(value) || value.length > max) return null;
  const parsed = value.map(parse);
  return parsed.every((item): item is T => item !== null) ? parsed : null;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, max: number): string {
  return typeof value === "string" && value.length > 0 && value.length <= max ? value : "";
}

function optionalText(value: unknown, max: number): string | undefined {
  return value === undefined || value === null ? undefined : text(value, max) || undefined;
}

function integer(value: unknown, min: number, max: number): number | undefined {
  return Number.isInteger(value) && Number(value) >= min && Number(value) <= max
    ? Number(value) : undefined;
}

function fieldValue(value: unknown): boolean {
  return typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))
    || (typeof value === "string" && value.length <= 4_000)
    || (Array.isArray(value) && value.length <= 50 && value.every((item) => typeof item === "string" && item.length <= 200));
}

function fieldValueText(value: unknown, max: number): boolean {
  return typeof value === "string" && value.length <= max;
}

function requiredDataText(value: unknown, max: number): boolean {
  return fieldValueText(value, max) && String(value).trim().length > 0;
}

function optionalDataText(value: unknown, max: number): boolean {
  return value === undefined || fieldValueText(value, max);
}

function stringList(value: unknown, max: number): boolean {
  return (typeof value === "string" && value.length > 0 && value.length <= 320)
    || (Array.isArray(value) && value.length > 0 && value.length <= max
      && value.every((item) => typeof item === "string" && item.length > 0 && item.length <= 320));
}

function coordinate(value: unknown, min: number, max: number): boolean {
  return typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
}

function encodedBytes(value: unknown): number {
  try { return new TextEncoder().encode(JSON.stringify(value)).byteLength; } catch { return MAX_BYTES + 1; }
}
