"use client";

import { useEffect, useState } from "react";
import { animated, easings, useSpring } from "@react-spring/web";

import { STORY_SECTIONS } from "@/data/story";

import { useStory } from "./story/use-story";
import { useBrainControls } from "./use-brain-controls";

const NEURON_COUNT = "86,000,000,000";
const REGIONS = [
  "frontal cortex",
  "occipital lobe",
  "hippocampus",
  "cerebellum",
  "parietal lobe",
  "brain stem",
  "temporal lobe",
] as const;
const SPARK_BARS = 36;

// The "focus" readout tracks the active chapter — its first data readout value,
// falling back to the cycling synthetic region if a chapter defines none.
const focusForSection = (section: number, fallback: string) =>
  STORY_SECTIONS[section]?.readouts?.[0]?.value ?? fallback;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const term = (s: string) => s.toUpperCase().replace(/\s+/g, "_");

// Deterministic seed so SSR and the first client render match; the live feed only
// starts mutating after mount (in effects), avoiding hydration drift.
const SEED_WAVE = Array.from({ length: SPARK_BARS }, (_, i) =>
  Math.round(45 + 35 * Math.sin(i * 0.6)),
);

/**
 * The neural monitor — a full-width, terminal-style status line fixed to the top
 * of the viewport (a console "title bar"). Streams synthetic synaptic activity:
 * a live firing rate, coherence, a running waveform, and a focus readout that
 * follows the active story chapter. Looping motion (cursor blink, status pulse,
 * animated numbers) is spring-based per rule #1; the streaming data updates on
 * timers in effects (client-only, so no hydration mismatch).
 */
export const BrainTelemetry = () => {
  const surfaceCount = useBrainControls((s) => s.config.surfaceCount);
  const section = useStory((s) => s.section);

  const [firing, setFiring] = useState(4.21);
  const [coherence, setCoherence] = useState(0.92);
  const [wave, setWave] = useState<number[]>(SEED_WAVE);
  const [regionIdx, setRegionIdx] = useState(0);

  // Fast tick — waveform + live readouts (the "scope" feel).
  useEffect(() => {
    const id = setInterval(() => {
      setFiring((f) => clamp(f + (Math.random() - 0.5) * 0.5, 3.4, 5.6));
      setCoherence((c) => clamp(c + (Math.random() - 0.5) * 0.05, 0.74, 0.99));
      setWave((w) => {
        const last = w[w.length - 1] ?? 50;
        const next = clamp(last + (Math.random() - 0.5) * 46, 6, 100);
        return [...w.slice(1), next];
      });
    }, 140);
    return () => clearInterval(id);
  }, []);

  // Slow tick — advance the synthetic focus region (fallback when a chapter has none).
  useEffect(() => {
    const id = setInterval(() => setRegionIdx((i) => (i + 1) % REGIONS.length), 1500);
    return () => clearInterval(id);
  }, []);

  const enter = useSpring({
    from: { opacity: 0, y: -12 },
    to: { opacity: 1, y: 0 },
    delay: 350,
    config: { tension: 120, friction: 26 },
  });
  const blink = useSpring({
    from: { o: 1 },
    to: { o: 0.12 },
    loop: { reverse: true },
    config: { duration: 620, easing: easings.easeInOutQuad },
  });
  const pulse = useSpring({
    from: { o: 0.25 },
    to: { o: 1 },
    loop: { reverse: true },
    config: { duration: 1400, easing: easings.easeInOutSine },
  });
  const firingSpring = useSpring({ v: firing, config: { tension: 140, friction: 18 } });
  const cohSpring = useSpring({ v: coherence, config: { tension: 140, friction: 20 } });

  const focus = term(focusForSection(section, REGIONS[regionIdx]));

  return (
    <animated.section
      aria-hidden
      style={{ opacity: enter.opacity, y: enter.y }}
      className="fixed inset-x-0 top-0 z-30 flex h-9 items-center gap-4 overflow-hidden border-b border-brain-sky/15 bg-brain-void/55 px-5 text-[0.6rem] uppercase tracking-[0.2em] text-brain-sky/80 backdrop-blur-md md:h-10 md:gap-5 md:px-8"
    >
      {/* Brand */}
      <span className="flex items-center gap-2 font-semibold text-brain-sky/90">
        <animated.span
          style={{ opacity: pulse.o }}
          className="h-1.5 w-1.5 rounded-full bg-brain-sky shadow-[0_0_10px_2px] shadow-brain-azure/60"
        />
        NEURAL_MONITOR
        <span className="hidden text-brain-sky/35 sm:inline">{"// LIVE"}</span>
      </span>

      <Seg label="NEURONS" className="hidden xl:flex">
        {NEURON_COUNT}
      </Seg>
      <Seg label="PARTICLES" className="hidden lg:flex">
        {surfaceCount.toLocaleString("en-US")}
      </Seg>
      <Seg label="FIRING" className="hidden sm:flex">
        <animated.span>{firingSpring.v.to((v) => `${v.toFixed(2)} M/S`)}</animated.span>
      </Seg>
      <Seg label="COHERENCE" className="hidden sm:flex">
        <animated.span>{cohSpring.v.to((v) => `${(v * 100).toFixed(1)}%`)}</animated.span>
      </Seg>
      <Seg label="FOCUS">
        <FocusRegion key={focus} name={focus} />
      </Seg>

      {/* Waveform + prompt, pushed right */}
      <div className="ml-auto flex items-center gap-4">
        <div className="hidden h-4 w-28 items-end gap-px md:flex md:w-40">
          {wave.map((h, i) => (
            <span
              key={i}
              style={{ height: `${h}%` }}
              className={`flex-1 ${i === wave.length - 1 ? "bg-brain-sky" : "bg-brain-sky/35"}`}
            />
          ))}
        </div>
        <span className="flex items-center gap-1 text-brain-sky/75">
          <span>&gt;</span>
          <animated.span style={{ opacity: blink.o }}>_</animated.span>
        </span>
      </div>
    </animated.section>
  );
};

const Seg = ({
  label,
  children,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) => (
  <span className={`flex items-center gap-2 border-l border-brain-sky/15 pl-4 md:pl-5 ${className}`}>
    <span className="text-brain-sky/40">{label}</span>
    <span className="tabular-nums text-brain-sky/90">{children}</span>
  </span>
);

// Keyed by `name` in the parent, so it mounts fresh (and animates once) per
// focus change — re-renders from the fast waveform tick must not restart it.
const FocusRegion = ({ name }: { name: string }) => {
  const style = useSpring({
    from: { opacity: 0, x: 6 },
    to: { opacity: 1, x: 0 },
    config: { tension: 220, friction: 24 },
  });
  return (
    <animated.span style={{ opacity: style.opacity, x: style.x }}>{name}</animated.span>
  );
};
