import { afterEach, describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import {
  WorkflowCanvas,
  deriveKind,
  extractSteps,
  stepsToGraph,
  type WorkflowStep,
} from "@/panels/WorkflowCanvas";
import type { VerbInfo } from "@/api/types";
import { graphToSteps } from "@/panels/workflowCanvas/graph";
import { clearApiMocks, mockApi } from "../helpers";

describe("WorkflowCanvas", () => {
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi({
      workflows: { workflows: [] },
      capabilities: { capabilities: [] },
    });
    render(<WorkflowCanvas routeWfId={undefined} />);
  });

  it("derives node kind from verb binding", () => {
    const agentVerb: VerbInfo = {
      id: "agent.do",
      noun: "agent",
      verb: "do",
      binding: { target_type: "agent" },
    } as VerbInfo;
    expect(deriveKind(agentVerb)).toBe("agent");

    const adapterVerb: VerbInfo = {
      id: "svc.do",
      noun: "svc",
      verb: "do",
      binding: { target_type: "adapter" },
    } as VerbInfo;
    expect(deriveKind(adapterVerb)).toBe("service");

    expect(deriveKind(undefined)).toBe("kernel-run");
  });

  it("extracts steps from array, object, and definition shapes", () => {
    const steps: WorkflowStep[] = [{ id: "a", action: "x" }];
    expect(extractSteps(steps)).toEqual(steps);
    expect(extractSteps({ steps })).toEqual(steps);
    expect(extractSteps({ definition: { steps } })).toEqual(steps);
    expect(extractSteps({})).toBeNull();
  });

  it("turns steps into a graph with nodes and edges", () => {
    const steps: WorkflowStep[] = [
      { id: "a", action: "x" },
      { id: "b", action: "y", parents: ["a"] },
    ];
    const { nodes, edges } = stepsToGraph(steps, new Map());
    expect(nodes).toHaveLength(2);
    expect(edges).toHaveLength(1);
    expect(edges[0].source).toBe("a");
    expect(edges[0].target).toBe("b");
  });

  it("round-trips a graph back to steps", () => {
    const steps: WorkflowStep[] = [
      { id: "a", action: "x" },
      { id: "b", action: "y", parents: ["a"] },
    ];
    const { nodes, edges } = stepsToGraph(steps, new Map());
    expect(graphToSteps(nodes, edges)).toEqual([
      { id: "a", parents: [], action: "x" },
      { id: "b", parents: ["a"], action: "y" },
    ]);
  });
});
