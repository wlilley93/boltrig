import { describe, expect, it } from "vitest";

import {
  blankWorkflowDraft,
  buildWorkflowRequest,
  isPreservedUnsupportedStep,
  validateWorkflowDraft,
  workflowActionLimitation,
  workflowDetailToDraft,
} from "../src/workflowDraft";

describe("Worker workflow drafts", () => {
  it("round-trips governed steps without dropping schedule metadata", () => {
    const draft = workflowDetailToDraft({
      id: "renewals",
      status: "active",
      version: "2.0.0",
      source: "precreated",
      intent_tags: ["renewal", "finance"],
      definition: {
        schedule: { type: "cron", cron: "0 9 * * 1", timezone: "UTC" },
        steps: [{
          id: "find",
          parents: [],
          action: "contract.search",
          params: { limit: 20 },
          description: "Find upcoming renewals",
        }],
      },
    });
    draft.steps[0]!.description = "Find renewals due soon";

    expect(buildWorkflowRequest(draft)).toEqual({
      id: "renewals",
      version: "2.0.0",
      intent_tags: ["renewal", "finance"],
      definition: {
        schedule: { type: "cron", cron: "0 9 * * 1", timezone: "UTC" },
        steps: [{
          id: "find",
          parents: [],
          action: "contract.search",
          params: { limit: 20 },
          description: "Find renewals due soon",
        }],
      },
    });
  });

  it("rejects malformed params, missing parents, and duplicate ids", () => {
    const draft = blankWorkflowDraft();
    draft.id = "bad-dag";
    draft.steps = [
      {
        id: "one",
        action: "work.create",
        parents: ["two"],
        description: "",
        paramsText: "{}",
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
      {
        id: "two",
        action: "work.update",
        parents: ["one", "missing"],
        description: "",
        paramsText: "[]",
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
      {
        id: "two",
        action: "",
        parents: [],
        description: "",
        paramsText: "{}",
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
    ];

    const errors = validateWorkflowDraft(draft).join(" ");
    expect(errors).toContain("unique");
    expect(errors).toContain("missing parent");
    expect(errors).toContain("needs an action");
    expect(errors).toContain("JSON object");
  });

  it("rejects cyclic dependencies", () => {
    const draft = blankWorkflowDraft();
    draft.id = "cyclic-dag";
    draft.steps = [
      {
        id: "one",
        action: "work.create",
        parents: ["two"],
        description: "",
        paramsText: "{}",
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
      {
        id: "two",
        action: "work.update",
        parents: ["one"],
        description: "",
        paramsText: "{}",
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
    ];
    expect(validateWorkflowDraft(draft)).toContain("The dependency graph contains a cycle.");
  });

  it("round-trips IF/ELSE arms and opaque step fields, editing only selected fields", () => {
    const definition = {
      schedule: { type: "cron", cron: "0 9 * * 1", timezone: "UTC" },
      kernel_extension: { mode: "strict", revision: 4 },
      steps: [
        {
          id: "decide",
          action: "flow.branch",
          parents: [],
          params: { left: "$trigger.output.approved", op: "eq", right: true },
          retry: { attempts: 2 },
        },
        {
          id: "approved",
          action: "work.create",
          parents: ["decide"],
          branch: "true",
          params: { title: "Approved" },
          description: "IF arm",
          timeout_seconds: 30,
        },
        {
          id: "declined",
          action: "work.create",
          parents: ["decide"],
          branch: "false",
          with: { title: "Declined" },
          description: "ELSE arm",
          extension: { audit_label: "declined-path" },
        },
      ],
    };
    const draft = workflowDetailToDraft({
      id: "conditional",
      status: "active",
      version: "1.0.0",
      source: "generated",
      intent_tags: ["conditional"],
      definition,
    });

    const unchanged = buildWorkflowRequest(draft);
    expect(unchanged).not.toHaveProperty("source");
    expect(unchanged.definition).toEqual(definition);
    expect(draft.steps[1]?.branchArm).toBe("true");
    expect(draft.steps[2]?.branchArm).toBe("false");
    expect(draft.steps[2]?.parameterField).toBe("with");

    draft.steps[1]!.description = "Updated IF arm";
    draft.steps[2]!.branchArm = "true";
    const rebuilt = buildWorkflowRequest(draft).definition;
    expect(rebuilt).toEqual({
      ...definition,
      steps: [
        definition.steps[0],
        {
          ...definition.steps[1],
          description: "Updated IF arm",
        },
        {
          ...definition.steps[2],
          branch: "true",
        },
      ],
    });
  });

  it("preserves existing code records but allows bounded loop authoring", () => {
    const definition = {
      steps: [
        {
          id: "script",
          action: "code.run",
          parents: [],
          params: { script: "return 1" },
          sandbox_profile: "legacy",
        },
        {
          id: "repeat",
          action: "flow.loop",
          parents: ["script"],
          params: { items: ["a", "b"] },
          loop_policy: { maximum: 2 },
        },
      ],
    };
    const existing = workflowDetailToDraft({
      id: "advanced",
      status: "active",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition,
    });

    expect(validateWorkflowDraft(existing)).toEqual([]);
    expect(isPreservedUnsupportedStep(existing.steps[0]!)).toBe(true);
    expect(isPreservedUnsupportedStep(existing.steps[1]!)).toBe(false);
    expect(buildWorkflowRequest(existing).definition).toEqual(definition);
    expect(workflowActionLimitation("code.run")).toContain("executed=false");

    const authored = blankWorkflowDraft();
    authored.id = "unsupported";
    authored.steps = [{
      id: "step-1",
      action: "code.run",
      parents: [],
      description: "",
      paramsText: "{}",
      loopBindingsText: "{}",
      branchArm: "",
      parameterField: "params" as const,
      baseRecord: {},
    }];
    const errors = validateWorkflowDraft(authored).join(" ");
    expect(errors).toContain("cannot author code.run");
  });

  it("authors and losslessly edits a typed loop item/index contract", () => {
    const definition = {
      extension: { retained: true },
      steps: [
        {
          id: "loop",
          action: "flow.loop",
          parents: [],
          params: { items: [{ title: "A" }, { title: "B" }] },
          future_loop_policy: "stable",
        },
        {
          id: "create",
          action: "ticket.create",
          parents: ["loop"],
          params: { payload: null, ordinal: null, constant: "kept" },
          loop_bindings: { payload: "item", ordinal: "index" },
          future_body_policy: { audit: true },
        },
      ],
    };
    const draft = workflowDetailToDraft({
      id: "typed-loop",
      status: "active",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition,
    });

    expect(validateWorkflowDraft(draft)).toEqual([]);
    expect(isPreservedUnsupportedStep(draft.steps[0]!)).toBe(false);
    expect(buildWorkflowRequest(draft).definition).toEqual(definition);

    draft.steps[1]!.loopBindingsText = JSON.stringify({
      payload: "item",
      ordinal: "index",
      label: "item",
    });
    draft.steps[1]!.paramsText = JSON.stringify({
      payload: null,
      ordinal: null,
      label: null,
      constant: "kept",
    });
    expect(validateWorkflowDraft(draft)).toEqual([]);
    expect(buildWorkflowRequest(draft).definition).toEqual({
      ...definition,
      steps: [
        definition.steps[0],
        {
          ...definition.steps[1],
          params: {
            payload: null,
            ordinal: null,
            label: null,
            constant: "kept",
          },
          loop_bindings: {
            payload: "item",
            ordinal: "index",
            label: "item",
          },
        },
      ],
    });
  });

  it("rejects malformed, unscoped, and nested loop bindings before save", () => {
    const draft = blankWorkflowDraft();
    draft.id = "invalid-loop";
    draft.steps = [
      {
        id: "loop",
        action: "flow.loop",
        parents: [],
        description: "",
        paramsText: JSON.stringify({
          items: ["a"],
          items_from: "$seed.output.rows",
        }),
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
      {
        id: "nested",
        action: "flow.loop",
        parents: ["loop"],
        description: "",
        paramsText: JSON.stringify({ items: [1] }),
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
      {
        id: "body",
        action: "ticket.create",
        parents: ["nested"],
        description: "",
        paramsText: JSON.stringify({ title: null }),
        loopBindingsText: JSON.stringify({ missing: "value" }),
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
    ];

    const errors = validateWorkflowDraft(draft).join(" ");
    expect(errors).toContain("exactly one of items or items_from");
    expect(errors).toContain("cannot nest");
    expect(errors).toContain("sources must be item or index");
    expect(errors).toContain("target missing must already exist");
  });

  it("rejects an oversized selected loop payload before save", () => {
    const draft = blankWorkflowDraft();
    draft.id = "oversized-loop";
    draft.steps = [{
      id: "loop",
      action: "flow.loop",
      parents: [],
      description: "",
      paramsText: JSON.stringify({ items: ["x".repeat(256 * 1024)] }),
      loopBindingsText: "{}",
      branchArm: "",
      parameterField: "params",
      baseRecord: {},
    }];

    expect(validateWorkflowDraft(draft).join(" ")).toContain(
      "exceed the 256 KiB loop payload limit",
    );
  });

  it("reserves deterministic loop clone ids before save", () => {
    const draft = blankWorkflowDraft();
    draft.id = "clone-id-collision";
    draft.steps = [
      {
        id: "loop",
        action: "flow.loop",
        parents: [],
        description: "",
        paramsText: JSON.stringify({ items: [1] }),
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
      {
        id: "body__0",
        action: "ticket.create",
        parents: ["loop"],
        description: "",
        paramsText: JSON.stringify({ title: "x" }),
        loopBindingsText: "{}",
        branchArm: "",
        parameterField: "params",
        baseRecord: {},
      },
    ];

    expect(validateWorkflowDraft(draft)).toContain(
      "Step ids ending __<number> are reserved for loop iterations.",
    );
  });

  it("refuses to serialize opaque malformed step records", () => {
    const draft = workflowDetailToDraft({
      id: "opaque",
      status: "active",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: {
        steps: [
          { id: "valid", action: "work.create", parents: [] },
          { future_shape: true },
        ],
      },
    });

    expect(validateWorkflowDraft(draft).join(" ")).toContain("will not overwrite");
    expect(() => buildWorkflowRequest(draft)).toThrow("cannot be safely serialized");
  });

  it("does not invent a steps field on an existing definition that omitted it", () => {
    const draft = workflowDetailToDraft({
      id: "metadata-only",
      status: "active",
      version: "1.0.0",
      source: "precreated",
      intent_tags: [],
      definition: { extension: { retained: true } },
    });

    expect(buildWorkflowRequest(draft).definition).toEqual({
      extension: { retained: true },
    });
  });
});
