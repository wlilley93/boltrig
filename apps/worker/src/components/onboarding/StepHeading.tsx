/** The heading block every onboarding step shares.
 *
 * An optional kicker above, a required title, an optional sub. It exists
 * because the provider step, the vision step and all three suspense fallbacks
 * render exactly this and were each carrying their own copy.
 */
export function StepHeading({ heading, kicker, sub }: {
  heading: string;
  kicker?: string;
  sub?: string;
}) {
  return (
    <div className="onboarding-heading onboarding-rise">
      {kicker ? <p className="onboarding-kicker">{kicker}</p> : null}
      <h1>{heading}</h1>
      {sub ? <p>{sub}</p> : null}
    </div>
  );
}
