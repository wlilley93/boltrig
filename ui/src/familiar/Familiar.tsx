/**
 * <Familiar> - one agent's body, at one size.
 *
 * Deliberately dumb: it owns a canvas, registers it with the shared renderer, and keeps a
 * smoothed phenotype in a ref. It does not fetch anything and it does not know what a run is.
 * Everything it needs arrives as props, which is what lets the same component serve a 24px
 * avatar in a message bubble and a 160px presence in a call without a second implementation.
 *
 * The phenotype lives in a REF, not in state. It changes every frame; putting it in state
 * would re-render the React tree at 60fps for a value only the GPU reads.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { deriveGenotype, type AgentIdentity, type Genotype } from "@/familiar/genotype";
import {
  approachPhenotype,
  phenotypeForRun,
  PHENOTYPE_REST,
  type Phenotype,
  type RunFacts,
} from "@/familiar/phenotype";
import { familiarRenderer, onFamiliarReady } from "@/familiar/renderer";

export interface FamiliarProps {
  agent: AgentIdentity;
  /** CSS pixels. The canvas is allocated at devicePixelRatio above this. */
  size?: number;
  run?: RunFacts;
  /** 0..1 live voice level, for calls */
  voice?: number;
  /** an explicit genotype, when the caller has already resolved one */
  genotype?: Genotype;
  title?: string;
}

export function Familiar({ agent, size = 32, run, voice = 0, genotype, title }: FamiliarProps): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const phenoRef = useRef<Phenotype>(PHENOTYPE_REST);
  const targetRef = useRef<Phenotype>(PHENOTYPE_REST);
  const voiceRef = useRef(voice);
  const lastRef = useRef(performance.now());

  // Derivation is pure and cheap, but it runs per frame's worth of renders otherwise. Keyed on
  // the three things it actually reads, so an unrelated prop change does not rebuild the body.
  const gene = useMemo(
    () => genotype ?? deriveGenotype(agent),
    [genotype, agent.id, agent.role, agent.familiar],
  );

  targetRef.current = useMemo(
    () => (run ? phenotypeForRun(run) : PHENOTYPE_REST),
    [run?.status, run?.elapsedS, run?.activity, run?.speaking, run?.blockedOnHuman],
  );
  voiceRef.current = voice;

  const dpr = typeof window === "undefined" ? 1 : Math.min(window.devicePixelRatio || 1, 2);
  const px = Math.round(size * dpr);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    return familiarRenderer.add({
      target: canvas,
      genotype: gene,
      size: px,
      voice: () => voiceRef.current,
      phenotype: () => {
        const now = performance.now();
        const dt = Math.min((now - lastRef.current) / 1000, 0.1);
        lastRef.current = now;
        // Smoothed here rather than at the caller so every surface eases identically. A
        // familiar that snapped in the sidebar and eased in the bubble would read as two
        // different beings.
        phenoRef.current = approachPhenotype(phenoRef.current, targetRef.current, dt);
        return phenoRef.current;
      },
    });
  }, [gene, px]);

  return (
    <canvas
      ref={canvasRef}
      className="familiar"
      width={px}
      height={px}
      style={{ width: size, height: size, display: "block" }}
      role={title ? "img" : "presentation"}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    />
  );
}

/** Whether a familiar can be drawn at all. Callers fall back to initials when false. */
export function familiarAvailable(): boolean {
  return familiarRenderer.available();
}

/**
 * The hook form, and the one components should use.
 *
 * The shader is fetched lazily (107KB of GLSL does not belong in the entry chunk), so
 * availability starts false and becomes true a moment later. A component that called
 * `familiarAvailable()` once during render would latch on that first false and show initials
 * forever - the feature would silently not exist, on every fast machine and every slow one,
 * and nothing would error.
 */
export function useFamiliarAvailable(): boolean {
  const [ready, setReady] = useState(() => familiarRenderer.available());
  useEffect(() => {
    if (ready) return;
    // Re-ask rather than trusting the event: `available()` is the single authority on whether
    // a program actually linked, and the notification only says the attempt has finished.
    return onFamiliarReady(() => setReady(familiarRenderer.available()));
  }, [ready]);
  return ready;
}
