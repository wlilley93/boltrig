import { beforeEach, describe, expect, it } from "vitest";

import { hitlRespondUrl, loadSettings, overviewUrl, saveSettings } from "./client";

beforeEach(() => {
  window.sessionStorage.clear();
});

describe("overviewUrl", () => {
  it("uses a same-origin path when no API base is configured", () => {
    expect(overviewUrl("", 50)).toBe("/v1/console/overview?limit=50");
  });

  it("joins API base and clamps the limit", () => {
    expect(overviewUrl("https://api.example.com/", 999)).toBe(
      "https://api.example.com/v1/console/overview?limit=200",
    );
  });

  it("builds approval response URLs", () => {
    expect(hitlRespondUrl("https://api.example.com/", "hitl/1")).toBe(
      "https://api.example.com/v1/hitl/hitl%2F1/respond",
    );
  });

  it("persists the API base but never stores bearer tokens", () => {
    window.sessionStorage.setItem("boltrig.console.bearerToken", "old-token");

    saveSettings({ apiBase: "https://api.example.com/", bearerToken: "secret-token" });

    expect(window.sessionStorage.getItem("boltrig.console.apiBase")).toBe(
      "https://api.example.com/",
    );
    expect(window.sessionStorage.getItem("boltrig.console.bearerToken")).toBeNull();
    expect(loadSettings()).toEqual({
      apiBase: "https://api.example.com/",
      bearerToken: "",
    });
  });
});
