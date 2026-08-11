import { describe, expect, it } from "vitest";

import {
  NO_WORK,
  SATURATION,
  workFromTurn,
} from "../src/components/jarvis/JarvisWork";

type Turn = Parameters<typeof workFromTurn>[0];

const turn = (over: Partial<NonNullable<Turn>> = {}): NonNullable<Turn> => ({
  tools: [],
  subagents: [],
  steps: [],
  ...over,
} as NonNullable<Turn>);

const tool = (status: string) => ({ key: "k", verb: "v", status }) as never;
const sub = (status?: string) =>
  ({ key: "k", childRunId: "r", task: "t", skills: [], status }) as never;
const step = (status: string) => ({ stepId: "s", action: "a", status }) as never;

describe("jarvis live work", () => {
  it("is dark with no turn and with an empty turn", () => {
    expect(workFromTurn(null)).toEqual(NO_WORK);
    expect(workFromTurn(turn())).toEqual(NO_WORK);
  });

  it("counts pending tools, running subagents and running steps together", () => {
    const work = workFromTurn(turn({
      tools: [tool("pending"), tool("ok")],
      subagents: [sub("running")],
      steps: [step("running"), step("ok")],
    }));
    expect(work.active).toBe(3);
    expect(work.load).toBeCloseTo(3 / SATURATION, 5);
  });

  // An un-upgraded kernel emits no settle frame, so `undefined` is honestly
  // "still running". Treating it as finished would darken a working board.
  it("treats a subagent with no settle frame as still running", () => {
    expect(workFromTurn(turn({ subagents: [sub(undefined)] })).active).toBe(1);
  });

  it("saturates at full load rather than exceeding it", () => {
    const tools = Array.from({ length: SATURATION + 4 }, () => tool("pending"));
    const work = workFromTurn(turn({ tools }));
    expect(work.active).toBe(SATURATION + 4);
    expect(work.load).toBe(1);
  });

  it("counts errored and degraded units as failures, not as load", () => {
    const work = workFromTurn(turn({
      tools: [tool("error"), tool("degraded")],
      steps: [step("failed")],
    }));
    expect(work.active).toBe(0);
    expect(work.load).toBe(0);
    expect(work.failed).toBe(3);
  });

  // Measured against everything that happened, not against what is still
  // running — otherwise a turn whose every unit failed reports zero failure,
  // because there is nothing left alive to divide by.
  it("reports total failure when everything failed", () => {
    const work = workFromTurn(turn({ tools: [tool("error"), tool("error")] }));
    expect(work.fail).toBe(1);
  });

  it("reports a fraction when work is part failed and part live", () => {
    const work = workFromTurn(turn({
      tools: [tool("pending"), tool("pending"), tool("pending"), tool("error")],
    }));
    expect(work.fail).toBeCloseTo(0.25, 5);
  });

  it("does not treat a clean finished turn as failure", () => {
    const work = workFromTurn(turn({
      tools: [tool("ok"), tool("ok")],
      subagents: [sub("ok")],
    }));
    expect(work).toEqual(NO_WORK);
  });
});
