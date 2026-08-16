import { BrandMark } from "../BrandMark";
import { BrandWordmark } from "../BrandWordmark";

/** The mark and the wordmark as ONE unit.
 *
 * Both onboarding headers render it, and they must stay identical: a lockup
 * that drifts between two screens of the same flow reads as two brands. Naming
 * it here is what makes that structural rather than a convention.
 */
export function BrandLockup() {
  return (
    <span className="onboarding-lockup">
      <BrandMark className="onboarding-mark" />
      <BrandWordmark className="onboarding-brand" />
    </span>
  );
}
