/** Eight bands, a level and an onset, taken from the preview clip as it plays.
 *
 * WHY THIS EXISTS. Animal Logic drove the film's holograms with audio signals,
 * and the companion card was driving them with a 2.6-second timer — a scripted
 * cycle of four moods that happens to be running while a voice happens to be
 * playing. Felicity Coonan, who designed those lab scenes, described the
 * approach as retrofitting the graphics to what the actor actually did, giving
 * "a really natural look, not overly choreographed". A timer is precisely the
 * choreographed version.
 *
 * So when a clip is playing, the body responds to THAT clip: click Jarvis and
 * the rings answer the words he is saying. The timer remains for when nothing
 * is playing, which is most of the time.
 *
 * BEST EFFORT, ALWAYS. Every step here can legitimately fail — no WebAudio, a
 * suspended context before the first gesture, a browser that refuses a second
 * MediaElementSource — and none of those may cost the user the voice or the
 * animation. Each returns null and the caller falls back to the timer.
 */

/** What a body needs to be driven by a voice. */
export interface VoiceSignal {
  level: number;
  bands: number[];
  onset: number;
}

interface Rig {
  context: AudioContext;
  analyser: AnalyserNode;
  data: Uint8Array;
  previous: Float32Array;
}

/**
 * One rig per element, forever.
 *
 * `createMediaElementSource` may be called ONCE per media element — a second
 * call throws, and the element is then routed to a dead graph and goes silent.
 * The map is keyed by the element rather than by companion id for that reason:
 * the preview reuses elements, and the identity that matters is the element's.
 */
const RIGS = new WeakMap<HTMLAudioElement, Rig | null>();

/** Eight log-spaced band edges over the analyser's bins, matching bandsFor(). */
function bandEdges(binCount: number): number[] {
  const edges: number[] = [];
  for (let i = 0; i <= 8; i++) {
    // Log spacing, so the low bands are not one bin wide and the high ones half
    // the spectrum — the same shape a voice actually occupies.
    edges.push(Math.round(binCount ** (i / 8)));
  }
  return edges;
}

function rigFor(audio: HTMLAudioElement): Rig | null {
  const existing = RIGS.get(audio);
  if (existing !== undefined) return existing;

  try {
    const Ctor = window.AudioContext
      ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) throw new Error("no WebAudio");
    const context = new Ctor();
    const source = context.createMediaElementSource(audio);
    const analyser = context.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.7;
    source.connect(analyser);
    // MUST reach the destination: routing an element into a graph that ends at
    // the analyser makes it inaudible, which would trade the voice for the
    // animation — the wrong way round for a feature whose point is the voice.
    analyser.connect(context.destination);
    const rig: Rig = {
      context,
      analyser,
      data: new Uint8Array(analyser.frequencyBinCount),
      previous: new Float32Array(8),
    };
    RIGS.set(audio, rig);
    return rig;
  } catch {
    // Remembered as a failure so a broken element is not retried every frame.
    RIGS.set(audio, null);
    return null;
  }
}

/**
 * Read the currently playing preview, or null if there is nothing to read.
 *
 * Null is the honest answer for "not playing", "no WebAudio" and "the context
 * has not been resumed yet" alike: in every one of them the caller has no
 * signal and should use its fallback rather than draw a flat line.
 */
export function readVoiceSignal(audio: HTMLAudioElement | null): VoiceSignal | null {
  if (!audio || audio.paused || audio.ended) return null;
  const rig = rigFor(audio);
  if (!rig) return null;
  // Autoplay policy can leave the context suspended until a gesture; resuming
  // is a promise nobody awaits here, because the next frame will simply try
  // again and the frame after that will succeed.
  if (rig.context.state === "suspended") void rig.context.resume().catch(() => undefined);

  rig.analyser.getByteFrequencyData(rig.data);
  const edges = bandEdges(rig.data.length);
  const bands: number[] = [];
  let sum = 0;
  let flux = 0;
  for (let b = 0; b < 8; b++) {
    const from = edges[b];
    const to = Math.max(from + 1, edges[b + 1]);
    let total = 0;
    for (let i = from; i < to && i < rig.data.length; i++) total += rig.data[i];
    const value = Math.min(1, total / ((to - from) * 255));
    bands.push(value);
    sum += value;
    // Spectral flux: only RISES count, which is what an onset is. Falling
    // energy is the end of a syllable, not the start of one.
    flux += Math.max(0, value - rig.previous[b]);
    rig.previous[b] = value;
  }
  return {
    level: Math.min(1, sum / 8 * 1.6),
    bands,
    onset: Math.min(1, flux * 1.4),
  };
}
