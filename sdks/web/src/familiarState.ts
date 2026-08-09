// FamiliarState v2 (ADR 0025): the versioned, content-free state contract every
// Familiar renderer consumes — WebGL today, Pixel-Streamed Unreal later. Bounded
// numbers, closed enums and timestamps ONLY. This contract must never carry
// conversation text, tool arguments, raw audio/video, identities, paths,
// credentials or inferred human emotion; and nothing derived from it may ever
// influence grants, HITL, routing or dispatch (emotion is downstream-only,
// decision 0013; expression is a granted verb, decision 0014).

export type FamiliarActivityMode =
  | "idle"
  | "listening"
  | "reasoning"
  | "tool"
  | "delegating"
  | "waiting_for_human"
  | "success"
  | "failure";

export type FamiliarGesture =
  | "none"
  | "look"
  | "pulse"
  | "flinch"
  | "celebrate"
  | "greet"
  | "nod"
  | "recoil"
  | "preen";

export type FamiliarPresentationModeV2 =
  | "hero"
  | "conversation"
  | "voice"
  | "minimised";

export type FamiliarGazeSource = "pointer" | "camera" | "none";

export interface FamiliarPhenotypeV2 {
  valence: number;
  arousal: number;
  irritation: number;
  fatigue: number;
  attention: number;
  social: number;
  buoyancy: number;
  luminosity: number;
  tension: number;
}

export type FamiliarVoiceBands = [
  number, number, number, number,
  number, number, number, number,
];

export interface FamiliarStateV2 {
  v: 2;
  /** Monotonic per-producer sequence; consumers reject stale/reordered states. */
  seq: number;
  timestampMs: number;
  identity: {
    genotypeSource?: "agent_capability.name.v1";
    palette?: [string, string, string];
  };
  phenotype: FamiliarPhenotypeV2;
  activity: {
    mode: FamiliarActivityMode;
    intensity: number;
    parallelWorkers: number;
    toolPulse: number;
  };
  expression: {
    gesture: FamiliarGesture;
    intensity: number;
    remainingMs: number;
  };
  voice: {
    active: boolean;
    level: number;
    bands: FamiliarVoiceBands;
    centroid: number;
    onset: number;
  };
  gaze: {
    valid: boolean;
    source: FamiliarGazeSource;
    x: number;
    y: number;
    distance: number;
    personPresent: boolean;
  };
  presentation: {
    mode: FamiliarPresentationModeV2;
    visibility: number;
    reducedMotion: boolean;
  };
}

const ACTIVITY_MODES: readonly FamiliarActivityMode[] = [
  "idle", "listening", "reasoning", "tool", "delegating",
  "waiting_for_human", "success", "failure",
];
const GESTURES: readonly FamiliarGesture[] = [
  "none", "look", "pulse", "flinch", "celebrate", "greet", "nod", "recoil", "preen",
];
const PRESENTATION_MODES: readonly FamiliarPresentationModeV2[] = [
  "hero", "conversation", "voice", "minimised",
];
const GAZE_SOURCES: readonly FamiliarGazeSource[] = ["pointer", "camera", "none"];

function num(value: unknown, fallback = 0, max = 1, min = 0): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

function count(value: unknown, max: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.min(max, Math.max(0, Math.floor(value)));
}

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return (allowed as readonly string[]).includes(value as string) ? value as T : fallback;
}

function bands(value: unknown): FamiliarVoiceBands {
  const out = [0, 0, 0, 0, 0, 0, 0, 0] as FamiliarVoiceBands;
  if (Array.isArray(value)) {
    for (let index = 0; index < 8; index += 1) out[index] = num(value[index]);
  }
  return out;
}

export const RESTING_FAMILIAR_STATE_V2: FamiliarStateV2 = Object.freeze({
  v: 2,
  seq: 0,
  timestampMs: 0,
  identity: {},
  phenotype: {
    valence: 0.5, arousal: 0.07, irritation: 0, fatigue: 0, attention: 0.6,
    social: 0.5, buoyancy: 0.5, luminosity: 0.5, tension: 0,
  },
  activity: { mode: "idle", intensity: 0, parallelWorkers: 0, toolPulse: 0 },
  expression: { gesture: "none", intensity: 0, remainingMs: 0 },
  voice: {
    active: false, level: 0,
    bands: [0, 0, 0, 0, 0, 0, 0, 0], centroid: 0, onset: 0,
  },
  gaze: { valid: false, source: "none", x: 0.5, y: 0.5, distance: 0.5, personPresent: false },
  presentation: { mode: "hero", visibility: 1, reducedMotion: false },
}) as FamiliarStateV2;

/**
 * Validates and bounds an untrusted candidate into a FamiliarStateV2. Every
 * field falls back INDEPENDENTLY (a malformed voice block must not cost the
 * phenotype), non-finite numbers are clamped away, and unknown enum values
 * land on the calm default. Returns null only when the envelope itself is
 * wrong (not v2 / no finite seq) or the sequence is stale.
 */
export function sanitizeFamiliarState(
  candidate: unknown,
  lastSeq?: number,
): FamiliarStateV2 | null {
  if (typeof candidate !== "object" || candidate === null) return null;
  const raw = candidate as Record<string, unknown>;
  if (raw.v !== 2) return null;
  if (typeof raw.seq !== "number" || !Number.isFinite(raw.seq)) return null;
  if (lastSeq !== undefined && raw.seq <= lastSeq) return null;

  const rest = RESTING_FAMILIAR_STATE_V2;
  const identity = (raw.identity ?? {}) as Record<string, unknown>;
  const phenotype = (raw.phenotype ?? {}) as Record<string, unknown>;
  const activity = (raw.activity ?? {}) as Record<string, unknown>;
  const expression = (raw.expression ?? {}) as Record<string, unknown>;
  const voice = (raw.voice ?? {}) as Record<string, unknown>;
  const gaze = (raw.gaze ?? {}) as Record<string, unknown>;
  const presentation = (raw.presentation ?? {}) as Record<string, unknown>;

  const palette = Array.isArray(identity.palette)
    && identity.palette.length === 3
    && identity.palette.every((entry) => typeof entry === "string" && /^#[0-9a-f]{6}$/i.test(entry))
    ? identity.palette as [string, string, string]
    : undefined;

  return {
    v: 2,
    seq: raw.seq,
    timestampMs: num(raw.timestampMs, 0, Number.MAX_SAFE_INTEGER),
    identity: {
      genotypeSource: identity.genotypeSource === "agent_capability.name.v1"
        ? "agent_capability.name.v1"
        : undefined,
      palette,
    },
    phenotype: {
      valence: num(phenotype.valence, rest.phenotype.valence),
      arousal: num(phenotype.arousal, rest.phenotype.arousal),
      irritation: num(phenotype.irritation, 0),
      fatigue: num(phenotype.fatigue, 0),
      attention: num(phenotype.attention, rest.phenotype.attention),
      social: num(phenotype.social, rest.phenotype.social),
      buoyancy: num(phenotype.buoyancy, rest.phenotype.buoyancy),
      luminosity: num(phenotype.luminosity, rest.phenotype.luminosity),
      tension: num(phenotype.tension, 0),
    },
    activity: {
      mode: pick(activity.mode, ACTIVITY_MODES, "idle"),
      intensity: num(activity.intensity),
      parallelWorkers: count(activity.parallelWorkers, 64),
      toolPulse: num(activity.toolPulse),
    },
    expression: {
      gesture: pick(expression.gesture, GESTURES, "none"),
      intensity: num(expression.intensity),
      remainingMs: num(expression.remainingMs, 0, 60_000),
    },
    voice: {
      active: voice.active === true,
      level: num(voice.level),
      bands: bands(voice.bands),
      centroid: num(voice.centroid),
      onset: num(voice.onset),
    },
    gaze: {
      valid: gaze.valid === true,
      source: pick(gaze.source, GAZE_SOURCES, "none"),
      x: num(gaze.x, 0.5),
      y: num(gaze.y, 0.5),
      distance: num(gaze.distance, 0.5),
      personPresent: gaze.personPresent === true,
    },
    presentation: {
      mode: pick(presentation.mode, PRESENTATION_MODES, "hero"),
      visibility: num(presentation.visibility, 1),
      reducedMotion: presentation.reducedMotion === true,
    },
  };
}
