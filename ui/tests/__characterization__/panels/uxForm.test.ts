import { describe, expect, it } from "vitest";
import { grantMatches, schemaDefaults } from "@/panels/uxForm";

describe("uxForm pure exports", () => {
  it("matches grant patterns against verb ids", () => {
    expect(grantMatches("*", "anything")).toBe(true);
    expect(grantMatches("noun.*", "noun.verb")).toBe(true);
    expect(grantMatches("noun.*", "other.verb")).toBe(false);
    expect(grantMatches("noun.verb", "noun.verb")).toBe(true);
    expect(grantMatches("noun.verb", "noun.other")).toBe(false);
  });

  it("seeds schema defaults from typed skeletons", () => {
    const schema = {
      type: "object",
      properties: {
        count: { type: "integer" },
        enabled: { type: "boolean" },
        tags: { type: "array" },
        nested: { type: "object" },
        name: { type: "string" },
      },
    };
    expect(schemaDefaults(schema)).toEqual({
      count: 0,
      enabled: false,
      tags: [],
      nested: {},
      name: "",
    });
  });
});
