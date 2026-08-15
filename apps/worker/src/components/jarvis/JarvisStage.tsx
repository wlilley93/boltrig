import { useEffect, useRef, useState } from "react";
import type { BudgetItem, FamiliarPhenotypeResponse, NormalizedTurn } from "@wlilley93/boltrig-web-sdk";
import { JarvisLabels } from "./JarvisLabels";
import { JarvisWebGLRenderer, type JarvisRendererOptions } from "./JarvisRenderer";
import type { JarvisStageState } from "./JarvisState";
import { NO_TELEMETRY, telemetryFromBudgets } from "./JarvisTelemetry";
import { workFromTurn } from "./JarvisWork";
import "./jarvis.css";

// The HUD instrument stage. Same contract as FamiliarStage — it owns its
// renderer's lifecycle and reports a fallback rather than showing a blank
// canvas — but it is a separate mount point on purpose: the instrument and the
// creature are two answers to the same question and are never shown at once.
//
// Unlike the Familiar's, this stage is NOT square: the circuit field wants the
// whole viewport, so the host element should be sized by its container.
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
}: {
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
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<JarvisWebGLRenderer | null>(null);
  const [fallback, setFallback] = useState(false);
  // accent/scale are construction-time identity, not per-frame state: changing
  // them rebuilds the renderer rather than being smuggled in through update().
  const accentKey = accent ? accent.join(",") : "";
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const renderer = new JarvisWebGLRenderer({
      accent,
      scale,
      labels: labels === "svg" ? "none" : "shader",
      maxDevicePixelRatio: highResolution ? 2 : 1.25,
    });
    rendererRef.current = renderer;
    renderer.mount(host);
    setFallback(renderer.status().state === "failed");
    return () => {
      renderer.destroy();
      rendererRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accentKey, scale, labels, highResolution]);
  useEffect(() => {
    rendererRef.current?.update(state);
  }, [state]);
  useEffect(() => {
    rendererRef.current?.applyWork(turn ? workFromTurn(turn) : null);
  }, [turn]);

  // Derived once and shared: the renderer draws the tracks from it and the
  // overlay decides which legends are honest to show.
  const telemetry = budgets ? telemetryFromBudgets(budgets) : NO_TELEMETRY;
  const telemetryKey = JSON.stringify(telemetry);
  useEffect(() => {
    rendererRef.current?.applyTelemetry(telemetry);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [telemetryKey]);

  useEffect(() => {
    rendererRef.current?.applyPhenotype(
      phenotype?.fresh && phenotype.phenotype ? phenotype.phenotype : null,
    );
  }, [phenotype]);

  useEffect(() => {
    if (suspended) rendererRef.current?.suspend();
    else rendererRef.current?.resume();
  }, [suspended]);

  return (
    <div
      ref={hostRef}
      className={`jarvis-stage${fallback ? " fallback" : ""}${className ? ` ${className}` : ""}`}
      role="img"
      aria-label={`Boltrig · ${state.mode}`}
      data-renderer={fallback ? "none" : "webgl2"}
      data-mode={state.mode}
    >
      {labels === "svg" && !fallback && (
        <JarvisLabels
          mode={state.mode}
          readout={state.readout}
          telemetry={telemetry}
        />
      )}
    </div>
  );
}
