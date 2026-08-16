import { describe, expect, it } from "vitest";

import {
  advanceSpin,
  approach,
  clamp01,
  spinRate,
  stepSweep,
  sweepPeriod,
  SWEEP_MAX_SECONDS,
  SWEEP_MIN_SECONDS,
  WAVE_SAMPLES,
} from "../src/components/jarvis/JarvisMotion";

describe("jarvis host motion", () => {
  it("approaches a target without overshooting, at any frame rate", () => {
    expect(approach(0, 1, 0.016, 0.2)).toBeGreaterThan(0);
    expect(approach(0, 1, 0.016, 0.2)).toBeLessThan(1);
    expect(approach(0, 1, 10, 0.2)).toBeCloseTo(1, 6);
  });

  // The whole reason this is exponential rather than a fixed step: one 1s frame
  // and sixty 1/60s frames must land in the same place, or a background tab
  // resuming would snap the dial.
  it("is frame-rate independent", () => {
    let stepped = 0;
    for (let i = 0; i < 60; i++) stepped = approach(stepped, 1, 1 / 60, 0.5);
    const single = approach(0, 1, 1, 0.5);
    expect(stepped).toBeCloseTo(single, 3);
  });

  it("speeds the dial with arousal and drags it with fatigue", () => {
    expect(spinRate(1, 0)).toBeGreaterThan(spinRate(0, 0));
    expect(spinRate(1, 1)).toBeLessThan(spinRate(1, 0));
    expect(spinRate(0, 0)).toBeGreaterThan(0);
  });

  // A mood change must never rewind the rings — the phase only accumulates.
  it("never moves the phase backwards when the rate changes", () => {
    let spin = 0;
    const rates: [number, number][] = [[0.9, 0], [0.1, 0.9], [0.5, 0.2], [1, 1]];
    for (const [arousal, fatigue] of rates) {
      const next = advanceSpin(spin, 0.1, arousal, fatigue);
      expect(next).toBeGreaterThanOrEqual(spin);
      spin = next;
    }
  });

  it("clamps non-finite and out-of-range values to 0..1", () => {
    expect(clamp01(NaN)).toBe(0);
    expect(clamp01(Infinity)).toBe(0);
    expect(clamp01(undefined)).toBe(0);
    expect(clamp01(-3)).toBe(0);
    expect(clamp01(9)).toBe(1);
  });

  describe("the listening sweep", () => {
    it("fills every slot the head crossed, not just the one under it", () => {
      const wave = new Float32Array(WAVE_SAMPLES);
      // A single slow frame covering a quarter of a revolution.
      stepSweep(wave, 0, SWEEP_MIN_SECONDS * 0.25, 0.8, SWEEP_MIN_SECONDS);
      const written = Array.from(wave.slice(0, 32)).filter((v) => v > 0).length;
      expect(written).toBeGreaterThan(30); // continuous, not a comb of gaps
    });

    it("wipes the buffer when the head passes 12 o'clock", () => {
      const wave = new Float32Array(WAVE_SAMPLES);
      stepSweep(wave, 0, SWEEP_MIN_SECONDS * 0.9, 1, SWEEP_MIN_SECONDS);
      expect(wave[100]).toBeGreaterThan(0);

      const step = stepSweep(wave, 0.9, SWEEP_MIN_SECONDS * 0.2, 1, SWEEP_MIN_SECONDS);
      expect(step.wrapped).toBe(true);
      expect(wave[100]).toBe(0); // the old trace is gone, not overwritten in place
    });

    it("reports a head that always sits in 0..1", () => {
      const wave = new Float32Array(WAVE_SAMPLES);
      let head = 0;
      for (let i = 0; i < 200; i++) {
        head = stepSweep(wave, head, 0.2, 0.5, SWEEP_MIN_SECONDS).head;
        expect(head).toBeGreaterThanOrEqual(0);
        expect(head).toBeLessThan(1);
      }
    });

    it("clamps the written level rather than trusting the caller", () => {
      const wave = new Float32Array(WAVE_SAMPLES);
      stepSweep(wave, 0, SWEEP_MIN_SECONDS * 0.1, 42, SWEEP_MIN_SECONDS);
      expect(Math.max(...wave)).toBe(1);
    });

    it("stretches the revolution as an utterance goes on", () => {
      expect(sweepPeriod(0)).toBe(SWEEP_MIN_SECONDS);
      expect(sweepPeriod(SWEEP_MAX_SECONDS)).toBe(SWEEP_MAX_SECONDS);
      expect(sweepPeriod(5)).toBeGreaterThan(sweepPeriod(1));
      // Never runs away: a very long spell still lands on the cap.
      expect(sweepPeriod(600)).toBe(SWEEP_MAX_SECONDS);
    });

    // The reason the head is integrated rather than derived from absolute time:
    // the period changes while a sweep is in progress, and a derived head would
    // jump backwards the moment it stretched, erasing part of the trace.
    it("never moves the head backwards when the period stretches", () => {
      const wave = new Float32Array(WAVE_SAMPLES);
      let head = 0;
      let spell = 0;
      for (let i = 0; i < 40; i++) {
        spell += 0.25;
        const next = stepSweep(wave, head, 0.25, 0.6, sweepPeriod(spell));
        if (!next.wrapped) expect(next.head).toBeGreaterThan(head);
        head = next.head;
      }
    });
  });
});
