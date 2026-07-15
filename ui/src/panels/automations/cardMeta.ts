// Presentation metadata for workflow cards. Descriptive fields are derived only
// from values returned by the workflow API; operational metrics remain empty
// until the run-stats endpoint supplies them.

import type { WorkflowRunStat } from "@/api/types";
const ACCENTS = ["#3DD3F0", "#5E69DD", "#FF7A45", "#3FB984", "#7C8BFF", "#E8B339"];
const STATUS_READY = "#3FB984";
const STATUS_DRAFT = "#E8B339";
const STATUS_LEARNED = "#3DD3F0";

export interface HomeCardStatus {
  label: string;
  color: string;
}

export interface HomeCardMeta {
  accent: string;
  status: HomeCardStatus;
  description: string;
  runCount: number;
  successRate: number | null;
  lastRun: string;
  hasRunStats: boolean;
}

// FNV-1a 32-bit hash -> unsigned int. Stable across runs and runtimes.
export function hashId(id: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export function deriveStatus(source: string): HomeCardStatus {
  switch (source) {
    case "precreated":
      return { label: "ready", color: STATUS_READY };
    case "generated":
      return { label: "draft", color: STATUS_DRAFT };
    case "learned":
      return { label: "learned", color: STATUS_LEARNED };
    default:
      return { label: "draft", color: STATUS_DRAFT };
  }
}

function deriveDescription(id: string, tags: string[]): string {
  const subject =
    tags.length > 0
      ? tags.slice(0, 2).join(" / ")
      : (id.split(".")[0] || id).replace(/[_-]+/g, " ");
  return `${subject} workflow`;
}

export function deriveCardMeta(
  id: string,
  source: string,
  tags: string[],
): HomeCardMeta {
  const seed = hashId(id);
  const accent = ACCENTS[seed % ACCENTS.length];
  return {
    accent,
    status: deriveStatus(source),
    description: deriveDescription(id, tags),
    runCount: 0,
    successRate: null,
    lastRun: "never",
    hasRunStats: false,
  };
}

// Merge real run stats onto the descriptive card metadata. A workflow with no
// stat row renders an explicit no-history state instead of synthetic activity.
const RELATIVE_UNITS: { unit: Intl.RelativeTimeFormatUnit; s: number }[] = [
  { unit: "year", s: 31536000 },
  { unit: "month", s: 2592000 },
  { unit: "day", s: 86400 },
  { unit: "hour", s: 3600 },
  { unit: "minute", s: 60 },
];
const _rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function formatLastRun(lastRunAt: string | null): string {
  if (!lastRunAt) return "never";
  const then = Date.parse(lastRunAt);
  if (Number.isNaN(then)) return "never";
  // Elapsed seconds since the run (Date.now() - then so a PAST run is positive);
  // floored at 0 so a clock-skewed future stamp renders as "just now".
  const diffSec = Math.max(0, (Date.now() - then) / 1000);
  if (diffSec < 60) return "just now";
  for (const { unit, s } of RELATIVE_UNITS) {
    if (diffSec >= s) return _rtf.format(-Math.round(diffSec / s), unit);
  }
  return "just now";
}

export function mergeCardStats(
  meta: HomeCardMeta,
  stat: WorkflowRunStat | undefined,
): HomeCardMeta {
  if (!stat || stat.run_count === 0) return meta;
  const successRate = Math.round((stat.success_count / stat.run_count) * 100);
  return {
    ...meta,
    runCount: stat.run_count,
    successRate,
    lastRun: formatLastRun(stat.last_run_at),
    hasRunStats: true,
  };
}
