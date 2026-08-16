/** The Boltrig mark: five dashed rings and an accent core.
 *
 * Inline SVG rather than an <img> to favicon.svg, for the same reason
 * BrandWordmark is inline text -- no second network request, no flash of a
 * missing logo, and it scales with the type around it.
 *
 * THE RINGS ARE NOT DECORATION. Each is dashed to about 83% of its
 * circumference and rotated 72 degrees from its neighbour, so the gaps spiral
 * rather than lining up into a seam. The dash pairs are absolute lengths
 * against each radius, which is why they are not one repeated value.
 *
 * TWO DELIBERATE DIFFERENCES FROM THE FAVICON. It drops the dark background
 * rect, because a favicon has to paint its own square and a logo sitting in a
 * panel must not. And the rings are `currentColor` instead of a fixed
 * near-white, so they inherit whatever the header is using; only the core keeps
 * the fixed accent, which is the one part that carries the brand.
 *
 * `strokeWidth` is 4.5 rather than the artwork's 2.8: the mark renders at about
 * 1.35em here, far below the 130px it was drawn at, and a hairline that thin
 * disappears at that size.
 */
const RINGS: Array<{ r: number; dash: string; rotate: number }> = [
  { r: 45, dash: "234.6 48.1", rotate: 0 },
  { r: 37, dash: "193 40", rotate: -72 },
  { r: 29, dash: "151 31", rotate: 72 },
  { r: 21, dash: "110 22", rotate: -144 },
  { r: 13, dash: "68 14", rotate: 144 },
];

export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`boltrig-mark ${className}`.trim()}
      viewBox="0 0 100 100"
      aria-hidden
      focusable="false"
    >
      <g fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth={4.5}>
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
      <circle cx="50" cy="50" fill="#3DD3F0" r="5" />
    </svg>
  );
}
