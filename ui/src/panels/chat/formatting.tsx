import type { CSSProperties, ReactNode } from "react";

import { GREETINGS } from "@/panels/chat/constants";

export function greetingFor(subject: string): ReactNode {
  const hour = new Date().getHours();
  const bucket = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";
  const list = GREETINGS[bucket];
  const msg = list[Math.floor((Date.now() / 60000) % list.length)];
  const name = subject || "there";
  return (
    <>
      {msg}, <span>{name}</span>.
    </>
  );
}

export function whenText(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return d.toLocaleDateString();
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function fileExtClass(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const safe = ext.replace(/[^a-z0-9]/g, "");
  return safe ? `file-row--${safe}` : "";
}

export function statusColor(status: "active" | "idle" | "offline"): string {
  if (status === "active") return "var(--color-ok)";
  if (status === "idle") return "var(--color-warn)";
  return "var(--color-text-muted)";
}

export function cssVarColor(name: string, value: string): CSSProperties {
  return { [name]: value } as CSSProperties;
}
