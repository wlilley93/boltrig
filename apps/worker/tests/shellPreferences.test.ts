// @vitest-environment happy-dom

import { beforeEach, describe, expect, it } from "vitest";

import {
  LEGACY_PINNED_CONVERSATIONS_KEY,
  SHELL_PREFERENCES_V1_KEY,
  loadShellPreferences,
  persistShellPreferences,
} from "../src/components/shell/shellPreferences";

beforeEach(() => {
  localStorage.clear();
});

describe("shell presentation preferences", () => {
  it("migrates legacy pins into the versioned schema", () => {
    localStorage.setItem(
      LEGACY_PINNED_CONVERSATIONS_KEY,
      JSON.stringify(["first", "second", "first", null]),
    );

    expect(loadShellPreferences()).toEqual({
      pinnedConversationIds: ["first", "second"],
    });
    expect(JSON.parse(localStorage.getItem(SHELL_PREFERENCES_V1_KEY) ?? "null"))
      .toEqual({
        schema_version: 1,
        pinned_conversation_ids: ["first", "second"],
      });
  });

  it("keeps the legacy mirror current for an application rollback", () => {
    persistShellPreferences({ pinnedConversationIds: ["new-shell-pin"] });

    expect(JSON.parse(
      localStorage.getItem(LEGACY_PINNED_CONVERSATIONS_KEY) ?? "null",
    )).toEqual(["new-shell-pin"]);
  });

  it("prefers the versioned value and repairs a stale rollback mirror", () => {
    localStorage.setItem(SHELL_PREFERENCES_V1_KEY, JSON.stringify({
      schema_version: 1,
      pinned_conversation_ids: ["versioned"],
    }));
    localStorage.setItem(
      LEGACY_PINNED_CONVERSATIONS_KEY,
      JSON.stringify(["stale"]),
    );

    expect(loadShellPreferences()).toEqual({
      pinnedConversationIds: ["versioned"],
    });
    expect(JSON.parse(
      localStorage.getItem(LEGACY_PINNED_CONVERSATIONS_KEY) ?? "null",
    )).toEqual(["versioned"]);
  });

  it("falls back to and re-migrates the legacy value after corrupt v1 data", () => {
    localStorage.setItem(SHELL_PREFERENCES_V1_KEY, "not-json");
    localStorage.setItem(
      LEGACY_PINNED_CONVERSATIONS_KEY,
      JSON.stringify(["rollback-safe"]),
    );

    expect(loadShellPreferences()).toEqual({
      pinnedConversationIds: ["rollback-safe"],
    });
    expect(JSON.parse(localStorage.getItem(SHELL_PREFERENCES_V1_KEY) ?? "null"))
      .toEqual({
        schema_version: 1,
        pinned_conversation_ids: ["rollback-safe"],
      });
  });
});
