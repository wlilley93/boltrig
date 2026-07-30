import type {
  UpsertWorkflowRequest,
  WorkflowDetail,
  WorkflowStepDefinition,
  WorkflowSourceValue,
} from "@wlilley93/boltrig-web-sdk";

export interface WorkflowStepDraft {
  id: string;
  action: string;
  parents: string[];
  description: string;
  paramsText: string;
  loopBindingsText: string;
  branchArm: string;
  parameterField: "params" | "with";
  /**
   * Complete server record. Build starts from this object so fields introduced
   * by the kernel remain intact even when this Worker version cannot edit them.
   */
  baseRecord: Record<string, unknown>;
}

export interface WorkflowDraft {
  id: string;
  version: string;
  readonly source: WorkflowSourceValue;
  tagsText: string;
  baseDefinition: Record<string, unknown>;
  steps: WorkflowStepDraft[];
  preservationErrors: string[];
  serializeSteps: boolean;
}

const UNSUPPORTED_WORKFLOW_ACTIONS = new Set(["code.run"]);
const LOOP_BINDING_KEY = /^[A-Za-z_][A-Za-z0-9_-]{0,63}$/;
const LOOP_CLONE_ID = /.+__[0-9]+$/;
const LOOP_BINDING_SOURCES = new Set(["item", "index"]);
const LOOP_MAX_BINDINGS = 32;
const LOOP_MAX_ITEMS = 100;
const LOOP_MAX_BOUND_BYTES = 256 * 1024;

export const WORKER_CONTROL_ACTIONS = [
  "trigger.start",
  "flow.branch",
  "flow.loop",
  "flow.end",
] as const;

export function blankWorkflowDraft(): WorkflowDraft {
  return {
    id: "",
    version: "1.0.0",
    source: "precreated",
    tagsText: "",
    baseDefinition: {},
    steps: [],
    preservationErrors: [],
    serializeSteps: true,
  };
}

export function workflowDetailToDraft(detail: WorkflowDetail): WorkflowDraft {
  const source = (
    detail.source === "generated" || detail.source === "learned"
      ? detail.source
      : "precreated"
  );
  const extracted = extractStepRecords(detail.definition);
  return {
    id: detail.id,
    version: detail.version || "1.0.0",
    source,
    tagsText: detail.intent_tags.join(", "),
    baseDefinition: { ...detail.definition },
    steps: extracted.steps,
    preservationErrors: extracted.errors,
    serializeSteps: Object.prototype.hasOwnProperty.call(detail.definition, "steps"),
  };
}

export function buildWorkflowRequest(draft: WorkflowDraft): UpsertWorkflowRequest {
  if (draft.preservationErrors.length) {
    throw new TypeError(
      `Workflow cannot be safely serialized: ${draft.preservationErrors.join(" ")}`,
    );
  }
  const definition = { ...draft.baseDefinition };
  if (draft.serializeSteps || draft.steps.length > 0) {
    definition.steps = draft.steps.map(buildStepRecord);
  }
  return {
    id: draft.id.trim(),
    version: draft.version.trim() || "1.0.0",
    definition,
    intent_tags: draft.tagsText
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean),
  };
}

export function validateWorkflowDraft(draft: WorkflowDraft): string[] {
  const errors: string[] = [...draft.preservationErrors];
  if (!draft.id.trim()) errors.push("Workflow id is required.");
  const ids = draft.steps.map((step) => step.id.trim());
  const idSet = new Set(ids);
  const stepById = new Map(draft.steps.map((step) => [step.id.trim(), step]));
  const loopBodies = new Map(
    draft.steps
      .filter((step) => step.action === "flow.loop")
      .map((step) => [step.id.trim(), new Set(loopBodyStepIds(draft.steps, step.id.trim()))]),
  );
  if (ids.some((id) => !id)) errors.push("Every step needs an id.");
  if (idSet.size !== ids.length) errors.push("Step ids must be unique.");
  if (loopBodies.size > 0 && ids.some((id) => LOOP_CLONE_ID.test(id))) {
    errors.push("Step ids ending __<number> are reserved for loop iterations.");
  }

  for (const step of draft.steps) {
    const id = step.id.trim() || "Unnamed step";
    if (!step.action.trim()) errors.push(`${id} needs a governed action.`);
    const limitation = workflowActionLimitation(step.action);
    const existingAction = typeof step.baseRecord.action === "string"
      ? step.baseRecord.action
      : "";
    if (limitation && existingAction !== step.action) {
      errors.push(`${id} cannot author ${step.action} in Worker. ${limitation}`);
    }
    const originalBranch = typeof step.baseRecord.branch === "string"
      ? step.baseRecord.branch
      : "";
    if (
      step.branchArm
      && !["true", "false"].includes(step.branchArm)
      && step.branchArm !== originalBranch
    ) {
      errors.push(`${id} branch arm must be true, false, or always.`);
    }
    const missing = step.parents.filter((parent) => !idSet.has(parent));
    if (missing.length) errors.push(`${id} names missing parent ${missing.join(", ")}.`);
    if (step.parents.includes(step.id.trim())) errors.push(`${id} cannot depend on itself.`);
    let params: Record<string, unknown> | null = null;
    try {
      params = parseParams(step.paramsText);
    } catch {
      errors.push(`${id} parameters must be a JSON object.`);
    }
    let bindings: Record<string, unknown> | null = null;
    try {
      bindings = parseLoopBindings(step.loopBindingsText);
    } catch {
      errors.push(`${id} loop bindings must be a JSON object.`);
    }
    const ancestors = ancestorStepIds(step.id.trim(), stepById);
    const ancestorLoops = [...ancestors].filter(
      (ancestor) => stepById.get(ancestor)?.action === "flow.loop",
    );
    if (step.action === "flow.loop") {
      if (ancestorLoops.length > 0) {
        errors.push(`${id} cannot nest a loop inside another loop body.`);
      }
      if (params) {
        const hasItems = Object.prototype.hasOwnProperty.call(params, "items");
        const hasItemsFrom = Object.prototype.hasOwnProperty.call(params, "items_from");
        if (hasItems === hasItemsFrom) {
          errors.push(`${id} needs exactly one of items or items_from.`);
        } else if (hasItems && !Array.isArray(params.items)) {
          errors.push(`${id} items must be a JSON array.`);
        } else if (
          hasItems
          && new TextEncoder().encode(
            JSON.stringify((params.items as unknown[]).slice(0, LOOP_MAX_ITEMS)),
          ).byteLength > LOOP_MAX_BOUND_BYTES
        ) {
          errors.push(
            `${id} first ${LOOP_MAX_ITEMS} items exceed the 256 KiB loop payload limit.`,
          );
        } else if (hasItemsFrom) {
          const sourceStep = loopItemsSourceStep(params.items_from);
          if (!sourceStep) {
            errors.push(`${id} items_from must be a $step.output reference.`);
          } else if (!ancestors.has(sourceStep)) {
            errors.push(`${id} items_from must reference an ancestor step.`);
          }
        }
      }
    }
    if (bindings && Object.keys(bindings).length > 0) {
      const containingLoops = [...loopBodies].filter(
        ([, body]) => body.has(step.id.trim()),
      );
      if (containingLoops.length !== 1) {
        errors.push(`${id} loop bindings require exactly one enclosing loop body.`);
      }
      if (Object.keys(bindings).length > LOOP_MAX_BINDINGS) {
        errors.push(`${id} has more than ${LOOP_MAX_BINDINGS} loop bindings.`);
      }
      for (const [target, source] of Object.entries(bindings)) {
        if (!LOOP_BINDING_KEY.test(target)) {
          errors.push(`${id} loop binding targets must be simple parameter names.`);
        }
        if (typeof source !== "string" || !LOOP_BINDING_SOURCES.has(source)) {
          errors.push(`${id} loop binding sources must be item or index.`);
        }
        if (params && !Object.prototype.hasOwnProperty.call(params, target)) {
          errors.push(`${id} loop binding target ${target} must already exist in parameters.`);
        }
      }
    }
  }
  if (ids.every(Boolean) && hasCycle(draft.steps)) {
    errors.push("The dependency graph contains a cycle.");
  }
  return [...new Set(errors)];
}

export function nextStepId(steps: WorkflowStepDraft[]): string {
  const ids = new Set(steps.map((step) => step.id));
  let index = steps.length + 1;
  while (ids.has(`step-${index}`)) index += 1;
  return `step-${index}`;
}

export function workflowActionLimitation(action: string): string | null {
  if (action === "code.run") {
    return "The kernel records the script intent with executed=false because no code sandbox is configured.";
  }
  return null;
}

export function loopBodyStepIds(
  steps: WorkflowStepDraft[],
  loopId: string,
): string[] {
  const byId = new Map(steps.map((step) => [step.id.trim(), step]));
  if (!byId.has(loopId)) return [];
  const children = new Map<string, string[]>(
    steps.map((step) => [step.id.trim(), []]),
  );
  for (const step of steps) {
    for (const parent of step.parents) {
      children.get(parent)?.push(step.id.trim());
    }
  }
  const body: string[] = [];
  const frontier = [...(children.get(loopId) ?? [])];
  while (frontier.length > 0) {
    const candidate = frontier.shift()!;
    if (body.includes(candidate)) continue;
    const parents = byId.get(candidate)?.parents ?? [];
    if (parents.every((parent) => parent === loopId || body.includes(parent))) {
      body.push(candidate);
      frontier.push(...(children.get(candidate) ?? []));
    }
  }
  return body;
}

export function isPreservedUnsupportedStep(step: WorkflowStepDraft): boolean {
  const originalAction = typeof step.baseRecord.action === "string"
    ? step.baseRecord.action
    : "";
  return UNSUPPORTED_WORKFLOW_ACTIONS.has(originalAction);
}

function buildStepRecord(step: WorkflowStepDraft): WorkflowStepDefinition {
  const record = { ...step.baseRecord };
  const isNew = typeof step.baseRecord.id !== "string"
    || typeof step.baseRecord.action !== "string";

  if (isNew || step.id !== step.baseRecord.id) record.id = step.id.trim();
  if (isNew || step.action !== step.baseRecord.action) {
    record.action = step.action.trim();
  }

  const originalParents = stringArray(step.baseRecord.parents);
  if (isNew || !arraysEqual(step.parents, originalParents ?? [])) {
    record.parents = [...step.parents];
  }

  const originalDescription = typeof step.baseRecord.description === "string"
    ? step.baseRecord.description
    : "";
  if (isNew || step.description !== originalDescription) {
    const description = step.description.trim();
    if (description) record.description = description;
    else delete record.description;
  }

  const params = parseParams(step.paramsText);
  const originalParams = recordObject(step.baseRecord[step.parameterField]) ?? {};
  if (isNew || !jsonEqual(params, originalParams)) {
    if (Object.keys(params).length > 0) record[step.parameterField] = params;
    else delete record[step.parameterField];
  }

  const loopBindings = parseLoopBindings(step.loopBindingsText);
  const originalLoopBindings = recordObject(step.baseRecord.loop_bindings) ?? {};
  if (isNew || !jsonEqual(loopBindings, originalLoopBindings)) {
    if (Object.keys(loopBindings).length > 0) {
      record.loop_bindings = loopBindings;
    } else {
      delete record.loop_bindings;
    }
  }

  const originalBranch = typeof step.baseRecord.branch === "string"
    ? step.baseRecord.branch
    : "";
  if (isNew || step.branchArm !== originalBranch) {
    if (step.branchArm) record.branch = step.branchArm;
    else delete record.branch;
  }
  return record as WorkflowStepDefinition;
}

function extractStepRecords(
  definition: Record<string, unknown>,
): { steps: WorkflowStepDraft[]; errors: string[] } {
  const value = definition.steps;
  if (value === undefined) return { steps: [], errors: [] };
  if (!Array.isArray(value)) {
    return {
      steps: [],
      errors: [
        "This definition has a non-array steps field. Worker will not overwrite it.",
      ],
    };
  }
  const steps: WorkflowStepDraft[] = [];
  const errors: string[] = [];
  value.forEach((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      errors.push(
        `Step ${index + 1} is not an object. Worker will not overwrite this definition.`,
      );
      return;
    }
    const row = item as Record<string, unknown>;
    if (typeof row.id !== "string" || typeof row.action !== "string") {
      errors.push(
        `Step ${index + 1} lacks a string id or action. Worker will not overwrite this definition.`,
      );
      return;
    }
    const parents = stringArray(row.parents);
    if (row.parents !== undefined && parents === null) {
      errors.push(
        `${row.id} has a parents value Worker cannot safely edit. The definition is read-only here.`,
      );
    }
    if (row.description !== undefined && typeof row.description !== "string") {
      errors.push(
        `${row.id} has a non-text description Worker cannot safely edit. The definition is read-only here.`,
      );
    }
    if (row.branch !== undefined && typeof row.branch !== "string") {
      errors.push(
        `${row.id} has a non-text branch arm Worker cannot safely edit. The definition is read-only here.`,
      );
    }
    for (const field of ["params", "with"] as const) {
      if (row[field] !== undefined && recordObject(row[field]) === null) {
        errors.push(
          `${row.id} has non-object ${field} parameters Worker cannot safely edit. The definition is read-only here.`,
        );
      }
    }
    if (
      row.loop_bindings !== undefined
      && recordObject(row.loop_bindings) === null
    ) {
      errors.push(
        `${row.id} has non-object loop bindings Worker cannot safely edit. The definition is read-only here.`,
      );
    }
    const parameterField = selectParameterField(row);
    const rawParams = row[parameterField];
    const params = recordObject(rawParams);
    steps.push({
      id: row.id,
      action: row.action,
      parents: parents ?? [],
      description: typeof row.description === "string" ? row.description : "",
      paramsText: JSON.stringify(params ?? {}, null, 2),
      loopBindingsText: JSON.stringify(
        recordObject(row.loop_bindings) ?? {},
        null,
        2,
      ),
      branchArm: typeof row.branch === "string" ? row.branch : "",
      parameterField,
      baseRecord: { ...row },
    });
  });
  return { steps, errors };
}

function parseParams(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value.trim() || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new TypeError("parameters are not an object");
  }
  return parsed as Record<string, unknown>;
}

function parseLoopBindings(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value.trim() || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new TypeError("loop bindings are not an object");
  }
  return parsed as Record<string, unknown>;
}

function ancestorStepIds(
  stepId: string,
  byId: Map<string, WorkflowStepDraft>,
  visiting = new Set<string>(),
): Set<string> {
  if (visiting.has(stepId)) return new Set();
  const nextVisiting = new Set(visiting).add(stepId);
  const found = new Set<string>();
  for (const parent of byId.get(stepId)?.parents ?? []) {
    if (!byId.has(parent)) continue;
    found.add(parent);
    for (const ancestor of ancestorStepIds(parent, byId, nextVisiting)) {
      found.add(ancestor);
    }
  }
  return found;
}

function loopItemsSourceStep(value: unknown): string | null {
  if (typeof value !== "string" || !value.startsWith("$")) return null;
  const path = value.slice(1).split(".");
  if (path.length < 2 || !path[0] || path[1] !== "output") return null;
  if (path.some((part) => !part)) return null;
  return path[0];
}

function selectParameterField(
  row: Record<string, unknown>,
): "params" | "with" {
  const params = recordObject(row.params);
  const withParams = recordObject(row.with);
  // Mirror the interpreter's `params or with or {}` precedence.
  if (params && Object.keys(params).length > 0) return "params";
  if (withParams) return "with";
  return "params";
}

function recordObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringArray(value: unknown): string[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    return null;
  }
  return [...value] as string[];
}

function arraysEqual(left: string[], right: string[]): boolean {
  return left.length === right.length
    && left.every((value, index) => value === right[index]);
}

function jsonEqual(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function hasCycle(steps: WorkflowStepDraft[]): boolean {
  const parents = new Map(steps.map((step) => [step.id.trim(), step.parents]));
  const visiting = new Set<string>();
  const visited = new Set<string>();
  function visit(id: string): boolean {
    if (visiting.has(id)) return true;
    if (visited.has(id)) return false;
    visiting.add(id);
    for (const parent of parents.get(id) ?? []) {
      if (parents.has(parent) && visit(parent)) return true;
    }
    visiting.delete(id);
    visited.add(id);
    return false;
  }
  return [...parents.keys()].some(visit);
}
