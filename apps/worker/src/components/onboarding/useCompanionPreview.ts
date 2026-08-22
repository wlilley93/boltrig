import { useEffect, useState } from "react";

import { RESTING_STAGE_STATE, type FamiliarStageState } from "../familiar/FamiliarState";
import { RESTING_JARVIS_STATE, type JarvisStageState } from "../jarvis/JarvisState";
import {
  RESTING_COLOSSUS_STATE,
  type ColossusStageState,
} from "../colossus/ColossusState";
import { RESTING_ULTRON_STATE, type UltronStageState } from "../ultron/UltronState";
import { currentPreviewAudio } from "./companionVoicePreview";
import { readVoiceSignal } from "./previewAudioSignal";

/** The behaviours the bodies cycle through on the companion card.
 *
 * `standby` LEADS now: it carries the baked loop and the canon look, so it is
 * the face of the instrument rather than a blank. Scripted `speaking` is gone
 * — he only ever speaks from standby, and fake bands demonstrated nothing a
 * real preview line does not do better: a playing clip still overrides the
 * cycle to speaking below, driven by its own audio.
 */
const JARVIS_CYCLE: Array<Partial<JarvisStageState>> = [
  { mode: "standby", level: 0.12 },
  { mode: "thinking", level: 0.18, readout: 2.4 },
  { mode: "working", level: 0.34, readout: 6.1 },
  { mode: "listening", level: 0.12, micLevel: 0.48 },
];

const MODE_MS = 2600;

function bandsFor(t: number): number[] {
  // Eight log bands, each on its own slow beat so the fan never pulses as a
  // block. THE FALLBACK, used when no preview clip is playing: while one is,
  // the bands come from that clip through previewAudioSignal, so the body
  // responds to its own voice rather than to a plausible-looking loop.
  return Array.from({ length: 8 }, (_, i) =>
    0.25 + 0.32 * Math.abs(Math.sin(t * (0.7 + i * 0.13) + i)));
}

export interface CompanionPreview {
  familiar: FamiliarStageState;
  jarvis: JarvisStageState;
  /** Ultron reads the same four signals; only the body differs. */
  ultron: UltronStageState;
  /** And Colossus reads three of them -- he has no use for a mic level. */
  colossus: ColossusStageState;
}

/**
 * What every body is told this frame, derived once.
 *
 * EXTRACTED WHEN THE FOURTH CHARACTER ARRIVED. With three, building all of
 * them inline in the rAF callback was one readable block; the fourth pushed it
 * past the complexity ratchet, and the honest fix is that four per-character
 * shapes derived from one drive is four functions, not one long one.
 */
interface PreviewDrive {
  /** Live analysis of the clip that is playing, or null when nothing is. */
  voice: ReturnType<typeof readVoiceSignal>;
  slot: Partial<JarvisStageState>;
  level: number;
  /** Seconds since mount, for the fallbacks. */
  t: number;
}

function driveFor(t: number): PreviewDrive {
  // THE CLIP FIRST, the timer second. When a preview line is playing the
  // bodies are driven by it -- the rings answer the words actually being said
  // -- and the scripted cycle is what runs the rest of the time.
  const voice = readVoiceSignal(currentPreviewAudio());
  const slot = voice
    ? { mode: "speaking" as const, level: voice.level }
    : JARVIS_CYCLE[Math.floor(t * 1000 / MODE_MS) % JARVIS_CYCLE.length];
  // Two sines an irrational-ish ratio apart, so the swirl does not settle into
  // a visible loop while somebody reads the copy beside it.
  const level = voice
    ? voice.level
    : 0.3 + 0.16 * Math.sin(t * 0.9) + 0.07 * Math.sin(t * 0.37);
  return { voice, slot, level: Math.min(1, Math.max(0, level)), t };
}

/** The bands a body should see: the clip's if one is playing, else the fallback. */
function bandsOf({ voice, slot, t }: PreviewDrive): number[] | null {
  if (voice) return voice.bands;
  return slot.mode === "speaking" ? bandsFor(t) : null;
}

function familiarPreview(drive: PreviewDrive): FamiliarStageState {
  return {
    ...RESTING_STAGE_STATE,
    // THE SAME CYCLE AS THE OTHER THREE, now that she has modes rather than two
    // booleans. She used to be pinned to `working: true` for the whole preview
    // -- the only body in the picker that could not show what its states look
    // like, because it did not have any.
    //
    // A playing clip still overrides to speaking: her voice embodiment is gated
    // on speaking AND bands together, and without both she takes the pulse path
    // and merely looks busy while her own voice plays over the top.
    mode: drive.voice
      ? "speaking"
      : (drive.slot.mode ?? "standby") as FamiliarStageState["mode"],
    bands: drive.voice ? drive.voice.bands : null,
    level: drive.level,
    micLevel: drive.slot.micLevel ?? 0,
    onset: drive.voice?.onset ?? Math.max(0, Math.sin(drive.t * 0.55)) * 0.4,
  };
}

function jarvisPreview(drive: PreviewDrive): JarvisStageState {
  return {
    ...RESTING_JARVIS_STATE,
    ...drive.slot,
    onset: drive.voice?.onset ?? 0,
    bands: bandsOf(drive),
  };
}

function ultronPreview(drive: PreviewDrive): UltronStageState {
  return {
    ...RESTING_ULTRON_STATE,
    // The same cycle, minus the readout and micLevel he has no use for.
    mode: (drive.slot.mode ?? "standby") as UltronStageState["mode"],
    level: drive.level,
    onset: drive.voice?.onset ?? 0,
    bands: bandsOf(drive),
  };
}

function colossusPreview(drive: PreviewDrive): ColossusStageState {
  return {
    ...RESTING_COLOSSUS_STATE,
    // Same cycle again. His sign scrolls faster and his rack answers the bands,
    // which is the whole of his reactivity -- there is no gauge or mic level
    // for a panel to do anything with.
    mode: (drive.slot.mode ?? "standby") as ColossusStageState["mode"],
    level: drive.level,
    onset: drive.voice?.onset ?? 0,
    bands: bandsOf(drive),
  };
}

export function useCompanionPreview(): CompanionPreview {
  const [preview, setPreview] = useState<CompanionPreview>({
    familiar: { ...RESTING_STAGE_STATE, mode: "thinking", level: 0.32 },
    jarvis: { ...RESTING_JARVIS_STATE, ...JARVIS_CYCLE[0] },
    ultron: { ...RESTING_ULTRON_STATE, mode: "thinking", level: 0.3 },
    colossus: { ...RESTING_COLOSSUS_STATE, mode: "thinking", level: 0.3 },
  });

  useEffect(() => {
    const reduced = typeof matchMedia === "function"
      && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof requestAnimationFrame !== "function") return;

    let frame = 0;
    const started = performance.now();

    const tick = (now: number) => {
      const drive = driveFor((now - started) / 1000);
      setPreview({
        familiar: familiarPreview(drive),
        jarvis: jarvisPreview(drive),
        ultron: ultronPreview(drive),
        colossus: colossusPreview(drive),
      });
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  return preview;
}
