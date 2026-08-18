// The handful of words a sign can carry.
//
// WHY THIS IS THE ONLY CONVERSATION TEXT IN THE STAGE CONTRACT.
// CharacterTurnInput hands a body FACTS about a turn -- is it loading, is a
// voice speaking, how loud, which bands -- and never its content, so that a
// third-party character cannot read somebody's conversation merely by
// declaring a stage. Colossus's panel is a sentence, though: a ticker that
// cannot show words is a ticker showing a canned string, which is what it did.
// So exactly one short phrase crosses, and it is bounded HERE, at the point it
// is made, rather than at the point it is drawn -- a body that receives a whole
// reply and promises to show six words of it has already been handed the reply.
//
// QUOTED, NOT SUMMARISED, and that is the substantive decision.
// "A five or six word takeaway of the message being spoken" reads as a summary,
// and a summary is either a model call per reply for a decoration or a
// heuristic that will eventually put a confident wrong sentence on a panel
// whose entire character is that it reports facts. The OPENING CLAUSE of what
// he is actually saying is a takeaway that cannot be wrong, because it is a
// quotation. It is also what a departure board does: the first words are the
// message and everything after them is elaboration.
//
// PLAIN TEXT, NOT SIGN TEXT. No uppercasing and no filtering to the glyph
// atlas happens here. Those are Colossus's typography, and a second body that
// wanted to show the same phrase in its own type should not have to undo his.

/** Words kept. Six is the ask; the seventh is where a sign stops being read. */
const MAX_WORDS = 6;

/**
 * A short reply is shown WHOLE up to this length rather than truncated at six.
 * "The deployment finished, and every check passed" is eight words and is worth
 * more complete than "THE DEPLOYMENT FINISHED, AND EVERY CHECK..." -- the
 * ellipsis is there to promise more, and there is no more.
 */
const KEEP_WHOLE_WORDS = 8;

/**
 * Discourse openers, dropped when they lead.
 *
 * These carry no information and they are exactly what a model puts in front of
 * the sentence that does. Spending one of six words on "So" is spending a sixth
 * of the sign. Dropped only in FIRST position, and only when something follows:
 * "No." as an entire reply is the most informative thing he could say.
 */
const OPENERS: ReadonlySet<string> = new Set([
  "well", "so", "right", "okay", "ok", "now", "sure",
  "actually", "basically", "honestly", "look", "anyway",
]);

/**
 * The phrase, or an empty string when there is nothing worth showing.
 *
 * Takes text that has ALREADY been through speechText() -- markdown stripped,
 * whitespace collapsed. Passing raw markdown here would put a code fence on the
 * sign.
 */
export function speechTakeaway(spoken: string): string {
  const sentence = firstSentence(spoken);
  if (!sentence) return "";
  const words = sentence.split(" ").filter(Boolean);
  const opened = words.length > 1 && OPENERS.has(strip(words[0]).toLowerCase())
    ? words.slice(1)
    : words;
  if (opened.length === 0) return "";
  if (opened.length <= KEEP_WHOLE_WORDS) return tidy(opened.join(" "));
  return `${tidy(trimDangling(opened.slice(0, MAX_WORDS)).join(" "))}...`;
}

/**
 * Function words dropped from the END of a truncation.
 *
 * A cut at a fixed word count lands wherever it lands, and half the time that
 * is on an article or a preposition: "YES, THE BUILD IS GREEN, THE..." reads as
 * a sign that broke mid-word rather than one that stopped. Ending on the last
 * word that carries something costs one word of the six and buys a phrase that
 * reads as a phrase.
 *
 * Not applied to a whole short reply, only to a truncation. "It is up to you"
 * is a complete sentence and ends on a preposition because that is what it
 * says.
 */
const DANGLING: ReadonlySet<string> = new Set([
  "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "for",
  "with", "from", "by", "as", "into", "over", "than", "that", "its", "their",
]);

function trimDangling(words: readonly string[]): string[] {
  const kept = [...words];
  while (kept.length > 1 && DANGLING.has(strip(kept[kept.length - 1]).toLowerCase())) {
    kept.pop();
  }
  return kept;
}

/**
 * Up to the first sentence-ending stop.
 *
 * Deliberately naive about abbreviations. "Dr. Chen approved it" would split at
 * "Dr." and the sign would say "DR" -- which is wrong, and is a sign showing
 * two fewer words rather than a system doing the wrong thing, and the cost of
 * being right about it is an abbreviation list that is wrong in a different way
 * in every language.
 */
function firstSentence(spoken: string): string {
  const text = spoken.trim();
  if (!text) return "";
  const stop = /[.!?](\s|$)/.exec(text);
  return (stop ? text.slice(0, stop.index) : text).trim();
}

/** A trailing comma or colon reads as a truncation the sign did not make. */
function tidy(phrase: string): string {
  return phrase.replace(/[\s,;:-]+$/, "");
}

/** Punctuation off a word, for comparing it against the opener list. */
function strip(word: string): string {
  return word.replace(/[^\p{L}\p{N}]/gu, "");
}
