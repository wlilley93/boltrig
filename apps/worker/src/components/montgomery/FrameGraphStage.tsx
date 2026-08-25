import { useEffect, useRef } from "react";
import type {
  FamiliarPhenotypeResponse,
  CharacterPresentationMode,
  CharacterStageState,
} from "@wlilley93/boltrig-web-sdk";
import { FrameGraphRenderer, type FrameGraphConfig } from "./FrameGraphRenderer";
import type { Phenotype } from "./frameGraphDrive";
import "./frame-stage.css";

// The Stage a frame-graph character mounts.
//
// IT FORWARDS THE PHENOTYPE, and that single line is why this file exists
// beside ClipStage rather than being a prop on it. ClipStage takes a phenotype
// and drops it -- "the v1 renderer has no phenotype channel into the player
// page, accepted so the contract holds, and deliberately not forwarded". That
// omission is defensible for a clip-library character whose player picks its
// own clip from a name pool. It is not defensible here: this character's ONLY
// expressive act is choosing which clip plays next, so a phenotype that stops
// at the Stage boundary is a measured mood with nothing to move.
export function FrameGraphStage({
  config,
  mode,
  state,
  phenotype,
  reply,
  address,
  label,
}: {
  config: FrameGraphConfig;
  mode: CharacterPresentationMode;
  state: CharacterStageState;
  phenotype?: FamiliarPhenotypeResponse | null;
  /** The reply about to be spoken, when the host has one. */
  reply?: string | null;
  /** How the user addressed him. "Monty" is the one word that loosens him. */
  address?: string | null;
  label?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<FrameGraphRenderer | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const renderer = new FrameGraphRenderer(config);
    rendererRef.current = renderer;
    renderer.mount(host);
    return () => {
      renderer.destroy();
      rendererRef.current = null;
    };
    // Remount on a character change: a different graph is a different body,
    // not a prop update.
  }, [config.id, config.library, config.playerUrl]);

  // ONE EFFECT, NOT THREE. The drive decides emotion, position and register
  // together, so splitting the inputs across separate effects would run it
  // three times per turn on three partial views of the same moment and post
  // the first two answers before the third input had arrived.
  useEffect(() => {
    rendererRef.current?.update(state, asPhenotype(phenotype), reply, address);
  }, [state, phenotype, reply, address]);

  useEffect(() => { rendererRef.current?.setMode(mode); }, [mode]);

  return (
    <div
      ref={hostRef}
      className={`frame-stage ${mode}`}
      role="img"
      aria-label={`${label ?? config.library} · ${state.working ? "working" : "ready"}`}
      data-renderer="iframe"
      data-character={config.id}
    />
  );
}

/**
 * The appraisal engine's shape, narrowed to the three scalars he can act on.
 *
 * Narrowed rather than passed whole, so the drive cannot quietly grow a
 * dependency on a field that the engine may rename: what he reads is three
 * numbers, and that is visible here rather than buried in a mapping.
 */
function asPhenotype(response: FamiliarPhenotypeResponse | null | undefined): Phenotype | null {
  if (!response || typeof response !== "object") return null;
  const source = response as unknown as Record<string, unknown>;
  const read = (key: string): number | undefined =>
    typeof source[key] === "number" ? (source[key] as number) : undefined;
  return {
    irritation: read("irritation"),
    alertness: read("alertness"),
    certainty: read("certainty"),
  };
}
