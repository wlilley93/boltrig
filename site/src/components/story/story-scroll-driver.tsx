"use client";

import { useEffect } from "react";

import { useStory } from "@/components/brain/story/use-story";
import { useScroll } from "@/hooks/smooth-scroll/use-scroll";

export interface StoryScrollDriverProps {
  /** Number of chapters — used to derive the active section from progress. */
  sectionCount: number;
}

/**
 * Render-nothing client component that feeds page scroll into the story store.
 * Progress normalises over the **story's own extent**, `sectionCount` screen-high
 * panels at the top of the page (scrollable range `(sectionCount - 1)` viewports),
 * NOT the whole document: content that follows the story in normal flow (the
 * features section) must not stretch the camera-keyframe mapping. Prefers the
 * live Lenis instance's pixel `scroll`; falls back to a native `scroll` listener
 * if Lenis hasn't mounted yet. Writes `progress` (0→1, clamped at the finale) and
 * the derived `section` index — the camera rig and scene read `progress`
 * imperatively, while DOM chrome subscribes to `section`.
 */
export const StoryScrollDriver = ({ sectionCount }: StoryScrollDriverProps) => {
  const lenis = useScroll((s) => s.lenis);
  const setProgress = useStory((s) => s.setProgress);
  const setSection = useStory((s) => s.setSection);

  useEffect(() => {
    // Each chapter panel is `h-dvh`, and `innerHeight` IS the dynamic viewport
    // height — the two stay in lock-step across mobile URL-bar show/hide. The
    // story's scrollable extent is `(sectionCount - 1)` viewport heights
    // (re-read per event: handles resize).
    const storyExtent = () => Math.max(1, (sectionCount - 1) * window.innerHeight);

    const apply = (scrollY: number) => {
      const clamped = Math.min(Math.max(scrollY / storyExtent(), 0), 1);
      setProgress(clamped);
      // Active chapter: split [0,1] into `sectionCount` equal bands.
      const section = Math.min(sectionCount - 1, Math.floor(clamped * sectionCount));
      setSection(section);
    };

    if (lenis) {
      // Lenis passes its own instance to the handler; reading `lenis.scroll`
      // (animated pixel offset) keeps this independent of the event-arg shape.
      const onScroll = () => apply(lenis.scroll ?? 0);
      lenis.on("scroll", onScroll);
      // Seed once with the current position (Lenis won't fire until the next move).
      onScroll();
      return () => lenis.off("scroll", onScroll);
    }

    // Fallback: native scroll until Lenis is ready.
    const onScroll = () => apply(window.scrollY);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [lenis, sectionCount, setProgress, setSection]);

  return null;
};
