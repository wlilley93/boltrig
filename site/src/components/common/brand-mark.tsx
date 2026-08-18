/** The Boltrig mark: five concentric dashed rings around a live core.
 *
 * The site had no mark at all - the header carried the wordmark alone, and the
 * only place the logo existed was `app/icon.svg`, which is a favicon and cannot
 * animate. So "the centre dot should pulse" had nowhere to happen.
 *
 * THE GEOMETRY IS THE WORKER'S, DELIBERATELY. `apps/worker/src/components/
 * BrandMark.tsx` carries the same radii, dash lengths and alternating rotations,
 * taken from the logo source; the rotations are the trick, turning each ring's
 * gap away from its neighbours so the eye never finds a seam. Two marks that
 * differ by a few units read as two brands, so this is a copy of those numbers
 * rather than a re-derivation of them.
 *
 * THE COLOUR IS THE SITE'S, ALSO DELIBERATELY. The Worker's core is #0066FF
 * (Opbox blue, shared so the two products read as one house); this site's
 * palette is built on --brain-azure #3dd3f0, which both `app/icon.svg` and
 * `public/favicon.svg` already carry. Painting the app's blue here would put a
 * third shade of the mark in front of people rather than removing one. Whether
 * the two should converge is a brand decision, not a bug fix.
 *
 * Inline SVG rather than an <img> to the favicon: no second request, no flash
 * of a missing logo, it scales with the type beside it, and only an inline
 * element can carry the animation this exists for.
 */
const RINGS: Array<{ r: number; dash: string; rotate: number }> = [
  { r: 45, dash: "234.6 48.1", rotate: 0 },
  { r: 37, dash: "193 40", rotate: -72 },
  { r: 29, dash: "151 31", rotate: 72 },
  { r: 21, dash: "110 22", rotate: -144 },
  { r: 13, dash: "68 14", rotate: 144 },
];

export const BrandMark = ({
  className = "",
  pulse = true,
}: {
  className?: string;
  /** Whether the core breathes. On wherever a person is waiting on something. */
  pulse?: boolean;
}) => (
  <svg
    aria-hidden
    className={`boltrig-mark ${className}`.trim()}
    data-pulse={pulse ? "true" : undefined}
    focusable="false"
    viewBox="0 0 100 100"
  >
    <g fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth={2.8}>
      {RINGS.map((ring) => (
        <circle
          cx="50"
          cy="50"
          key={ring.r}
          r={ring.r}
          strokeDasharray={ring.dash}
          transform={ring.rotate ? `rotate(${ring.rotate} 50 50)` : undefined}
        />
      ))}
    </g>
    {/* Drawn BEFORE the core so the expanding ring never crosses in front of
        it, and rendered only when pulsing: an element animated to opacity 0 is
        still an element, and leaving it in the static mark would put a stray
        hairline ring at r=5 under any renderer that ignores the animation. */}
    {pulse ? (
      <circle className="boltrig-mark__ping" cx="50" cy="50" r="5" />
    ) : null}
    <circle className="boltrig-mark__core" cx="50" cy="50" r="5" />
  </svg>
);
