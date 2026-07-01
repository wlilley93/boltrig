"use client";

import { animated, useSpring } from "@react-spring/web";

import { useStory } from "@/components/brain/story/use-story";
import { type StorySectionData } from "@/data/story";

export interface StoryChromeProps {
  sections: StorySectionData[];
}

/**
 * Minimal persistent chrome: a single **bottom-centre chapter progress rail** that
 * tracks the active section (the top edge is framed by the telemetry status bar;
 * corner brackets and the scroll hint were removed for a cleaner console look).
 * Pointer-transparent so it never blocks the canvas; reveals on load with a spring.
 */
export const StoryChrome = ({ sections }: StoryChromeProps) => {
  const section = useStory((s) => s.section);

  const enter = useSpring({
    from: { opacity: 0 },
    to: { opacity: 1 },
    delay: 300,
    config: { tension: 80, friction: 26 },
  });

  return (
    <animated.nav
      aria-hidden
      style={{ opacity: enter.opacity }}
      className="pointer-events-none fixed inset-x-0 bottom-8 z-30 flex select-none items-end justify-center gap-3 md:bottom-10"
    >
      {sections.map((s, i) => (
        <div key={s.id} className="flex flex-col items-center gap-1.5">
          <span
            className={`h-px transition-all ${
              i === section ? "w-8 bg-brain-sky/90" : "w-4 bg-brain-sky/25"
            }`}
          />
          <span
            className={`text-[0.6rem] tabular-nums tracking-[0.2em] transition-opacity ${
              i === section ? "text-brain-sky/90" : "text-brain-sky/30"
            }`}
          >
            {String(i + 1).padStart(2, "0")}
          </span>
        </div>
      ))}
    </animated.nav>
  );
};
