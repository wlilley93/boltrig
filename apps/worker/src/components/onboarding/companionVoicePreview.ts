/** Short pre-rendered lines in each companion's own voice, for the carousel.
 *
 * Pre-rendered rather than synthesised on demand: the card is shown before any
 * provider is configured, so it must not depend on the kernel, a voice adapter
 * or an API key. Each set is rendered with the voice that character actually
 * uses at runtime -- Familiar's `vera` and Jarvis's `jarvis`, both Pocket TTS
 * catalog voices named in their bundles -- so the preview is the voice you get.
 *
 * Cycling matters. One clip replayed on every arrival stops being a voice and
 * becomes a notification sound.
 *
 * BOTH JARVIS SKINS SHARE ONE SET, deliberately. A skin is a body, not a
 * different person: giving the Ultron look its own lines would say the two are
 * different characters, which is the one thing the skin model exists to deny.
 */
const CLIPS: Record<string, readonly string[]> = {
  familiar: [
    "/companion/familiar-1.wav",
    "/companion/familiar-2.wav",
    "/companion/familiar-3.wav",
  ],
  jarvis: [
    "/companion/jarvis-1.wav",
    "/companion/jarvis-2.wav",
    "/companion/jarvis-3.wav",
  ],
};

/** Per-companion, so walking to Jarvis and back does not replay Familiar's first line. */
const next: Record<string, number> = {};
let current: HTMLAudioElement | null = null;

/**
 * The element the preview is playing through, for anything that wants to WATCH
 * the audio rather than just start it -- the companion stage drives its bands
 * and level from this so the body responds to its own voice.
 *
 * Null when nothing is playing, which is the honest answer: an analyser hung
 * off a finished element would report silence forever and look like a bug.
 */
export function currentPreviewAudio(): HTMLAudioElement | null {
  return current;
}

export function playCompanionPreview(id: string): void {
  if (typeof Audio !== "function") return;
  const clips = CLIPS[id];
  if (!clips || clips.length === 0) return;

  // Cut the previous line off rather than letting two overlap, which is what
  // happens when somebody walks the carousel faster than a clip is long.
  if (current) {
    current.pause();
    current = null;
  }
  const index = next[id] ?? 0;
  next[id] = index + 1;
  try {
    const audio = new Audio(clips[index % clips.length]);
    audio.volume = 0.85;
    audio.crossOrigin = "anonymous";
    current = audio;
    audio.addEventListener("ended", () => {
      if (current === audio) current = null;
    });
    // Best-effort: autoplay policy may refuse until the page has been
    // interacted with. A refusal must not break choosing the companion.
    void audio.play().catch(() => undefined);
  } catch {
    current = null;
  }
}
