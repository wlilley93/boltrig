import { describe, expect, it } from "vitest";

import {
  getSubAgentData,
  SUB_RUN_AGENT_IDS,
  type SeededAgentData,
} from "@/panels/chat/subRunSeed";

describe("chat/subRunSeed", () => {
  it("covers all six agents enumerated in the brief (sec 11)", () => {
    expect(SUB_RUN_AGENT_IDS).toEqual([
      "bolt",
      "head-eng",
      "release-manager",
      "deps-checker",
      "changelog-writer",
      "notifier",
    ]);
  });

  it.each(SUB_RUN_AGENT_IDS)(
    "%s returns non-empty messages and tool receipts",
    (agentId) => {
      const data: SeededAgentData = getSubAgentData(agentId);
      expect(data.messages.length).toBeGreaterThan(0);
      expect(data.tools.length).toBeGreaterThan(0);
      for (const m of data.messages) {
        expect(m.id).toBeTruthy();
        expect(m.text.trim().length).toBeGreaterThan(0);
        expect(m.time.trim().length).toBeGreaterThan(0);
      }
      for (const t of data.tools) {
        expect(t.verb.trim().length).toBeGreaterThan(0);
        expect(["ok", "running", "error", "pending"]).toContain(t.status);
      }
    },
  );

  it("bolt returns a delegation overview", () => {
    const data = getSubAgentData("bolt");
    const text = data.messages.map((m) => m.text).join(" ").toLowerCase();
    expect(text).toContain("delegat");
  });

  it("release manager has a PR-create tool", () => {
    const data = getSubAgentData("release-manager");
    const verbs = data.tools.map((t) => t.verb.toLowerCase());
    expect(verbs.some((v) => v.includes("pr create"))).toBe(true);
  });

  it("deps checker reads a manifest and verifies compatibility", () => {
    const verbs = getSubAgentData("deps-checker").tools.map((t) => t.verb.toLowerCase());
    expect(verbs.some((v) => v.includes("manifest"))).toBe(true);
    expect(verbs.some((v) => v.includes("compatibility"))).toBe(true);
  });

  it("changelog writer reads the commit log and creates a changelog PR", () => {
    const verbs = getSubAgentData("changelog-writer").tools.map((t) => t.verb.toLowerCase());
    expect(verbs.some((v) => v.includes("commit log"))).toBe(true);
    expect(verbs.some((v) => v.includes("changelog pr"))).toBe(true);
  });

  it("notifier is in a pending / waiting state", () => {
    const data = getSubAgentData("notifier");
    expect(data.tools.some((t) => t.status === "pending" || t.status === "running")).toBe(true);
  });

  it("returns a non-empty fallback for unknown agent ids", () => {
    const data = getSubAgentData("head-sre");
    expect(data.messages.length).toBeGreaterThan(0);
  });

  it("returns independent data copies across calls", () => {
    const a = getSubAgentData("bolt");
    a.messages.push({ id: "mut", text: "x", time: "now" });
    const b = getSubAgentData("bolt");
    expect(b.messages.some((m) => m.id === "mut")).toBe(false);
  });
});
