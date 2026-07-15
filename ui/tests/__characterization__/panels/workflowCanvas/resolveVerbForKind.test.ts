import { describe, expect, it } from "vitest";
import type { VerbInfo } from "@/api/types";
import {
  resolveVerbForKind,
  PREFERRED_VERB_FOR_KIND,
} from "@/panels/workflowCanvas/nodeTaxonomy";

const verb = (id: string): VerbInfo => ({ id, noun: id.split(".")[0] });
const catalogue = (ids: string[]): Map<string, VerbInfo> =>
  new Map(ids.map((id) => [id, verb(id)]));

describe("resolveVerbForKind", () => {
  it("binds a capability kind to its preferred real verb when present", () => {
    const v = resolveVerbForKind("http", catalogue(["web.fetch", "channel.send"]));
    expect(v?.action).toBe("web.fetch");
  });

  it("seeds the governed question contract for an ask-user node", () => {
    const v = resolveVerbForKind("agent-call", catalogue(["chat.ask_user"]));
    expect(v?.action).toBe("chat.ask_user");
    expect(v?.params).toEqual({ prompt: "" });
  });

  it("falls back to undefined when the preferred verb is absent", () => {
    expect(resolveVerbForKind("http", catalogue(["channel.send"]))).toBeUndefined();
  });

  it("returns undefined for control kinds (handled by the interpreter)", () => {
    expect(resolveVerbForKind("trigger", catalogue(["web.fetch"]))).toBeUndefined();
    expect(resolveVerbForKind("conditional", catalogue(["web.fetch"]))).toBeUndefined();
  });

  it("real preferred verbs resolve without a synthetic capability fallback", () => {
    const present = catalogue(Object.keys(PREFERRED_VERB_FOR_KIND).map(
      (k) => PREFERRED_VERB_FOR_KIND[k as keyof typeof PREFERRED_VERB_FOR_KIND]!,
    ));
    for (const kind of Object.keys(PREFERRED_VERB_FOR_KIND) as Array<
      keyof typeof PREFERRED_VERB_FOR_KIND
    >) {
      const resolved = resolveVerbForKind(kind, present);
      expect(resolved?.action).toBe(PREFERRED_VERB_FOR_KIND[kind]);
    }
    expect(resolveVerbForKind("template", present)).toBeUndefined();
  });
});
