const UNSUPPORTED_SCHEMA_KEYS = [
  "$ref",
  "allOf",
  "anyOf",
  "oneOf",
  "not",
  "if",
  "then",
  "else",
  "patternProperties",
  "dependentSchemas",
  "unevaluatedProperties",
  "$defs",
  "definitions",
  "const",
  "multipleOf",
  "exclusiveMinimum",
  "exclusiveMaximum",
  "minProperties",
  "maxProperties",
  "propertyNames",
  "prefixItems",
  "contains",
  "minContains",
  "maxContains",
  "uniqueItems",
] as const;

const RESERVED_PROPERTY_NAMES = new Set(["__proto__", "prototype", "constructor"]);
const SAFE_STRING_FORMATS = new Set(["date", "email", "uri"]);
const SAFE_SCALAR_TYPES = new Set(["string", "integer", "number", "boolean"]);
const MAX_FIELDS = 100;
const MAX_DEPTH = 5;
const MAX_OUTPUT_ITEMS = 100;
const MAX_OUTPUT_STRING = 10_000;

type JsonRecord = Record<string, unknown>;
type ScalarType = "string" | "integer" | "number" | "boolean";

export type CapabilityFieldKind =
  | ScalarType
  | "string_array"
  | "integer_array"
  | "number_array"
  | "boolean_array";

export interface CapabilityFormField {
  id: string;
  path: string[];
  label: string;
  kind: CapabilityFieldKind;
  required: boolean;
  description?: string;
  enum?: Array<string | number | boolean>;
  minimum?: number;
  maximum?: number;
  min_length?: number;
  max_length?: number;
  min_items?: number;
  max_items?: number;
  pattern?: string;
  format?: "date" | "email" | "uri";
}

export type CapabilityFormContract =
  | {
      status: "ready";
      fields: CapabilityFormField[];
      required_object_paths: string[][];
    }
  | { status: "unavailable"; reason: string };

export type CapabilityParamsResult =
  | { status: "ready"; params: Record<string, unknown> }
  | { status: "invalid"; field_errors: Record<string, string> };

export type CapabilityOutputProjection =
  | { status: "visible"; value: unknown }
  | { status: "hidden"; reason: string };

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function pointer(path: string[]): string {
  return `/${path.map((part) => part.replaceAll("~", "~0").replaceAll("/", "~1")).join("/")}`;
}

function humanize(value: string): string {
  const spaced = value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replaceAll(/[-_.]+/g, " ")
    .trim();
  return spaced ? spaced[0]!.toUpperCase() + spaced.slice(1) : value;
}

function normalizedName(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replaceAll(/[^A-Za-z0-9]+/g, "_")
    .replaceAll(/^_+|_+$/g, "")
    .toLowerCase();
}

function isSecretShapedName(value: string): boolean {
  const name = normalizedName(value);
  if (!name) return false;
  if (
    name.endsWith("_ref")
    || name.endsWith("_id")
    || name.endsWith("_kind")
    || name.endsWith("_store")
    || name.endsWith("_configured")
    || name.endsWith("_limit")
    || name.endsWith("_count")
    || name.endsWith("_usage")
  ) {
    return false;
  }
  if (
    name === "key"
    || name === "token"
    || name === "secret"
    || name === "credential"
    || name === "cookie"
    || name === "password"
    || name === "passphrase"
    || name === "authorization"
    || name === "bearer"
  ) {
    return true;
  }
  return name.endsWith("_key")
    || name.endsWith("_token")
    || name.endsWith("_secret")
    || name.endsWith("_password")
    || /(^|_)(credential|cookie|api_key|access_token|refresh_token|session_token|private_key|client_secret|password|passphrase|secret|bearer|authorization)(_|$)/.test(name);
}

function schemaAnnotationIsSecret(schema: JsonRecord): boolean {
  const format = typeof schema.format === "string" ? schema.format.toLowerCase() : "";
  return schema.writeOnly === true
    || format === "password"
    || format === "binary"
    || schema.contentEncoding === "base64"
    || schema.contentMediaType !== undefined;
}

function unsupportedKeyword(schema: JsonRecord): string | null {
  for (const key of UNSUPPORTED_SCHEMA_KEYS) {
    if (key in schema) return key;
  }
  return null;
}

function unavailable(path: string[], reason: string): CapabilityFormContract {
  const location = path.length ? `Field ${path.join(".")}: ` : "";
  return { status: "unavailable", reason: `${location}${reason}` };
}

function scalarType(schema: JsonRecord): ScalarType | null {
  const declared = schema.type;
  if (typeof declared === "string") {
    return SAFE_SCALAR_TYPES.has(declared) ? declared as ScalarType : null;
  }
  if (Array.isArray(declared)) {
    const nonNull = declared.filter((item) => item !== "null");
    if (
      nonNull.length === 1
      && typeof nonNull[0] === "string"
      && SAFE_SCALAR_TYPES.has(nonNull[0])
      && declared.includes("null")
    ) {
      return nonNull[0] as ScalarType;
    }
  }
  return null;
}

function numericKeyword(schema: JsonRecord, key: string): number | undefined {
  const value = schema[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function invalidBound(
  schema: JsonRecord,
  key: string,
  options: { integer?: boolean } = {},
): boolean {
  const integer = options.integer ?? false;
  if (!(key in schema)) return false;
  const value = schema[key];
  return typeof value !== "number"
    || !Number.isFinite(value)
    || (integer && (!Number.isInteger(value) || value < 0));
}

function compileScalarField(
  propertyName: string,
  path: string[],
  schema: JsonRecord,
  required: boolean,
): CapabilityFormField | CapabilityFormContract {
  if (schemaAnnotationIsSecret(schema) || schema.readOnly === true) {
    return unavailable(path, "secret or binary fields require a purpose-built secure-input surface.");
  }
  const type = scalarType(schema);
  if (type === null) {
    return unavailable(path, "only one scalar JSON type (optionally nullable) is supported.");
  }
  if (schema.enum !== undefined) {
    if (
      !Array.isArray(schema.enum)
      || schema.enum.length === 0
      || schema.enum.some((item) => {
        if (type === "string") return typeof item !== "string";
        if (type === "boolean") return typeof item !== "boolean";
        return typeof item !== "number" || !Number.isFinite(item)
          || (type === "integer" && !Number.isInteger(item));
      })
    ) {
      return unavailable(path, "enum values do not match the declared scalar type.");
    }
    if (type === "string" && schema.enum.includes("")) {
      return unavailable(path, "empty-string enum values are not supported by the safe form.");
    }
  }
  const format = typeof schema.format === "string" ? schema.format : undefined;
  if (format !== undefined && (type !== "string" || !SAFE_STRING_FORMATS.has(format))) {
    return unavailable(path, `string format ${format} is not supported by the safe form.`);
  }
  if (schema.pattern !== undefined) {
    if (type !== "string" || typeof schema.pattern !== "string") {
      return unavailable(path, "pattern must be a string constraint on a string field.");
    }
    try {
      new RegExp(schema.pattern);
    } catch {
      return unavailable(path, "pattern is not a valid browser regular expression.");
    }
  }
  if (
    invalidBound(schema, "minimum")
    || invalidBound(schema, "maximum")
    || invalidBound(schema, "minLength", { integer: true })
    || invalidBound(schema, "maxLength", { integer: true })
  ) {
    return unavailable(path, "schema bounds must be finite, non-negative integers where required.");
  }
  const minimum = numericKeyword(schema, "minimum");
  const maximum = numericKeyword(schema, "maximum");
  const minLength = numericKeyword(schema, "minLength");
  const maxLength = numericKeyword(schema, "maxLength");
  if (
    (minimum !== undefined && maximum !== undefined && minimum > maximum)
    || (minLength !== undefined && maxLength !== undefined && minLength > maxLength)
  ) {
    return unavailable(path, "minimum bounds cannot exceed maximum bounds.");
  }
  return {
    id: pointer(path),
    path,
    label: typeof schema.title === "string" && schema.title.trim()
      ? schema.title.trim()
      : humanize(propertyName),
    kind: type,
    required,
    description: typeof schema.description === "string" ? schema.description : undefined,
    enum: schema.enum as Array<string | number | boolean> | undefined,
    minimum,
    maximum,
    min_length: minLength,
    max_length: maxLength,
    pattern: typeof schema.pattern === "string" ? schema.pattern : undefined,
    format: format as "date" | "email" | "uri" | undefined,
  };
}

interface CompileState {
  fields: CapabilityFormField[];
  requiredObjects: string[][];
}

function compileObject(
  schema: JsonRecord,
  path: string[],
  required: boolean,
  state: CompileState,
): CapabilityFormContract | null {
  if (path.length > MAX_DEPTH) return unavailable(path, `nesting exceeds ${MAX_DEPTH} levels.`);
  const keyword = unsupportedKeyword(schema);
  if (keyword !== null) return unavailable(path, `${keyword} is not supported by the safe form.`);
  if (schemaAnnotationIsSecret(schema) || schema.readOnly === true) {
    return unavailable(path, "secret or binary annotations cannot be rendered in the generic runner.");
  }
  if (schema.additionalProperties !== undefined && schema.additionalProperties !== false) {
    return unavailable(path, "open-ended additional properties require a purpose-built surface.");
  }
  const declaredType = schema.type;
  if (
    declaredType !== undefined
    && declaredType !== "object"
    && !(Array.isArray(declaredType)
      && declaredType.includes("object")
      && declaredType.includes("null")
      && declaredType.filter((item) => item !== "null").length === 1)
  ) {
    return unavailable(path, "an object schema is required.");
  }
  const requiredNames = schema.required === undefined ? [] : schema.required;
  if (
    !Array.isArray(requiredNames)
    || requiredNames.some((item) => typeof item !== "string")
  ) {
    return unavailable(path, "required must be an array of declared property names.");
  }
  const properties = schema.properties;
  if (properties === undefined) {
    if (requiredNames.length > 0) {
      return unavailable(path, "required names cannot be satisfied without declared properties.");
    }
    if (Object.keys(schema).length === 0 || declaredType === "object") {
      if (required && path.length) state.requiredObjects.push(path);
      return null;
    }
    return unavailable(path, "the object has no declared properties.");
  }
  if (!isRecord(properties)) return unavailable(path, "properties must be an object.");
  const requiredSet = new Set(requiredNames as string[]);
  for (const name of requiredSet) {
    if (!(name in properties)) return unavailable(path, `required property ${name} is not declared.`);
  }
  if (required && path.length) state.requiredObjects.push(path);

  for (const [propertyName, rawPropertySchema] of Object.entries(properties)) {
    const fieldPath = [...path, propertyName];
    if (RESERVED_PROPERTY_NAMES.has(propertyName)) {
      return unavailable(fieldPath, "this reserved property name cannot be authored safely.");
    }
    if (isSecretShapedName(propertyName)) {
      return unavailable(fieldPath, "secret-shaped fields require a purpose-built secure-input surface.");
    }
    if (!isRecord(rawPropertySchema)) {
      return unavailable(fieldPath, "the field schema must be an object.");
    }
    const fieldKeyword = unsupportedKeyword(rawPropertySchema);
    if (fieldKeyword !== null) {
      return unavailable(fieldPath, `${fieldKeyword} is not supported by the safe form.`);
    }
    if (schemaAnnotationIsSecret(rawPropertySchema) || rawPropertySchema.readOnly === true) {
      return unavailable(fieldPath, "secret or binary fields require a purpose-built secure-input surface.");
    }
    const propertyRequired = requiredSet.has(propertyName);
    const propertyType = rawPropertySchema.type;
    const objectLike = propertyType === "object"
      || rawPropertySchema.properties !== undefined
      || (Array.isArray(propertyType) && propertyType.includes("object"));
    if (objectLike) {
      const nested = compileObject(
        rawPropertySchema,
        fieldPath,
        propertyRequired,
        state,
      );
      if (nested !== null) return nested;
      continue;
    }
    if (propertyType === "array") {
      if (!isRecord(rawPropertySchema.items)) {
        return unavailable(fieldPath, "arrays need one declared primitive item schema.");
      }
      const itemType = scalarType(rawPropertySchema.items);
      if (itemType === null) {
        return unavailable(fieldPath, "only arrays of primitive values are supported.");
      }
      if (
        invalidBound(rawPropertySchema, "minItems", { integer: true })
        || invalidBound(rawPropertySchema, "maxItems", { integer: true })
      ) {
        return unavailable(fieldPath, "array bounds must be non-negative integers.");
      }
      const minItems = numericKeyword(rawPropertySchema, "minItems");
      const maxItems = numericKeyword(rawPropertySchema, "maxItems");
      if (minItems !== undefined && maxItems !== undefined && minItems > maxItems) {
        return unavailable(fieldPath, "minimum item count cannot exceed maximum item count.");
      }
      const itemField = compileScalarField(
        propertyName,
        fieldPath,
        rawPropertySchema.items,
        propertyRequired,
      );
      if ("status" in itemField) return itemField;
      state.fields.push({
        ...itemField,
        kind: `${itemType}_array`,
        description: typeof rawPropertySchema.description === "string"
          ? rawPropertySchema.description
          : itemField.description,
        min_items: minItems,
        max_items: maxItems,
      });
    } else {
      const field = compileScalarField(
        propertyName,
        fieldPath,
        rawPropertySchema,
        propertyRequired,
      );
      if ("status" in field) return field;
      state.fields.push(field);
    }
    if (state.fields.length > MAX_FIELDS) {
      return unavailable([], `the schema exceeds the ${MAX_FIELDS}-field safe form limit.`);
    }
  }
  return null;
}

export function compileCapabilityForm(schema: unknown): CapabilityFormContract {
  if (!isRecord(schema)) {
    return { status: "unavailable", reason: "The registry did not provide an object input schema." };
  }
  const state: CompileState = { fields: [], requiredObjects: [] };
  const failure = compileObject(schema, [], false, state);
  if (failure !== null) return failure;
  return {
    status: "ready",
    fields: state.fields,
    required_object_paths: state.requiredObjects,
  };
}

function setPath(target: Record<string, unknown>, path: string[], value: unknown): void {
  let cursor = target;
  for (const [index, part] of path.entries()) {
    if (index === path.length - 1) {
      cursor[part] = value;
      return;
    }
    const next = cursor[part];
    if (!isRecord(next)) cursor[part] = {};
    cursor = cursor[part] as Record<string, unknown>;
  }
}

type ScalarParseResult =
  | { ok: true; value: string | number | boolean }
  | { ok: false; error: string };

function parseScalar(field: CapabilityFormField, value: string): ScalarParseResult {
  const scalar = field.kind.replace("_array", "") as ScalarType;
  if (scalar === "string") {
    if (field.min_length !== undefined && value.length < field.min_length) {
      return { ok: false, error: `Enter at least ${field.min_length} characters.` };
    }
    if (field.max_length !== undefined && value.length > field.max_length) {
      return { ok: false, error: `Enter at most ${field.max_length} characters.` };
    }
    if (field.pattern !== undefined && !new RegExp(field.pattern).test(value)) {
      return { ok: false, error: "The value does not match the required pattern." };
    }
    if (field.format === "email" && !/^[^@\s]+@[^@\s]+$/.test(value)) {
      return { ok: false, error: "Enter a valid email address." };
    }
    if (field.format === "date") {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
      const date = match
        ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
        : null;
      if (
        match === null
        || date === null
        || date.getUTCFullYear() !== Number(match[1])
        || date.getUTCMonth() !== Number(match[2]) - 1
        || date.getUTCDate() !== Number(match[3])
      ) {
        return { ok: false, error: "Enter a valid calendar date." };
      }
    }
    if (field.format === "uri") {
      try {
        new URL(value);
      } catch {
        return { ok: false, error: "Enter a valid absolute URI." };
      }
    }
    return { ok: true, value };
  }
  if (scalar === "boolean") {
    if (value !== "true" && value !== "false") {
      return { ok: false, error: "Choose true or false." };
    }
    return { ok: true, value: value === "true" };
  }
  if (scalar === "integer" && !/^-?(0|[1-9]\d*)$/.test(value)) {
    return { ok: false, error: "Enter a whole number." };
  }
  const number = Number(value);
  if (!Number.isFinite(number)) return { ok: false, error: "Enter a finite number." };
  if (field.minimum !== undefined && number < field.minimum) {
    return { ok: false, error: `Enter a value of at least ${field.minimum}.` };
  }
  if (field.maximum !== undefined && number > field.maximum) {
    return { ok: false, error: `Enter a value of at most ${field.maximum}.` };
  }
  return { ok: true, value: number };
}

export function buildCapabilityParams(
  contract: CapabilityFormContract,
  values: Record<string, string>,
): CapabilityParamsResult {
  if (contract.status !== "ready") {
    return { status: "invalid", field_errors: { _schema: contract.reason } };
  }
  const params: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const objectPath of contract.required_object_paths) setPath(params, objectPath, {});

  for (const field of contract.fields) {
    const raw = values[field.id] ?? "";
    if (raw === "") {
      if (field.required) errors[field.id] = "This field is required.";
      continue;
    }
    if (field.kind.endsWith("_array")) {
      const items = raw.split(/\r?\n/).filter((item) => item.length > 0);
      if (field.min_items !== undefined && items.length < field.min_items) {
        errors[field.id] = `Enter at least ${field.min_items} items, one per line.`;
        continue;
      }
      if (field.max_items !== undefined && items.length > field.max_items) {
        errors[field.id] = `Enter at most ${field.max_items} items, one per line.`;
        continue;
      }
      const parsed: unknown[] = [];
      for (const item of items) {
        const result = parseScalar(field, item);
        if (!result.ok) {
          errors[field.id] = result.error;
          break;
        }
        if (
          field.enum !== undefined
          && !field.enum.some((candidate) => Object.is(candidate, result.value))
        ) {
          errors[field.id] = "Choose only declared values.";
          break;
        }
        parsed.push(result.value);
      }
      if (!(field.id in errors)) setPath(params, field.path, parsed);
      continue;
    }
    const result = parseScalar(field, raw);
    if (!result.ok) {
      errors[field.id] = result.error;
      continue;
    }
    if (
      field.enum !== undefined
      && !field.enum.some((candidate) => Object.is(candidate, result.value))
    ) {
      errors[field.id] = "Choose a declared value.";
      continue;
    }
    setPath(params, field.path, result.value);
  }
  return Object.keys(errors).length
    ? { status: "invalid", field_errors: errors }
    : { status: "ready", params };
}

function projectValue(
  schema: JsonRecord,
  value: unknown,
  path: string[],
  depth: number,
): CapabilityOutputProjection {
  if (depth > MAX_DEPTH) return { status: "hidden", reason: "Output exceeds the safe display depth." };
  const keyword = unsupportedKeyword(schema);
  if (keyword !== null) {
    return { status: "hidden", reason: `Output schema uses unsupported ${keyword}.` };
  }
  if (schemaAnnotationIsSecret(schema)) {
    return { status: "hidden", reason: "Output schema contains secret or binary data." };
  }
  const type = schema.type;
  const objectLike = type === "object" || schema.properties !== undefined;
  if (objectLike) {
    if (!isRecord(value) || !isRecord(schema.properties)) {
      return { status: "hidden", reason: "Output did not match its closed object schema." };
    }
    const projected: Record<string, unknown> = {};
    for (const [name, childSchema] of Object.entries(schema.properties)) {
      if (
        RESERVED_PROPERTY_NAMES.has(name)
        || isSecretShapedName(name)
        || !isRecord(childSchema)
      ) {
        return { status: "hidden", reason: "Output schema contains an unsafe field." };
      }
      if (!(name in value)) continue;
      const child = projectValue(childSchema, value[name], [...path, name], depth + 1);
      if (child.status === "hidden") return child;
      projected[name] = child.value;
    }
    return { status: "visible", value: projected };
  }
  if (type === "array") {
    if (!Array.isArray(value) || !isRecord(schema.items)) {
      return { status: "hidden", reason: "Output did not match its declared array schema." };
    }
    if (value.length > MAX_OUTPUT_ITEMS) {
      return { status: "hidden", reason: `Output exceeds the ${MAX_OUTPUT_ITEMS}-item safe display limit.` };
    }
    const projected: unknown[] = [];
    for (const item of value) {
      const child = projectValue(schema.items, item, path, depth + 1);
      if (child.status === "hidden") return child;
      projected.push(child.value);
    }
    return { status: "visible", value: projected };
  }
  const scalar = scalarType(schema);
  if (scalar === "string") {
    if (typeof value !== "string" || value.length > MAX_OUTPUT_STRING) {
      return { status: "hidden", reason: "Output string is invalid or exceeds the safe display limit." };
    }
    return { status: "visible", value };
  }
  if (scalar === "boolean") {
    return typeof value === "boolean"
      ? { status: "visible", value }
      : { status: "hidden", reason: "Output did not match its boolean schema." };
  }
  if (scalar === "integer") {
    return typeof value === "number" && Number.isInteger(value)
      ? { status: "visible", value }
      : { status: "hidden", reason: "Output did not match its integer schema." };
  }
  if (scalar === "number") {
    return typeof value === "number" && Number.isFinite(value)
      ? { status: "visible", value }
      : { status: "hidden", reason: "Output did not match its number schema." };
  }
  return { status: "hidden", reason: `Output schema at ${path.join(".") || "root"} is not safe to display generically.` };
}

export function projectCapabilityOutput(
  schema: unknown,
  output: unknown,
): CapabilityOutputProjection {
  if (!isRecord(schema) || Object.keys(schema).length === 0) {
    return {
      status: "hidden",
      reason: "The capability has no closed output schema, so its payload is not rendered here.",
    };
  }
  return projectValue(schema, output, [], 0);
}
