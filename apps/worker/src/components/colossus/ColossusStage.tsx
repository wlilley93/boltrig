import { useEffect, useRef, useState } from "react";
import type { FamiliarPhenotypeResponse } from "@wlilley93/boltrig-web-sdk";

import { ColossusRenderer } from "./ColossusRenderer";
import type { ColossusStageState } from "./ColossusState";
import { TickerBed } from "./tickerBed";
import "./colossus.css";

/**
 * Colossus's mount point.
 *
 * Same contract as the other three -- it owns its renderer's lifecycle and
 * reports a fallback rather than showing a blank canvas -- and it takes the
 * phenotype prop it does not use, because the Stage hands it to every character
 * and dropping it here would mean a branch at the call site naming him by id.
 * The renderer ignores it; see ColossusRenderer.applyPhenotype.
 *
 * The aria-label carries the MODE WORD, which is the same word the sign itself
 * is scrolling. A ticker is the one body here whose content is literally text,
 * so a screen reader should get the text rather than a description of a glow.
 */
export function ColossusStage({
  state,
  suspended = false,
  highResolution = false,
  className,
}: {
  state: ColossusStageState;
  /** Present for parity with the other stages; deliberately unused. */
  phenotype?: FamiliarPhenotypeResponse | null;
  suspended?: boolean;
  highResolution?: boolean;
  className?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<ColossusRenderer | null>(null);
  const bedRef = useRef<TickerBed | null>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const renderer = new ColossusRenderer({
      maxDevicePixelRatio: highResolution ? 2 : 1.5,
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
    if (suspended) rendererRef.current?.suspend();
    else rendererRef.current?.resume();
  }, [suspended]);

  // The room tone, under his voice and only while he has one. Gated on the
  // mode rather than on the level, so a quiet passage in a sentence does not
  // switch the building off and on again.
  useEffect(() => {
    const bed = bedRef.current ?? (bedRef.current = new TickerBed());
    if (state.mode === "speaking" && !suspended) bed.start();
    else bed.stop();
  }, [state.mode, suspended]);

  useEffect(() => () => {
    bedRef.current?.destroy();
    bedRef.current = null;
  }, []);

  return (
    <div
      ref={hostRef}
      className={`colossus-stage${fallback ? " fallback" : ""}${className ? ` ${className}` : ""}`}
      role="img"
      aria-label={`World Control · ${state.mode}`}
      data-renderer={fallback ? "none" : "webgl2"}
      data-mode={state.mode}
    />
  );
}
