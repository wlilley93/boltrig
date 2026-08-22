// The tail of the live reasoning, bounded HERE — the stage contract carries
// one short phrase, never the stream (see CharacterTurnInput.thinkingTrace).
// Only Colossus reads it: his sign shows what the machine is doing while it
// thinks. Word-clipped at the front so the phrase starts on a word.

import { type ChatEvent } from "@wlilley93/boltrig-web-sdk";

export function traceFromEvents(events: readonly ChatEvent[]): string | null {
  let reasoning = "";
  for (const ev of events) {
    if (ev.type === "reasoning_delta") reasoning += ev.delta;
  }
  const flat = reasoning.replace(/\s+/g, " ").trim();
  if (!flat) return null;
  return flat.length <= 80 ? flat : flat.slice(-80).replace(/^\S*\s/, "");
}
