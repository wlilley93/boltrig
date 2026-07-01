"use client";

import { useEffect, useState } from "react";
import { useProgress } from "@react-three/drei";
import { animated, easings, useSpring } from "@react-spring/web";

import { useStory } from "./story/use-story";

const MIN_VISIBLE_MS = 900; // never flash — hold a beat even on instant loads
const HARD_CAP_MS = 6000; // ultimate fallback if the loader manager never settles

const bootLine = (p: number) =>
  p < 35 ? "INITIALIZING NEURAL FIELD" : p < 75 ? "SAMPLING CORTICAL SURFACE" : "CALIBRATING SYNAPSES";

/**
 * Immersive entry loader for the particle brain — a slick console "boot
 * sequence": a slow breathing core over the deep void, a terminal status line
 * with a blinking caret, and a thin progress meter. Reads load progress from
 * drei's `useProgress`; once idle it flips the shared `entered` flag (so the
 * brain plays its assemble-in entrance *as* this fades) and fades itself out.
 * All motion is `@react-spring/web` (rule #1).
 */
export const BrainLoader = () => {
  const { active, progress } = useProgress();
  const setEntered = useStory((s) => s.setEntered);
  const [done, setDone] = useState(false);
  const [unmounted, setUnmounted] = useState(false);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }, []);

  // Fade out once loading is idle (with a minimum hold), and a hard cap so a
  // cached/instant load — where the manager never re-fires — can't get stuck.
  useEffect(() => {
    const cap = setTimeout(() => setDone(true), HARD_CAP_MS);
    let hold: ReturnType<typeof setTimeout> | undefined;
    if (!active && progress >= 100) {
      hold = setTimeout(() => setDone(true), MIN_VISIBLE_MS);
    }
    return () => {
      clearTimeout(cap);
      if (hold) clearTimeout(hold);
    };
  }, [active, progress]);

  // Hand off to the scene the moment we start leaving — the brain assembles in
  // as the curtain fades, for a seamless crossfade rather than a pop.
  useEffect(() => {
    if (done) setEntered(true);
  }, [done, setEntered]);

  const breathe = useSpring({
    from: { scale: 0.85, glow: 0.3 },
    to: { scale: 1.12, glow: 0.7 },
    loop: { reverse: true },
    pause: reduced,
    config: { duration: 2900, easing: easings.easeInOutSine },
  });
  const caret = useSpring({
    from: { o: 1 },
    to: { o: 0.1 },
    loop: { reverse: true },
    config: { duration: 600, easing: easings.easeInOutQuad },
  });
  const curtain = useSpring({
    opacity: done ? 0 : 1,
    config: { duration: 1100, easing: easings.easeInOutCubic },
    onRest: () => {
      if (done) setUnmounted(true);
    },
  });
  const meter = useSpring({ p: Math.min(100, progress), config: { tension: 120, friction: 26 } });

  if (unmounted) return null;

  return (
    <animated.div
      aria-hidden
      style={{
        opacity: curtain.opacity,
        background: "radial-gradient(circle at 50% 44%, var(--brain-deep), var(--brain-void) 70%)",
      }}
      className="pointer-events-none fixed inset-0 z-50 flex flex-col items-center justify-center gap-14 px-8"
    >
      {/* Breathing neural core */}
      <div className="relative flex h-40 w-40 items-center justify-center md:h-48 md:w-48">
        <animated.span
          style={{ scale: breathe.scale, opacity: breathe.glow }}
          className="absolute h-32 w-32 rounded-full bg-brain-azure/30 blur-3xl"
        />
        {[0.62, 1].map((ring, i) => (
          <animated.span
            key={ring}
            style={{
              scale: breathe.scale.to((s) => s * ring),
              opacity: breathe.glow.to((g) => g * (1 - i * 0.3)),
            }}
            className="absolute h-40 w-40 rounded-full border border-brain-sky/40"
          />
        ))}
        <animated.span
          style={{ scale: breathe.scale.to((s) => s * 0.26), opacity: breathe.glow }}
          className="h-40 w-40 rounded-full bg-brain-sky/70 blur-xl"
        />
      </div>

      {/* Terminal boot readout */}
      <div className="flex w-full max-w-xs flex-col items-center gap-5">
        <p className="text-sm font-semibold uppercase tracking-[0.5em] text-brain-sky/85 md:text-base">
          NEURAL_ATLAS
        </p>
        <p className="flex items-center gap-2 text-[0.66rem] uppercase tracking-[0.24em] text-brain-sky/55">
          <span aria-hidden className="text-brain-sky/40">
            &gt;
          </span>
          <animated.span>{meter.p.to((p) => bootLine(p))}</animated.span>
          <animated.span style={{ opacity: caret.o }}>_</animated.span>
        </p>

        {/* Progress meter */}
        <div className="flex w-full items-center gap-3">
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-brain-sky/12">
            <animated.div
              style={{ width: meter.p.to((p) => `${p}%`) }}
              className="h-full rounded-full bg-brain-sky shadow-[0_0_10px_1px] shadow-brain-azure/60"
            />
          </div>
          <animated.span className="w-9 text-right text-[0.66rem] font-medium tabular-nums tracking-wider text-brain-sky/60">
            {meter.p.to((p) => `${Math.round(p)}%`)}
          </animated.span>
        </div>
      </div>
    </animated.div>
  );
};
