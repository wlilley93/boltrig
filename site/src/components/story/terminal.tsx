"use client";

import { animated, easings, useSpring } from "@react-spring/web";
import TextEngine from "spring-text-engine";

/** Terminal-ise a label → SCREAMING_SNAKE_CASE (e.g. "The Whole" → "THE_WHOLE"). */
export const term = (s: string) => s.toUpperCase().replace(/\s+/g, "_");

/**
 * A blinking block cursor (`_`) — spring-driven (rule #1), terminal-style. Pair it
 * with a `>` prompt to make a label read like a console command line.
 */
export const TerminalCursor = () => {
  const blink = useSpring({
    from: { o: 1 },
    to: { o: 0.1 },
    loop: { reverse: true },
    config: { duration: 600, easing: easings.easeInOutQuad },
  });
  return (
    <animated.span aria-hidden style={{ opacity: blink.o }} className="text-brain-sky/80">
      _
    </animated.span>
  );
};

export interface TerminalPanelProps {
  /** Becomes the panel's `NAME.LOG` window title. */
  name: string;
  /** The narrative line, rendered as prompted terminal output. */
  body: string;
  /** Optional key/value data rows. */
  readouts?: { label: string; value: string }[];
  className?: string;
}

/**
 * A slick dark "terminal window" that holds a chapter's copy — a framed dark
 * panel with a `NAME.LOG` titlebar + LIVE light, the body as a `>`-prompted line
 * (text-engine reveal), `▸ KEY … VALUE` data rows, and a trailing blinking cursor.
 * Replaces the plain subtitle so each section reads like console output.
 */
export const TerminalPanel = ({ name, body, readouts, className = "" }: TerminalPanelProps) => {
  const pulse = useSpring({
    from: { o: 0.3 },
    to: { o: 1 },
    loop: { reverse: true },
    config: { duration: 1400, easing: easings.easeInOutSine },
  });

  return (
    <div
      className={`overflow-hidden rounded-md border border-brain-sky/20 bg-brain-void/80 text-left shadow-[0_24px_60px_-30px_rgba(0,0,0,0.9)] backdrop-blur-md ${className}`}
    >
      <header className="flex items-center justify-between border-b border-brain-sky/12 px-4 py-2.5">
        <span className="flex items-center gap-2.5 text-[0.6rem] uppercase tracking-[0.24em] text-brain-sky/50">
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-brain-sky/25" />
            <span className="h-1.5 w-1.5 rounded-full bg-brain-sky/25" />
            <span className="h-1.5 w-1.5 rounded-full bg-brain-sky/40" />
          </span>
          {term(name)}.LOG
        </span>
        <span className="flex items-center gap-1.5 text-[0.56rem] uppercase tracking-[0.2em] text-brain-sky/45">
          <animated.span
            style={{ opacity: pulse.o }}
            className="h-1.5 w-1.5 rounded-full bg-brain-sky shadow-[0_0_8px_1px] shadow-brain-azure/60"
          />
          LIVE
        </span>
      </header>

      <div className="space-y-3 px-5 py-4">
        <p className="flex gap-2.5 text-sm leading-relaxed text-brain-sky/75 md:text-[0.95rem]">
          <span aria-hidden className="text-brain-sky/40">
            &gt;
          </span>
          <TextEngine
            tag="span"
            mode="always"
            wordIn={{ opacity: 1 }}
            wordOut={{ opacity: 0 }}
            wordStagger={16}
            wordConfig={{ duration: 600, easing: easings.easeOutQuart }}
          >
            {body}
          </TextEngine>
        </p>

        {readouts && readouts.length > 0 && (
          <dl className="space-y-1.5 border-t border-brain-sky/12 pt-3">
            {readouts.map((r) => (
              <div key={r.label} className="flex items-baseline justify-between gap-4 text-xs">
                <dt className="flex items-center gap-2 uppercase tracking-[0.2em] text-brain-sky/40">
                  <span aria-hidden className="text-brain-sky/30">
                    &#9656;
                  </span>
                  {term(r.label)}
                </dt>
                <dd className="tabular-nums uppercase tracking-[0.1em] text-brain-sky/90">{r.value}</dd>
              </div>
            ))}
          </dl>
        )}

        <p className="flex items-center gap-1 text-brain-sky/70">
          <span aria-hidden>&gt;</span>
          <TerminalCursor />
        </p>
      </div>
    </div>
  );
};
