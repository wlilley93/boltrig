/**
 * VOICE LEVEL - what makes a familiar pulse when its agent is talking.
 *
 * There are two sources here and they are NOT the same thing, which is the whole reason this
 * file exists rather than one `useVoiceLevel` that quietly blends them.
 *
 *   MEASURED. A live microphone stream, read through an AnalyserNode. This is real amplitude:
 *   the body swells because a sound is actually that loud. Available while dictation is
 *   running, because that is when boltrig holds a mic stream.
 *
 *   SYNTHESISED. `speechSynthesis` gives no output level at all - no analyser node, no
 *   metering, nothing. When an agent is being read aloud, the only fact available is the
 *   boolean "it is speaking". So the envelope below is generated, and it is named
 *   `speakingEnvelope` rather than `voiceLevel` so that no call site can mistake it for
 *   measurement. It says "this one is talking", which is true; it does not say "this is how
 *   loud", which would be invented.
 *
 * The distinction matters beyond pedantry. A synthesised envelope that looked like real
 * metering would be the exact defect this whole feature is built against: a picture that
 * appears to be evidence and is not.
 */

import { useEffect, useRef, useState } from "react";

/**
 * A generated 0..1 envelope for "this agent is speaking".
 *
 * Deliberately irregular rather than a clean sine. Speech is not periodic, and a body pulsing
 * on a metronome reads as a loading spinner - a machine waiting - which is the opposite of the
 * impression wanted. Three incommensurable frequencies never repeat over any watchable span.
 *
 * Pure and time-parameterised so it can be tested without a clock or a GPU.
 */
export function speakingEnvelope(tSeconds: number): number {
  const a = Math.sin(tSeconds * 7.3);
  const b = Math.sin(tSeconds * 11.7 + 1.1);
  const c = Math.sin(tSeconds * 3.1 + 2.6);
  // Biased upward and floored: a speaking agent should never drop to fully silent mid-word,
  // because a familiar that flickers to nothing looks like it is failing rather than talking.
  const v = 0.55 + 0.28 * a + 0.12 * b + 0.16 * c;
  return v < 0.18 ? 0.18 : v > 1 ? 1 : v;
}

/**
 * Real amplitude from a live MediaStream. Returns a ref rather than state on purpose: this
 * updates at frame rate, and putting it in state would re-render the React tree 60 times a
 * second for a number only the GPU consumes.
 *
 * Returns a ref that reads 0 when there is no stream, which is the correct rest value: no
 * microphone means no sound, not unknown.
 */
export function useMicLevel(stream: MediaStream | null): React.MutableRefObject<number> {
  const level = useRef(0);

  useEffect(() => {
    if (!stream) {
      level.current = 0;
      return;
    }
    let raf = 0;
    let ctx: AudioContext | null = null;
    try {
      ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      // A short smoothing constant: too long and the body lags the voice visibly, too short
      // and it jitters on every consonant.
      analyser.smoothingTimeConstant = 0.6;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);

      const tick = () => {
        raf = requestAnimationFrame(tick);
        analyser.getByteTimeDomainData(buf);
        // RMS about the 128 midpoint. Peak would spike on a single sample and make the body
        // twitch; RMS is what "how loud is this" actually means.
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const d = (buf[i] - 128) / 128;
          sum += d * d;
        }
        const rms = Math.sqrt(sum / buf.length);
        // Speech RMS sits well under 0.5 even when loud, so it is scaled to use the range.
        level.current = Math.min(1, rms * 3.2);
      };
      tick();
    } catch {
      // No AudioContext (or the tab has no user gesture yet). Silence is the honest answer,
      // and the familiar simply does not pulse - it does not fall back to a fake envelope,
      // because a fake reading is worse than no reading.
      level.current = 0;
    }

    return () => {
      if (raf) cancelAnimationFrame(raf);
      void ctx?.close().catch(() => {});
      level.current = 0;
    };
  }, [stream]);

  return level;
}

/**
 * The value to hand a <Familiar> for an agent that is being read aloud.
 *
 * Ticks on rAF while speaking and holds 0 otherwise, so a page full of silent agents costs
 * nothing. State rather than a ref here because `speaking` flips rarely, and the Familiar
 * component reads the value through a callback that samples whatever the latest render gave
 * it - a ref would work equally well but would not survive the component being remounted.
 */
export function useSpeakingLevel(speaking: boolean): number {
  const [level, setLevel] = useState(0);

  useEffect(() => {
    if (!speaking) {
      setLevel(0);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = () => {
      raf = requestAnimationFrame(tick);
      setLevel(speakingEnvelope((performance.now() - t0) / 1000));
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [speaking]);

  return level;
}
