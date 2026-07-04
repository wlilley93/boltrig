// Deterministic home-card metadata for the automations listing (design brief
// sec 22.1). The WorkflowSummary API only carries { id, version, source,
// intent_tags }, so the richer card fields (description, sparkline, run count,
// success rate, last run, owner, trigger) are DERIVED from the workflow id via a
// stable hash + PRNG. The structure is faithful to the brief and degrades to
// placeholder data; swap deriveCardMeta for real API fields when they exist.

import type { TriggerKind } from "../workflowCanvas/types";

const ACCENTS = ["#3DD3F0", "#5E69DD", "#FF7A45", "#3FB984", "#7C8BFF", "#E8B339"];
const STATUS_READY = "#3FB984";
const STATUS_DRAFT = "#E8B339";
const STATUS_LEARNED = "#3DD3F0";
const SPARK_OK = "#3FB984";
const SPARK_FAIL = "#F0654A";
const LAST_RUN_LABELS = [
  "just now",
  "8m ago",
  "27m ago",
  "1h ago",
  "3h ago",
  "6h ago",
  "1d ago",
  "2d ago",
  "5d ago",
  "never",
];
const TRIGGERS: TriggerKind[] = ["webhook", "cron", "chat"];

export interface HomeCardStatus {
  label: string;
  color: string;
}

export interface HomeCardMeta {
  accent: string;
  status: HomeCardStatus;
  description: string;
  spark: { ok: boolean; color: string; level: number }[];
  runCount: number;
  successRate: number;
  lastRun: string;
  owner: string;
  trigger: TriggerKind;
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

// mulberry32 PRNG seeded from a uint32 -> [0, 1).
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
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

function deriveSpark(
  rand: () => number,
): { ok: boolean; color: string; level: number }[] {
  const bars: { ok: boolean; color: string; level: number }[] = [];
  for (let i = 0; i < 7; i++) {
    const ok = rand() >= 0.22;
    bars.push({ ok, color: ok ? SPARK_OK : SPARK_FAIL, level: 0.32 + rand() * 0.68 });
  }
  return bars;
}

export function deriveCardMeta(
  id: string,
  source: string,
  tags: string[],
): HomeCardMeta {
  const seed = hashId(id);
  const rand = mulberry32(seed);
  const accent = ACCENTS[seed % ACCENTS.length];
  const runCount = Math.floor(rand() * 49);
  const successRate = 60 + Math.floor(rand() * 40);
  const lastRun = LAST_RUN_LABELS[Math.floor(rand() * LAST_RUN_LABELS.length)];
  const trigger = TRIGGERS[Math.floor(rand() * TRIGGERS.length)];
  return {
    accent,
    status: deriveStatus(source),
    description: deriveDescription(id, tags),
    spark: deriveSpark(rand),
    runCount,
    successRate,
    lastRun,
    owner: "Bolt",
    trigger,
  };
}
