import { useEffect, useRef, useState } from "react";
import type { FamiliarGenotype, FamiliarPhenotypeResponse } from "@wlilley93/boltrig-web-sdk";
import { FamiliarBadge } from "./FamiliarBadge";
import { FamiliarWebGLRenderer } from "./FamiliarWebGLRenderer";
import type { FamiliarPresentationMode, FamiliarStageState } from "./FamiliarState";
import "./familiar.css";

// The one premium visual body (ADR 0025). Mount at most one Stage per Worker
// client — badges stay cheap CSS. The Stage owns its renderer's lifecycle and
// falls back to the badge the moment the renderer cannot run, so there is
// never a blank stage.
export function FamiliarStage({
  mode,
  state,
  phenotype,
  genotype,
  label,
}: {
  mode: FamiliarPresentationMode;
  state: FamiliarStageState;
  phenotype?: FamiliarPhenotypeResponse | null;
  genotype?: FamiliarGenotype | null;
  label?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<FamiliarWebGLRenderer | null>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const renderer = new FamiliarWebGLRenderer();
    rendererRef.current = renderer;
    renderer.mount(host);
    if (renderer.status().state === "failed") setFallback(true);
    return () => {
      renderer.destroy();
      rendererRef.current = null;
    };
  }, []);

  useEffect(() => {
    rendererRef.current?.update(state);
  }, [state]);

  useEffect(() => {
    rendererRef.current?.setMode(mode);
  }, [mode]);

  useEffect(() => {
    rendererRef.current?.applyPhenotype(
      phenotype?.fresh && phenotype.phenotype ? phenotype.phenotype : null,
    );
  }, [phenotype]);

  const busy = state.working || state.speaking;
  return (
    <div
      ref={hostRef}
      className={`familiar-stage ${mode}${fallback ? " fallback" : ""}`}
      role="img"
      aria-label={`Boltrig Familiar · ${busy ? "working" : "ready"}`}
      data-renderer={fallback ? "badge" : "webgl2"}
    >
      {fallback && (
        <FamiliarBadge
          state={busy ? "working" : "ready"}
          genotype={genotype}
          label={label}
        />
      )}
    </div>
  );
}
