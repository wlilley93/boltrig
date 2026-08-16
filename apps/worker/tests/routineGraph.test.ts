// The shared routine graph checks and the engine-faithful predicate mirror.
// These rules feed the canvas Problems strip AND the picker State word, and
// the Try-it dry walk claims to match control_flow.py, so the fail-closed
// cases are asserted explicitly.

import { describe, expect, it } from "vitest";

import {
  checkGraph,
  definitionToCheckStep,
  problemToneByStep,
  type GraphCheckStep,
} from "../src/components/routine/graphChecks";
import {
  BRANCH_OPERATORS,
  coerceSampleText,
  comparePredicate,
  evalPredicate,
  predicateSampleRefs,
  selectBranchLabel,
  simplePredicateFromParams,
  simplePredicateToParams,
} from "../src/components/routine/predicates";

function step(partial: Partial<GraphCheckStep> & { id: string }): GraphCheckStep {
  return {
    action: "doc.write",
    parents: [],
    branch: "",
    refs: [],
    ...partial,
  };
}

describe("shared routine graph checks", () => {
  it("finds nothing wrong with a clean fan-out", () => {
    const problems = checkGraph([
      step({ id: "start", action: "trigger.start" }),
      step({ id: "read", parents: ["start"] }),
      step({ id: "write", parents: ["read"], refs: ["read"] }),
    ]);
    expect(problems).toEqual([]);
  });

  it("marks a cycle red and everything else amber", () => {
    const problems = checkGraph([
      step({ id: "a", parents: ["b"] }),
      step({ id: "b", parents: ["a"] }),
    ]);
    const tones = problemToneByStep(problems);
    expect(tones.get("a")).toBe("red");
    expect(tones.get("b")).toBe("red");
  });

  it("says an orphaned step never runs", () => {
    const problems = checkGraph([
      step({ id: "start" }),
      step({ id: "island", parents: ["missing"] }),
    ]);
    expect(problems.some((problem) => (
      problem.stepId === "island" && problem.text.includes("never runs")
    ))).toBe(true);
  });

  it("flags a missing action and a label nothing produces", () => {
    const problems = checkGraph([
      step({ id: "start", action: "trigger.start" }),
      step({ id: "later", action: "", parents: ["start"], branch: "true" }),
    ]);
    const texts = problems.map((problem) => problem.text).join(" ");
    expect(texts).toContain("no action set yet");
    expect(texts).toContain("the label is ignored");
  });

  it("does not flag a label under a real branch ancestor", () => {
    const problems = checkGraph([
      step({ id: "start", action: "trigger.start" }),
      step({ id: "fork", action: "flow.branch", parents: ["start"] }),
      step({ id: "yes", parents: ["fork"], branch: "true" }),
    ]);
    expect(problems).toEqual([]);
  });

  it("flags a $ref to a step that is not an ancestor", () => {
    const problems = checkGraph([
      step({ id: "start", action: "trigger.start" }),
      step({ id: "left", parents: ["start"] }),
      step({ id: "right", parents: ["start"], refs: ["left"] }),
    ]);
    expect(problems.some((problem) => (
      problem.stepId === "right" && problem.text.includes("$left")
    ))).toBe(true);
  });

  it("flags a step waiting on the loop and on something outside it", () => {
    const problems = checkGraph([
      step({ id: "start", action: "trigger.start" }),
      step({ id: "loop", action: "flow.loop", parents: ["start"] }),
      step({ id: "inner", parents: ["loop"] }),
      step({ id: "straddle", parents: ["inner", "start"] }),
    ]);
    expect(problems.some((problem) => (
      problem.stepId === "straddle" && problem.text.includes("outside")
    ))).toBe(true);
  });

  it("normalizes a saved definition, reading refs from params or with", () => {
    const checked = definitionToCheckStep({
      id: "notify",
      action: "mail.send",
      parents: ["fetch"],
      branch: "true",
      with: { to: "$fetch.output.owner" },
    });
    expect(checked.refs).toEqual(["fetch"]);
    expect(checked.branch).toBe("true");
  });
});

describe("engine-faithful predicates", () => {
  const empty = () => null;

  it("fails closed on an unknown operator, exactly like _compare", () => {
    expect(comparePredicate(1, "matches", 1)).toBe(false);
  });

  it("refuses cross-type ordering instead of coercing", () => {
    expect(comparePredicate("9", "gt", 5)).toBe(false);
    expect(comparePredicate(9, "gt", 5)).toBe(true);
  });

  it("covers the containment forms both ways round", () => {
    expect(comparePredicate("a", "in", ["a", "b"])).toBe(true);
    expect(comparePredicate(["a", "b"], "contains", "a")).toBe(true);
    expect(comparePredicate("abc", "contains", "b")).toBe(true);
    expect(comparePredicate("abc", "starts_with", "ab")).toBe(true);
  });

  it("treats no predicate as an unconditional true branch", () => {
    expect(evalPredicate({}, empty)).toBe(true);
    expect(selectBranchLabel({}, empty)).toBe("true");
  });

  it("supports the bare {value} truthiness form", () => {
    expect(evalPredicate({ value: "$fetch.output.rows" }, () => [])).toBe(false);
    expect(evalPredicate({ value: "$fetch.output.rows" }, () => [1])).toBe(true);
  });

  it("labels multi-case branches by first match, then default_label", () => {
    const params = {
      cases: [
        { label: "hot", conditions: [{ left: "$score", op: "gte", right: 80 }] },
        { label: "warm", conditions: [] },
      ],
      default_label: "cold",
    };
    expect(selectBranchLabel(params, () => 90)).toBe("hot");
    expect(selectBranchLabel(params, () => 10)).toBe("warm");
    expect(selectBranchLabel({ cases: [] as unknown[], default_label: "cold" }, empty))
      .toBe("cold");
  });

  it("collects every $ref a predicate compares, including case conditions", () => {
    expect(predicateSampleRefs({
      left: "$read.output.health",
      op: "lt",
      right: 50,
      cases: [{ label: "x", conditions: [{ left: "$risk.output.tier", op: "eq", right: "high" }] }],
    })).toEqual(["$read.output.health", "$risk.output.tier"]);
  });

  it("round-trips only the simple left/op/right shape", () => {
    const simple = simplePredicateFromParams({ left: "$a.output.v", op: "gte", right: 3 });
    expect(simple).toEqual({ left: "$a.output.v", op: "gte", right: "3" });
    expect(simplePredicateToParams(simple!)).toEqual({
      left: "$a.output.v",
      op: "gte",
      right: 3,
    });
    // Multi-case and bare-value forms stay out of the structured editor so it
    // can never clobber a shape it does not represent.
    expect(simplePredicateFromParams({ cases: [] as unknown[] })).toBeNull();
    expect(simplePredicateFromParams({ value: "$a.output.flag" })).toBeNull();
  });

  it("keeps typed samples typed", () => {
    expect(coerceSampleText("42")).toBe(42);
    expect(coerceSampleText("true")).toBe(true);
    expect(coerceSampleText("null")).toBeNull();
    expect(coerceSampleText("northwind")).toBe("northwind");
  });

  it("offers the engine's operator set, not the design's nine", () => {
    expect(BRANCH_OPERATORS).toContain("not_contains");
    expect(BRANCH_OPERATORS).toContain("is_null");
    expect(BRANCH_OPERATORS.length).toBe(18);
  });
});
