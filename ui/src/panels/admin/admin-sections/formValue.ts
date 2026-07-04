// Section value <-> SchemaFormV2 value helpers. These keep the admin section
// register fail-closed: only known fields are seeded/returned, and unknown keys
// in the loaded section value survive untouched.
import { schemaDefaults } from "@/panels/uxForm";
import type { AdminSection } from "./types";

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// Section value (as the server stores it) -> the object SchemaFormV2 edits.
// List sections wrap the array; object sections seed defaults under the loaded
// value so no known field opens blank while unknown keys are preserved.
export function toFormValue(
  section: AdminSection,
  loaded: unknown,
): Record<string, unknown> {
  if (section.list) {
    return { items: Array.isArray(loaded) ? loaded : [] };
  }
  return { ...schemaDefaults(section.schema), ...(isObject(loaded) ? loaded : {}) };
}

// The SchemaFormV2 object -> the section value the server persists. List
// sections unwrap back to the bare array; object sections send the whole object
// (preserved unknown keys included).
export function fromFormValue(section: AdminSection, form: Record<string, unknown>): unknown {
  if (section.list) {
    const items = form.items;
    return Array.isArray(items) ? items : [];
  }
  return form;
}

// A stable structural compare for the dirty check (key order independent enough
// for a form whose keys come from a fixed schema + a preserved loaded object).
export function stableKey(value: unknown): string {
  return JSON.stringify(value);
}
