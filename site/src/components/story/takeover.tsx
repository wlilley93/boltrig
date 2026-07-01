"use client";

import { useEffect, useRef } from "react";
import { animated, easings, useSpring } from "@react-spring/web";
import TextEngine from "spring-text-engine";

import { useStory } from "@/components/brain/story/use-story";
import { type StorySectionData } from "@/data/story";
import { subscribeToTicker } from "@/lib/animation/ticker";

import { TerminalCursor, TerminalPanel, term } from "./terminal";

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const NODE_COUNT = 64;
const LINK_DIST = 150; // px — nodes closer than this get a connecting line

/**
 * Full-screen procedural "signal field" that takes over for the Signals chapter,
 * hiding the brain behind an opaque drifting-node network (a stand-in for the
 * brain's electrical traffic — no video assets). Mounted once, fixed; its opacity
 * springs to 1 while the takeover chapter is active and back to 0 otherwise, so
 * the brain dissolves away and then returns. The canvas itself animates on the
 * shared ticker (the supported per-frame extension point), only while visible.
 */
export const TakeoverVisual = ({ activeIndex }: { activeIndex: number }) => {
  const section = useStory((s) => s.section);
  const active = section === activeIndex;
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const cover = useSpring({
    opacity: active ? 1 : 0,
    config: { duration: 700, easing: easings.easeInOutCubic },
  });

  useEffect(() => {
    if (!active) return; // only burn CPU while the field is on screen
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    let nodes: Node[] = [];
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (nodes.length === 0) {
        nodes = Array.from({ length: NODE_COUNT }, () => ({
          x: Math.random() * window.innerWidth,
          y: Math.random() * window.innerHeight,
          vx: (Math.random() - 0.5) * 0.35,
          vy: (Math.random() - 0.5) * 0.35,
        }));
      }
    };
    resize();
    window.addEventListener("resize", resize);

    const draw = (time: number) => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      ctx.clearRect(0, 0, w, h);

      for (const n of nodes) {
        n.x += n.vx;
        n.y += n.vy;
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;
      }
      // Links
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const d = Math.hypot(dx, dy);
          if (d < LINK_DIST) {
            ctx.strokeStyle = `rgba(142, 203, 255, ${0.18 * (1 - d / LINK_DIST)})`;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }
      // Nodes — pulse the brightness so the field "fires".
      for (const n of nodes) {
        const pulse = 0.5 + 0.5 * Math.sin(time * 0.004 + n.x * 0.01);
        ctx.fillStyle = `rgba(190, 224, 255, ${0.35 + 0.45 * pulse})`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, 1.6, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const unsubscribe = subscribeToTicker(draw, () => 16);
    return () => {
      unsubscribe();
      window.removeEventListener("resize", resize);
    };
  }, [active]);

  return (
    <animated.div
      aria-hidden
      style={{ opacity: cover.opacity, pointerEvents: "none" }}
      className="fixed inset-0 z-10 bg-brain-void"
    >
      <canvas ref={canvasRef} className="h-full w-full" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_center,transparent_40%,var(--brain-void)_92%)]" />
    </animated.div>
  );
};

/**
 * The takeover chapter's in-flow text — a deliberately minimal centred block
 * (no scan frame), sitting over the signal field as it scrolls past.
 */
export const TakeoverPanel = ({ data }: { data: StorySectionData }) => (
  <section
    id={data.id}
    aria-label={data.title}
    className="pointer-events-none relative flex h-screen w-full flex-col items-center justify-center px-8 text-center"
  >
    <p className="mb-6 flex items-center gap-2 text-[0.72rem] font-semibold uppercase tracking-[0.45em] text-brain-sky/75 md:text-sm">
      <span aria-hidden className="text-brain-sky/45">
        &gt;
      </span>
      <TextEngine
        tag="span"
        mode="always"
        wordIn={{ y: 0, opacity: 1 }}
        wordOut={{ y: 10, opacity: 0 }}
        wordStagger={50}
        wordConfig={{ duration: 700, easing: easings.easeOutQuart }}
      >
        {term(data.eyebrow)}
      </TextEngine>
      <TerminalCursor />
    </p>
    <TextEngine
      tag="h2"
      mode="always"
      overflow
      lineIn={{ y: "0%", opacity: 1 }}
      lineOut={{ y: "110%", opacity: 0 }}
      lineStagger={100}
      lineConfig={{ duration: 1000, easing: easings.easeOutCubic }}
      style={{ justifyContent: "center" }}
      className="max-w-4xl text-center text-[2.1rem] font-semibold leading-[1.12] tracking-tight text-white md:text-5xl lg:text-6xl"
    >
      {data.title}
    </TextEngine>
    <TerminalPanel
      name={data.id}
      body={data.body}
      readouts={data.readouts}
      className="mt-9 w-full max-w-2xl md:w-[52vw] md:max-w-3xl"
    />
  </section>
);
