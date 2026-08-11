import { useId } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { FamiliarGenotype } from "@wlilley93/boltrig-web-sdk";
import {
  familiarVisualIdentity,
  type FamiliarAccessory,
  type FamiliarBody,
  type FamiliarMarking,
} from "./FamiliarGenotype";
import "./familiar.css";

// The lightweight Familiar: message avatars, subagent markers, and the floor of
// the renderer ladder (ADR 0025). Extracted verbatim from ChatView's `Familiar`.
// It must stay per-message cheap — the premium Stage renderer is never mounted
// for a badge.
export function FamiliarBadge({
  state,
  genotype,
  label,
  decorative = false,
  size,
}: {
  state: "ready" | "working";
  genotype?: FamiliarGenotype | null;
  label?: string;
  decorative?: boolean;
  size?: number | string;
}) {
  const identity = familiarVisualIdentity(genotype);
  const titleId = useId().replaceAll(":", "");
  const transform = identity.bound
    ? `rotate(${((identity.seed % 17) - 8) * 0.55} 12 12)`
    : undefined;
  return (
    <span
      className={`familiar-orb familiar-identity ${state}`}
      data-familiar-accessories={identity.accessories.join(" ") || undefined}
      data-familiar-body={identity.body}
      data-familiar-markings={identity.markings.join(" ") || undefined}
      data-genotype-source={identity.source}
      data-renderer="badge"
      aria-hidden={decorative ? "true" : undefined}
      role={decorative ? undefined : "img"}
      aria-label={decorative
        ? undefined
        : identity.bound
          ? `${label ?? "Agent"} Familiar · ${state}`
          : `Boltrig activity · ${state}`}
      style={{
        ...familiarPalette(identity.palette),
        ...(size === undefined ? {} : { width: size, height: size }),
      }}
    >
      <svg aria-hidden="true" className="familiar-badge-svg" viewBox="0 0 24 24">
        <title id={titleId}>{identity.body} Familiar</title>
        <circle
          className="familiar-badge-ring"
          cx="12"
          cy="12"
          fill="none"
          r="10.35"
          stroke={state === "working" ? identity.palette[0] : identity.palette[2]}
        />
        <g className="familiar-badge-body" transform={transform}>
          {bodyShape(identity.body, identity.palette)}
        </g>
        <g className="familiar-badge-markings">
          {identity.markings.map((marking) => markingShape(marking, identity.palette))}
        </g>
        <g className="familiar-badge-accessories">
          {identity.accessories.map((accessory) => accessoryShape(accessory, identity.palette))}
        </g>
      </svg>
    </span>
  );
}

export function familiarPalette(palette?: string[] | null): CSSProperties {
  const colors = [...(palette ?? [])].slice(0, 3);
  if (colors.length !== 3) return {};
  return {
    "--familiar-light": colors[0],
    "--familiar-mid": colors[1],
    "--familiar-dark": colors[2],
    background: "transparent",
    borderRadius: 0,
    boxShadow: "none",
  } as CSSProperties;
}

function bodyShape(body: FamiliarBody, palette: [string, string, string]): ReactNode {
  const [light, mid, dark] = palette;
  if (body === "cassini") {
    return <>
      <path d="M11.45 4.1C8.15 4.1 5.7 7.55 5.7 12s2.45 7.9 5.75 7.9z" fill={mid} />
      <path d="M12.55 4.1c3.3 0 5.75 3.45 5.75 7.9s-2.45 7.9-5.75 7.9z" fill={light} opacity=".82" />
    </>;
  }
  if (body === "kepler") {
    return <polygon fill={mid} points={radialPoints(5, 8.1, 3.45)} stroke={dark} strokeWidth=".35" />;
  }
  if (body === "pioneer") {
    return <polygon fill={mid} points={radialPoints(8, 8.15, 5.5)} stroke={light} strokeWidth=".4" />;
  }
  if (body === "voyager") {
    return <path d="M12 3.65 18.45 6v5.3c0 4.18-2.9 6.62-6.45 7.7-3.55-1.08-6.45-3.52-6.45-7.7V6z" fill={mid} stroke={light} strokeWidth=".45" />;
  }
  return <circle cx="12" cy="12" fill={mid} r="7.5" />;
}

function markingShape(
  marking: FamiliarMarking,
  palette: [string, string, string],
): ReactNode {
  const [light, , dark] = palette;
  if (marking === "arc") {
    return <path d="M7.2 13.8c1.8 2.15 6.15 2.45 9.35-.35" fill="none" key={marking} stroke={light} strokeLinecap="round" strokeWidth="1" />;
  }
  if (marking === "constellation") {
    return <g fill={light} key={marking} stroke={dark} strokeWidth=".35">
      <path d="m8.2 14.9 3-5.2 4.25 3.1" fill="none" opacity=".8" />
      <circle cx="8.2" cy="14.9" r=".8" /><circle cx="11.2" cy="9.7" r=".7" /><circle cx="15.45" cy="12.8" r=".85" />
    </g>;
  }
  if (marking === "halo") {
    return <circle cx="12" cy="12" fill="none" key={marking} opacity=".78" r="8.45" stroke={light} strokeWidth=".9" />;
  }
  return <ellipse cx="12" cy="12" fill="none" key={marking} opacity=".86" rx="8.7" ry="3.65" stroke={light} strokeWidth=".9" transform="rotate(-18 12 12)" />;
}

function accessoryShape(
  accessory: FamiliarAccessory,
  palette: [string, string, string],
): ReactNode {
  const [light, mid, dark] = palette;
  if (accessory === "antenna") {
    return <g key={accessory} stroke={light} strokeLinecap="round">
      <path d="m12 4.35 2.35-2.05" strokeWidth=".9" />
      <circle cx="14.65" cy="2.05" fill={mid} r=".9" stroke={dark} strokeWidth=".35" />
    </g>;
  }
  if (accessory === "orbit-ring") {
    return <ellipse cx="12" cy="12" fill="none" key={accessory} rx="10.1" ry="4.3" stroke={light} strokeWidth=".75" transform="rotate(24 12 12)" />;
  }
  return <g key={accessory}>
    <path d="M17.1 5.7c0-1.25.95-2.2 2.15-2.2s2.15.95 2.15 2.2c0 1.55-2.15 3.55-2.15 3.55S17.1 7.25 17.1 5.7Z" fill={light} stroke={dark} strokeWidth=".35" />
    <circle cx="19.25" cy="5.65" fill={mid} r=".65" />
  </g>;
}

function radialPoints(points: number, outer: number, inner: number): string {
  return Array.from({ length: points * 2 }, (_, index) => {
    const radius = index % 2 === 0 ? outer : inner;
    const angle = Math.PI * index / points;
    return `${(12 + radius * Math.sin(angle)).toFixed(2)},${(12 - radius * Math.cos(angle)).toFixed(2)}`;
  }).join(" ");
}
