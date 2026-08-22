/** The Boltrig mark: five concentric dashed rings around a live core.
 *
 * Inline SVG rather than an <img> to favicon.svg, for the same reason
 * BrandWordmark is inline text -- no second network request, no flash of a
 * missing logo, and it scales with the type around it.
 *
 * THE GEOMETRY IS THE DESIGN'S, NOT AN APPROXIMATION. Radii, dash lengths and
 * the alternating rotations come straight from `Boltrig Logo.dc.html`. The
 * rotations are the whole trick: each ring's gap is turned away from its
 * neighbours, so the eye never finds a seam running through the mark.
 *
 * TWO DELIBERATE DIFFERENCES FROM THE FAVICON. It drops the dark background
 * rect, because a favicon has to paint its own square and a logo sitting in a
 * panel must not. And the rings are `currentColor` instead of a fixed
 * near-white, so they inherit whatever the surface is using; only the core
 * keeps the fixed accent, which is the one part that carries the brand.
 */
const RINGS: Array<{ r: number; dash: string; rotate: number }> = [
  { r: 45, dash: "234.6 48.1", rotate: 0 },
  { r: 37, dash: "193 40", rotate: -72 },
  { r: 29, dash: "151 31", rotate: 72 },
  { r: 21, dash: "110 22", rotate: -144 },
  { r: 13, dash: "68 14", rotate: 144 },
];

/**
 * The core, and the one fixed colour in the mark.
 *
 * Opbox blue, copied from `public/opbox-mark.svg` in the Opbox tree so the two
 * products' marks read as one house rather than two. Opbox's in-app dot renders
 * `var(--accent)`, which is `#006BFF` in its default theme -- five units of
 * green from the logo asset and indistinguishable at dot size. The LOGO file is
 * the one copied here, because the logo is what this element is.
 *
 * `public/favicon.svg` carries this value too, and must keep carrying it: the
 * desktop icons are rasterised from the favicon (4b392a21), so changing the
 * core in one place only would put a third shade of the mark back in the tree.
 */
const CORE = "#0066FF";

export function BrandMark({
  className = "",
  pulse = true,
}: {
  className?: string;
  /**
   * Whether the core breathes. Opbox's policy, which this follows: pulse on
   * auth cards, modal headers and gates -- surfaces a person is waiting on --
   * and off in dense app chrome, table rows and status cells, where a moving
   * dot is noise. Every current call site is the first kind, so it defaults on.
   */
  pulse?: boolean;
}) {
  return (
    <svg
      className={`boltrig-mark ${className}`.trim()}
      data-pulse={pulse ? "true" : undefined}
      viewBox="0 0 100 100"
      aria-hidden
      focusable="false"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth={2.8}
      >
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
      {/* The radar ping, drawn BEFORE the core so an expanding ring never
          crosses in front of it. Rendered only when pulsing: an element
          animated to opacity 0 is still an element, and leaving it in the
          static mark would put a stray hairline ring at r=5 under any renderer
          that ignores the animation. */}
      {pulse ? (
        <circle className="boltrig-mark__ping" cx="50" cy="50" r="5" stroke={CORE} />
      ) : null}
      <circle className="boltrig-mark__core" cx="50" cy="50" fill={CORE} r="5" />
    </svg>
  );
}
