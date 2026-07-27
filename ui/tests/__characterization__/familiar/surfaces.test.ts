/**
 * The three surfaces added after chat: subagents, automations, and voice.
 *
 * Each one has a rule that is easy to state, easy to break, and invisible when broken - the
 * picture keeps rendering and quietly stops meaning anything. So each rule gets a test.
 */

import { describe, expect, it } from "vitest";

import { deriveGenotype, stableAgentKey } from "@/familiar/genotype";
import {
  AUTOMATION_HEALTHY_RATE,
  automationRole,
  automationRunFacts,
} from "@/familiar/automation";
import { phenotypeForRun, PHENOTYPE_REST } from "@/familiar/phenotype";
import { speakingEnvelope } from "@/familiar/voiceLevel";

describe("stable identity", () => {
  it("never accepts a run id as an identity", () => {
    // THE defect this exists to prevent: a subagent carries childRunId, it is right there and
    // unique, and using it would give the same agent a different body on every run - a picture
    // that looks like evidence and is not.
    expect(stableAgentKey({ name: null, runId: "run_abc123" })).toBeNull();
    expect(stableAgentKey({ id: "run_abc123", runId: "run_abc123" })).toBeNull();
  });

  it("prefers the name, and accepts an id only when it is not the run id", () => {
    expect(stableAgentKey({ name: "pr_explorer", runId: "run_1" })).toBe("pr_explorer");
    expect(stableAgentKey({ id: "agent-7", runId: "run_1" })).toBe("agent-7");
  });

  it("gives every unnamed agent of a role the same body, on purpose", () => {
    // Honest, not lazy: we know what KIND of thing it is and not WHICH one, and the picture
    // should say exactly that. Two unnamed reviewers looking alike is the truth.
    const a = deriveGenotype({ id: "role:reviewer", role: "reviewer" });
    const b = deriveGenotype({ id: "role:reviewer", role: "reviewer" });
    expect(a).toEqual(b);
  });
});

describe("automation mood", () => {
  it("says 'never run' differently from 'ran and succeeded'", () => {
    // A workflow that has never executed is UNPROVEN, which is the thing that matters most
    // about it. Idle would claim it is the same as one that ran cleanly an hour ago.
    const never = automationRunFacts({ successRate: null, runCount: 0 });
    const good = automationRunFacts({ successRate: 100, runCount: 12 });
    expect(never.status).toBe("queued");
    expect(good.status).toBe("done");
    expect(never.status).not.toBe(good.status);
  });

  it("tolerates a retry without painting the whole fleet magenta", () => {
    // A job that retries a flaky endpoint and succeeds is healthy. A warning that is always on
    // is a warning nobody reads.
    expect(automationRunFacts({ successRate: 95, runCount: 40 }).status).toBe("done");
    expect(automationRunFacts({ successRate: AUTOMATION_HEALTHY_RATE, runCount: 40 }).status).toBe("done");
    expect(automationRunFacts({ successRate: AUTOMATION_HEALTHY_RATE - 1, runCount: 40 }).status).toBe("failed");
  });

  it("lets firing beat any historical judgement", () => {
    // What it is doing now is more urgent than how it has done on average, and it is the only
    // signal that separates "scheduled" from "happening".
    expect(automationRunFacts({ successRate: 10, runCount: 50, firing: true }).status).toBe("running");
  });

  it("reads its shape family from meaning, and refuses to guess", () => {
    expect(automationRole("nightly-compliance-check", [])).toBe("guardian");
    expect(automationRole("weekly-metrics-digest", [])).toBe("analyst");
    expect(automationRole("deploy-site", [])).toBe("builder");
    // Unrecognised gets "", which bandForRole turns into the generic circle.
    expect(automationRole("wibble", [])).toBe("");
  });

  it("puts an automation and an agent of the same kind in the same family", () => {
    // A workflow that reviews things and an agent that reviews things should look like
    // relatives, because they are. If these two ever diverge the vocabulary has split.
    const auto = deriveGenotype({ id: "x", role: automationRole("review-prs", []) });
    const agent = deriveGenotype({ id: "x", role: "reviewer" });
    expect(auto.shape).toBe(agent.shape);
  });
});

describe("speaking envelope", () => {
  it("stays in range and never drops to silent mid-word", () => {
    // A familiar that flickers to nothing looks like it is failing, not talking.
    for (let t = 0; t < 30; t += 0.013) {
      const v = speakingEnvelope(t);
      expect(v).toBeGreaterThanOrEqual(0.18);
      expect(v).toBeLessThanOrEqual(1);
    }
  });

  it("does not repeat on a watchable period", () => {
    // Speech is not periodic. A body pulsing on a metronome reads as a loading spinner - a
    // machine waiting - which is the opposite of the impression wanted.
    const at = (t: number) => speakingEnvelope(t);
    for (const period of [0.5, 1, 2, 3, 5]) {
      let same = 0;
      for (let t = 0; t < 10; t += 0.1) if (Math.abs(at(t) - at(t + period)) < 0.01) same++;
      expect(same, `envelope looks periodic at ${period}s`).toBeLessThan(20);
    }
  });

  it("is pure: the same time always gives the same level", () => {
    expect(speakingEnvelope(3.25)).toBe(speakingEnvelope(3.25));
  });
});

describe("speaking is additive, not a state", () => {
  it("keeps the underlying run state visible while an agent talks", () => {
    // An agent can be speaking while running, while awaiting approval, or while reporting a
    // failure, and it must still look like the state it is in. If speaking overwrote the
    // state, a failing agent would look fine the moment it read its own error aloud.
    const failedQuiet = phenotypeForRun({ status: "failed" });
    const failedTalking = phenotypeForRun({ status: "failed", speaking: true });
    expect(failedTalking.irritation).toBe(failedQuiet.irritation);
    expect(failedTalking.valence).toBe(failedQuiet.valence);
    // ...while still showing that it is talking.
    expect(failedTalking.social).toBeGreaterThan(failedQuiet.social);
  });

  it("leaves a run-less familiar at rest rather than inventing a mood", () => {
    expect(phenotypeForRun({ status: "idle" })).toEqual(PHENOTYPE_REST);
  });
});
