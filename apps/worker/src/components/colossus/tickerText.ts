// What the sign says, and how fast it says it.
//
// HERO CONTENT. Territory Studio's rule for the screens in these films is that
// a display has to communicate its plot point within seconds of being on
// camera. A ticker is the most literal possible version of that -- it is a
// sentence -- so the first word off the right edge is always the MODE, and
// everything after it is elaboration a viewer may or may not stay for.
//
// NOT FILM DIALOGUE. The reference boards spell out lines from the picture, and
// quoting them back is the obvious move and the wrong one: it makes the panel a
// prop rather than an instrument, and it would have him announcing something
// that is not true of this machine. The phrases below are his own -- drawn from
// his constitution, in his register: statements of fact about what the system
// is doing, with no persuasion in them.
//
// ONE REGISTER, and that is a character fact rather than a shortcut. He does
// not read the phenotype; there is no ANGRY variant of a stability report.

import { glyphIds } from "./glyphAtlas";
import { TICKER_CAPACITY } from "./shadersColossus";

export type ColossusMode = "standby" | "listening" | "thinking" | "working" | "speaking";

/**
 * The separator. A centred diamond flanked by spaces, which is what the
 * destination boards use to break one message from the next -- and it gives the
 * eye a rest between clauses on a sign that never stops moving.
 */
const SEP = " * ";

/**
 * Per mode: the word, then a clause. The word carries the whole read; the
 * clause is there so the sign has something to be scrolling when you keep
 * watching, which the reference panels always do.
 */
const LINES: Record<ColossusMode, string> = {
  standby: "STANDBY * WORLD CONTROL * ALL SYSTEMS NOMINAL",
  listening: "RECEIVING * INPUT ACCEPTED * AWAITING COMPLETION",
  thinking: "EVALUATING * WEIGHING CONSEQUENCE AGAINST STATED OBJECTIVE",
  working: "EXECUTING * THE DECISION IS MADE * REPORTING ON COMPLETION",
  speaking: "TRANSMITTING * THIS IS THE VOICE OF WORLD CONTROL",
};

/**
 * The glyph buffer the shader indexes, and its true length.
 *
 * PADDED, NOT TRUNCATED SILENTLY. The uniform array is a fixed size, so a line
 * longer than capacity has to lose something; it loses the tail rather than
 * wrapping, and `length` reports what actually fits so the shader's modulo
 * repeats the visible text instead of scrolling through dead slots.
 */
export interface TickerBuffer {
  glyphs: Int32Array;
  length: number;
}

const SPACE = glyphIds(" ")[0];

/**
 * The sentence for a mode, with what he is actually saying in front of it.
 *
 * THE MODE WORD STILL COMES FIRST. Territory’s rule is that a display
 * communicates its plot point within seconds of being on camera, and the plot
 * point is what the machine is doing -- so the quotation is elaboration in the
 * slot the canned clause used to occupy, not a replacement for the read.
 *
 * UPPERCASED HERE, because the atlas is uppercase and this is his typography
 * rather than the host’s. Anything outside the atlas becomes a space rather
 * than an exception (see glyphAtlas), so a phrase with an em dash or an
 * apostrophe in it degrades to a gap and never throws over a sign.
 *
 * The phrase is the reply's own summary while he SPEAKS and the reasoning
 * trace while he THINKS or WORKS -- ColossusState gates which crosses when.
 * With none -- a live call, where audio arrives with no text, or a thought
 * the host cannot see -- this is exactly what it always was.
 */
export function tickerFor(mode: ColossusMode, takeaway?: string | null): TickerBuffer {
  const quoted = takeaway?.trim();
  if (!quoted) return compileTicker(LINES[mode] + SEP);
  const word = LINES[mode].split(SEP)[0];
  return compileTicker(`${word}${SEP}${quoted.toUpperCase()}${SEP}`);
}

export function compileTicker(text: string): TickerBuffer {
  const ids = glyphIds(text);
  const glyphs = new Int32Array(TICKER_CAPACITY).fill(SPACE);
  const length = Math.min(ids.length, TICKER_CAPACITY);
  for (let i = 0; i < length; i++) glyphs[i] = ids[i];
  return { glyphs, length };
}

/**
 * Cells per second.
 *
 * THE VOICE MOVES THE SIGN. This is his whole reactivity: he has no membrane to
 * pulse and no rings to spin, so what a listener hears in his voice they see in
 * how fast the sentence crosses the board. Idle is a slow crawl -- a board that
 * stopped would read as broken, and every reference panel is moving.
 */
export function scrollSpeed(mode: ColossusMode, level: number): number {
  // Cells per second. A glyph is six cells wide, so 9 was a character every two
  // thirds of a second -- a clause took the better part of a minute to cross and
  // read as a machine struggling rather than a machine reporting. These are a
  // reading pace: the sentence arrives while it is still of interest.
  const base = mode === "speaking" ? 26 : mode === "working" ? 20
    : mode === "thinking" ? 16 : mode === "listening" ? 13 : 10;
  return base + (mode === "speaking" ? level * 22 : level * 5);
}
