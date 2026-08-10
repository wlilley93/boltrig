import { describe, expect, it } from "vitest";

import {
  formatMicros,
  formatPercent,
  gatewaySummary,
  platformSummary,
  worstStatus,
} from "./format";
import type { ConsoleComponent, ConsoleOverview } from "./types";

const component = (id: string, status: ConsoleComponent["status"]): ConsoleComponent => ({
  id,
  kind: "runtime",
  message: "",
  metadata: {},
  status,
  updated_at: "",
});

describe("console format helpers", () => {
  it("formats cost micros as pounds", () => {
    expect(formatMicros(1_234_567)).toBe("£1.23");
  });

  it("selects the worst platform status", () => {
    expect(worstStatus([component("a", "ok"), component("b", "degraded")])).toBe(
      "degraded",
    );
    expect(worstStatus([component("a", "unknown"), component("b", "down")])).toBe(
      "down",
    );
  });

  it("summarises platform rows", () => {
    const overview = {
      platform: {
        components: [component("runpod", "ok")],
        runtimes: [component("opencode", "unknown")],
      },
    } as ConsoleOverview;
    expect(platformSummary(overview)).toBe("unknown · 2 services");
  });

  it("formats percentages", () => {
    expect(formatPercent(0.8123)).toBe("81.2%");
    expect(formatPercent(null)).toBe("n/a");
  });

  it("extracts gateway status from redacted platform metadata", () => {
    const overview = {
      platform: {
        components: [
          {
            ...component("bifrost", "ok"),
            message: "configured",
            metadata: {
              cache_hit_rate: 0.8,
              cache_hits: 12,
              cache_misses: 3,
              live_health: "ok",
              profile_count: 5,
              provider_count: 2,
              raw_payload: { unsafe: true },
            },
          },
        ],
        runtimes: [],
      },
    } as unknown as ConsoleOverview;

    expect(gatewaySummary(overview)).toEqual({
      cacheHitRate: 0.8,
      cacheHits: 12,
      cacheMisses: 3,
      liveHealth: "ok",
      message: "configured",
      profileCount: 5,
      providerCount: 2,
      status: "ok",
    });
  });

  it("returns null when gateway status is absent", () => {
    const overview = {
      platform: { components: [component("runpod", "ok")], runtimes: [] },
    } as unknown as ConsoleOverview;
    expect(gatewaySummary(overview)).toBeNull();
  });
});
