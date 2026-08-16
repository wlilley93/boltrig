// @vitest-environment happy-dom

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { WorkflowStepDefinition } from "@wlilley93/boltrig-web-sdk";

import { RoutineThumb, layoutGrid, layoutSteps } from "../src/components/RoutineThumb";

afterEach(cleanup);

// A fan-out and fan-in: start feeds read; read feeds two siblings; both feed
// check; check feeds a code step. This is the shape the decided target draws on
// a routine card, so the layout has to reproduce it from `parents[]` alone.
const FAN: WorkflowStepDefinition[] = [
  { id: "start", action: "trigger.start" },
  { id: "read", action: "crm.account.read", parents: ["start"] },
  { id: "score", action: "doc.write", parents: ["read"] },
  { id: "draft", action: "doc.write", parents: ["read"] },
  { id: "check", action: "", parents: ["score", "draft"] },
  { id: "code", action: "code.run", parents: ["check"] },
];

describe("routine thumbnail", () => {
  it("lays the saved spec out by depth, so a fan-in sits after both branches", () => {
    const { nodes } = layoutSteps(FAN);
    const at = (id: string) => nodes.find((node) => node.id === id)!;

    expect(at("start").x).toBe(0);
    expect(at("score").x).toBe(at("draft").x);
    expect(at("score").y).not.toBe(at("draft").y);
    // Depth is the LONGEST path, so check clears both siblings rather than
    // overlapping the shorter branch.
    expect(at("check").x).toBeGreaterThan(at("score").x);
    expect(at("code").x).toBeGreaterThan(at("check").x);
  });

  it("marks the trigger, the code step and the step that cannot run unattended", () => {
    const { nodes } = layoutSteps(FAN);
    const kind = (id: string) => nodes.find((node) => node.id === id)!;

    expect(kind("start").kind).toBe("trigger");
    expect(kind("code").kind).toBe("code");
    expect(kind("read").kind).toBe("step");
    // An action-less step is the "needs you" case the amber pip marks.
    expect(kind("check").needsYou).toBe(true);
    expect(kind("read").needsYou).toBe(false);
  });

  it("draws one edge per parent link", () => {
    const { edges } = layoutSteps(FAN);
    expect(edges.length).toBe(6);
  });

  it("terminates on a cyclic spec instead of recursing forever", () => {
    const cyclic: WorkflowStepDefinition[] = [
      { id: "a", action: "x", parents: ["b"] },
      { id: "b", action: "y", parents: ["a"] },
    ];
    const { nodes } = layoutSteps(cyclic);
    expect(nodes.length).toBe(2);
  });

  it("shares one grid between the thumbnail and the full canvas", () => {
    // The canvas seeds its default positions from the same depth grid, so a
    // routine looks like a bigger version of its own card.
    const cells = layoutGrid(FAN);
    expect(cells.get("start")).toEqual({ col: 0, row: 0 });
    expect(cells.get("score")?.col).toBe(cells.get("draft")?.col);
    expect(cells.get("score")?.row).not.toBe(cells.get("draft")?.row);
    expect(cells.get("check")?.col).toBeGreaterThan(cells.get("score")?.col ?? 0);
  });

  it("says a routine has no steps rather than drawing an empty box", () => {
    const { container } = render(<RoutineThumb steps={[]} />);
    expect(container.textContent).toContain("no steps yet");
    expect(container.querySelectorAll("rect").length).toBe(0);
  });

  it("renders a node per step and ignores a parent that is not in the spec", () => {
    const orphan: WorkflowStepDefinition[] = [
      { id: "only", action: "doc.write", parents: ["missing"] },
    ];
    const { nodes, edges } = layoutSteps(orphan);
    expect(nodes.length).toBe(1);
    expect(edges.length).toBe(0);
    const { container } = render(<RoutineThumb steps={FAN} />);
    expect(container.querySelectorAll("rect").length).toBe(FAN.length);
  });
});
