import { useEffect, useState } from "react";

import { RESTING_STAGE_STATE, type FamiliarStageState } from "../familiar/FamiliarState";
import { RESTING_JARVIS_STATE, type JarvisStageState } from "../jarvis/JarvisState";

/** The behaviours Jarvis cycles through on the companion card.
 *
 * `standby` is deliberately absent: it is what the card showed before, and it
 * demonstrates nothing about the instrument. Each entry carries the inputs that
 * mode actually reads, so the dial, the fan and the sweep each get their turn.
 */
const JARVIS_CYCLE: Array<Partial<JarvisStageState>> = [
  { mode: "thinking", level: 0.18, readout: 2.4 },
  { mode: "working", level: 0.34, readout: 6.1 },
  { mode: "speaking", level: 0.62 },
  { mode: "listening", level: 0.12, micLevel: 0.48 },
];

const MODE_MS = 2600;

function bandsFor(t: number): number[] {
  // Eight log bands, each on its own slow beat so the fan never pulses as a
  // block. Not audio-derived -- this is a preview, and pretending otherwise
  // would mean holding a decoder open on the setup screen.
  return Array.from({ length: 8 }, (_, i) =>
    0.25 + 0.32 * Math.abs(Math.sin(t * (0.7 + i * 0.13) + i)));
}

export interface CompanionPreview {
  familiar: FamiliarStageState;
  jarvis: JarvisStageState;
}

export function useCompanionPreview(): CompanionPreview {
  const [preview, setPreview] = useState<CompanionPreview>({
    familiar: { ...RESTING_STAGE_STATE, working: true, level: 0.32 },
    jarvis: { ...RESTING_JARVIS_STATE, ...JARVIS_CYCLE[0] },
  });

  useEffect(() => {
    const reduced = typeof matchMedia === "function"
      && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof requestAnimationFrame !== "function") return;

    let frame = 0;
    const started = performance.now();

    const tick = (now: number) => {
      const t = (now - started) / 1000;
      const slot = JARVIS_CYCLE[Math.floor(t * 1000 / MODE_MS) % JARVIS_CYCLE.length];
      // Two sines an irrational-ish ratio apart, so the swirl does not settle
      // into a visible loop while somebody reads the copy beside it.
      const level = 0.3 + 0.16 * Math.sin(t * 0.9) + 0.07 * Math.sin(t * 0.37);
      setPreview({
        familiar: {
          ...RESTING_STAGE_STATE,
          working: true,
          level: Math.min(1, Math.max(0, level)),
          onset: Math.max(0, Math.sin(t * 0.55)) * 0.4,
        },
        jarvis: {
          ...RESTING_JARVIS_STATE,
          ...slot,
          bands: slot.mode === "speaking" ? bandsFor(t) : null,
        },
      });
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  return preview;
}
