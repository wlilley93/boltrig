import { useEffect, useRef, useState } from "react";
import type { FamiliarPhenotypeResponse, NormalizedTurn } from "@wlilley93/boltrig-web-sdk";

import { JarvisWebGLRenderer, type JarvisRendererOptions } from "./JarvisRenderer";
import type { JarvisStageState } from "./JarvisState";
import type { JarvisTelemetry } from "./JarvisTelemetry";
import { workFromTurn } from "./JarvisWork";
import { JarvisNeuralRenderer } from "./v2/JarvisNeuralRenderer";

/**
 * The renderer's whole lifecycle, so the stage component is just markup.
 *
 * Extracted when the skin switch pushed JarvisStage past the worker's function
 * floor, and it is the right seam regardless: everything here is imperative GL
 * bookkeeping -- construct, feed, suspend, tear down -- and none of it is about
 * what the stage looks like in the DOM.
 *
 * TWO RENDERERS, DELIBERATELY NOT UNIFIED BEHIND ONE INTERFACE. V1 has a dial,
 * telemetry tracks and a work board; V2 is a particle field with nowhere to put
 * a number and is not going to grow one. A shared interface would have to
 * declare applyWork and applyTelemetry, and V2 would implement them as empty
 * methods -- which reads as "supported, currently doing nothing" at every call
 * site. An instanceof test says the true thing instead.
 */
export interface JarvisRendererInputs {
  state: JarvisStageState;
  phenotype?: FamiliarPhenotypeResponse | null;
  turn?: Pick<NormalizedTurn, "tools" | "subagents" | "steps"> | null;
  telemetry: JarvisTelemetry;
  suspended: boolean;
  accent?: JarvisRendererOptions["accent"];
  scale?: number;
  labels: "shader" | "svg";
  highResolution: boolean;
  /** "ultron" selects the neural field; anything else is the instrument dial. */
  neural: boolean;
}

function buildRenderer(
  neural: boolean,
  opts: Pick<JarvisRendererInputs, "accent" | "scale" | "labels" | "highResolution">,
): JarvisWebGLRenderer | JarvisNeuralRenderer {
  if (!neural) {
    return new JarvisWebGLRenderer({
      accent: opts.accent,
      scale: opts.scale,
      labels: opts.labels === "svg" ? "none" : "shader",
      maxDevicePixelRatio: opts.highResolution ? 2 : 1.25,
    });
  }
  const renderer = new JarvisNeuralRenderer({
    maxDevicePixelRatio: opts.highResolution ? 2 : 1.5,
  });
  // The neural body's look is built ON its baked lattice film ("Jarvis Final
  // 1740" idles the film's gain around 1.5) — a body without the loop mounted
  // is deliberately near-empty. One loop serves every state; the per-mode
  // latticeSpeed tuning is what makes standby drift and thinking race.
  renderer.setLatticeVideo("/companion/jarvis-lattice.mp4");
  return renderer;
}

export function useJarvisRenderer(inputs: JarvisRendererInputs) {
  const {
    state, phenotype, turn, telemetry, suspended,
    accent, scale, labels, highResolution, neural,
  } = inputs;
  const hostRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<JarvisWebGLRenderer | JarvisNeuralRenderer | null>(null);
  const [fallback, setFallback] = useState(false);

  // accent/scale/skin are construction-time identity, not per-frame state:
  // changing any of them rebuilds the renderer rather than being smuggled in
  // through update(). The two bodies share no GL state at all.
  const accentKey = accent ? accent.join(",") : "";
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const renderer = buildRenderer(neural, { accent, scale, labels, highResolution });
    rendererRef.current = renderer;
    renderer.mount(host);
    setFallback(renderer.status().state === "failed");
    return () => {
      renderer.destroy();
      rendererRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accentKey, scale, labels, highResolution, neural]);

  useEffect(() => {
    rendererRef.current?.update(state);
  }, [state]);

  useEffect(() => {
    // V1 ONLY. The work board is a grid of lit cells on the dial's face; the
    // neural field has no face and no cells, and inventing a place to put them
    // would be decorating one body with another's furniture.
    const renderer = rendererRef.current;
    if (renderer instanceof JarvisWebGLRenderer) {
      renderer.applyWork(turn ? workFromTurn(turn) : null);
    }
  }, [turn]);

  const telemetryKey = JSON.stringify(telemetry);
  useEffect(() => {
    // V1 only, for the same reason: budget tracks are gauge geometry. What the
    // neural field DOES read is energy and the phenotype, and both reach it
    // through update() and applyPhenotype().
    const renderer = rendererRef.current;
    if (renderer instanceof JarvisWebGLRenderer) renderer.applyTelemetry(telemetry);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [telemetryKey]);

  useEffect(() => {
    // BOTH bodies read the phenotype. A skin that ignored the machine's mood
    // while the other displayed it would make the choice a change of subject
    // rather than a change of clothes.
    const fresh = phenotype?.fresh && phenotype.phenotype ? phenotype.phenotype : null;
    const renderer = rendererRef.current;
    if (renderer instanceof JarvisNeuralRenderer) {
      renderer.applyPhenotype(fresh as Record<string, unknown> | null);
    } else {
      renderer?.applyPhenotype(fresh);
    }
  }, [phenotype]);

  useEffect(() => {
    if (suspended) rendererRef.current?.suspend();
    else rendererRef.current?.resume();
  }, [suspended]);

  return { hostRef, fallback };
}
