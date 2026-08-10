// The proposal diff is the Studio's trust surface: what you approve is
// exactly the delta you previewed. Pure-data tests.

import { describe, expect, it } from "vitest";

import { diffSteps, proposedStepsFromContext } from "@/panels/workflowCanvas/workflowDiff";

const step = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  parents: [],
  action: "ticket.create",
  ...extra,
});

describe("diffSteps", () => {
  it("classifies added, removed, changed, and untouched steps", () => {
    const current = [step("keep"), step("edit", { params: { a: 1 } }), step("drop")];
    const proposed = [step("keep"), step("edit", { params: { a: 2 } }), step("new")];
    const d = diffSteps(current, proposed);
    expect(d.added).toEqual(["new"]);
    expect(d.removed).toEqual(["drop"]);
    expect(d.changed).toEqual(["edit"]);
    expect(d.byStep.has("keep")).toBe(false);
  });

  it("ignores key order when comparing", () => {
    const current = [{ id: "s", parents: [], action: "a.b", params: { x: 1, y: 2 } }];
    const proposed = [{ id: "s", action: "a.b", params: { y: 2, x: 1 }, parents: [] }];
    expect(diffSteps(current, proposed).changed).toEqual([]);
  });
});

describe("proposedStepsFromContext", () => {
  it("reads steps from an upsert hold's display context", () => {
    const ctx = {
      version: 1,
      verb: "control.workflow.upsert",
      inputs: { id: "wf", definition: { steps: [step("a"), step("b", { parents: ["a"] })] } },
    };
    const steps = proposedStepsFromContext(ctx);
    expect(steps?.map((s) => s.id)).toEqual(["a", "b"]);
    expect(steps?.[1].parents).toEqual(["a"]);
  });

  it("returns null rather than guessing on unreadable shapes", () => {
    expect(proposedStepsFromContext(null)).toBeNull();
    expect(proposedStepsFromContext({ inputs: { definition: { steps: "junk" } } })).toBeNull();
    expect(
      proposedStepsFromContext({ inputs: { definition: { steps: [{ action: 1 }] } } }),
    ).toBeNull();
  });
});
