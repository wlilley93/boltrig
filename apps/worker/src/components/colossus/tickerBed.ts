// The room he is in.
//
// WHY HE HAS ONE AND THE OTHERS DO NOT. Familiar, Jarvis and Ultron are bodies
// in a void, and the only sound any of them makes is speech. Colossus is a
// building: the 1970 reference is a hall of relays, and the sound of one
// working is a continuous mechanical clatter under everything anybody says in
// it. The bed is the board updating while he talks -- the same claim the
// scrolling ticker makes visually, made audible.
//
// IT LIVES WITH THE BODY, NOT WITH A CALLER. The first version hung off the
// onboarding preview, which meant it played on the companion card and nowhere
// else -- not in a voice call, not on the Stage, not anywhere he actually
// speaks. Owning it here means every path that makes him speak gets it, and
// none of them had to know it exists.
//
// A BED, NOT AN EFFECT. It fades in under the line, loops for as long as he is
// speaking, and fades out with him -- head and tail measure within a few dB of
// each other, so the loop seam falls inside the texture rather than clicking.
// Autoplay policy may refuse it before the page has been interacted with; that
// is a silent no-op by design, because a missing room tone must never be able
// to cost him his voice.

const SRC = "/companion/colossus-ticker.mp3";

/** Well under the voice. It is the room, not a second speaker. */
const VOLUME = 0.16;

/** Seconds. Long enough that it arrives and leaves rather than switching. */
const FADE_S = 0.45;

export class TickerBed {
  private audio: HTMLAudioElement | null = null;
  private fade = 0;

  /** Play the arrival, once.
   *
   * NOT A LOOP ANY MORE. Running it for the whole time he speaks makes the
   * clatter ambient, and ambient sound stops carrying information. The board
   * only makes that noise when the message CHANGES, so this fires on the
   * message first appearing and is silent while the same one keeps scrolling --
   * which is what makes hearing it mean something new arrived.
   *
   * Idempotent while a play is in flight, so a re-render cannot stack two. */
  start(): void {
    if (this.audio) return;
    if (typeof Audio !== "function") return;
    try {
      const audio = new Audio(SRC);
      audio.volume = 0;
      this.audio = audio;
      // Ends itself: one pass, then release, so nothing has to remember to
      // stop it when the message stops being new.
      audio.addEventListener("ended", () => {
        if (this.audio === audio) this.audio = null;
      });
      void audio.play().catch(() => this.stop());
      audio.volume = VOLUME;
    } catch {
      this.audio = null;
    }
  }

  /** Fade out and release. Safe to call when nothing is playing. */
  stop(): void {
    const audio = this.audio;
    if (!audio) return;
    this.audio = null;
    this.ramp(0, audio, () => audio.pause());
  }

  /** Immediate, for unmount -- a fade would outlive the component. */
  destroy(): void {
    window.clearInterval(this.fade);
    this.fade = 0;
    this.audio?.pause();
    this.audio = null;
  }

  private ramp(to: number, on?: HTMLAudioElement, done?: () => void): void {
    const audio = on ?? this.audio;
    if (!audio) return;
    window.clearInterval(this.fade);
    const from = audio.volume;
    const started = performance.now();
    this.fade = window.setInterval(() => {
      const t = Math.min(1, (performance.now() - started) / (FADE_S * 1000));
      audio.volume = Math.min(1, Math.max(0, from + (to - from) * t));
      if (t < 1) return;
      window.clearInterval(this.fade);
      this.fade = 0;
      done?.();
    }, 40);
  }
}
