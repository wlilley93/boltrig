/**
 * THE PHENOTYPE - how a familiar feels right now, layered live on top of the genotype.
 *
 * The genotype says what an agent IS and never changes. This says what it is DOING, and
 * changes every frame. Same body, different weather.
 *
 * WHERE THE NUMBERS COME FROM. Not from a per-agent emotion engine: boltrig does not have
 * one, and inventing a stored mood per agent would put a second source of truth beside the
 * run state that already exists. Every value below is DERIVED from run facts the console has
 * already fetched - the run's status, how long it has been in it, whether it is waiting on a
 * human, whether it failed. That is the binding shape ([2026] derive-don't-store): the record
 * is the truth and the mood is a projection of it, so a familiar cannot be calm while its run
 * is on fire.
 *
 * The test for whether a mood channel belongs here is blunt: can a user point at the screen
 * and say "why is it doing that", and can you answer with a fact? If the answer is "it just
 * does that sometimes", it is decoration and it does not go in.
 */

/** The nine channels the shader consumes. Names and 0..1 range match the desktop familiar's
 *  phenotype exactly, so the same body can be driven from either source. */
export interface Phenotype {
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

/** At rest: awake, unbothered, mildly attentive. What an idle agent looks like. */
export const PHENOTYPE_REST: Phenotype = {
  valence: 0.55,
  arousal: 0.30,
  irritation: 0.0,
  fatigue: 0.10,
  attention: 0.40,
  social: 0.30,
  buoyancy: 0.50,
  luminosity: 0.45,
  tension: 0.20,
};

/** The run facts this projection reads. All of them are already on the wire. */
export interface RunFacts {
  status: "idle" | "queued" | "running" | "awaiting_approval" | "failed" | "done" | "offline";
  /** seconds in the current status; drives fatigue and the tension of a long wait */
  elapsedS?: number;
  /** 0..1 recent output rate, if known. Absent is not zero - see below. */
  activity?: number;
  /** this agent is the one currently speaking in a call */
  speaking?: boolean;
  /** a human is being asked for something */
  blockedOnHuman?: boolean;
}

const clamp01 = (v: number): number => (v < 0 ? 0 : v > 1 ? 1 : v);

/**
 * Run facts in, mood out. Pure, so it can be tested without a GPU or a clock.
 *
 * One deliberate asymmetry: `activity` absent means "not measured", and is treated as the
 * status's own baseline rather than as zero. Absent-means-zero would make every agent whose
 * runtime does not report a rate look asleep while it worked, which is exactly the kind of
 * confidently wrong picture this whole design exists to avoid.
 */
export function phenotypeForRun(facts: RunFacts): Phenotype {
  const p: Phenotype = { ...PHENOTYPE_REST };
  const elapsed = facts.elapsedS ?? 0;
  const act = facts.activity;

  switch (facts.status) {
    case "running":
      // Working: bright, awake, moving. Activity drives arousal when it is measured.
      p.arousal = clamp01(act ?? 0.70);
      p.attention = 0.85;
      p.luminosity = 0.70;
      p.valence = 0.65;
      p.buoyancy = 0.62;
      // A long-running step reads as effort, not distress: fatigue climbs, irritation does
      // not. Ten minutes is the half-way point, which is slow enough that a normal step never
      // looks tired and a stuck one visibly does.
      p.fatigue = clamp01(0.10 + elapsed / 1200);
      p.tension = clamp01(0.20 + elapsed / 2400);
      break;

    case "queued":
      // Held, not working. Dim and still, so a queue reads as a queue at a glance.
      p.arousal = 0.15;
      p.attention = 0.25;
      p.luminosity = 0.30;
      p.buoyancy = 0.40;
      break;

    case "awaiting_approval":
      // Waiting on a person: the only state where nothing at all happens until the user acts.
      //
      // It is the BRIGHTEST body on the screen, and that is the extent of the claim.
      //
      // Measured on the preview page, mean luminance 37.4 against running's 33.8 - about 11%,
      // up from a first attempt's 4%, which was not a gap anybody would have noticed. An
      // intermediate version of this comment also claimed it was the STILLEST body, on the
      // theory that dropping arousal would calm the interior. Measured over 0.7s, frame-to-
      // frame change was 0.35 against running's 0.36: no effect at all. The silk's churn is
      // driven by the shader's own time term, not by arousal, so the claim was removed rather
      // than left standing. Brightness is the signal; stillness is not.
      //
      // What this is NOT is an alarm. The unambiguous, accessible statement of "this needs
      // you" is the status dot and the approvals queue; the familiar is the glanceable
      // companion to those, not a replacement for them. A body that shouted would be
      // unbearable in a list of twenty and would still be invisible to a screen reader.
      p.arousal = 0.12;
      p.attention = 1.0;
      p.tension = clamp01(0.45 + elapsed / 600);
      p.luminosity = 1.0;
      p.social = 0.90;
      p.buoyancy = 0.30;
      break;

    case "failed":
      // The one place irritation is used. It is the shader's single magenta exception, so it
      // is spent on the single state that genuinely needs to break the blue field.
      p.irritation = 0.85;
      p.valence = 0.12;
      p.arousal = 0.55;
      p.tension = 0.80;
      p.luminosity = 0.55;
      p.buoyancy = 0.15;
      break;

    case "done":
      // Finished well: settled, still lit, not asleep.
      p.valence = 0.85;
      p.arousal = 0.18;
      p.buoyancy = 0.70;
      p.luminosity = 0.50;
      p.attention = 0.25;
      p.tension = 0.05;
      break;

    case "offline":
      // Nearly out. Not black - an offline agent still has to be identifiable, or the fleet
      // bar develops holes and you cannot tell "gone" from "never existed".
      p.arousal = 0.04;
      p.luminosity = 0.12;
      p.attention = 0.0;
      p.social = 0.0;
      p.buoyancy = 0.10;
      p.fatigue = 0.85;
      break;

    case "idle":
    default:
      break;
  }

  if (facts.blockedOnHuman) {
    p.attention = 1.0;
    p.social = Math.max(p.social, 0.85);
  }
  if (facts.speaking) {
    // Speaking is additive on top of whatever it was doing, because an agent can be speaking
    // while running, while awaiting approval, or while reporting a failure - and it should
    // still look like the state it is in.
    p.social = 1.0;
    p.arousal = Math.max(p.arousal, 0.75);
    p.luminosity = Math.max(p.luminosity, 0.85);
  }

  return p;
}

/**
 * Move toward a target rather than snapping to it. A familiar that jumped between moods on
 * every poll would strobe, and strobing in a list of twenty avatars is genuinely unpleasant
 * to sit next to. `rate` is per second, so the smoothing is frame-rate independent - tie it
 * to the frame count instead and the animation changes speed on a slower machine, which is
 * how "it feels wrong on my laptop" bugs get made.
 */
export function approachPhenotype(cur: Phenotype, target: Phenotype, dt: number, rate = 3.0): Phenotype {
  const k = 1 - Math.exp(-rate * Math.max(dt, 0));
  const out = {} as Phenotype;
  for (const key of Object.keys(cur) as Array<keyof Phenotype>) {
    out[key] = cur[key] + (target[key] - cur[key]) * k;
  }
  return out;
}
