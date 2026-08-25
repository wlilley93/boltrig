import type { CharacterId } from "../../character";

/**
 * The companions offered during setup, in rail order.
 *
 * SEPARATE FROM THE REGISTRY ON PURPOSE. The registry is what is INSTALLED and
 * is open to plugins; this is what a first-run user is walked through, and it
 * is a curated, ordered, copy-written list. Driving onboarding off the registry
 * would put any locally registered dev character into a stranger's first
 * experience of the product, in registration order, with a blurb written for a
 * settings row.
 *
 * The copy here is the pitch. The blurb in each bundle is the settings-row
 * description, and they are deliberately not the same sentence.
 */
export interface CompanionChoice {
  id: CharacterId;
  name: string;
  blurb: string;
  note: string;
}

/**
 * The stock rail: the four bodies every build can actually draw.
 *
 * A character whose RENDERER is not in this build must not appear here. The
 * registry degrades an unknown id to the default at render time, so an entry
 * for a body this build cannot draw is not an error -- it is a first-run user
 * choosing a companion by name and silently receiving a different one. That is
 * the worst outcome available on this screen, because it looks like it worked.
 */
const STOCK: readonly CompanionChoice[] = [
  {
    id: "familiar",
    name: "Familiar",
    blurb: "A living presence with a private inner life.",
    note: "Warm, organic and quietly expressive.",
  },
  {
    id: "jarvis",
    name: "Jarvis",
    blurb: "An instrument for the machine's measured state.",
    note: "Precise, technical and visibly connected to the work.",
  },
  {
    id: "ultron",
    name: "Ultron",
    blurb: "An intelligence that has finished evaluating the situation.",
    note: "Cold, certain, and unimpressed by effort.",
  },
  {
    id: "colossus",
    name: "Colossus",
    blurb: "A defence system that has finished reasoning, and now reports.",
    note: "A panel of lamps, not a face. Formal, literal and immovable.",
  },
  {
    id: "general-montgomery",
    name: "General Montgomery",
    blurb: "An intelligence officer who reads the room and tells you what is in it.",
    note: "A man in an office, not a shape on a canvas. He moves, and he does not soften.",
  },
];

/**
 * The rail, in order: what ships, then what a private distribution added.
 *
 * THE SAME INVERSION THE REGISTRY ALREADY USES. Core states the contract and
 * discovers what is installed; a character supplies itself. `registerCharacter`
 * does that for BODIES and `register_persona` does it for prompts, and until
 * now onboarding was the one surface with no join -- so a privately registered
 * character could be installed, drawable and choosable in Settings, and still
 * be absent from the only screen that introduces it.
 *
 * Deliberately NOT driven off the registry, which is what the note at the top
 * of this file already refuses: the registry holds whatever is installed,
 * including a locally registered dev character, and first-run would then walk
 * a stranger through that character in registration order with a blurb written
 * for a settings row. This list holds only what somebody wrote a pitch for.
 *
 * `readonly` is the type every caller sees; `rail` is the single reference
 * that may append, and it is not exported.
 */
const rail: CompanionChoice[] = [...STOCK];
export const COMPANIONS: readonly CompanionChoice[] = rail;

/**
 * Offer a companion during setup.
 *
 * Idempotent by id, and the FIRST pitch wins: an import cycle or a
 * double-installed plugin re-registering an id must not rewrite copy a user is
 * part-way through reading.
 *
 * A caller must only register a character this build can actually DRAW. The
 * registry degrades an unknown id to the default at render time, so offering a
 * body whose renderer is absent is not an error -- it is a first-run user
 * picking a companion by name and silently receiving a different one.
 */
export function registerCompanionChoice(choice: CompanionChoice): void {
  if (rail.some((existing) => existing.id === choice.id)) return;
  rail.push(choice);
}

/** Rail position of a companion, or 0 for one that is not offered here. */
export function companionIndex(id: CharacterId): number {
  const found = COMPANIONS.findIndex((choice) => choice.id === id);
  return found < 0 ? 0 : found;
}

/**
 * The stored choice setup starts from: kept when it is one of the companions
 * offered here, the first companion otherwise. A choice setup cannot show is
 * not silently rewritten to a different one.
 */
export function offeredCompanion(id: CharacterId): CharacterId {
  return COMPANIONS.some((choice) => choice.id === id) ? id : COMPANIONS[0].id;
}

/** The companion's own name, for copy that greets the person with it. */
export function companionName(id: CharacterId): string {
  return COMPANIONS[companionIndex(id)].name;
}
