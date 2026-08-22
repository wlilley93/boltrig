// THE SYLLABLE ENVELOPE, shared by every body that speaks with its dials.
//
// A speech map ("field:index" -> the value that dial holds at full syllable)
// is most of what "speaking" looks like — the mode deltas are nearly bare on
// purpose. This class is the one copy of the meter and the reach ride; it was
// twin private methods in two renderers, which is one copy and a disagreement
// waiting to happen.

/** A VU needle over the live voice level, and the reach ride on top of it. */
export class SpeechReach {
  private env = 0;

  /** Advance the meter one frame: fast toward a louder syllable (0.45),
   *  easing back through the gaps between words (0.1). Per-frame at rAF
   *  rate, matching the bench where the reaches were tuned against real
   *  clips. 1.13 restores the bench's headroom: it metered the reach at
   *  peak*1.3 while reporting level at peak*1.15. */
  advance(level: number): void {
    const target = Math.min(1, level * 1.13);
    this.env += (target - this.env) * (target > this.env ? 0.45 : 0.1);
  }

  /** Ride every reach on the envelope: each mapped dial travels from the
   *  mode's value toward its spoken one and settles back as the envelope
   *  releases. Applied on the SHIPPED path only — the bench pins its tuning
   *  and folds the same reaches in itself, so applying them here too would
   *  speak twice. */
  apply<T>(tuning: T, reaches: Readonly<Record<string, number>>): T {
    const k = this.env;
    if (k < 0.002) return tuning;
    const out = { ...tuning } as unknown as Record<string, number | number[]>;
    for (const [id, reach] of Object.entries(reaches)) {
      const [field, indexText] = id.split(":");
      const value = out[field];
      if (value === undefined) continue;
      if (typeof value === "number") {
        out[field] = value + (reach - value) * k;
      } else {
        const next = value.slice();
        const index = Number(indexText);
        next[index] = next[index] + (reach - next[index]) * k;
        out[field] = next;
      }
    }
    return out as unknown as T;
  }
}
