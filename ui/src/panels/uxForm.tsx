/* Form-primitive register (docs/design/ui-patterns.md section 9): the seat
 * that owns the FORM vocabulary. N1 Switch (+ useSavedWisp), P3 SegmentedV2,
 * N2 CardSelect, N3 ChipPicker (amendment 12 disabled-with-reason variant),
 * N4 EntityPicker, N5 ScopeBuilder, N6 Stepper, N9 JsonDisclosure,
 * N17 OrderedPicker and the P9 SchemaFormV2 upgrade.
 *
 * Contracts every component here honours: presentational only (no fetching,
 * no polling; values flow in via props, out via onChange); semantic --color-*
 * tokens only (the ux- append block in styles.css); the global focus-visible
 * ring and reduce-motion rules are relied on, never restyled; keyboard maps
 * follow P36 (arrows inside pickers, roving tabindex so Tab leaves a widget
 * in one step, Backspace-on-empty removes the last chip). */

export { nextEnabled } from "@/panels/uxForm/nextEnabled";
export { Switch, useSavedWisp } from "@/panels/uxForm/Switch";
export { SegmentedV2 } from "@/panels/uxForm/SegmentedV2";
export { CardSelect, type CardOption } from "@/panels/uxForm/CardSelect";
export { ChipPicker, type ChipOption } from "@/panels/uxForm/ChipPicker";
export { EntityPicker, type EntityItem, type EntityGroup } from "@/panels/uxForm/EntityPicker";
export { ScopeBuilder, type ScopeVerb } from "@/panels/uxForm/ScopeBuilder";
export { grantMatches, scopeMatches } from "@/panels/uxForm/scopeMatches";
export { Stepper } from "@/panels/uxForm/Stepper";
export { JsonDisclosure } from "@/panels/uxForm/JsonDisclosure";
export { OrderedPicker } from "@/panels/uxForm/OrderedPicker";
export { SchemaFormV2, schemaDefaults, type PropSpec, type FieldEditorProps } from "@/panels/uxForm/SchemaFormV2";
