/** Which steps first-run setup walks, and in what order.
 *
 * Split out of OnboardingGate so the sequence has one home: the gate used to
 * encode it three times over, as a `step + 1` in Continue, a `step - 1` in Back
 * and a literal `[0, 1, 2, 3, 4, 5]` in the progress dots, which is how those
 * three came to disagree.
 */

export type Step = 0 | 1 | 2 | 3 | 4 | 5;

/**
 * The steps actually walked, in order.
 *
 * 4 is the voice step and is deliberately absent: voice is not asked during
 * setup any more (see continueOnboarding). A deployment with a speech service
 * already configured was still being asked to add one, and a speech provider is
 * connectable afterwards from Integrations, with the voice model in Settings.
 *
 * Counting a step nobody visits made the progress read "of 6" while five were
 * reachable, and offered a dot for a position nobody could arrive at.
 */
export const VISITED_STEPS: readonly Step[] = [0, 1, 2, 3, 5];

/** Back follows the same sequence Continue does.
 *
 * `step - 1` was correct only while every index was reachable. With voice no
 * longer visited, Back from the ready step landed on "Add voice" - a screen the
 * flow had deliberately stopped showing, reachable only by going backwards.
 */
export function previousStep(step: Step): Step {
  const at = VISITED_STEPS.indexOf(step);
  return at > 0 ? VISITED_STEPS[at - 1]! : VISITED_STEPS[0]!;
}
