import { useState } from "react";
import { GAUGE_RADII, LABEL_CAP_H, R_OUTER, toSvg } from "./geometry";
import { JarvisLabel, labelsForMode, type JarvisMode } from "./JarvisState";
import type { GaugeReading } from "./JarvisTelemetry";

// The DOM alternative to the shader's glyph atlas: state labels as real text on
// an SVG arc, laid over the canvas.
//
// What this buys over the in-shader version: real font, real hinting, real
// kerning, selectable and screen-reader-visible text, and copy changes that do
// not touch GLSL. What it costs: the desktop GLES host has no DOM, so this path
// cannot follow the instrument to the wallpaper — and the arc radius now lives
// in two places (see geometry.ts).

const R = toSvg(R_OUTER);

// Both arcs run left-to-right so the type is upright on each. The top arc
// sweeps clockwise over 12 o'clock; the bottom sweeps the other way under 6.
// Radii differ because a textPath puts the BASELINE on the curve: the top label
// hangs its glyphs above the line, the bottom label needs the line pushed out to
// keep the same optical gap from the ring.
const TOP_R = R - toSvg(LABEL_CAP_H) * 0.35;
const BOTTOM_R = R + toSvg(LABEL_CAP_H) * 0.75;

const ARC_TOP = `M ${-TOP_R} 0 A ${TOP_R} ${TOP_R} 0 0 1 ${TOP_R} 0`;
const ARC_BOTTOM = `M ${-BOTTOM_R} 0 A ${BOTTOM_R} ${BOTTOM_R} 0 0 0 ${BOTTOM_R} 0`;

const WORDS: Record<number, string> = {
  [JarvisLabel.SPEAKING]: "SPEAKING",
  [JarvisLabel.LISTENING]: "LISTENING",
  [JarvisLabel.THINKING]: "THINKING",
  [JarvisLabel.WORKING]: "WORKING",
  [JarvisLabel.STANDBY]: "STANDBY",
  [JarvisLabel.YOUR_TURN]: "YOUR TURN",
};

function textFor(id: number, readout: number): string | null {
  if (id === JarvisLabel.NONE) return null;
  if (id === JarvisLabel.READOUT) {
    return Math.min(9.99, Math.max(0, readout)).toFixed(2);
  }
  return WORDS[id] ?? null;
}

/**
 * Gauge legends. Two arcs of identical shape are indistinguishable without
 * them: nothing about a ring says "money" rather than "tokens", so a person
 * cannot learn to read the instrument unaided — which defeats the whole point
 * of making the tracks real.
 *
 * They sit at 9 o'clock, clear of both label arcs (12 and 6) and of the
 * listening sweep's busiest quadrant, and they only appear when their gauge has
 * a reading: labelling a ghost track would announce a number that is not there.
 */
function GaugeLegends({ budget, tokens }: { budget: boolean; tokens: boolean }) {
  const items: [number, string][] = [];
  if (budget) items.push([toSvg(GAUGE_RADII.budget), "SPEND"]);
  if (tokens) items.push([toSvg(GAUGE_RADII.tokens), "TOKENS"]);
  if (!items.length) return null;

  return (
    <g className="jarvis-labels__legend" aria-hidden="true">
      {items.map(([r, text]) => (
        <text key={text} x={-r} y={0} dy="-1.1" textAnchor="middle">
          {text}
        </text>
      ))}
    </g>
  );
}

const money = (micros: number) =>
  new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" })
    .format(micros / 1_000_000);

const tokens = (n: number) =>
  new Intl.NumberFormat(undefined, { notation: "compact" }).format(n);

/** The sentence a track says when you ask it. */
export function readingText(
  label: string, reading: GaugeReading, metric: "cost" | "tokens",
): string {
  if (!reading.known) return `${label}: no reading`;
  const fmt = metric === "cost" ? money : tokens;
  const pct = Math.round(reading.fill * 100);
  const window = reading.window ? ` ${reading.window}` : "";
  const stop = reading.hard ? ", hard stop" : "";
  return `${label}: ${fmt(reading.spent)} of ${fmt(reading.limit)}${window} (${pct}%)${stop}`;
}

/**
 * Pointer interrogation. The hit targets are the gauge tracks themselves — a
 * transparent stroked circle with `pointer-events: stroke`, so only the ring is
 * live and the dial underneath stays inert.
 *
 * These are deliberately NOT the accessible controls. `role="button"` on an SVG
 * <circle> does not reliably reach the accessibility tree, so relying on it
 * would have meant keyboard and screen-reader users silently getting nothing
 * while the markup looked correct. The real controls are HTML buttons in
 * GaugeReadouts; this layer only serves the mouse.
 */
function GaugeProbes({
  budget, tokensReading, onAsk,
}: {
  budget: GaugeReading;
  tokensReading: GaugeReading;
  onAsk(text: string | null): void;
}) {
  const tracks: [number, string, GaugeReading, "cost" | "tokens"][] = [
    [toSvg(GAUGE_RADII.budget), "Spend", budget, "cost"],
    [toSvg(GAUGE_RADII.tokens), "Tokens", tokensReading, "tokens"],
  ];
  return (
    <g className="jarvis-labels__probes">
      {tracks.map(([r, label, reading, metric]) => {
        const text = readingText(label, reading, metric);
        return (
          <circle
            key={label}
            aria-hidden="true"
            cx={0}
            cy={0}
            onPointerEnter={() => onAsk(text)}
            onPointerLeave={() => onAsk(null)}
            r={r}
          />
        );
      })}
    </g>
  );
}

/**
 * The accessible half of interrogation: one real button per track, visually
 * hidden but focusable, each carrying its own reading. A sighted mouse user
 * gets the SVG probe; everyone else gets these.
 */
function GaugeReadouts({
  budget, tokensReading, onAsk,
}: {
  budget: GaugeReading;
  tokensReading: GaugeReading;
  onAsk(text: string | null): void;
}) {
  const tracks: [string, GaugeReading, "cost" | "tokens"][] = [
    ["Spend", budget, "cost"],
    ["Tokens", tokensReading, "tokens"],
  ];
  return (
    <ul className="jarvis-readouts">
      {tracks.map(([label, reading, metric]) => {
        const text = readingText(label, reading, metric);
        return (
          <li key={label}>
            <button
              onBlur={() => onAsk(null)}
              onFocus={() => onAsk(text)}
              type="button"
            >
              {text}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function JarvisLabels({
  mode,
  readout = 0,
  telemetry,
  idPrefix = "jarvis",
}: {
  mode: JarvisMode;
  readout?: number;
  /** The gauge readings — drives both the legends and what a probe answers. */
  telemetry?: { budget: GaugeReading; tokens: GaugeReading };
  /** Disambiguates the path ids when more than one instrument is mounted. */
  idPrefix?: string;
}) {
  const [asked, setAsked] = useState<string | null>(null);
  const { top, bottom, topAmt, bottomAmt } = labelsForMode(mode);
  const topText = textFor(top, readout);
  const bottomText = textFor(bottom, readout);
  const topId = `${idPrefix}-arc-top`;
  const bottomId = `${idPrefix}-arc-bottom`;

  return (
    <>
    <svg
      className="jarvis-labels"
      viewBox="-50 -50 100 100"
      preserveAspectRatio="xMidYMid meet"
      role="group"
      aria-label="Instrument readings"
    >
      <defs>
        <path id={topId} d={ARC_TOP} fill="none" />
        <path id={bottomId} d={ARC_BOTTOM} fill="none" />
      </defs>
      {topText && (
        <text aria-hidden="true" className="jarvis-labels__top" style={{ opacity: topAmt }}>
          <textPath href={`#${topId}`} startOffset="50%" textAnchor="middle">
            {topText}
          </textPath>
        </text>
      )}
      <GaugeLegends
        budget={telemetry?.budget.known ?? false}
        tokens={telemetry?.tokens.known ?? false}
      />
      {telemetry && (
        <GaugeProbes
          budget={telemetry.budget}
          onAsk={setAsked}
          tokensReading={telemetry.tokens}
        />
      )}
      {asked && (
        <text className="jarvis-labels__asked" x={0} y={0} dy="14" textAnchor="middle">
          {asked}
        </text>
      )}
      {bottomText && (
        <text aria-hidden="true" className="jarvis-labels__bottom" style={{ opacity: bottomAmt }}>
          <textPath href={`#${bottomId}`} startOffset="50%" textAnchor="middle">
            {bottomText}
          </textPath>
        </text>
      )}
    </svg>
    {telemetry && (
      <GaugeReadouts
        budget={telemetry.budget}
        onAsk={setAsked}
        tokensReading={telemetry.tokens}
      />
    )}
    </>
  );
}
