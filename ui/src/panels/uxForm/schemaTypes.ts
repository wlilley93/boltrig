import type { Dispatch, ReactNode, SetStateAction } from "react";

export interface PropSpec {
  type?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  format?: string;
  items?: PropSpec;
  properties?: Record<string, PropSpec>;
  required?: string[];
  additionalProperties?: unknown;
  // Optional per-property custom control (the admin section flagships). When set,
  // SchemaFormV2 renders this component INSTEAD of deriving a control from the
  // type, so a shape the generic engine cannot express typedly (a role-mapping
  // row, a key/value map) still renders as structured controls rather than a JSON
  // blob. Rendered as a component (JSX element) so it may hold its own row-draft
  // state. The schema stays a client-side descriptor; schemaDefaults ignores this.
  editor?: (props: FieldEditorProps) => ReactNode;
}

// The contract a custom section editor (ui/src/panels/admin/editors/*) is handed
// by SchemaFormV2: the current value + a commit fn (undefined clears the key),
// plus the field framing (label, required, error) so the editor can wrap itself
// in a Field / inset consistently with the generic controls around it.
export interface FieldEditorProps {
  value: unknown;
  onChange: (v: unknown) => void;
  spec: PropSpec;
  path: string;
  label: string;
  required: boolean;
  error?: string;
}

export interface SchemaFieldContext {
  path: string;
  fieldKey: string;
  spec: PropSpec;
  value: unknown;
  onChange: (v: unknown) => void;
  required: boolean;
  depth: number;
  errors?: Record<string, string>;
  drafts: Record<string, string>;
  setDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  jsonErrs: Record<string, string>;
  setJsonErrs: Dispatch<SetStateAction<Record<string, string>>>;
  clearJsonErr: (path: string) => void;
}
