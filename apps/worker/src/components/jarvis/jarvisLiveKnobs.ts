// THE BENCH'S LIVE KNOBS for the V1 dial: identity genes, accent, scale,
// bloom, presence -- the honest set the renderer can change without a
// remount. Parsing and clamping live here; the renderer applies the result.
// Unknown fields are ignored so the tuning object can grow freely.

import { GENE } from "./JarvisGenotype";

export type JarvisLiveKnobsInput = Partial<{
  presence: number;
  accent: readonly [number, number, number];
  scale: number;
  bloom: readonly [number, number, number];
}> & Partial<Record<keyof typeof GENE, number>>;

export interface JarvisLiveKnobs {
  presence?: number;
  accent?: readonly [number, number, number];
  scale?: number;
  bloom?: readonly [number, number, number];
  /** [gene index, value] pairs, already validated. */
  genes: Array<[number, number]>;
}

export function parseLiveKnobs(next: JarvisLiveKnobsInput): JarvisLiveKnobs {
  const parsed: JarvisLiveKnobs = { genes: [] };
  if (typeof next.presence === "number" && Number.isFinite(next.presence)) {
    parsed.presence = Math.min(2.5, Math.max(0.2, next.presence));
  }
  if (Array.isArray(next.accent) && next.accent.length === 3) {
    parsed.accent = [next.accent[0], next.accent[1], next.accent[2]];
  }
  if (typeof next.scale === "number" && Number.isFinite(next.scale)) parsed.scale = next.scale;
  if (Array.isArray(next.bloom) && next.bloom.length === 3) {
    parsed.bloom = [next.bloom[0], next.bloom[1], next.bloom[2]];
  }
  for (const [field, index] of Object.entries(GENE)) {
    const value = (next as Record<string, unknown>)[field];
    if (typeof value === "number" && Number.isFinite(value)) parsed.genes.push([index, value]);
  }
  return parsed;
}
