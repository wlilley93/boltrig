import { describe, expect, it } from "vitest";
import {
  ADMIN_SECTION_OPTIONS,
  ADMIN_SECTIONS,
  fromFormValue,
  stableKey,
  toFormValue,
  type AdminSection,
} from "@/panels/admin/sections";
import { governanceSections } from "@/panels/admin/admin-sections/governanceSections";
import { integrationSections } from "@/panels/admin/admin-sections/integrationSections";
import { orgSections } from "@/panels/admin/admin-sections/orgSections";
import { runtimeSections } from "@/panels/admin/admin-sections/runtimeSections";
import { surfaceSections } from "@/panels/admin/admin-sections/surfaceSections";

describe("admin/sections", () => {
  it("round-trips a simple object section through form value", () => {
    const section: AdminSection = {
      key: "test",
      label: "Test",
      blurb: "",
      schema: {
        type: "object",
        properties: { name: { type: "string" } },
      },
    };
    const loaded = { name: "Alice" };
    const form = toFormValue(section, loaded);
    expect(form.name).toBe("Alice");
    expect(fromFormValue(section, form)).toEqual(loaded);
  });

  it("wraps list sections under items", () => {
    const section: AdminSection = {
      key: "list",
      label: "List",
      blurb: "",
      schema: { type: "array" },
      list: true,
    };
    const loaded = [{ id: 1 }];
    expect(toFormValue(section, loaded)).toEqual({ items: loaded });
  });

  it("produces a stable structural key", () => {
    expect(stableKey({ a: 1, b: 2 })).toBe(JSON.stringify({ a: 1, b: 2 }));
  });

  it("exposes non-empty admin sections and options", () => {
    expect(ADMIN_SECTIONS.length).toBeGreaterThan(0);
    expect(ADMIN_SECTION_OPTIONS.length).toBe(ADMIN_SECTIONS.length);
  });

  it("composes the full registry from extracted groups in order", () => {
    const groups = [
      orgSections,
      integrationSections,
      runtimeSections,
      governanceSections,
      surfaceSections,
    ];
    expect(groups.reduce((sum, g) => sum + g.length, 0)).toBe(ADMIN_SECTIONS.length);
    expect(ADMIN_SECTIONS[0]?.key).toBe("identity");
    expect(ADMIN_SECTIONS[ADMIN_SECTIONS.length - 1]?.key).toBe("personal_agents");
  });
});
