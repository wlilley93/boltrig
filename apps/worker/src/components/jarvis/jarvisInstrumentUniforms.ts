// The instrument's state uniforms — spin, parallax, phenotype, telemetry,
// the work board and the face labels — pushed in one place. Lifted out of
// the V1 renderer's frame, which is an over-budget function on borrowed
// time; this block is pure pushes with no GL control flow of its own.

import { labelsForMode, type JarvisMode } from "./JarvisState";
import { type JarvisTelemetry } from "./JarvisTelemetry";

export interface UniformSetters {
  f(name: string, value: number): void;
  i1(name: string, value: number): void;
  set2(name: string, x: number, y: number): void;
}

export interface InstrumentState {
  spin: number;
  spinDelta: number;
  parallax: { x: number; y: number };
  phenoFresh: number;
  pheno: Record<string, number>;
  telemetry: JarvisTelemetry;
  workLoad: number;
  workFail: number;
  mode: JarvisMode;
  shaderLabels: boolean;
}

export function pushInstrumentState(set: UniformSetters, state: InstrumentState): void {
  set.f("uSpin", state.spin);
  set.f("uSpinDelta", state.spinDelta);
  set.set2("uParallax", state.parallax.x, state.parallax.y);
  set.f("uPhenoFresh", state.phenoFresh);
  set.f("uValence", state.pheno.valence);
  set.f("uArousal", state.pheno.arousal);
  set.f("uIrritation", state.pheno.irritation);
  set.f("uFatigue", state.pheno.fatigue);
  set.f("uAttention", state.pheno.attention);
  set.f("uLuminosity", state.pheno.luminosity);
  set.f("uTension", state.pheno.tension);

  const { budget, tokens } = state.telemetry;
  set.f("uBudgetFill", budget.fill);
  set.f("uBudgetKnown", budget.known ? 1 : 0);
  set.f("uBudgetHard", budget.hard ? 1 : 0);
  set.f("uTokenFill", tokens.fill);
  set.f("uTokenKnown", tokens.known ? 1 : 0);

  set.f("uWorkLoad", state.workLoad);
  set.f("uWorkFail", state.workFail);

  const labels = labelsForMode(state.mode);
  const labelGain = state.shaderLabels ? 1 : 0;
  set.i1("uLabelTop", labels.top);
  set.i1("uLabelBottom", labels.bottom);
  set.f("uLabelTopAmt", labels.topAmt * labelGain);
  set.f("uLabelBottomAmt", labels.bottomAmt * labelGain);
}
