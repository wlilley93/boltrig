import { useEffect, useRef, useState } from "react";
import type { FamiliarGenotype, FamiliarPhenotypeResponse } from "@wlilley93/boltrig-web-sdk";
import { FamiliarBadge, familiarPalette } from "./FamiliarBadge";
import { familiarVisualIdentity } from "./FamiliarGenotype";
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
  const [rendererKind, setRendererKind] = useState<"pending" | "webgl2" | "badge">("pending");

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let active = true;
    const renderer = new FamiliarWebGLRenderer({
      onFirstPaint: () => {
        if (active) setRendererKind("webgl2");
      },
    });
    renderer.setGenotype(genotype);
    rendererRef.current = renderer;
    renderer.mount(host);
    if (renderer.status().state === "failed") setRendererKind("badge");
    return () => {
      active = false;
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

  useEffect(() => {
    rendererRef.current?.setGenotype(genotype);
  }, [genotype]);

  const busy = state.working || state.speaking;
  const identity = familiarVisualIdentity(genotype);
  const accessibleName = familiarStageAccessibleName(label);
  return (
    <div
      ref={hostRef}
      className={`familiar-stage ${mode}${rendererKind === "badge" ? " fallback" : ""}`}
      role="img"
      aria-label={`${accessibleName} · ${busy ? "working" : "ready"}`}
      aria-busy={rendererKind === "pending" ? "true" : undefined}
      data-familiar-body={identity.body}
      data-genotype-source={identity.source}
      data-renderer={rendererKind}
      style={familiarPalette(identity.palette)}
    >
      {rendererKind === "badge" && (
        <FamiliarBadge
          decorative
          state={busy ? "working" : "ready"}
          genotype={genotype}
          label={label}
        />
      )}
    </div>
  );
}

function familiarStageAccessibleName(label?: string) {
  const trimmed = label?.trim();
  return trimmed?.toLocaleLowerCase() === "familiar"
    ? trimmed
    : `${trimmed || "Boltrig"} Familiar`;
}
