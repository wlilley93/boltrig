import type { CSSProperties } from "react";
import type { FamiliarGenotype } from "@wlilley93/boltrig-web-sdk";

// The lightweight Familiar: message avatars, subagent markers, and the floor of
// the renderer ladder (ADR 0025). Extracted verbatim from ChatView's `Familiar`.
// It must stay per-message cheap — the premium Stage renderer is never mounted
// for a badge.
export function FamiliarBadge({
  state,
  genotype,
  label,
}: {
  state: "ready" | "working";
  genotype?: FamiliarGenotype | null;
  label?: string;
}) {
  const hasIdentity = genotype?.source === "agent_capability.name.v1";
  return (
    <span
      className={`familiar-orb ${state}`}
      data-genotype-source={hasIdentity ? genotype.source : "unbound"}
      role="img"
      aria-label={hasIdentity
        ? `${label ?? "Agent"} Familiar · ${state}`
        : `Boltrig activity · ${state}`}
      style={hasIdentity ? familiarPalette(genotype.palette) : undefined}
    ><i /></span>
  );
}

export function familiarPalette(palette?: string[] | null): CSSProperties {
  const colors = [...(palette ?? [])]
    .filter((value) => /^#[0-9a-f]{6}$/i.test(value))
    .slice(0, 3);
  if (colors.length !== 3) return {};
  return { background: `radial-gradient(circle at 35% 30%, ${colors.join(", ")})` };
}
