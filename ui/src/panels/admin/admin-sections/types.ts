// The AdminSection descriptor names a manifest section an org-admin may edit and
// gives it a typed SchemaFormV2 schema so it renders as structured controls.
// The schema is an allowlist of editable fields; unknown keys in the loaded
// section value are preserved untouched by the form-value helpers.
export interface AdminSection {
  key: string;
  label: string;
  blurb: string;
  // SchemaFormV2 schema (the JSON-schema subset it renders). Only these keys are
  // editable; everything else in the loaded section value is preserved.
  schema: Record<string, unknown>;
  // true when the section value is a top-level array (wrapped under `items`).
  list?: boolean;
  // a one-line note about operator-only keys intentionally kept out of the form.
  preserves?: string;
}
