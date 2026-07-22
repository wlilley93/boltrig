import { describe, expect, it } from "vitest";

import { FEATURE_GROUPS } from "./features";

const items = FEATURE_GROUPS.flatMap((group) => group.items);

describe("feature catalogue", () => {
  it("keeps six stable groups with five unique, complete claims each", () => {
    expect(FEATURE_GROUPS).toHaveLength(6);
    expect(FEATURE_GROUPS.map((group) => group.id)).toEqual([
      "outcomes",
      "control",
      "evidence",
      "experience",
      "extension",
      "deployment",
    ]);
    expect(FEATURE_GROUPS.every((group) => group.items.length === 5)).toBe(true);
    expect(items).toHaveLength(30);
    expect(new Set(items.map((item) => item.name)).size).toBe(items.length);
    expect(items.every((item) => item.name.trim() && item.outcome.trim().endsWith("."))).toBe(
      true,
    );
  });

  it("does not advertise known seams as active product behaviour", () => {
    const copy = items.map((item) => `${item.name} ${item.outcome}`).join(" ").toLowerCase();

    for (const unsupportedClaim of [
      "schedule or trigger",
      "per-run budgets",
      "file-backed systems",
      "chat platforms",
    ]) {
      expect(copy).not.toContain(unsupportedClaim);
    }
  });

  it("includes the shipped agent-profile and evaluation surfaces", () => {
    const names = new Set(items.map((item) => item.name));
    expect(names.has("Governed agent profiles")).toBe(true);
    expect(names.has("Evaluation cases")).toBe(true);
    expect(names.has("Knowledge with citations")).toBe(true);
  });

  it("bounds Knowledge to the implemented first slice", () => {
    const knowledge = items.find((item) => item.name === "Knowledge with citations");
    expect(knowledge?.outcome).toContain("text, Markdown and PDF");
    expect(knowledge?.outcome).toContain("immutable revision citations");
    expect(knowledge?.outcome.toLowerCase()).not.toContain("all data");
  });
});
