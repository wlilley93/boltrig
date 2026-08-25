// WHICH CLIP HE PLAYS NEXT, AND WHICH VOICE SAYS IT.
//
// A frame-video character has no dials. Every other body in boltrig expresses
// itself by moving a number -- aggression, energy, irritation -- into a shader
// uniform. He cannot. His whole expressive range is the set of clips that were
// rendered, and the only expressive act available is CHOOSING one. So this
// module is his equivalent of a shader drive, and it emits three choices:
//
//     emotion   which state hub he settles into      (clip:emotion)
//     position  which part of the room he is in      (clip:position)
//     register  which of his voice clones speaks     (voice.speak)
//
// The three are decided together and on purpose. A grave assessment delivered
// from the window in the amused register is three correct choices that are
// wrong as a set, and nothing downstream can see enough to catch it.
//
// WHAT THIS MODULE MAY NOT DO. Cosmetic only (ADR 0025): nothing here can
// influence dispatch, grants, HITL or routing. It reads a turn and a phenotype
// and returns three enum-ish strings. It sends no text, no audio, no
// credentials and no identifiers anywhere.

import type { CharacterStageState } from "@wlilley93/boltrig-web-sdk";

/**
 * The six tags his graph actually carries, split the way the bundle splits
 * them. This is NOT a taxonomy this module invented -- it ships inside the
 * .frame.mp4 as `manifest.emotions` and is echoed on the wire in every
 * `clip:state`. It is restated here as a type so a tag that is not in his
 * graph cannot be constructed, and mirrored at runtime against what the player
 * reports (see `agreeOnVocabulary`) so a bundle regeneration that changes the
 * set is caught rather than silently ignored.
 */
export type Emotion =
  | "composed" | "patient" | "reflective"      // ambient
  | "vigilant" | "displeased" | "wry";         // directed

/**
 * AMBIENT TAGS ARE NEVER DIRECTED, AND THAT IS THE WHOLE CONTRACT.
 *
 * His manifest divides the six into `ambient` and `directed`, and the division
 * is not a performance hint -- it is what keeps him honest. The ambient three
 * are where he lives when nothing has happened: the player drifts between them
 * on its own adjacency walk, at its own pace, and a host that also pushed them
 * would be overriding a drift with a poll and calling the result a mood.
 *
 * The directed three are the ones that need a cause. "A surprised face never
 * appears without a surprise" -- so displeasure appears when something is
 * displeasing, and never because a timer came round. This module therefore
 * emits ONLY directed tags, and returns undefined for everything else, which
 * leaves him drifting rather than parking him on a chosen calm.
 */
const DIRECTED = new Set<Emotion>(["vigilant", "displeased", "wry"]);
export function isDirectable(tag: Emotion): boolean {
  return DIRECTED.has(tag);
}

/**
 * The positions that survive. H2 (standing beyond the far end of the
 * conference table) and H5 (seated) were retired by the author on 2026-08-25:
 * both read too far or too small on the stage. The clips are still in the
 * bundle and the walks still exist -- the player refuses them, and this module
 * never names them, so the refusal is not the only thing standing between him
 * and a position nobody wants to see.
 */
export type Position = "H1" | "H3" | "H4";
export const DESK: Position = "H1";
export const FIREPLACE: Position = "H3";
export const WINDOW: Position = "H4";

/**
 * His voice clones, cut 2026-08-25 from lines he already had in each register
 * rather than from a generic script -- a clone learns the performance, not the
 * tag, so a character rendered from another character's lines inherits that
 * character's rhythm permanently.
 *
 * `base` is not a register. It is the voice, and `neutral` is the name of the
 * mistake: pocket-voice warns about any `<character>-neutral` sibling because
 * neutral IS the base, and the duplicates it found (`ultron-neutral`,
 * `jarvis-neutral`) went on to serve a stale voice under a register's name
 * with nothing to notice. There is no `montgomery-neutral` and there must not
 * be one.
 *
 * There is also no `bright`. Every other character carries one; he has no
 * bright register, and a clone named for a register he does not have is the
 * same failure as `-neutral` wearing a different word.
 */
export type Register =
  | "base" | "calm" | "serious" | "urgent" | "warm" | "amused" | "tender" | "monty";

/** What the appraisal engine measures. Only the fields he can act on. */
export interface Phenotype {
  /** How irritated the machine is with the situation. 0..1 */
  irritation?: number;
  /** How alert it is: unread signal, budget pressure, a failing run. 0..1 */
  alertness?: number;
  /** Confidence in its own reading. 0..1 */
  certainty?: number;
}

export interface DriveInput {
  /** Turn facts: is a run in flight, is he speaking. */
  turn: CharacterStageState;
  /** The machine's measured affect, or null when nothing is measuring. */
  phenotype?: Phenotype | null;
  /** The reply about to be spoken, when there is one. */
  reply?: string | null;
  /** How the user addressed him in the message he is answering. */
  address?: string | null;
  /** Where the player says he currently is. */
  at?: Position | null;
}

export interface Drive {
  /** A DIRECTED tag, or undefined to leave his ambient drift alone. */
  emotion?: Emotion;
  /** Where to walk him, or undefined to leave him where he is. */
  position?: Position;
  /** Which clone speaks this reply. Always answered. */
  register: Register;
  /** Why, in a few words. Carried for the HUD and for tests to assert on. */
  because: string;
}

// Cheap surface reads of the reply. They are deliberately shallow: this runs
// on every turn in the browser, and a mood that needed a model to decide would
// be a second inference per reply to move a video by one clip.
// `the situation has changed` is his own p36, and it is never small when he
// says it -- the phrase IS the escalation, with or without a clause after it.
const GRAVE = /\b(regret|casualt|loss(es)?|cost|grave|serious|failed|failure|breach|collapse|not in our favou?r|worse|the situation has changed|requires a decision)\b/i;
const URGENT = /\b(at once|immediately|now|hold|stand by|move|act|urgent|before)\b/i;
const WRY = /\b(well\.|quite\.|one way to do it|fractionally|i suppose|charming|marvellous|splendid)\b/i;
const REGARD = /\b(right call|well (done|played|judged)|competent|good work|correct|precisely|exactly the right)\b/i;
const LONG_VIEW = /\b(history|three thousand|every power|the long|in the end|generation|Owen|Sassoon|Kipling|patience)\b/i;
const REFUSAL = /^\s*(no\.|absolutely not|that is wrong|wrong\.)/i;

/** "Monty" is an address, not an emotion, and it is the one thing that
 *  loosens him. Matched on the whole word so "Montgomery" does not trip it. */
export function addressedAsMonty(address: string | null | undefined): boolean {
  return !!address && /\bmonty\b/i.test(address) && !/\bmontgomery\b/i.test(address);
}

/**
 * One branch of the policy, as data.
 *
 * The ordering below IS the character, so it is a list you can read top to
 * bottom rather than a chain of ifs whose precedence you have to reconstruct.
 * That started as a comment saying "order is the policy" above a function with
 * a complexity of 27; the comment was true and the shape did not show it.
 */
interface Rule {
  /** Why this branch fired. Carried for the HUD and asserted by no test. */
  because(context: Context): string;
  when(context: Context): boolean;
  /** A DIRECTED tag, or absent to leave his ambient drift alone. */
  emotion?: Emotion;
  /** Where to walk him, or absent to leave him where he is. */
  position?(context: Context): Position | undefined;
  /** The register when he is NOT being called Monty. */
  register: Register;
}

interface Context {
  turn: CharacterStageState;
  irritation: number;
  alertness: number;
  text: string;
  at: Position | null;
}

/**
 * Most specific cause first; the first match wins.
 *
 * Displeasure outranks urgency because a man who is both is displeased. The
 * long view outranks command because "hold" appears in both and only one of
 * them is an instruction.
 */
const RULES: readonly Rule[] = [
  {
    // Ordinary work does not wear a face.
    because: () => "a run is in flight; he works at the desk",
    when: (c) => c.turn.working === true && c.turn.speaking !== true,
    position: () => DESK,
    register: "base",
  },
  {
    because: (c) => c.irritation >= 0.6 ? "measured irritation" : "the reply opens by refusing",
    when: (c) => c.irritation >= 0.6 || REFUSAL.test(c.text),
    emotion: "displeased",
    // The fireplace is where displeasure and the long pause live. He does not
    // deliver bad news from the window; the window is for the long view.
    position: () => FIREPLACE,
    register: "serious",
  },
  {
    because: (c) => c.alertness >= 0.6 ? "measured alertness" : "the assessment is grave",
    when: (c) => c.alertness >= 0.6 || GRAVE.test(c.text),
    emotion: "vigilant",
    position: (c) => c.at ?? DESK,
    register: "serious",
  },
  {
    // His humour is a directed state: it does not drift in.
    because: () => "a dry aside",
    when: (c) => WRY.test(c.text),
    emotion: "wry",
    position: (c) => c.at ?? DESK,
    register: "amused",
  },
  {
    // Rare, never announced, and a register rather than a face -- there is no
    // clip of him being pleased with you, which is correct.
    because: () => "something is being acknowledged",
    when: (c) => REGARD.test(c.text),
    position: (c) => c.at ?? DESK,
    register: "warm",
  },
  {
    // AMBIENT, so nothing is directed: he is walked to the window and left to
    // arrive at `reflective` himself, which is what the ambient set is for.
    because: () => "the long view; drift carries the mood, not a direction",
    when: (c) => LONG_VIEW.test(c.text),
    position: () => WINDOW,
    register: "tender",
  },
  {
    because: () => "an instruction, not an assessment",
    when: (c) => URGENT.test(c.text),
    position: (c) => c.at ?? DESK,
    register: "urgent",
  },
];

/**
 * The whole decision, in one place.
 *
 * Being addressed as "Monty" replaces the register at every branch and changes
 * nothing else: it is about who is being spoken to rather than what is being
 * said, and he does not stop being loosened because the news is bad.
 */
export function drive(input: DriveInput): Drive {
  const context: Context = {
    turn: input.turn,
    irritation: clamp01(input.phenotype?.irritation),
    alertness: clamp01(input.phenotype?.alertness),
    text: input.reply ?? "",
    at: input.at ?? null,
  };
  const monty = addressedAsMonty(input.address);
  const rule = RULES.find((candidate) => candidate.when(context));
  if (!rule) {
    // Nothing directed and nothing moved: he speaks from wherever he is,
    // because movement is never the price of a reply.
    return {
      register: monty ? "monty" : context.text ? "calm" : "base",
      because: context.text ? "an ordinary assessment" : "nothing to say yet",
    };
  }
  const position = rule.position?.(context);
  return {
    ...(rule.emotion ? { emotion: rule.emotion } : {}),
    ...(position ? { position } : {}),
    register: monty ? "monty" : rule.register,
    because: rule.because(context),
  };
}

/**
 * The voice id to ask the runtime for.
 *
 * Falls back to the BASE CLONE, never to another character and never to a
 * catalogue voice: a register he has not been cut yet should sound like him
 * anyway. That is the one substitution the SDK's rule permits, because it is
 * not a substitution -- it is the same man, in the register he starts from.
 */
export function voiceIdFor(base: string, register: Register, available: readonly string[]): string {
  if (register === "base") return base;
  const wanted = `${base}-${register}`;
  return available.includes(wanted) ? wanted : base;
}

/**
 * Does the player's live vocabulary still match what this module believes?
 *
 * Called with the `emotions.tags` and `positions` arrays out of `clip:state`.
 * A bundle regeneration that renamed a tag or dropped a position would
 * otherwise show up as this module quietly directing a state that no longer
 * exists -- the player ignores an unknown tag, so the failure is a character
 * who simply stops reacting, which nobody reports as a bug.
 *
 * Returns what is missing rather than throwing: a mismatch should degrade him
 * to his ambient drift, not take the Stage down.
 */
export function agreeOnVocabulary(
  tags: readonly string[],
  positions: readonly string[],
): { emotions: string[]; positions: string[] } {
  const missingEmotions = [...DIRECTED].filter((tag) => !tags.includes(tag));
  const missingPositions = [DESK, FIREPLACE, WINDOW].filter((hub) => !positions.includes(hub));
  return { emotions: missingEmotions, positions: missingPositions };
}

function baseOrMonty(address: string | null | undefined): Register {
  return addressedAsMonty(address) ? "monty" : "base";
}

function clamp01(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return value < 0 ? 0 : value > 1 ? 1 : value;
}
