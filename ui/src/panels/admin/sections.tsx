// The admin console section register (Beat 5 chunk 3, the settings/admin
// retrofit). The manifest stays the source of truth (C1); this descriptor names
// the manifest sections an org-admin may edit and gives each one a typed
// SchemaFormV2 schema so a section renders as structured controls (switches,
// segmented, steppers, chip pickers), never a raw JSON blob.
//
// Two rails carried here:
//  - Fail-closed partial edit: control.config.upsert REPLACES the whole section
//    value, so a schema is an ALLOWLIST of editable fields, not the full shape.
//    toFormValue seeds the known fields over the loaded value so any key the UI
//    does not expose (operator-only wiring such as the OIDC issuer/audience/JWKS
//    under identity) survives untouched and is sent back on save.
//  - Deploy-time env stays out (ports, secrets, OIDC endpoints, backups): those
//    are operator-only and never appear as a section here.
//
// A section whose manifest value is a top-level LIST (spawn_rules, adapters,
// ephemeral_runtimes) sets list:true; the array is wrapped under `items` so the
// object-shaped SchemaFormV2 can render it as one labelled, validated field
// (fail-closed via onValidity), and fromFormValue unwraps it back to the array.

import type { AdminSection } from "@/panels/admin/admin-sections/types";
import {
  fromFormValue,
  stableKey,
  toFormValue,
} from "@/panels/admin/admin-sections/formValue";
import { governanceSections } from "@/panels/admin/admin-sections/governanceSections";
import { integrationSections } from "@/panels/admin/admin-sections/integrationSections";
import { orgSections } from "@/panels/admin/admin-sections/orgSections";
import { runtimeSections } from "@/panels/admin/admin-sections/runtimeSections";
import { surfaceSections } from "@/panels/admin/admin-sections/surfaceSections";

export type { AdminSection };
export { fromFormValue, stableKey, toFormValue };

export const ADMIN_SECTIONS: ReadonlyArray<AdminSection> = [
  ...orgSections,
  ...integrationSections,
  ...runtimeSections,
  ...governanceSections,
  ...surfaceSections,
];

export const ADMIN_SECTION_OPTIONS = ADMIN_SECTIONS.map((s) => ({
  value: s.key,
  label: s.label,
}));
