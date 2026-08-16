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
];

/** Rail position of a companion, or 0 for one that is not offered here. */
export function companionIndex(id: CharacterId): number {
  const found = COMPANIONS.findIndex((choice) => choice.id === id);
  return found < 0 ? 0 : found;
}
