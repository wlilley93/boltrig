"use client";

import { useEffect } from "react";

import { useStory } from "@/components/brain/story/use-story";
import { useScroll } from "@/hooks/smooth-scroll/use-scroll";

export interface StoryScrollDriverProps {
  /** Number of chapters — used to derive the active section from progress. */
  sectionCount: number;
}

/**
 * Render-nothing client component that feeds whole-page scroll into the story
 * store. Prefers the live Lenis instance (its `scroll` event already carries a
 * normalised `progress`); falls back to a native `scroll` listener if Lenis
 * hasn't mounted yet. Writes `progress` (0→1) and the derived `section` index —
 * the camera rig and scene read `progress` imperatively, while DOM chrome
 * subscribes to `section`.
 */
export const StoryScrollDriver = ({ sectionCount }: StoryScrollDriverProps) => {
  const lenis = useScroll((s) => s.lenis);
  const setProgress = useStory((s) => s.setProgress);
  const setSection = useStory((s) => s.setSection);

  useEffect(() => {
    const apply = (progress: number) => {
      const clamped = Math.min(Math.max(progress, 0), 1);
      setProgress(clamped);
      // Active chapter: split [0,1] into `sectionCount` equal bands.
      const section = Math.min(sectionCount - 1, Math.floor(clamped * sectionCount));
      setSection(section);
    };

    if (lenis) {
      // Lenis passes its own instance to the handler; reading `lenis.progress`
      // directly keeps this independent of the event-arg shape.
      const onScroll = () => apply(lenis.progress ?? 0);
      lenis.on("scroll", onScroll);
      // Seed once with the current position (Lenis won't fire until the next move).
      onScroll();
      return () => lenis.off("scroll", onScroll);
    }

    // Fallback: native scroll until Lenis is ready.
    const onScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      apply(max > 0 ? window.scrollY / max : 0);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [lenis, sectionCount, setProgress, setSection]);

  return null;
};
