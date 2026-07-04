/* Radio-group arrow movement: next enabled index in a wrapping scan. Shared by
 * SegmentedV2 and CardSelect so both keep identical radio semantics. */
export function nextEnabled(
  count: number,
  isDisabled: (i: number) => boolean,
  from: number,
  delta: number,
): number {
  if (count === 0) return -1;
  let i = from;
  for (let hop = 0; hop < count; hop++) {
    i = (i + delta + count) % count;
    if (!isDisabled(i)) return i;
  }
  return -1;
}
