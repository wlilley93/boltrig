/** An SSE reader that keeps the event NAME.
 *
 *  THE SDK'S OWN PUMP CANNOT BE USED HERE, and reaching for it is the single
 *  most expensive mistake available on this port. `pumpSseFrames` in
 *  sdks/web/src/client.ts filters to lines starting `data:` and throws the rest
 *  away - and Hermes's session stream puts the event name on the `event:` line.
 *  Reusing it sends every frame into the shim's default branch, and the whole
 *  transcript renders as nothing, with no error anywhere to explain it.
 */

export interface SseFrame<T> {
  name: string;
  data: T;
}

/** SSE's own default when a frame carries no `event:` line, per the spec. The
 *  run stream relies on it: its frames carry the name inside the JSON. */
const DEFAULT_EVENT = "message";

export async function pumpSse<T>(
  stream: ReadableStream<Uint8Array>,
  onFrame: (frame: SseFrame<T>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (!signal?.aborted) {
      const { value, done } = await reader.read();
      if (value) buffer += decoder.decode(value, { stream: !done });

      const chunks = buffer.split(/\r?\n\r?\n/);
      // The last piece is either an incomplete frame or an empty string; either
      // way it is not ready to parse and carries over to the next read.
      buffer = chunks.pop() ?? "";
      for (const chunk of chunks) {
        const frame = parseFrame<T>(chunk);
        if (frame) onFrame(frame);
      }

      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
}

/** One `event:`/`data:` block, or null for a frame with no payload.
 *
 *  Extracted from the read loop rather than nested inside it: the loop was four
 *  levels deep before the parsing began, which the structural gate refuses at
 *  more than four, and which made the one interesting line - where the name is
 *  taken from `event:` - the hardest to find in the file. */
function parseFrame<T>(chunk: string): SseFrame<T> | null {
  let name = DEFAULT_EVENT;
  const payload: string[] = [];

  for (const line of chunk.split(/\r?\n/)) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) payload.push(line.slice(5).trimStart());
    // Anything else is a comment (`: keepalive`) or a field this reader has no
    // use for (`id:`, `retry:`). Skipped, not an error.
  }

  const data = payload.join("\n");
  if (!data) return null;

  try {
    return { name, data: JSON.parse(data) as T };
  } catch {
    // Hermes promises JSON on both streams, so this is a malformed frame rather
    // than a supported shape. Handed on as-is so the caller sees what arrived
    // instead of the frame vanishing.
    return { name, data: data as unknown as T };
  }
}
