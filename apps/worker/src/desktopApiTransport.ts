import { invoke } from "@tauri-apps/api/core";

import { configuredApiOrigin } from "./apiOrigin";

interface DesktopApiHead {
  status: number;
  status_text: string;
  headers: Array<[string, string]>;
}

const DESKTOP_API_MAX_REQUEST_BYTES = 25 * 1024 * 1024;
const DESKTOP_API_MAX_METADATA_BYTES = 64 * 1024;
const DESKTOP_API_MAGIC = [0x42, 0x41, 0x50, 0x49] as const;
const NULL_BODY_STATUSES = new Set([101, 103, 204, 205, 304]);
const SAFE_RESPONSE_HEADERS = new Set([
  "content-type",
  "content-length",
  "content-disposition",
  "etag",
]);

function abortError(): DOMException {
  return new DOMException("The request was aborted", "AbortError");
}

function invalidResponse(): never {
  throw new Error("desktop_api_response_invalid");
}

function apiEnvelopeBytes(value: ArrayBuffer | Uint8Array | number[]): Uint8Array {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (Array.isArray(value) && value.every((byte) => (
    Number.isInteger(byte) && byte >= 0 && byte <= 255
  ))) return new Uint8Array(value);
  return invalidResponse();
}

function validHeader(entry: unknown): entry is [string, string] {
  if (!Array.isArray(entry) || entry.length !== 2) return false;
  const [name, value] = entry;
  if (typeof name !== "string" || typeof value !== "string") return false;
  if (!SAFE_RESPONSE_HEADERS.has(name) || value.length > 8192) return false;
  return !Array.from(value).some((character) => (
    character.charCodeAt(0) < 32 && character !== "\t"
  ));
}

function validHead(value: unknown): value is DesktopApiHead {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<DesktopApiHead>;
  if (!Number.isInteger(candidate.status)) return false;
  if ((candidate.status ?? 0) < 100 || (candidate.status ?? 0) > 599) return false;
  if (typeof candidate.status_text !== "string" || candidate.status_text.length > 128) {
    return false;
  }
  return Array.isArray(candidate.headers)
    && candidate.headers.length <= 8
    && candidate.headers.every(validHeader);
}

function decodeHead(bytes: Uint8Array, metadataLength: number): DesktopApiHead {
  try {
    const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(
      bytes.subarray(8, 8 + metadataLength),
    ));
    if (validHead(value)) return value;
  } catch {
    // The native envelope is a trust boundary; all parse failures share one safe reason.
  }
  return invalidResponse();
}

function parseApiEnvelope(value: ArrayBuffer | Uint8Array | number[]): {
  head: DesktopApiHead;
  body: Uint8Array;
} {
  const bytes = apiEnvelopeBytes(value);
  if (bytes.byteLength < 8) return invalidResponse();
  if (DESKTOP_API_MAGIC.some((byte, index) => bytes[index] !== byte)) {
    return invalidResponse();
  }
  const metadataLength = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    .getUint32(4, true);
  if (
    metadataLength === 0
    || metadataLength > DESKTOP_API_MAX_METADATA_BYTES
    || 8 + metadataLength > bytes.byteLength
  ) return invalidResponse();
  return {
    head: decodeHead(bytes, metadataLength),
    body: bytes.slice(8 + metadataLength),
  };
}

async function invokeDesktopApi(
  args: Record<string, unknown>,
  signal: AbortSignal,
): Promise<ArrayBuffer | Uint8Array | number[]> {
  if (signal.aborted) throw abortError();
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", abort);
      callback();
    };
    const abort = () => finish(() => reject(abortError()));
    signal.addEventListener("abort", abort, { once: true });
    void invoke<ArrayBuffer | Uint8Array | number[]>("desktop_api_request", args).then(
      (result) => finish(() => resolve(result)),
      (reason) => finish(() => reject(reason)),
    );
  });
}

export async function desktopApiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  if (!(typeof window !== "undefined" && "__TAURI_INTERNALS__" in window)) {
    return globalThis.fetch(input, init);
  }
  const configured = configuredApiOrigin();
  if (!configured) throw new Error("desktop_api_origin_not_configured");
  const request = new Request(input, init);
  const url = new URL(request.url);
  if (
    url.origin !== configured
    || !(url.pathname === "/v1" || url.pathname.startsWith("/v1/"))
    || url.hash
  ) throw new Error("desktop_api_path_invalid");
  const body = new Uint8Array(await request.arrayBuffer());
  if (body.byteLength > DESKTOP_API_MAX_REQUEST_BYTES) {
    throw new Error("desktop_api_request_too_large");
  }
  const envelope = await invokeDesktopApi({
    method: request.method,
    path: `${url.pathname}${url.search}`,
    headers: Array.from(request.headers.entries()),
    body: Array.from(body),
  }, request.signal);
  const parsed = parseApiEnvelope(envelope);
  const response = new Response(
    NULL_BODY_STATUSES.has(parsed.head.status) ? null : parsed.body,
    {
      status: parsed.head.status,
      statusText: parsed.head.status_text,
      headers: parsed.head.headers,
    },
  );
  Object.defineProperty(response, "url", { value: url.href, writable: false });
  return response;
}
