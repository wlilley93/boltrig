import { describe, expect, it } from "vitest";

import type { BudgetItem } from "@wlilley93/boltrig-web-sdk";
import {
  bindingBudget,
  NO_READING,
  telemetryFromBudgets,
} from "../src/components/jarvis/JarvisTelemetry";

const budget = (over: Partial<BudgetItem>): BudgetItem => ({
  id: "b1",
  scope_type: "tenant",
  window: "daily",
  hard_stop: false,
  token_limit: null,
  spent_tokens: 0,
  cost_limit_micros: null,
  spent_micros: 0,
  usage_state: "current",
  window_key: null,
  window_started_at: null,
  window_ends_at: null,
  ...over,
});

describe("jarvis telemetry", () => {
  it("has no reading without budgets", () => {
    expect(bindingBudget(null, "cost")).toEqual(NO_READING);
    expect(bindingBudget([], "cost")).toEqual(NO_READING);
  });

  // The gauge must agree with the console's budget table, which prints "—"
  // rather than a figure when usage is not computable outside a run.
  it("refuses to read a budget whose usage is not current", () => {
    const reading = bindingBudget([
      budget({ usage_state: "run_context_required", cost_limit_micros: 1000, spent_micros: 900 }),
    ], "cost");
    expect(reading.known).toBe(false);
  });

  // An unlimited budget is not a full gauge and not an empty one — it has no
  // ceiling to be a fraction of, so there is nothing to draw.
  it("treats an absent ceiling as no reading, not as zero", () => {
    const reading = bindingBudget([
      budget({ cost_limit_micros: null, spent_micros: 5_000 }),
    ], "cost");
    expect(reading).toEqual(NO_READING);
  });

  it("shows the ceiling you are closest to breaching, not the first or the total", () => {
    const reading = bindingBudget([
      budget({ id: "a", cost_limit_micros: 1_000_000, spent_micros: 100_000 }),  // 10%
      budget({ id: "b", cost_limit_micros: 200_000, spent_micros: 180_000 }),    // 90%
      budget({ id: "c", cost_limit_micros: 500_000, spent_micros: 150_000 }),    // 30%
    ], "cost");
    expect(reading.known).toBe(true);
    expect(reading.fill).toBeCloseTo(0.9, 5);
  });

  it("carries hard_stop from the binding budget, not from any other", () => {
    const reading = bindingBudget([
      budget({ id: "soft", cost_limit_micros: 100, spent_micros: 95, hard_stop: false }),
      budget({ id: "hard", cost_limit_micros: 100, spent_micros: 20, hard_stop: true }),
    ], "cost");
    expect(reading.fill).toBeCloseTo(0.95, 5);
    expect(reading.hard).toBe(false);
  });

  // Clamping an overrun to a pinned full circle would hide it; 103% must be
  // distinguishable from 100%.
  it("reports an overrun past 1 rather than clamping it", () => {
    const reading = bindingBudget([
      budget({ cost_limit_micros: 1000, spent_micros: 1030 }),
    ], "cost");
    expect(reading.fill).toBeCloseTo(1.03, 5);
  });

  it("reads money and tokens independently", () => {
    const telemetry = telemetryFromBudgets([
      budget({ cost_limit_micros: 1000, spent_micros: 250, token_limit: 100, spent_tokens: 80 }),
    ]);
    expect(telemetry.budget.fill).toBeCloseTo(0.25, 5);
    expect(telemetry.tokens.fill).toBeCloseTo(0.8, 5);
  });

  it("can know one metric while the other has no ceiling", () => {
    const telemetry = telemetryFromBudgets([
      budget({ cost_limit_micros: null, spent_micros: 9_999, token_limit: 200, spent_tokens: 50 }),
    ]);
    expect(telemetry.budget.known).toBe(false);
    expect(telemetry.tokens.known).toBe(true);
    expect(telemetry.tokens.fill).toBeCloseTo(0.25, 5);
  });
});
