// Colossus replies in JSON, and this is the only place that knows it.
//
// His bundle prompt instructs the model to return one object per reply:
//   {"say": "<the reply itself>", "sign": "<a summary in at most six words>"}
// The host reads "say" aloud and prints it; "sign" crosses the panel's ticker
// while he speaks. The user asked for exactly this shape — a model-written
// summary on the sign, carried by the same reply that says the words, so it
// costs no second call and cannot describe a different reply.
//
// EVERY PATH FAILS OPEN TO THE RAW TEXT. A model that ignores the format, a
// truncated stream, a fenced object — none of them may cost the user the
// reply. Parsing is attempted; the text is never withheld because parsing
// failed.

export interface ColossusReply {
  say: string;
  sign: string | null;
}

/** The sign never carries more than this; ColossusState caps again at 80. */
const MAX_SIGN_CHARS = 80;

/**
 * The parsed reply, or null when the text is not (yet) his JSON shape.
 *
 * Accepts the bare object and the fenced variant a model emits when it
 * forgets "no code fences" — stripping the fence is cheaper than losing the
 * reply to it.
 */
export function parseColossusReply(raw: string): ColossusReply | null {
  const text = unfence(raw.trim());
  if (!text.startsWith("{") || !text.endsWith("}")) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const say = (parsed as Record<string, unknown>).say;
  if (typeof say !== "string" || say.trim().length === 0) return null;
  const sign = (parsed as Record<string, unknown>).sign;
  return {
    say: say.trim(),
    sign: typeof sign === "string" && sign.trim().length > 0
      ? sign.trim().slice(0, MAX_SIGN_CHARS)
      : null,
  };
}

/**
 * What the chat SHOWS for a colossus reply, streaming included.
 *
 * While the object is still arriving the raw buffer reads as `{"say": "The
 * finding is...` — braces on a panel whose whole character is that it reports
 * cleanly. The complete object parses properly; an incomplete one that has
 * opened its "say" string yields the string's partial content, unescaped, so
 * the reply streams as prose from the first token. Anything else passes
 * through untouched.
 */
export function colossusReplyText(raw: string): string {
  const parsed = parseColossusReply(raw);
  if (parsed) return parsed.say;
  const text = unfence(raw.trim());
  if (!text.startsWith("{")) return raw;
  const opened = /"say"\s*:\s*"((?:[^"\\]|\\.)*)/.exec(text);
  // No "say" opened: either the first tokens of the object, or not his format
  // at all. Fail OPEN — a brief flash of braces beats a withheld reply.
  if (!opened) return raw;
  return unescapeJson(opened[1]);
}

function unfence(text: string): string {
  const fenced = /^```(?:json)?\s*([\s\S]*?)\s*```$/.exec(text);
  return fenced ? fenced[1].trim() : text;
}

/** The escapes a streamed half-string can contain; enough to read as prose. */
function unescapeJson(value: string): string {
  return value
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\");
}
