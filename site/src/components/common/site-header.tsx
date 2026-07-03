"use client";

import { animated, useSpring } from "@react-spring/web";

/**
 * Persistent site header: the Boltrig wordmark (left, scrolls to the top) and the
 * two standing calls to action (right): "Request access" (primary, the honest next
 * step for an invite-only product, opens a pre-addressed email) and "Open console"
 * (secondary, -> the governed console, for a returning user). Fixed over the scene
 * so branding and conversion are always in reach, not only at the finale. Springs
 * the whole bar in on first paint (rule #1). The telemetry status bar lives at the
 * foot of the viewport, so the top is the header's alone.
 */
export const SiteHeader = () => {
  const enter = useSpring({
    from: { opacity: 0, y: -14 },
    to: { opacity: 1, y: 0 },
    delay: 500,
    config: { tension: 120, friction: 26 },
  });

  return (
    <animated.header
      style={{ opacity: enter.opacity, y: enter.y }}
      className="pointer-events-none fixed inset-x-0 top-0 z-40 flex items-center justify-between px-5 py-4 md:px-8 md:py-5"
    >
      <a
        href="#arrival"
        aria-label="Boltrig home"
        className="pointer-events-auto inline-flex items-center gap-2.5 text-brain-sky transition-colors hover:text-white max-md:min-h-11"
      >
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden className="drop-shadow-[0_0_10px_rgba(61,211,240,0.5)]">
          <path d="M7.5 3.5H4.5V20.5H7.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
          <path d="M16.5 3.5H19.5V20.5H16.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
          <path d="M13.2 4.5L8.5 12.6H12L10.8 19.5L15.5 11.4H12L13.2 4.5Z" fill="currentColor" />
        </svg>
        <span className="text-base font-semibold tracking-tight text-white">boltrig</span>
      </a>

      <nav className="pointer-events-auto flex items-center gap-2 md:gap-3">
        <a
          href="https://app.boltrig.io"
          className="hidden items-center gap-2 border border-brain-sky/25 px-4 py-2 text-[0.62rem] font-semibold uppercase tracking-[0.24em] text-brain-sky/80 backdrop-blur-md transition-colors hover:border-brain-sky/60 hover:text-white max-md:min-h-11 sm:inline-flex md:px-5"
        >
          Open console
        </a>
        <a
          href="mailto:access@boltrig.io?subject=Boltrig%20access%20request"
          className="inline-flex items-center gap-2 border border-brain-sky/45 bg-brain-sky/10 px-4 py-2 text-[0.62rem] font-semibold uppercase tracking-[0.24em] text-brain-sky backdrop-blur-md transition-colors hover:border-brain-sky hover:bg-brain-sky/20 hover:text-white max-md:min-h-11 md:px-5"
        >
          <span aria-hidden className="hidden h-1.5 w-1.5 rounded-full bg-brain-sky shadow-[0_0_8px_1px] shadow-brain-azure/60 sm:inline-block" />
          Request access
        </a>
      </nav>
    </animated.header>
  );
};
