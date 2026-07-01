"use client";

import { easings } from "@react-spring/web";
import TextEngine from "spring-text-engine";

import { type StorySectionData } from "@/data/story";
import { Inview } from "@/components/animation/springs/in-view";

import { TerminalCursor, term } from "./terminal";

const titleConfig = { duration: 950, easing: easings.easeOutCubic };
const bodyConfig = { duration: 720, easing: easings.easeOutQuart };

export interface StorySectionProps {
  data: StorySectionData;
  /** Default side when `data.align` is unset (the brain takes the other side). */
  side: "left" | "right";
}

/**
 * One narrative chapter framing the live brain. Copy sits to one side (or centred,
 * for the finale). Chrome is styled like a console terminal — a `>` command prompt
 * with a blinking `_` cursor, `SCREAMING_SNAKE` kickers, wide letter-spacing, a
 * `▸ KEY  VALUE` data row, and a `[ BRACKETED ]` CTA — in the scene's blue palette.
 * Title/body reveal in place with the text engine; the column fades up with
 * `<Inview>`. Pointer-transparent except the CTA.
 */
export const StorySection = ({ data, side }: StorySectionProps) => {
  const align = data.align ?? side;
  const centered = align === "center";
  const justify = centered ? "justify-center" : align === "left" ? "justify-start" : "justify-end";

  return (
    <section
      id={data.id}
      aria-label={data.title}
      className={`pointer-events-none relative flex h-screen w-full items-center px-8 md:px-16 lg:px-24 ${justify}`}
    >
      <Inview
        tag="article"
        mode="always"
        from={{ opacity: 0, y: 28 }}
        to={{ opacity: 1, y: 0 }}
        config={{ tension: 90, friction: 24 }}
        className={`relative w-full ${centered ? "max-w-3xl text-center" : "max-w-2xl"}`}
      >
        {/* Terminal prompt kicker */}
        <p
          className={`mb-6 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.42em] text-white/70 md:text-sm ${
            centered ? "justify-center" : ""
          }`}
        >
          <span aria-hidden className="text-brain-sky/45">
            &gt;
          </span>
          <TextEngine
            tag="span"
            mode="always"
            wordIn={{ opacity: 1 }}
            wordOut={{ opacity: 0 }}
            wordStagger={40}
            wordConfig={bodyConfig}
          >
            {term(data.eyebrow)}
          </TextEngine>
          <TerminalCursor />
        </p>

        {/* Title — clean headline, line-clipped reveal */}
        <TextEngine
          tag="h2"
          mode="always"
          overflow
          lineIn={{ y: "0%", opacity: 1 }}
          lineOut={{ y: "110%", opacity: 0 }}
          lineStagger={95}
          lineConfig={titleConfig}
          style={centered ? { justifyContent: "center" } : undefined}
          className={`text-[2rem] font-semibold leading-[1.16] tracking-tight text-white md:text-[2.9rem] lg:text-[3.4rem] ${
            centered ? "text-center" : ""
          }`}
        >
          {data.title}
        </TextEngine>

        {/* Body */}
        <TextEngine
          tag="p"
          mode="always"
          wordIn={{ y: 0, opacity: 1 }}
          wordOut={{ y: 16, opacity: 0 }}
          wordStagger={20}
          wordConfig={bodyConfig}
          delayIn={250}
          style={centered ? { justifyContent: "center" } : undefined}
          className={`mt-7 text-lg leading-relaxed text-white/90 md:text-xl ${
            centered ? "mx-auto max-w-xl text-center" : "max-w-lg"
          }`}
        >
          {data.body}
        </TextEngine>

        {/* Readouts — terminal key/value rows */}
        {data.readouts && data.readouts.length > 0 && (
          <dl
            className={`mt-9 flex flex-wrap gap-x-9 gap-y-3 border-t border-brain-sky/15 pt-6 ${
              centered ? "justify-center" : ""
            }`}
          >
            {data.readouts.map((r) => (
              <div key={r.label} className="flex items-center gap-2.5">
                <span aria-hidden className="text-brain-sky/35">
                  &#9656;
                </span>
                <dt className="text-[0.62rem] uppercase tracking-[0.24em] text-brain-sky/40">
                  {term(r.label)}
                </dt>
                <dd className="text-xs uppercase tabular-nums tracking-[0.12em] text-brain-sky/90">
                  {r.value}
                </dd>
              </div>
            ))}
          </dl>
        )}

        {/* CTA — bracketed terminal link to the governed console */}
        {data.cta && (
          <a
            href="https://app.boltrig.io"
            className="pointer-events-auto mt-10 inline-flex items-center gap-2.5 border border-brain-sky/50 bg-brain-sky/10 px-7 py-3.5 text-xs font-semibold uppercase tracking-[0.28em] text-brain-sky backdrop-blur-md transition-colors hover:border-brain-sky hover:bg-brain-sky/20 hover:text-white"
          >
            <span aria-hidden>&#9656;</span>
            <span>[ {term(data.cta.label)} ]</span>
          </a>
        )}
      </Inview>
    </section>
  );
};
