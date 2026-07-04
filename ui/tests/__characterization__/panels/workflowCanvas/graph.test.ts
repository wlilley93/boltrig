import { describe, expect, it } from "vitest";
import type { VerbInfo } from "@/api/types";
import {
  deriveKind,
  deriveNodeKind,
  graphToSteps,
  stepsToGraph,
  type WorkflowStep,
} from "@/panels/workflowCanvas/graph";
import { DEFAULT_NODE_KIND } from "@/panels/workflowCanvas/nodeTaxonomy";

function agentVerb(id: string): VerbInfo {
  return {
    id,
    noun: "agent",
    verb: "call",
    binding: { target_type: "agent", target_ref: "bolt" },
  } as VerbInfo;
}

describe("graph nodeKind round-trip", () => {
  it("derives agent-call from an agent-targeting verb", () => {
    expect(deriveNodeKind(agentVerb("agent.call"))).toBe("agent-call");
  });

  it("derives the default kind for a non-agent verb", () => {
    const adapter: VerbInfo = {
      id: "svc.do",
      noun: "svc",
      verb: "do",
      binding: { target_type: "adapter", target_ref: "x" },
    } as VerbInfo;
    expect(deriveNodeKind(adapter)).toBe(DEFAULT_NODE_KIND);
    expect(deriveNodeKind(undefined)).toBe(DEFAULT_NODE_KIND);
  });

  it("persists a non-default nodeKind through graphToSteps and restores it", () => {
    const steps: WorkflowStep[] = [
      {
        id: "db",
        action: "database.query",
        parents: [],
        params: { __nodeKind: "database" },
      },
    ];
    const { nodes } = stepsToGraph(steps, new Map());
    expect(nodes[0].data.nodeKind).toBe("database");
    const restored = graphToSteps(nodes, []);
    expect(restored[0].params?.__nodeKind).toBe("database");
  });

  it("does not add params for a default-kind step (keeps the clean shape)", () => {
    const steps: WorkflowStep[] = [{ id: "a", parents: [], action: "x" }];
    const { nodes } = stepsToGraph(steps, new Map());
    expect(nodes[0].data.nodeKind).toBe(DEFAULT_NODE_KIND);
    expect(graphToSteps(nodes, [])).toEqual([
      { id: "a", parents: [], action: "x" },
    ]);
  });

  it("keeps the legacy engine kind alongside the visual kind", () => {
    const steps: WorkflowStep[] = [
      {
        id: "call",
        action: "agent.call",
        parents: [],
        params: { __nodeKind: "agent-call" },
      },
    ];
    const byId = new Map<string, VerbInfo>([["agent.call", agentVerb("agent.call")]]);
    const { nodes } = stepsToGraph(steps, byId);
    expect(deriveKind(byId.get("agent.call"))).toBe("agent");
    expect(nodes[0].data.kind).toBe("agent");
    expect(nodes[0].data.nodeKind).toBe("agent-call");
  });
});
