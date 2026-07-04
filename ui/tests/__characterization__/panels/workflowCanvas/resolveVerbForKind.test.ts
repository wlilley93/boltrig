import { describe, expect, it } from "vitest";
import type { VerbInfo } from "@/api/types";
import {
  resolveVerbForKind,
  PREFERRED_VERB_FOR_KIND,
  defaultActionForKind,
} from "@/panels/workflowCanvas/nodeTaxonomy";

const verb = (id: string): VerbInfo => ({ id, noun: id.split(".")[0] });
const catalogue = (ids: string[]): Map<string, VerbInfo> =>
  new Map(ids.map((id) => [id, verb(id)]));

describe("resolveVerbForKind", () => {
  it("binds a capability kind to its preferred real verb when present", () => {
    const v = resolveVerbForKind("http", catalogue(["web.fetch", "channel.send"]));
    expect(v?.action).toBe("web.fetch");
  });

  it("seeds the agent param for an agent-call node", () => {
    const v = resolveVerbForKind("agent-call", catalogue(["chat.ask_user"]));
    expect(v?.action).toBe("chat.ask_user");
    expect(v?.params).toEqual({ agent: "bolt" });
  });

  it("falls back to undefined when the preferred verb is absent", () => {
    expect(resolveVerbForKind("http", catalogue(["channel.send"]))).toBeUndefined();
  });

  it("returns undefined for control kinds (handled by the interpreter)", () => {
    expect(resolveVerbForKind("trigger", catalogue(["web.fetch"]))).toBeUndefined();
    expect(resolveVerbForKind("conditional", catalogue(["web.fetch"]))).toBeUndefined();
  });

  it("the synthetic default still covers every kind as a last resort", () => {
    const present = catalogue(Object.keys(PREFERRED_VERB_FOR_KIND).map(
      (k) => PREFERRED_VERB_FOR_KIND[k as keyof typeof PREFERRED_VERB_FOR_KIND]!,
    ));
    // every capability kind resolves OR has a synthetic default action
    for (const kind of Object.keys(PREFERRED_VERB_FOR_KIND) as Array<
      keyof typeof PREFERRED_VERB_FOR_KIND
    >) {
      const resolved = resolveVerbForKind(kind, present);
      const fallback = defaultActionForKind(kind);
      expect((resolved?.action ?? fallback.action).length).toBeGreaterThan(0);
    }
  });
});
