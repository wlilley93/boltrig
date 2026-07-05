import { describe, expect, it } from "vitest";

import {
  deriveCardMeta,
  formatLastRun,
  hashId,
  mergeCardStats,
} from "@/panels/automations/cardMeta";
import type { WorkflowRunStat } from "@/api/types";

// Design brief 22.1: REAL run stats override the deterministic placeholders on
// the automations home cards; a workflow with no stat row keeps its placeholder.
// The merge is a pure function (the route just feeds it the stats response), so
// the characterization is the contract: real wins where present, placeholder
// survives where absent, and the non-stat fields (accent / spark / owner /
// trigger) are never touched.

describe("mergeCardStats", () => {
  const wfId = "smoke-loop";

  it("overrides runCount / successRate / lastRun when a stat exists", () => {
    const base = deriveCardMeta(wfId, "precreated", []);
    const stat: WorkflowRunStat = {
      workflow_id: wfId,
      run_count: 25,
      success_count: 20,
      last_run_at: "2026-07-01T00:00:00.000Z",
    };
    const merged = mergeCardStats(base, stat);
    expect(merged.runCount).toBe(25);
    // 20 / 25 = 0.8 -> rounded to 80
    expect(merged.successRate).toBe(80);
    expect(merged.lastRun).not.toBe(base.lastRun);
    // lastRun is a relative label derived from last_run_at (never the raw ISO).
    expect(merged.lastRun).not.toContain("2026");
  });

  it("preserves the deterministic accent / spark / owner / trigger", () => {
    const base = deriveCardMeta(wfId, "precreated", ["onboarding"]);
    const stat: WorkflowRunStat = {
      workflow_id: wfId,
      run_count: 3,
      success_count: 3,
      last_run_at: "2026-07-01T00:00:00.000Z",
    };
    const merged = mergeCardStats(base, stat);
    expect(merged.accent).toBe(base.accent);
    expect(merged.spark).toBe(base.spark);
    expect(merged.owner).toBe(base.owner);
    expect(merged.trigger).toBe(base.trigger);
    expect(merged.status).toBe(base.status);
    expect(merged.description).toBe(base.description);
  });

  it("keeps the placeholder when no stat is provided", () => {
    const base = deriveCardMeta(wfId, "precreated", []);
    const seed = hashId(wfId);
    expect(mergeCardStats(base, undefined)).toEqual(base);
    expect(mergeCardStats(base, undefined).runCount).toBe(base.runCount);
    // sanity: the placeholder is the deterministic seed-derived value
    expect(base.runCount).toBeLessThan(50);
    expect(seed).toBeGreaterThan(0);
  });

  it("keeps the placeholder when the stat has zero runs", () => {
    const base = deriveCardMeta(wfId, "precreated", []);
    const stat: WorkflowRunStat = {
      workflow_id: wfId,
      run_count: 0,
      success_count: 0,
      last_run_at: null,
    };
    expect(mergeCardStats(base, stat)).toEqual(base);
  });

  it("rounds success_rate to a whole percent", () => {
    const base = deriveCardMeta(wfId, "precreated", []);
    const stat: WorkflowRunStat = {
      workflow_id: wfId,
      run_count: 3,
      success_count: 2,
      last_run_at: "2026-07-01T00:00:00.000Z",
    };
    // 2 / 3 = 0.6666... -> 67
    expect(mergeCardStats(base, stat).successRate).toBe(67);
  });

  it("treats a fully-failed workflow as 0% (does not skip the merge)", () => {
    const base = deriveCardMeta(wfId, "precreated", []);
    const stat: WorkflowRunStat = {
      workflow_id: wfId,
      run_count: 5,
      success_count: 0,
      last_run_at: "2026-07-01T00:00:00.000Z",
    };
    const merged = mergeCardStats(base, stat);
    expect(merged.runCount).toBe(5);
    expect(merged.successRate).toBe(0);
  });
});

describe("formatLastRun", () => {
  it("returns 'never' for null", () => {
    expect(formatLastRun(null)).toBe("never");
  });

  it("returns 'never' for an unparseable string", () => {
    expect(formatLastRun("not-a-date")).toBe("never");
  });

  it("returns 'just now' for the present moment", () => {
    expect(formatLastRun(new Date().toISOString())).toBe("just now");
  });

  it("returns a relative label for a past timestamp", () => {
    const past = new Date(Date.now() - 2 * 60 * 1000).toISOString(); // 2m ago
    const label = formatLastRun(past);
    expect(label).toMatch(/minute/);
  });
});
