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

  it("labels live spawn routing and the remaining parsed-only policy fields honestly", () => {
    const spawn = integrationSections.find((section) => section.key === "spawn_rules");
    const hitl = governanceSections.find((section) => section.key === "hitl");
    const privacy = governanceSections.find((section) => section.key === "privacy");

    expect(spawn?.blurb).toContain("Live governed routing");
    expect(hitl?.blurb).toContain("remain stored policy");
    expect(privacy?.blurb).toContain("remain stored policy");

    const spawnItems = (
      (spawn?.schema.properties as Record<string, { items?: { properties?: Record<string, {
        description?: string;
        minimum?: number;
        maximum?: number;
      }> } }>).items?.items?.properties ?? {}
    );
    expect(spawnItems.priority?.minimum).toBe(0);
    expect(spawnItems.priority?.maximum).toBe(1000);
    expect(spawnItems.capability?.description).toContain("conflicting caller routing pin");
    expect(spawnItems.skills?.description).toContain("capped by caller authority");

    const hitlProperties = (hitl?.schema.properties ?? {}) as Record<
      string,
      { description?: string }
    >;
    const privacyProperties = (privacy?.schema.properties ?? {}) as Record<
      string,
      { description?: string; minimum?: number }
    >;
    expect(hitlProperties.escalation_chain?.description).toContain("do not traverse");
    expect(privacyProperties.pii_redaction?.description).toContain("not wired");
    expect(privacyProperties.data_residency?.description).toContain("does not currently");
    expect(privacyProperties.redact_fields?.description).toContain("not currently applied");
    expect(privacyProperties.retention_days?.minimum).toBe(1);
    expect(privacyProperties.retention_days?.description).toContain(
      "after a conversation is closed",
    );
  });
});
