/* Shared "dreamy UX" primitives.
 *
 * The vocabulary every panel uses to explain itself and guide input: a page
 * intro that states the page's purpose in plain language, fields that carry a
 * label + a hint + an example, structured controls (select / segmented) in
 * place of naked free-text, and calm empty / denied / error states. Components
 * reference the design-system semantic tokens only (see styles.css).
 *
 * This module is a thin barrel: the primitives live one-per-file under ux/ so
 * each file stays under the structural floor. The public surface (every named
 * export below) is unchanged. */

export { PageIntro } from "./ux/PageIntro";
export { Field } from "./ux/Field";
export { Select } from "./ux/Select";
export { InfoCallout } from "./ux/InfoCallout";
export { EmptyState } from "./ux/EmptyState";
export { ErrorState, FetchError } from "./ux/ErrorState";
export { Hint } from "./ux/Hint";
export {
  WORK_STATUS,
  AUDIT_STATUS,
  MEMORY_INGEST_STATUS,
  HITL_TYPE,
  HITL_URGENCY,
  TOOL_STATUS,
  CONSEQUENCE,
  StatusBadge,
  TermTip,
} from "./ux/glossary";
export {
  NOTIFY_EVENT_OPTIONS,
  NOTIFY_CHANNEL_OPTIONS,
  ROLE_OPTIONS,
  ROLE_VALUES,
  TTL_OPTIONS,
  ttlDaysFromSelection,
} from "./ux/options";
export type { Option, Term } from "./ux/types";
