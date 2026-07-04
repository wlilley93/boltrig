import { describe, expect, it } from "vitest";
import {
  CATEGORIES,
  BOLT_AGENT_ID,
  allKinds,
  findKind,
  defaultActionForKind,
  DEFAULT_NODE_KIND,
  type NodeVisualKind,
} from "@/panels/workflowCanvas/nodeTaxonomy";

describe("nodeTaxonomy", () => {
  it("exposes the four design-brief categories with three items each", () => {
    const ids = CATEGORIES.map((c) => c.id);
    expect(ids).toEqual(["common", "logic", "data", "integration"]);
    for (const cat of CATEGORIES) {
      expect(cat.items).toHaveLength(3);
    }
  });

  it("includes the Agent Call node (decision #51) under Common", () => {
    const common = CATEGORIES.find((c) => c.id === "common")!;
    const agent = common.items.find((i) => i.kind === "agent-call");
    expect(agent).toBeDefined();
    expect(agent!.name).toBe("Agent Call");
    expect(agent!.color).toBe("#5E69DD");
  });

  it("findKind resolves every known kind", () => {
    for (const meta of allKinds()) {
      expect(findKind(meta.kind)).toBe(meta);
    }
  });

  it("findKind returns undefined for unknown or empty input", () => {
    expect(findKind("nope")).toBeUndefined();
    expect(findKind(undefined)).toBeUndefined();
    expect(findKind(null)).toBeUndefined();
  });

  it("defaults the visual kind to agent-call", () => {
    expect(DEFAULT_NODE_KIND).toBe("agent-call");
  });

  it("the agent-call default action targets the Bolt agent", () => {
    const { action, params } = defaultActionForKind("agent-call");
    expect(params.agent).toBe(BOLT_AGENT_ID);
    expect(action).toBeTruthy();
  });

  it("gives every kind a non-empty scaffolded action", () => {
    const kinds = allKinds().map((m) => m.kind) as NodeVisualKind[];
    for (const kind of kinds) {
      const { action } = defaultActionForKind(kind);
      expect(action.length).toBeGreaterThan(0);
    }
  });
});
