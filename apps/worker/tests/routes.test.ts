import { describe, expect, it } from "vitest";

import {
  conversationFromHash,
  routeFromHash,
  routeHash,
  selectionFromHash,
} from "../src/routes";

describe("Worker routes", () => {
  it("keeps the task surface as the default", () => {
    expect(routeFromHash("")).toBe("chat");
    expect(routeFromHash("#/not-a-worker-route")).toBe("chat");
    expect(routeFromHash("#/inbox")).toBe("chat");
    expect(routeFromHash("#/operate")).toBe("chat");
  });

  it("recognises every first-party Worker section", () => {
    for (const route of [
      "home", "chat", "runs", "work", "agents", "automations", "browser",
      "knowledge", "memory", "integrations", "channels", "build",
      "evaluations", "account", "organisation", "settings",
    ]) {
      expect(routeFromHash(`#/${route}`)).toBe(route);
    }
  });

  it("parses a bounded encoded conversation deep link", () => {
    expect(conversationFromHash("#/chat/conversation%2Fa")).toBe("conversation/a");
    expect(conversationFromHash("#/runs/conversation%2Fa")).toBeNull();
    expect(conversationFromHash("#/chat/%E0%A4%A")).toBeNull();
    expect(conversationFromHash(`#/chat/${"a".repeat(257)}`)).toBeNull();
  });

  it("round-trips bounded selections for every durable Worker resource", () => {
    for (const route of [
      "runs", "work", "agents", "knowledge", "automations", "evaluations",
    ] as const) {
      const hash = routeHash(route, "selected/id");
      expect(hash).toBe(`#/${route}/selected%2Fid`);
      expect(selectionFromHash(hash, route)).toBe("selected/id");
    }
    expect(selectionFromHash("#/runs/run-a/extra", "runs")).toBeNull();
    expect(selectionFromHash("#/runs/%E0%A4%A", "runs")).toBeNull();
    expect(selectionFromHash("#/runs/run-a", "work")).toBeNull();
  });
});
