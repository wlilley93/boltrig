import type { BudgetItem, FamiliarPhenotypeResponse, NormalizedTurn } from "@wlilley93/boltrig-web-sdk";
import { JarvisLabels } from "./JarvisLabels";
import type { JarvisRendererOptions } from "./JarvisRenderer";
import type { JarvisStageState } from "./JarvisState";
import { NO_TELEMETRY, telemetryFromBudgets } from "./JarvisTelemetry";
import { useJarvisRenderer } from "./useJarvisRenderer";
import "./jarvis.css";

// The HUD instrument stage. Same contract as FamiliarStage — it owns its
// renderer's lifecycle and reports a fallback rather than showing a blank
// canvas — but it is a separate mount point on purpose: the instrument and the
// creature are two answers to the same question and are never shown at once.
//
// Unlike the Familiar's, this stage is NOT square: the circuit field wants the
// whole viewport, so the host element should be sized by its container.
interface JarvisStageProps {
  state: JarvisStageState;
  /**
   * The server phenotype from GET /v1/familiar/phenotype. Absent or stale and
   * the dial rests at neutral and drops its signal ring — it will not invent a
   * mood to fill the gap.
   */
  phenotype?: FamiliarPhenotypeResponse | null;
  /**
   * Budgets from GET /v1/budgets. The dial shows the ceiling you are closest
   * to breaching. Absent, unlimited or not-yet-computed all render as a ghost
   * track — never as a gauge sitting at zero.
   */
  budgets?: readonly BudgetItem[] | null;
  /**
   * The turn being streamed. Its tools, subagents and workflow steps are the
   * agent's real DAG, and they are what energise the circuit board.
   */
  turn?: Pick<NormalizedTurn, "tools" | "subagents" | "steps"> | null;
  /** Mirrors the Familiar's "minimised" mode: stop drawing but keep the context. */
  suspended?: boolean;
  accent?: JarvisRendererOptions["accent"];
  scale?: number;
  /**
   * "svg" (default, decided 2026-08-11) lays real text over the canvas: better
   * letterforms, real kerning, accessible copy, and copy changes that never
   * touch GLSL. "shader" draws the words from the built-in glyph atlas instead.
   *
   * The atlas is NOT dead code — it is the only path with no DOM, so the
   * desktop GLES wallpaper host must pass "shader". Keep both working.
   */
  labels?: "shader" | "svg";
  highResolution?: boolean;
  className?: string;
  /**
   * Which body to draw. "ultron" is the neural field (components/jarvis/v2) --
   * Jarvis's own look in Age of Ultron, not Ultron's; anything else, including
   * absent, is the instrument dial.
   *
   * Construction-time identity, like accent and scale: changing it rebuilds the
   * renderer rather than being smuggled through update(), because the two
   * bodies share no GL state at all.
   */
  skin?: string;
}

export function JarvisStage({
  state,
  phenotype,
  budgets,
  turn,
  suspended = false,
  accent,
  scale,
  labels = "svg",
  highResolution = false,
  className,
  skin,
}: JarvisStageProps) {
  const neural = skin === "ultron";
  // Derived once and shared: the renderer draws the tracks from it and the
  // overlay decides which legends are honest to show.
  const telemetry = budgets ? telemetryFromBudgets(budgets) : NO_TELEMETRY;
  const { hostRef, fallback } = useJarvisRenderer({
    accent,
    highResolution,
    labels,
    neural,
    phenotype,
    scale,
    state,
    suspended,
    telemetry,
    turn,
  });

  return (
    <div
      ref={hostRef}
      className={`jarvis-stage${neural ? " neural" : ""}${fallback ? " fallback" : ""}${className ? ` ${className}` : ""}`}
      data-skin={neural ? "ultron" : "default"}
      role="img"
      aria-label={`Boltrig · ${state.mode}`}
      data-renderer={fallback ? "none" : "webgl2"}
      data-mode={state.mode}
    >
      {labels === "svg" && !fallback && !neural && (
        <JarvisLabels
          mode={state.mode}
          readout={state.readout}
          telemetry={telemetry}
        />
      )}
    </div>
  );
}
