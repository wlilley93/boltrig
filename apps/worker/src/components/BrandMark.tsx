/** The Boltrig mark: the dashed ring and its core.
 *
 * Inline SVG rather than an <img> to favicon.svg, for the same reason
 * BrandWordmark is inline text -- no second network request, no flash of a
 * missing logo, and it scales with the type around it.
 *
 * TWO DELIBERATE DIFFERENCES FROM THE FAVICON. It drops the dark background
 * rect, because a favicon has to paint its own square and a logo sitting in a
 * panel must not. And the ring is `currentColor` instead of a fixed near-white,
 * so it inherits whatever the header is using; only the core keeps the fixed
 * accent, which is the one part that carries the brand.
 */
export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`boltrig-mark ${className}`.trim()}
      viewBox="0 0 100 100"
      aria-hidden
      focusable="false"
    >
      <g fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth={6}>
        <circle cx="50" cy="50" r="44" strokeDasharray="230 46" />
      </g>
      <circle cx="50" cy="50" r="9" fill="#3DD3F0" />
    </svg>
  );
}
