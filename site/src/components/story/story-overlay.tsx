"use client";

import { useEffect, useState } from "react";
import { animated, useSpring } from "@react-spring/web";

import { STORY_SECTIONS, TAKEOVER_INDEX } from "@/data/story";
import { useStory } from "@/components/brain/story/use-story";

import { StoryChrome } from "./story-chrome";
import { StoryScrollDriver } from "./story-scroll-driver";
import { StorySection } from "./story-section";
import { TakeoverPanel, TakeoverVisual } from "./takeover";

/** Beat between the loader handing off and the narrative content revealing — lets
 *  the brain reveal breathe alone for a moment before the copy arrives. */
const CONTENT_DELAY_MS = 500;

/**
 * True once the loader has handed off (`useStory.entered`) **and** a short beat
 * has passed, so the story copy/chrome reveal *after* the brain's fly-in begins
 * rather than behind the loader curtain.
 */
function useContentReady() {
  const entered = useStory((s) => s.entered);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!entered) return;
    const id = setTimeout(() => setReady(true), CONTENT_DELAY_MS);
    return () => clearTimeout(id);
  }, [entered]);
  return ready;
}

/**
 * The scroll narrative layered over the fixed brain canvas. Stacks one
 * full-height panel per chapter (which gives the page its scroll length): brain
 * chapters render a `StorySection` whose copy alternates sides so the brain
 * always stands opposite, while the takeover chapter renders its minimal centred
 * panel over the fixed signal-field visual. Also mounts the persistent chrome and
 * the scroll driver. The whole layer is `pointer-events-none` so drags/clicks
 * fall through to nothing (there is no orbit any more) — only future interactive
 * controls would opt back in.
 *
 * Content arrives a beat after the loader (see {@link useContentReady}). Crucially
 * the scroll stack stays **mounted from first paint** so (a) it always carries the
 * page's scroll length — if it mounted late, `StoryScrollDriver` would seed
 * `progress` from a zero-height document and the scene would snap to the finale —
 * and (b) all the heavy mounting (every `TextEngine`, the text measuring/splitting)
 * happens **behind the loader curtain**, not at reveal time. The reveal itself is
 * therefore a cheap opacity/translate fade with **no remount**, so it can't stall
 * the frame while the brain is flying in. (An earlier version keyed a remount here
 * for a "fresh" staggered reveal — that rebuild of the whole stack was the lag.)
 */
export const StoryOverlay = () => {
  const contentReady = useContentReady();
  const reveal = useSpring({
    opacity: contentReady ? 1 : 0,
    y: contentReady ? 0 : 14,
    config: { tension: 90, friction: 26 },
  });

  return (
    <>
      <StoryScrollDriver sectionCount={STORY_SECTIONS.length} />
      <TakeoverVisual activeIndex={TAKEOVER_INDEX} />
      {contentReady && <StoryChrome sections={STORY_SECTIONS} />}

      <animated.div
        style={{ opacity: reveal.opacity, y: reveal.y }}
        className="relative z-20"
      >
        {STORY_SECTIONS.map((data, i) =>
          data.kind === "takeover" ? (
            <TakeoverPanel key={data.id} data={data} />
          ) : (
            <StorySection key={data.id} data={data} side={i % 2 === 0 ? "left" : "right"} />
          ),
        )}
      </animated.div>
    </>
  );
};
