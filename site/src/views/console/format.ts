import type { ConsoleComponent, ConsoleOverview } from "./types";

const currencyFormatter = new Intl.NumberFormat("en-GB", {
  currency: "GBP",
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
  style: "currency",
});

export function formatMicros(value: number | null | undefined): string {
  return currencyFormatter.format((value ?? 0) / 1_000_000);
}

export function formatNumber(value: number | null | undefined): string {
  return new Intl.NumberFormat("en-GB").format(value ?? 0);
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return new Intl.NumberFormat("en-GB", {
    maximumFractionDigits: 1,
    style: "percent",
  }).format(value);
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
  });
}

export function worstStatus(items: ConsoleComponent[]): ConsoleComponent["status"] {
  const rank: Record<ConsoleComponent["status"], number> = {
    down: 4,
    degraded: 3,
    unknown: 2,
    ok: 1,
  };
  return items.reduce<ConsoleComponent["status"]>(
    (worst, item) => (rank[item.status] > rank[worst] ? item.status : worst),
    "ok",
  );
}

export function platformSummary(overview: ConsoleOverview): string {
  const items = [
    ...overview.platform.components,
    ...overview.platform.runtimes,
  ];
  const status = worstStatus(items);
  return `${status} · ${items.length} services`;
}

function textMeta(item: ConsoleComponent, key: string): string | null {
  const value = item.metadata[key];
  return typeof value === "string" ? value : null;
}

function numberMeta(item: ConsoleComponent, key: string): number | null {
  const value = item.metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export type GatewaySummary = {
  status: ConsoleComponent["status"];
  liveHealth: string;
  message: string;
  profileCount: number | null;
  providerCount: number | null;
  cacheHitRate: number | null;
  cacheHits: number | null;
  cacheMisses: number | null;
};

export function gatewaySummary(overview: ConsoleOverview): GatewaySummary | null {
  const item = overview.platform.components.find((row) => row.id === "bifrost");
  if (!item) return null;
  return {
    cacheHitRate: numberMeta(item, "cache_hit_rate"),
    cacheHits: numberMeta(item, "cache_hits"),
    cacheMisses: numberMeta(item, "cache_misses"),
    liveHealth: textMeta(item, "live_health") ?? "unknown",
    message: item.message,
    profileCount: numberMeta(item, "profile_count"),
    providerCount: numberMeta(item, "provider_count"),
    status: item.status,
  };
}
