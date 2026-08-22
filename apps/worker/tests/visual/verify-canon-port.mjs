// Does the app still draw what the bench saved?
//
// The character canon lives in tests/visual/presets.json, which is GITIGNORED —
// so the shipped tuning tables are the only copy of it in the repo, and nothing
// in CI can notice when the two drift apart. This is that check, run by hand
// against a bench store that has the named versions in it.
//
// NOT A VITEST TEST, deliberately. A test that needs an untracked file fails on
// every fresh clone, which teaches people to ignore it — the exact shape of a
// check that cannot pass. Run it when you port a canon or touch a tuning table:
//
//   npx tsx tests/visual/verify-canon-port.mjs
//
// WHAT IT PROVES, per body and per mode: every field of the shipped tuning
// equals the canon's; every field the bench SWEPT ships as that sweep's centre
// (a rate-0 LFO holds at min and needs no pulse); every sweep has a pulse whose
// depth/rate/phase match the translation (depth = half-range/centre, phase
// shifted back a quarter turn); no pulse exists without a canon LFO behind it;
// and both speech maps are exact, both ways.
//
// It caught a real defect the day it was written: Ultron's port had read only
// standby's rack, found it empty, and shipped "no sweeps" — freezing working's
// eye aura at a mid-sweep 0.698739 instead of centring it at 0.42 with a pulse.
// See [[a-bounded-search-is-not-a-fact-about-the-system]].

import { readFileSync } from "node:fs";
const canon = JSON.parse(readFileSync(new URL("presets.json", import.meta.url), "utf8"));

const { JARVIS_TUNING } = await import("../../src/components/canvas/jarvisTuning.ts");
const { ULTRON_TUNING } = await import("../../src/components/canvas/ultronTuning.ts");
const J = await import("../../src/components/canvas/jarvisPresets.ts");
const U = await import("../../src/components/canvas/ultronPresets.ts");

const MODES = ["standby", "listening", "thinking", "working", "speaking"];
const near = (a, b) => Math.abs(a - b) < 1e-3;

function check(body, label, base, modes, pulses) {
  let problems = 0;
  for (const mode of MODES) {
    const vs = canon[`${body}.${mode}`].versions;
    const want = [...vs].reverse().find((v) => v.label === label);
    const lfos = want.lfos ?? {};
    const shipped = { ...base, ...modes[mode] };
    for (const [field, value] of Object.entries(want.tuning)) {
      const got = shipped[field];
      const arr = Array.isArray(value);
      const parts = arr ? value.length : 1;
      for (let i = 0; i < parts; i += 1) {
        const w = arr ? value[i] : value;
        const g = arr ? got?.[i] : got;
        const lfo = lfos[`${field}:${i}`];
        if (lfo?.on) {
          // Swept: the shipped base must be the sweep's CENTRE (rate 0 holds at min).
          const centre = lfo.rate === 0 ? lfo.min : (lfo.min + lfo.max) / 2;
          if (!near(g, centre)) {
            console.log(`  ✗ ${mode} ${field}[${i}] swept: shipped ${g}, want centre ${centre}`);
            problems += 1;
          }
          const p = pulses[mode].find((x) => x.field === field && x.index === i);
          if (lfo.rate === 0) continue; // a held constant needs no pulse
          if (!p) { console.log(`  ✗ ${mode} ${field}[${i}] has an LFO but NO pulse`); problems += 1; continue; }
          const wantDepth = centre === 0 ? 0 : (lfo.max - lfo.min) / 2 / centre;
          const wantPhase = ((lfo.phase - 0.25) % 1 + 1) % 1;
          if (!near(p.depth, wantDepth) || !near(p.rate, lfo.rate) || !near(p.phase, wantPhase)) {
            console.log(`  ✗ ${mode} ${field}[${i}] pulse: got d=${p.depth} r=${p.rate} ph=${p.phase}, want d=${wantDepth.toFixed(4)} r=${lfo.rate} ph=${wantPhase}`);
            problems += 1;
          }
        } else if (!near(g, w)) {
          console.log(`  ✗ ${mode} ${field}[${i}]: shipped ${g}, canon ${w}`);
          problems += 1;
        }
      }
    }
    // Any pulse with no LFO behind it is invented motion.
    for (const p of pulses[mode]) {
      if (!lfos[`${p.field}:${p.index}`]?.on) {
        console.log(`  ✗ ${mode} ${p.field}[${p.index}] pulse has NO canon LFO`);
        problems += 1;
      }
    }
  }
  console.log(`${body}: ${problems === 0 ? "MATCHES CANON" : problems + " mismatches"}`);
  return problems;
}

let bad = 0;
bad += check("jarvis", "Jarvis v2 final 1822", JARVIS_TUNING, J.JARVIS_MODES, J.JARVIS_PULSES);
bad += check("ultron", "Ultron final 1800", ULTRON_TUNING, U.ULTRON_MODES, U.ULTRON_PULSES);

// Speech maps, verbatim from the speaking slot.
for (const [body, label, map] of [["jarvis", "Jarvis v2 final 1822", J.JARVIS_SPEECH], ["ultron", "Ultron final 1800", U.ULTRON_SPEECH]]) {
  const vs = canon[`${body}.speaking`].versions;
  const want = [...vs].reverse().find((v) => v.label === label).speech;
  const missing = Object.keys(want).filter((k) => !(k in map));
  const wrong = Object.entries(want).filter(([k, v]) => k in map && !near(map[k], v));
  const extra = Object.keys(map).filter((k) => !(k in want));
  console.log(`${body} speech: ${Object.keys(map).length} entries | missing ${missing.length} | wrong ${wrong.length} | extra ${extra.length}`);
  bad += missing.length + wrong.length + extra.length;
}
console.log(bad === 0 ? "\nALL GREEN" : `\n${bad} PROBLEMS`);
