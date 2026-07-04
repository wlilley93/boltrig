import { describe, expect, it } from "vitest";
import {
  CardSelect,
  ChipPicker,
  EntityPicker,
  JsonDisclosure,
  OrderedPicker,
  SchemaFormV2,
  ScopeBuilder,
  SegmentedV2,
  Stepper,
  Switch,
  grantMatches,
  schemaDefaults,
  scopeMatches,
  useSavedWisp,
} from "@/panels/uxForm";
import type { CardOption, ChipOption, EntityGroup, EntityItem, FieldEditorProps, PropSpec, ScopeVerb } from "@/panels/uxForm";

describe("uxForm pure exports", () => {
  it("matches grant patterns against verb ids", () => {
    expect(grantMatches("*", "anything")).toBe(true);
    expect(grantMatches("noun.*", "noun.verb")).toBe(true);
    expect(grantMatches("noun.*", "other.verb")).toBe(false);
    expect(grantMatches("noun.verb", "noun.verb")).toBe(true);
    expect(grantMatches("noun.verb", "noun.other")).toBe(false);
  });

  it("matches scope patterns against a registry of verbs", () => {
    const verbs: ScopeVerb[] = [
      { id: "a.read", noun: "a" },
      { id: "a.write", noun: "a" },
      { id: "b.run", noun: "b" },
    ];
    expect(scopeMatches(["a.*"], verbs).map((v) => v.id)).toEqual(["a.read", "a.write"]);
    expect(scopeMatches(["*"], verbs).map((v) => v.id)).toEqual(["a.read", "a.write", "b.run"]);
    expect(scopeMatches(["a.read", "b.run"], verbs).map((v) => v.id)).toEqual(["a.read", "b.run"]);
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

  it("exports every public component as a function", () => {
    const components = [
      Switch,
      SegmentedV2,
      CardSelect,
      ChipPicker,
      EntityPicker,
      ScopeBuilder,
      Stepper,
      JsonDisclosure,
      OrderedPicker,
      SchemaFormV2,
    ];
    for (const c of components) {
      expect(typeof c).toBe("function");
    }
  });

  it("exports hooks as functions", () => {
    expect(typeof useSavedWisp).toBe("function");
  });

  it("exports type shapes used by callers", () => {
    // Type-only compile check; the test body just asserts the imports resolved.
    const card: CardOption = { value: "x", label: "X" };
    const chip: ChipOption = { value: "x" };
    const item: EntityItem = { id: "x" };
    const group: EntityGroup = { label: "G", items: [item] };
    const spec: PropSpec = { type: "string" };
    const editor: FieldEditorProps = {
      value: "x",
      onChange: () => {},
      spec,
      path: "x",
      label: "X",
      required: true,
    };
    expect({ card, chip, item, group, spec, editor }).toBeTruthy();
  });
});
