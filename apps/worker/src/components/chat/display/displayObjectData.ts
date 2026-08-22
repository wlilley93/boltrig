import type {
  DisplayBlock,
  DisplayJSON,
  DisplayObjectEnvelope,
} from "@wlilley93/boltrig-web-sdk";

export function displayText(data: Record<string, DisplayJSON>, ...keys: string[]): string {
  for (const key of keys) {
    const value = data[key];
    if (typeof value === "string") return value;
  }
  return "";
}

export function displayNumber(data: Record<string, DisplayJSON>, key: string): number | null {
  const value = data[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function displayStrings(value: DisplayJSON | undefined): string[] {
  if (typeof value === "string") return [value];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

export function displayRecords(value: DisplayJSON | undefined): Array<Record<string, DisplayJSON>> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, DisplayJSON> => (
    item !== null && typeof item === "object" && !Array.isArray(item)
  ));
}

export function blocksForObject(object: DisplayObjectEnvelope): DisplayBlock[] {
  if (object.blocks?.length) return object.blocks;
  const data = object.data;
  const build = BLOCK_BUILDERS[object.kind];
  if (build) return build(data);
  const summary = displayText(data, "summary", "message", "description", "text", "body");
  return summary ? [{ type: "text", text: summary }] : keyValueFallback(data);
}

type BlockBuilder = (data: Record<string, DisplayJSON>) => DisplayBlock[];

const BLOCK_BUILDERS: Partial<Record<DisplayObjectEnvelope["kind"], BlockBuilder>> = {
  "content.markdown": markdownBlocks,
  "content.code": codeBlocks,
  "content.image": imageBlocks,
  "content.gallery": galleryBlocks,
  "content.sources": sourceBlocks,
  "data.table": tableBlocks,
  "data.key_value": keyValueBlocks,
  "data.metrics": metricBlocks,
  "data.chart": chartBlocks,
  "data.timeline": timelineBlocks,
  "data.map": mapBlocks,
  "data.place": mapBlocks,
  "data.diff": diffBlocks,
  "status.progress": progressBlocks,
  "status.steps": stepBlocks,
  "status.computer_batch": stepBlocks,
};

function markdownBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  return [{ type: "markdown", text: displayText(data, "markdown", "text", "content") }];
}

function codeBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const language = displayText(data, "language");
  return [{ type: "code", code: displayText(data, "code", "text"), ...(language ? { language } : {}) }];
}

function imageBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const url = displayText(data, "url", "image_url");
  if (!url) return [];
  return [{
    type: "image", url, alt: displayText(data, "alt") || "Attached image",
    ...(displayText(data, "caption") ? { caption: displayText(data, "caption") } : {}),
  }];
}

function galleryBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const items = displayRecords(data.items).flatMap((item) => {
    const url = displayText(item, "url", "image_url");
    return url ? [{
      url, alt: displayText(item, "alt") || "Gallery image",
      ...(displayText(item, "caption") ? { caption: displayText(item, "caption") } : {}),
    }] : [];
  });
  return items.length ? [{ type: "gallery", items }] : [];
}

function sourceBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  return displayRecords(data.sources).slice(0, 20).map((item) => ({
    type: "source" as const,
    label: displayText(item, "label", "title") || "Source",
    ...(displayText(item, "url", "href") ? { url: displayText(item, "url", "href") } : {}),
  }));
}

function tableBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const columns = displayStrings(data.columns).slice(0, 12);
  const rows = Array.isArray(data.rows)
    ? data.rows.slice(0, 100).map((row) => Array.isArray(row)
      ? row.slice(0, columns.length || 12).map(cellText) : [])
    : [];
  return columns.length ? [{ type: "table", columns, rows }] : [];
}

function keyValueBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const items = displayRecords(data.items).slice(0, 40).map((item) => ({
    label: displayText(item, "label", "key"), value: displayText(item, "value"),
  })).filter((item) => item.label);
  return items.length ? [{ type: "key_value", items }] : keyValueFallback(data);
}

function metricBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const items = displayRecords(data.items).slice(0, 12).map((item) => ({
    label: displayText(item, "label"), value: cellText(item.value),
    ...(displayText(item, "change") ? { change: displayText(item, "change") } : {}),
  })).filter((item) => item.label);
  return items.length ? [{ type: "metrics", items }] : [];
}

function chartBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const series = displayRecords(data.series).slice(0, 24).flatMap((item) => {
    const value = typeof item.value === "number" ? item.value : null;
    const label = displayText(item, "label", "name");
    return value !== null && label ? [{ label, value }] : [];
  });
  const chart = displayText(data, "chart", "type");
  return series.length ? [{
    type: "chart", series,
    ...(["bar", "line", "donut"].includes(chart) ? { chart: chart as "bar" | "line" | "donut" } : {}),
  }] : [];
}

function timelineBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const items = displayRecords(data.items).slice(0, 40).map((item) => ({
    label: displayText(item, "label", "title"),
    ...(displayText(item, "detail", "description") ? { detail: displayText(item, "detail", "description") } : {}),
    ...(displayText(item, "time", "date") ? { time: displayText(item, "time", "date") } : {}),
    ...(displayText(item, "status") ? { status: displayText(item, "status") } : {}),
  })).filter((item) => item.label);
  return items.length ? [{ type: "timeline", items }] : [];
}

function mapBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const latitude = displayNumber(data, "latitude");
  const longitude = displayNumber(data, "longitude");
  if (latitude === null || longitude === null) return [];
  return [{
    type: "map", latitude, longitude,
    label: displayText(data, "label", "place", "address") || "Mapped place",
    ...(displayNumber(data, "zoom") !== null ? { zoom: displayNumber(data, "zoom")! } : {}),
  }];
}

function diffBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const before = displayText(data, "before");
  const after = displayText(data, "after");
  return before || after ? [{
    type: "diff", before, after,
    ...(displayText(data, "label") ? { label: displayText(data, "label") } : {}),
  }] : [];
}

function progressBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const value = displayNumber(data, "value");
  if (value === null) return [];
  return [{
    type: "progress", value,
    ...(displayNumber(data, "max") !== null ? { max: displayNumber(data, "max")! } : {}),
    ...(displayText(data, "label") ? { label: displayText(data, "label") } : {}),
  }];
}

function stepBlocks(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const items = displayRecords(data.items ?? data.steps).slice(0, 50).map((item) => ({
    label: displayText(item, "label", "action", "title"),
    ...(displayText(item, "status") ? { status: displayText(item, "status") } : {}),
  })).filter((item) => item.label);
  return items.length ? [{ type: "steps", items }] : [];
}

function keyValueFallback(data: Record<string, DisplayJSON>): DisplayBlock[] {
  const items = Object.entries(data).flatMap(([label, value]) => {
    const rendered = cellText(value);
    return rendered ? [{ label: readable(label), value: rendered }] : [];
  }).slice(0, 30);
  return items.length ? [{ type: "key_value", items }] : [];
}

function cellText(value: DisplayJSON | undefined): string {
  if (value === null || value === undefined) return "";
  if (["string", "number", "boolean"].includes(typeof value)) return String(value);
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) return value.join(", ");
  return "";
}

function readable(value: string): string {
  return value.replace(/[._-]+/g, " ").replace(/^./, (letter) => letter.toUpperCase());
}
