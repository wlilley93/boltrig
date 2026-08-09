import assert from "node:assert/strict";
import { test } from "node:test";

import {
  RESTING_FAMILIAR_STATE_V2,
  sanitizeFamiliarState,
} from "../src/index.js";

test("familiar state v2 rejects wrong envelopes and stale sequences", () => {
  assert.equal(sanitizeFamiliarState(null), null);
  assert.equal(sanitizeFamiliarState("x"), null);
  assert.equal(sanitizeFamiliarState({ v: 1, seq: 1 }), null);
  assert.equal(sanitizeFamiliarState({ v: 2, seq: Number.NaN }), null);
  assert.equal(sanitizeFamiliarState({ v: 2, seq: 5 }, 5), null);
  assert.equal(sanitizeFamiliarState({ v: 2, seq: 4 }, 5), null);
  assert.notEqual(sanitizeFamiliarState({ v: 2, seq: 6 }, 5), null);
});

test("malformed fields fall back independently to the calm baseline", () => {
  const state = sanitizeFamiliarState({
    v: 2,
    seq: 1,
    phenotype: { valence: 0.9, arousal: Number.POSITIVE_INFINITY, tension: -4 },
    activity: { mode: "world_domination", intensity: 7, parallelWorkers: 3.9 },
    expression: { gesture: "explode", intensity: 0.5 },
    voice: { active: true, level: 2, bands: [0.1, "x", 9, -1] },
    gaze: { source: "telepathy", x: 55 },
    presentation: { mode: "fullscreen", visibility: -2 },
  });
  assert.ok(state);
  assert.equal(state.phenotype.valence, 0.9);
  assert.equal(state.phenotype.arousal, RESTING_FAMILIAR_STATE_V2.phenotype.arousal);
  assert.equal(state.phenotype.tension, 0);
  assert.equal(state.activity.mode, "idle");
  assert.equal(state.activity.intensity, 1);
  assert.equal(state.activity.parallelWorkers, 3);
  assert.equal(state.expression.gesture, "none");
  assert.equal(state.expression.intensity, 0.5);
  assert.deepEqual(state.voice.bands, [0.1, 0, 1, 0, 0, 0, 0, 0]);
  assert.equal(state.voice.level, 1);
  assert.equal(state.gaze.source, "none");
  assert.equal(state.gaze.x, 1);
  assert.equal(state.presentation.mode, "hero");
  assert.equal(state.presentation.visibility, 0);
});

test("identity palette only survives as exactly three hex colours", () => {
  const good = sanitizeFamiliarState({
    v: 2, seq: 1,
    identity: { genotypeSource: "agent_capability.name.v1", palette: ["#010203", "#a0b0c0", "#FFffFF"] },
  });
  assert.ok(good);
  assert.equal(good.identity.palette?.length, 3);
  const bad = sanitizeFamiliarState({
    v: 2, seq: 1,
    identity: { genotypeSource: "other.source", palette: ["#010203", "nope", "#FFffFF"] },
  });
  assert.ok(bad);
  assert.equal(bad.identity.genotypeSource, undefined);
  assert.equal(bad.identity.palette, undefined);
});

test("resting baseline is itself a valid, frozen v2 state", () => {
  assert.equal(RESTING_FAMILIAR_STATE_V2.v, 2);
  assert.throws(() => {
    (RESTING_FAMILIAR_STATE_V2 as { seq: number }).seq = 9;
  });
});
