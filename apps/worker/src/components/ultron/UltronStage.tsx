import { useEffect, useRef, useState } from "react";
import type { FamiliarPhenotypeResponse } from "@wlilley93/boltrig-web-sdk";

import { UltronRenderer } from "./UltronRenderer";
import type { UltronStageState } from "./UltronState";
import "./ultron.css";

/**
 * Ultron's mount point.
 *
 * Same contract as the other two stages -- it owns its renderer's lifecycle and
 * reports a fallback rather than showing a blank canvas -- and deliberately
 * thinner than JarvisStage, because there is nothing to overlay. Jarvis has a
 * dial with legends and budget tracks; Ultron has a membrane, and laying text
 * over it would be putting an instrument's furniture on a creature.
 */
export function UltronStage({
  state,
  phenotype,
  suspended = false,
  highResolution = false,
  className,
}: {
  state: UltronStageState;
  /**
   * The server phenotype. He reads it, but it lands on how fast he comes apart
   * rather than on colour -- see UltronRenderer.drive.
   */
  phenotype?: FamiliarPhenotypeResponse | null;
  suspended?: boolean;
  highResolution?: boolean;
  className?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<UltronRenderer | null>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const renderer = new UltronRenderer({
      maxDevicePixelRatio: highResolution ? 2 : 1.5,
    });
    // "Ultron final 1800" is built ON the membrane films (lattice idles at
    // 2.2) — unlike Jarvis he keeps one loop PER STATE, and the deck
    // crossfades between them on a change of mode.
    renderer.setLatticeVideo({
      standby: "/companion/ultron-membrane.mp4",
      listening: "/companion/ultron-membrane-listening.mp4",
      thinking: "/companion/ultron-membrane-thinking.mp4",
      working: "/companion/ultron-membrane-working.mp4",
      speaking: "/companion/ultron-membrane-speaking.mp4",
    });
    rendererRef.current = renderer;
    renderer.mount(host);
    setFallback(renderer.status().state === "failed");
    return () => {
      renderer.destroy();
      rendererRef.current = null;
    };
  }, [highResolution]);

  useEffect(() => {
    rendererRef.current?.update(state);
  }, [state]);

  useEffect(() => {
    rendererRef.current?.applyPhenotype(
      phenotype?.fresh && phenotype.phenotype
        ? (phenotype.phenotype as unknown as Record<string, unknown>)
        : null,
    );
  }, [phenotype]);

  useEffect(() => {
    if (suspended) rendererRef.current?.suspend();
    else rendererRef.current?.resume();
  }, [suspended]);

  return (
    <div
      ref={hostRef}
      className={`ultron-stage${fallback ? " fallback" : ""}${className ? ` ${className}` : ""}`}
      role="img"
      aria-label={`Boltrig · ${state.mode}`}
      data-renderer={fallback ? "none" : "webgl2"}
      data-mode={state.mode}
    />
  );
}
