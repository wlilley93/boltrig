import { StepHeading } from "./StepHeading";

/** The suspense fallback for a lazily-loaded onboarding step.
 *
 * Was three near-identical functions in OnboardingGate that differed only in
 * the step class, the kicker and the title. `aria-busy` is on the wrapper so a
 * screen reader announces the wait rather than reading a half-built step.
 */
export function StepSkeleton({ heading, kicker, step }: {
  heading: string;
  kicker?: string;
  step: string;
}) {
  return (
    <div className={`onboarding-step ${step}`} aria-busy="true">
      <StepHeading heading={heading} kicker={kicker} />
      <div className="onboarding-loader"><span /><span /><span /></div>
    </div>
  );
}
