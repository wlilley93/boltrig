/** Short pre-rendered lines in Familiar's own voice, for the companion card.
 *
 * Pre-rendered rather than synthesised on demand: the card is shown before any
 * provider is configured, so it must not depend on the kernel, a voice adapter
 * or an API key. They are `vera`, the Pocket TTS catalog voice Familiar uses at
 * runtime, so the preview is the voice you actually get.
 *
 * Cycling matters. One clip replayed on every click stops being a voice and
 * becomes a notification sound.
 */
const CLIPS = [
  "/companion/familiar-1.wav",
  "/companion/familiar-2.wav",
  "/companion/familiar-3.wav",
];

let next = 0;
let current: HTMLAudioElement | null = null;

export function playFamiliarPreview(): void {
  if (typeof Audio !== "function") return;
  // Cut the previous line off rather than letting two overlap, which is what
  // happens when somebody clicks the card twice.
  if (current) {
    current.pause();
    current = null;
  }
  const clip = CLIPS[next % CLIPS.length];
  next += 1;
  try {
    const audio = new Audio(clip);
    audio.volume = 0.85;
    current = audio;
    // Best-effort: autoplay policy may refuse until the page has been
    // interacted with. A refusal must not break selecting the companion.
    void audio.play().catch(() => undefined);
  } catch {
    current = null;
  }
}
