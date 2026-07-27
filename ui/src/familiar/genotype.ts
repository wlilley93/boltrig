/**
 * THE GENOTYPE - what an agent's familiar IS, as opposed to how it feels right now.
 *
 * Codex gives each agent one of eight fixed icons, drawn from a bag at random. In its own
 * screenshots "Third architecture", "Third accessibility" and "Trial classify" all get the
 * same blue pinwheel, while "Test secure" gets a globe and "Test audit" a four-loop mark.
 * Nothing about the picture tells you anything about the agent. It is decoration.
 *
 * This is the opposite: the familiar is DERIVED from the agent, so the picture is evidence.
 * Two rules make that true, and both matter.
 *
 *   1. AUTHORED BEATS DERIVED. An agent whose config carries a `familiar` block gets exactly
 *      that body. The derivation is the fallback for agents nobody has dressed, not a thing
 *      that overrides an author.
 *
 *   2. DERIVED IS A FUNCTION OF MEANING, NOT OF BYTES. The naive version hashes the agent id
 *      and indexes a table, which is Codex's bag of eight with more entries - still random,
 *      still telling you nothing. Instead the agent's ROLE picks the shape family (what kind
 *      of thing it is) and its identity varies only WITHIN that family (which one it is). So
 *      every reviewer looks like a reviewer at a glance, and no two reviewers look alike.
 *
 * The consequence worth stating plainly: you can learn to read the fleet. A bar of familiars
 * is legible as "three researchers, a reviewer and a builder" before you read a single label.
 * That is only true while rule 2 holds, so the role bands below are load-bearing and the test
 * beside this file pins them.
 */

/** The 14 authored genes, in the uniform's slot order. Names match genotype.h exactly. */
export interface Genotype {
  /** 0 circle, 1 cassini, 2 superformula, 3 blend of 1 and 2 */
  shape: number;
  /** crossfade for shape 3 */
  blend: number;
  /** cassini focal separation `a`: the gene that walks circle -> egg -> peanut -> figure-of-8 */
  focal: number;
  /** cassini `b`. a == b is the true lemniscate; a > b parts the lobes */
  cassiniB: number;
  /** bias one half of the figure larger, so a figure-of-8 can have a head and a tail */
  lobeBalance: number;
  /** superformula symmetry: 3 triangle, 5 star, 8 gear */
  superM: number;
  superN1: number;
  superN2: number;
  superN3: number;
  superA: number;
  superB: number;
  /** stretch across the long axis */
  aspect: number;
  /** turn the whole figure, radians */
  rotation: number;
  /** orientation that varies with radius, shearing lobes into a spiral */
  twist: number;
  /** identity tint, radians about the achromatic axis. Applied to the BODY palette only */
  hue: number;
  /** saturation delta on the tinted body. Small: a grey familiar stops reading as alive */
  saturation: number;

  /* Interior tuning. All MULTIPLIERS defaulting to 1.0, so an absent genotype reproduces the
   * body that shipped before they existed - verified byte-identical on the circle case. */
  /** the warm ember in the heart, against an otherwise cool body */
  warmth: number;
  /** how far the body swells on each breath */
  breathDepth: number;
  /** surface relief */
  bumpAmp: number;
  /** how violently the interior silk churns */
  silkChurn: number;
  /** specular tightness: low is a broad wet sheen, high is a pinpoint */
  specSharp: number;
  /** how far the halo reaches past the silhouette */
  haloReach: number;
}

/**
 * ABSENT IS A CIRCLE. Identical to GENOTYPE_DEFAULTS in the desktop familiar's genotype.h.
 * `shape: 0` makes the shader's distance function return plain `length()`, which is the body
 * it drew before the genotype existed - so a missing or partial genotype degrades to the
 * original familiar rather than to a black hole in the middle of the chat.
 */
export const GENOTYPE_DEFAULTS: Genotype = {
  shape: 0,
  blend: 0,
  focal: 0,
  cassiniB: 0.75,
  lobeBalance: 0,
  superM: 4,
  superN1: 1,
  superN2: 1,
  superN3: 1,
  superA: 1,
  superB: 1,
  aspect: 1,
  rotation: 0,
  twist: 0,
  hue: 0,
  saturation: 0,
  warmth: 1,
  breathDepth: 1,
  bumpAmp: 1,
  silkChurn: 1,
  specSharp: 1,
  haloReach: 1,
};

/** Slot order IS the uniform layout: index i lands in uGene[i/4][i%4]. Reordering re-labels
 *  every gene, so this list is not cosmetic. */
export const GENOTYPE_SLOTS: ReadonlyArray<keyof Genotype> = [
  "shape", "blend", "focal", "cassiniB",
  "lobeBalance", "superM", "superN1", "superN2",
  "superN3", "superA", "superB", "aspect",
  "rotation", "twist", "hue", "saturation",
  "warmth", "breathDepth", "bumpAmp", "silkChurn",
  "specSharp", "haloReach",
];

/** Pack a genotype into the 16 floats the shader's `uniform vec4 uGene[4]` expects. */
/** The uniform is `vec4 uGene[GENOTYPE_VEC4S]`; the renderer uploads that many vec4s. Derived
 *  from the slot list so growing the genotype cannot leave an upload writing a prefix. */
export const GENOTYPE_VEC4S = 6;

export function packGenotype(g: Genotype): Float32Array {
  const out = new Float32Array(GENOTYPE_VEC4S * 4);
  GENOTYPE_SLOTS.forEach((key, i) => {
    const v = g[key];
    out[i] = Number.isFinite(v) ? v : GENOTYPE_DEFAULTS[key];
  });
  return out;
}

/**
 * FNV-1a. Not for security - this only has to be stable and well-mixed, and it has to give
 * the SAME answer in the browser and on the server, so an agent's familiar does not change
 * shape depending on which side drew it. A cryptographic hash would be slower and would still
 * need pinning; what actually needs pinning is the ALGORITHM, which is why it is written out
 * here rather than pulled from a library that might get swapped.
 */
function hash32(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/** A deterministic 0..1 stream from one seed, so each gene draws independently. */
function stream(seed: string): () => number {
  let h = hash32(seed);
  return () => {
    // xorshift32 on the hash state: cheap, and stable across engines because every step is
    // masked back to 32 bits. `>>> 0` after each op is what keeps it from drifting into
    // doubles, which would make the browser and the server disagree in the low bits.
    h ^= (h << 13) >>> 0; h >>>= 0;
    h ^= h >>> 17;
    h ^= (h << 5) >>> 0; h >>>= 0;
    return h / 4294967296;
  };
}

const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/**
 * THE ROLE BANDS. Each role owns a region of genotype space, chosen so the families are
 * distinguishable at 24px - which is the real constraint, because that is the size in a
 * message bubble. Subtlety that only reads at 200px is decoration again.
 *
 * The mapping is deliberately iconic rather than arbitrary:
 *   orchestrator  a whole circle: the thing the others are parts of
 *   researcher    an egg, slightly parted: something opening
 *   reviewer      a lemniscate: two lobes weighing against each other
 *   builder       a gear
 *   guardian      a shield-ish triangle, point down
 *   analyst       a star: many radiating directions
 *
 * An unknown role falls to `default`, which is a plain circle. That is on purpose: a familiar
 * whose role boltrig does not recognise should look like the generic being, not like a role it
 * is not. Guessing would make the picture lie, and the whole point is that it does not.
 */
interface Band {
  shape: number;
  ranges: Partial<Record<keyof Genotype, [number, number]>>;
}

/**
 * THE MAGENTA WEDGE IS RESERVED, and no role may enter it.
 *
 * The shader spends magenta on exactly one thing: irritation, which the phenotype raises for
 * exactly one state, a failed run. That makes "magenta means failed" the most valuable signal
 * on the screen, because it is the only one that is learnable at a glance across a whole fleet.
 *
 * A per-agent hue threatens it directly. Rendered, hue 1.047 rad comes out frankly magenta - so
 * an agent that happened to be seeded there would sit at rest looking exactly like an agent
 * whose run had just died. Identity would be quietly destroying the alarm.
 *
 * So the wedge is off limits to the derivation, and `roleHuesAvoidMagenta` in the test beside
 * this file is what makes that true rather than merely written down. An author may still put a
 * familiar there deliberately; the derivation may never wander there by accident.
 */
export const MAGENTA_WEDGE: [number, number] = [0.70, 1.45];

export const ROLE_BANDS: Record<string, Band> = {
  orchestrator: { shape: 0, ranges: { aspect: [0.96, 1.04], rotation: [0, 0.3] , hue: [6.0, 6.25], saturation: [-0.05, 0.10]} },
  researcher: {
    shape: 1,
    ranges: { focal: [0.40, 0.62], cassiniB: [0.90, 1.00], lobeBalance: [0.10, 0.35], aspect: [0.95, 1.15] , hue: [2.45, 2.7], saturation: [-0.05, 0.10]},
  },
  reviewer: {
    // Held just BELOW the part (focal < cassiniB), and the reason changed on 2026-07-27.
    // It used to be that a parted body had no centre, so no nucleus, so almost no light -
    // 5.9% lit, invisible at 24px. That is fixed upstream: a parted body now measures depth
    // across each lobe's own thickness and renders at 12.9% lit, peak 239.
    // The band stays closed anyway, for a design reason rather than a rendering one: a parted
    // body reads as TWO beings, and one agent must be one body. Two blobs side by side in a
    // 24px avatar say "two agents" to every glance, which is the opposite of identification.
    // The geometry is reachable and presentable; it is reserved for something that is
    // genuinely plural.
    shape: 1,
    ranges: { focal: [0.74, 0.86], cassiniB: [0.86, 0.92], lobeBalance: [0.0, 0.25], twist: [0, 0.8] , hue: [3.3, 3.55], saturation: [-0.05, 0.10]},
  },
  builder: {
    shape: 2,
    ranges: { superM: [6, 8], superN1: [4.0, 7.0], superN2: [9, 13], superN3: [9, 13], aspect: [0.97, 1.03] , hue: [4.15, 4.4], saturation: [-0.05, 0.10]},
  },
  guardian: {
    // rotation ~0.52 (30 degrees) is what actually points the triangle DOWN, verified by
    // rendering it. A superformula shape with m=3 is 3-fold symmetric, so rotation is only
    // meaningful modulo 120 degrees - an earlier value of 3.14 looked like it did nothing,
    // because 180 and 60 degrees are the same triangle. The range is kept narrow so every
    // guardian reads as a shield rather than as an arbitrarily tipped triangle.
    shape: 2,
    ranges: { superM: [3, 3], superN1: [0.45, 0.62], superN2: [0.9, 1.1], superN3: [0.9, 1.1], rotation: [0.44, 0.60] , hue: [5.0, 5.25], saturation: [-0.05, 0.10]},
  },
  analyst: {
    shape: 2,
    ranges: { superM: [5, 7], superN1: [0.35, 0.50], superN2: [1.5, 1.9], superN3: [1.5, 1.9], rotation: [0, 1.2] , hue: [1.8, 2.05], saturation: [-0.05, 0.10]},
  },
  default: { shape: 0, ranges: { aspect: [0.94, 1.06], rotation: [0, 6.28] } },
};

/**
 * Normalise whatever the agent record calls its role onto a band key. Roles arrive from
 * several places (config, capability name, a free-text label a user typed), so this matches
 * on substrings rather than demanding an exact enum. Unmatched returns "default" rather than
 * a guess - see the note on ROLE_BANDS.
 */
export function bandForRole(role: string | null | undefined): string {
  const r = (role ?? "").toLowerCase();
  if (!r) return "default";
  if (/orchestrat|conductor|chief|lead|router/.test(r)) return "orchestrator";
  if (/research|explore|search|scout|discover/.test(r)) return "researcher";
  if (/review|critic|judge|verif|audit|qa\b/.test(r)) return "reviewer";
  if (/build|implement|engineer|code|write|author/.test(r)) return "builder";
  if (/guard|security|safety|compliance|approv|gate/.test(r)) return "guardian";
  if (/analy|report|measure|metric|eval|summar/.test(r)) return "analyst";
  return "default";
}

/** What the derivation needs to know about an agent. Deliberately tiny - anything more and
 *  the familiar would start depending on state that changes, and a genotype must not. */
export interface AgentIdentity {
  id: string;
  role?: string | null;
  /** An authored genotype from the agent's config. Wins outright when present. */
  familiar?: Partial<Genotype> | null;
}

/**
 * WHAT COUNTS AS AN IDENTITY. The single most dangerous mistake available here.
 *
 * A subagent arrives carrying a `childRunId`, and it is right there, and it is unique, and
 * using it would be a disaster: a run id is per RUN, so the same agent would come back with a
 * different body every single time it ran. The familiar would still render, still look
 * plausible, and would have silently stopped being evidence about anything - which is worse
 * than the bag of eight, because at least the bag never pretended.
 *
 * So identity is the agent's NAME, and a run id is never accepted as a substitute.
 *
 * When there is no name, this returns null and the caller derives from the role alone. That
 * yields the same body for every unnamed agent of a role, which looks like a limitation and is
 * actually the honest answer: we know what KIND of thing it is and we do not know WHICH one,
 * so the picture says exactly that and no more.
 */
export function stableAgentKey(candidate: {
  name?: string | null;
  id?: string | null;
  runId?: string | null;
}): string | null {
  const name = candidate.name?.trim();
  if (name) return name;
  const id = candidate.id?.trim();
  // A run id passed as `id` is still a run id. Callers that only have one must pass it as
  // `runId`, where it is ignored - the parameter exists to make that refusal explicit rather
  // than to accept it.
  if (id && id !== candidate.runId) return id;
  return null;
}

/**
 * The whole point, in one function: agent in, body out, same answer every time.
 *
 * Determinism is not a nicety here. The familiar is how you recognise an agent across the
 * fleet bar, a message bubble and a call, so if it varied per render it would be worse than
 * useless - it would actively mislead. Nothing in here reads a clock, a random source, or any
 * state that can change while the agent exists.
 */
export function deriveGenotype(agent: AgentIdentity): Genotype {
  const band = ROLE_BANDS[bandForRole(agent.role)] ?? ROLE_BANDS.default;
  const next = stream(`${agent.id}:${bandForRole(agent.role)}`);

  const g: Genotype = { ...GENOTYPE_DEFAULTS, shape: band.shape };
  // Iterate the SLOT order, not Object.keys(band.ranges): object key order is stable in
  // practice but is not something to hang determinism on, and the slot list is already the
  // canonical order everything else uses.
  for (const key of GENOTYPE_SLOTS) {
    const range = band.ranges[key];
    if (!range) continue;
    const [lo, hi] = range;
    // superM must land on an integer or the symmetry is not a symmetry - a gear with 6.4
    // teeth is a smear. Rounding here rather than in the shader keeps the value the config
    // shows equal to the value that renders.
    const raw = lerp(lo, hi, next());
    g[key] = key === "superM" ? Math.round(raw) : raw;
  }

  // AUTHORED BEATS DERIVED, applied last so it wins over every band choice above. Unknown
  // keys are dropped rather than passed through: the uniform has 14 named slots and writing
  // past them would silently corrupt a neighbouring gene.
  if (agent.familiar) {
    for (const key of GENOTYPE_SLOTS) {
      const v = agent.familiar[key];
      if (typeof v === "number" && Number.isFinite(v)) g[key] = v;
    }
  }
  return g;
}
