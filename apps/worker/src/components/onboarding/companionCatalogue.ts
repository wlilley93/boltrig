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

export const COMPANIONS: readonly CompanionChoice[] = [
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
];

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
