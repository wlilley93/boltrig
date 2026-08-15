export interface BrowserFrame {
  id: string;
  mediaType: "image/jpeg";
  width: number;
  height: number;
  url: string;
  title: string;
  capturedAt: string;
}

export interface BrowserCursor {
  x: number;
  y: number;
  kind: "click" | "type" | "scroll" | "key";
}

export interface BrowserTab {
  id: string;
  title: string;
  url: string;
}

export interface BrowserNode {
  nodeId: number;
  role: string;
  name: string;
}

export interface BrowserActionOutput {
  status: "ok" | "stale_frame";
  frame: BrowserFrame;
  cursor: BrowserCursor | null;
}

export function parseBrowserAction(value: unknown): BrowserActionOutput | null {
  if (!record(value) || (value.status !== "ok" && value.status !== "stale_frame")) return null;
  const frame = parseFrame(value.frame);
  if (!frame) return null;
  return {
    status: value.status,
    frame,
    cursor: parseCursor(value.cursor),
  };
}

export function parseBrowserFrameData(value: unknown): string | null {
  if (!record(value) || value.media_type !== "image/jpeg") return null;
  if (typeof value.data !== "string" || value.data.length > 2_796_204) return null;
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(value.data)) return null;
  return `data:image/jpeg;base64,${value.data}`;
}

export function parseBrowserTabs(value: unknown): BrowserTab[] {
  if (!record(value) || !Array.isArray(value.tabs)) return [];
  return value.tabs.slice(0, 100).flatMap((item) => {
    if (!record(item) || !text(item.id, 256)) return [];
    return [{ id: item.id, title: text(item.title, 512) ?? "Untitled", url: text(item.url, 4096) ?? "" }];
  });
}

export function parseBrowserNodes(value: unknown): BrowserNode[] {
  if (!record(value) || !Array.isArray(value.nodes)) return [];
  return value.nodes.slice(0, 80).flatMap((item) => {
    if (!record(item) || !integer(item.node_id) || !text(item.role, 80)) return [];
    return [{ nodeId: item.node_id, role: item.role, name: text(item.name, 240) ?? "" }];
  });
}

function parseFrame(value: unknown): BrowserFrame | null {
  if (!record(value) || value.media_type !== "image/jpeg") return null;
  if (!text(value.id, 64) || !integer(value.width) || !integer(value.height)) return null;
  if (value.width > 16_384 || value.height > 16_384) return null;
  return {
    id: value.id,
    mediaType: value.media_type,
    width: value.width,
    height: value.height,
    url: text(value.url, 4096) ?? "",
    title: text(value.title, 512) ?? "",
    capturedAt: text(value.captured_at, 64) ?? "",
  };
}

function parseCursor(value: unknown): BrowserCursor | null {
  if (!record(value) || !integer(value.x, true) || !integer(value.y, true)) return null;
  if (!["click", "type", "scroll", "key"].includes(String(value.kind))) return null;
  return { x: value.x, y: value.y, kind: value.kind as BrowserCursor["kind"] };
}

function record(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, limit: number): string | null {
  return typeof value === "string" && value.length <= limit ? value : null;
}

function integer(value: unknown, zero = false): value is number {
  return Number.isInteger(value) && (value as number) >= (zero ? 0 : 1);
}
