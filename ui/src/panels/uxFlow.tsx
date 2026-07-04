/** Flow primitives (register N10-N16, N18, N19 + GrantList): the save / confirm /
 * pause vocabulary every surface composes. Constraints carried here:
 * - L4: amber (--color-consequence-high) only where the kernel gate is in play
 *   (PendingHumanCard, the governed SaveBar foreshadow, the consequence tone).
 * - P27/P36: arm-confirm swaps in place; disarms on Escape / Cancel / blur-away
 *   / slide navigation; Enter confirms only on the focused confirm button.
 * - AMENDMENTS item 1: approval does not apply the change - PendingHumanCard
 *   re-invokes the same verb + params with approval_id and renders THAT result.
 * - Semantic --color-* tokens only (see the ux- append in styles.css).
 *
 * This barrel preserves the original public API; implementations live in the
 * sibling `uxFlow/` directory.
 */

export { ArmConfirm, useArmConfirm } from "@/panels/uxFlow/armConfirm";
export type { ArmTone, UseArmConfirm } from "@/panels/uxFlow/armConfirm";

export { ByChat } from "@/panels/uxFlow/byChat";
export { CoachMark } from "@/panels/uxFlow/coachMark";
export { DiffView } from "@/panels/uxFlow/diffView";
export { Disclosure } from "@/panels/uxFlow/disclosure";
export { GrantList } from "@/panels/uxFlow/grantList";
export { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
export { SaveBar } from "@/panels/uxFlow/saveBar";
export { SecretOnce } from "@/panels/uxFlow/secretOnce";
export { Skeleton } from "@/panels/uxFlow/skeleton";
