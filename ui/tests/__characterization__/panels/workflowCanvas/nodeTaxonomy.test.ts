import { describe, expect, it } from "vitest";
import type { VerbInfo } from "@/api/types";
import {
  CATEGORIES,
  allKinds,
  categoriesForCatalogue,
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

  it("labels the native question node by its real governed behavior", () => {
    const common = CATEGORIES.find((c) => c.id === "common")!;
    const agent = common.items.find((i) => i.kind === "agent-call");
    expect(agent).toBeDefined();
    expect(agent!.name).toBe("Ask user");
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

  it("the question default uses the real native question contract", () => {
    const { action, params } = defaultActionForKind("agent-call");
    expect(params).toEqual({ prompt: "" });
    expect(action).toBe("chat.ask_user");
  });

  it("gives every kind a non-empty scaffolded action", () => {
    const kinds = allKinds().map((m) => m.kind) as NodeVisualKind[];
    for (const kind of kinds) {
      const { action } = defaultActionForKind(kind);
      expect(action.length).toBeGreaterThan(0);
    }
  });

  it("shows only safe control nodes and caller-scoped real capabilities", () => {
    const verbs = new Map<string, VerbInfo>([
      ["channel.send", { id: "channel.send", noun: "channel" }],
    ]);
    const visible = categoriesForCatalogue(verbs).flatMap((category) => category.items);
    expect(visible.map((item) => item.kind)).toEqual([
      "trigger",
      "end",
      "conditional",
      "loop",
      "notify",
    ]);
    expect(visible.some((item) => item.kind === "code")).toBe(false);
    expect(visible.some((item) => item.kind === "http")).toBe(false);
  });
});
