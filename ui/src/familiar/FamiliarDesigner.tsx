/**
 * THE FAMILIAR DESIGNER - the character-creation half of making an agent.
 *
 * Three ways to get a body, in the order most people will actually use them:
 *
 *   1. DERIVE. Do nothing. The role picks a family, the id picks the individual, and the
 *      agent already looks like itself. This is the default and most agents will never leave
 *      it - which is the point, because a designer nobody has to open is the sign the
 *      derivation is good.
 *   2. ROLL. Press the button until you like one. Rolling stays INSIDE the role's band, so a
 *      reviewer that has been rolled forty times is still visibly a reviewer. A roll that
 *      could land anywhere would break the one property that makes the fleet legible.
 *   3. AUTHOR. Open the genes and move them. Every slider is a real number in the shader, and
 *      the preview beside it is the same shader the chat renders - not an approximation of it,
 *      the actual one, so what you approve is what ships.
 *
 * The preview is deliberately large and the avatar chips beside it are deliberately small.
 * A body that reads beautifully at 200px and turns to mush at 24px is a body that fails at
 * the size it will actually be seen, and the only honest way to know is to show both at once.
 */

import { useCallback, useMemo, useState } from "react";

import { Familiar } from "@/familiar/Familiar";
import {
  bandForRole,
  deriveGenotype,
  GENOTYPE_DEFAULTS,
  ROLE_BANDS,
  type Genotype,
} from "@/familiar/genotype";
import { PHENOTYPE_REST, type RunFacts } from "@/familiar/phenotype";

/** Slider bounds. Wider than the role bands on purpose: the bands are what the derivation
 *  chooses, and an author is allowed to leave them. The bounds here are the limits of what
 *  the shader renders sensibly, not the limits of taste. */
const GENE_UI: Array<{
  key: keyof Genotype;
  label: string;
  min: number;
  max: number;
  step: number;
  hint: string;
  /** only meaningful for these shape modes; hidden otherwise so the panel is not a wall */
  shapes?: number[];
}> = [
  { key: "shape", label: "Family", min: 0, max: 3, step: 1, hint: "0 round, 1 lobed, 2 radial, 3 blend" },
  { key: "focal", label: "Separation", min: 0, max: 1.2, step: 0.01, hint: "walks round to egg to peanut to figure-of-8", shapes: [1, 3] },
  { key: "cassiniB", label: "Girth", min: 0.3, max: 1.3, step: 0.01, hint: "past Separation the body parts and loses its core", shapes: [1, 3] },
  { key: "lobeBalance", label: "Balance", min: -1, max: 1, step: 0.01, hint: "one lobe bigger: a head and a tail", shapes: [1, 3] },
  { key: "superM", label: "Points", min: 2, max: 12, step: 1, hint: "3 shield, 5 star, 8 gear", shapes: [2, 3] },
  { key: "superN1", label: "Sharpness", min: 0.2, max: 8, step: 0.05, hint: "low is spiky, high is blunt", shapes: [2, 3] },
  { key: "superN2", label: "Fill A", min: 0.2, max: 14, step: 0.1, hint: "", shapes: [2, 3] },
  { key: "superN3", label: "Fill B", min: 0.2, max: 14, step: 0.1, hint: "", shapes: [2, 3] },
  { key: "blend", label: "Blend", min: 0, max: 1, step: 0.01, hint: "crossfade lobed into radial", shapes: [3] },
  { key: "aspect", label: "Stretch", min: 0.5, max: 2, step: 0.01, hint: "" },
  { key: "rotation", label: "Turn", min: 0, max: 6.283, step: 0.01, hint: "" },
  { key: "twist", label: "Twist", min: -4, max: 4, step: 0.05, hint: "shears lobes into a spiral" },
];

/** Moods to preview against. A body is only finished when it still reads in all of them -
 *  most obviously `failed`, which floods the palette magenta and can swallow fine detail. */
const MOODS: Array<{ label: string; run: RunFacts }> = [
  { label: "Idle", run: { status: "idle" } },
  { label: "Running", run: { status: "running", elapsedS: 20 } },
  { label: "Waiting on you", run: { status: "awaiting_approval", elapsedS: 60 } },
  { label: "Failed", run: { status: "failed" } },
  { label: "Done", run: { status: "done" } },
];

export interface FamiliarDesignerProps {
  agentId: string;
  role: string;
  /** null means "derived" - the agent has no authored body */
  value: Partial<Genotype> | null;
  onChange: (next: Partial<Genotype> | null) => void;
}

export function FamiliarDesigner({ agentId, role, value, onChange }: FamiliarDesignerProps): JSX.Element {
  const [mood, setMood] = useState(0);
  const [open, setOpen] = useState(false);

  const band = bandForRole(role);
  const derived = useMemo(() => deriveGenotype({ id: agentId, role }), [agentId, role]);
  const gene: Genotype = useMemo(
    () => (value ? { ...derived, ...value } : derived),
    [derived, value],
  );

  const set = useCallback(
    (key: keyof Genotype, v: number) => onChange({ ...(value ?? gene), [key]: v }),
    [onChange, value, gene],
  );

  /**
   * Roll a new body INSIDE the role's band. Uses Math.random deliberately - this is a user
   * pressing a button, not the derivation, so it must NOT be deterministic. (The derivation
   * next door must never use it, which is why the two live in different files.)
   */
  const roll = useCallback(() => {
    const b = ROLE_BANDS[band] ?? ROLE_BANDS.default;
    const next: Partial<Genotype> = { shape: b.shape };
    for (const [key, range] of Object.entries(b.ranges) as Array<[keyof Genotype, [number, number]]>) {
      const raw = range[0] + (range[1] - range[0]) * Math.random();
      next[key] = key === "superM" ? Math.round(raw) : raw;
    }
    onChange(next);
  }, [band, onChange]);

  const visible = GENE_UI.filter((g) => !g.shapes || g.shapes.includes(Math.round(gene.shape)));

  return (
    <section className="familiar-designer">
      <header className="familiar-designer__head">
        <h3>Familiar</h3>
        <p className="familiar-designer__sub">
          {value ? "Authored for this agent." : `Derived from the ${band} role. Every ${band} shares this family.`}
        </p>
      </header>

      <div className="familiar-designer__stage">
        <Familiar
          agent={{ id: agentId, role, familiar: value }}
          size={196}
          run={MOODS[mood].run}
          title={`Preview of this agent's familiar, ${MOODS[mood].label.toLowerCase()}`}
        />
        <div className="familiar-designer__sizes">
          {/* The sizes it is actually seen at, live, beside the big one. A body that only
              works large is not finished. */}
          {[40, 28, 20].map((s) => (
            <Familiar key={s} agent={{ id: agentId, role, familiar: value }} size={s} run={MOODS[mood].run} />
          ))}
          <span className="familiar-designer__sizes-label">as seen in chat</span>
        </div>
      </div>

      <div className="familiar-designer__moods" role="group" aria-label="Preview mood">
        {MOODS.map((m, i) => (
          <button
            key={m.label}
            type="button"
            className={i === mood ? "is-active" : undefined}
            onClick={() => setMood(i)}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="familiar-designer__actions">
        <button type="button" onClick={roll}>Roll</button>
        <button type="button" onClick={() => onChange(null)} disabled={!value}>
          Back to derived
        </button>
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? "Hide genes" : "Edit genes"}
        </button>
      </div>

      {open && (
        <div className="familiar-designer__genes">
          {visible.map((g) => (
            <label key={g.key} className="familiar-designer__gene">
              <span className="familiar-designer__gene-label">
                {g.label}
                <em>{gene[g.key].toFixed(g.step >= 1 ? 0 : 2)}</em>
              </span>
              <input
                type="range"
                min={g.min}
                max={g.max}
                step={g.step}
                value={gene[g.key]}
                onChange={(e) => set(g.key, Number(e.target.value))}
              />
              {g.hint && <small>{g.hint}</small>}
            </label>
          ))}
          <button type="button" onClick={() => onChange({ ...GENOTYPE_DEFAULTS })}>
            Reset to plain circle
          </button>
        </div>
      )}
    </section>
  );
}

export { PHENOTYPE_REST };
