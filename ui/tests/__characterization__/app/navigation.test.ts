import { describe, expect, it } from "vitest";

import {
  BUILD_NAV,
  OPERATE_NAV,
  PRIMARY_NAV,
  visibleItems,
  zoneForTab,
} from "@/app/navigation";

describe("console navigation", () => {
  it("keeps the primary IA to five stable zones", () => {
    expect(PRIMARY_NAV.map((item) => item.label)).toEqual([
      "Home",
      "Chat",
      "Runs",
      "Build",
      "Operate",
    ]);
  });

  it("maps legacy surface routes into Build and Operate", () => {
    expect(zoneForTab("agents")).toBe("build");
    expect(zoneForTab("automations")).toBe("build");
    expect(zoneForTab("approvals")).toBe("operate");
    expect(zoneForTab("health")).toBe("operate");
    expect(zoneForTab("runs")).toBe("runs");
  });

  it("keeps cosmetic role gates out of the visible navigation model", () => {
    expect(visibleItems(BUILD_NAV, "member").map((item) => item.id)).not.toContain("studio");
    expect(visibleItems(OPERATE_NAV, "member").map((item) => item.id)).not.toContain("admin");
    expect(visibleItems(BUILD_NAV, "org-admin").map((item) => item.id)).toContain("studio");
    expect(visibleItems(OPERATE_NAV, "org-admin").map((item) => item.id)).toContain("admin");
  });
});
