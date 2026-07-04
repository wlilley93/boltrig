/** Skeleton (N13, P25): first-load shape, never during polls. */
// The shimmer is pure CSS; the global reduce-motion rules zero its duration,
// leaving a static block. aria-hidden: a skeleton is never content.

export function Skeleton({
  variant,
  count,
}: {
  variant: "rows" | "cards" | "transcript";
  count?: number;
}) {
  const n = count ?? (variant === "cards" ? 3 : 4);
  return (
    <div className={`ux-skel ux-skel--${variant}`} aria-hidden="true">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="ux-skel__item" />
      ))}
    </div>
  );
}
