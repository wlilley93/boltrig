import type { ReactNode } from "react";

import {
  formatMicros,
  formatNumber,
  formatPercent,
  formatTime,
  gatewaySummary,
} from "./format";
import type {
  ConsoleApproval,
  ConsoleComponent,
  ConsoleOverview,
  ConsoleRun,
} from "./types";

function statusClass(status: string): string {
  if (status === "ok") return "border-emerald-500/50 bg-emerald-50 text-emerald-800";
  if (status === "degraded") return "border-amber-500/60 bg-amber-50 text-amber-800";
  if (status === "down" || status === "error") return "border-red-500/60 bg-red-50 text-red-800";
  return "border-zinc-300 bg-zinc-100 text-zinc-700";
}

export function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="rounded-md border border-zinc-200 bg-white p-4 shadow-sm">
      <div className="text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-zinc-500">
        {label}
      </div>
      <div className="mt-3 text-2xl font-semibold text-zinc-950">{value}</div>
      <div className="mt-1 text-sm text-zinc-500">{sub}</div>
    </div>
  );
}

export function ComponentRows({ items }: { items: ConsoleComponent[] }) {
  if (!items.length) return <EmptyLine label="No runtime status rows" />;
  return (
    <div className="divide-y divide-zinc-100">
      {items.map((item) => (
        <div key={`${item.kind}:${item.id}`} className="flex items-center gap-3 py-3">
          <span className={`shrink-0 rounded-md border px-2 py-1 text-xs ${statusClass(item.status)}`}>
            {item.status}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-zinc-950">{item.id}</div>
            <div className="truncate text-xs text-zinc-500">
              {item.kind}
              {item.message ? ` · ${item.message}` : ""}
            </div>
          </div>
          <div className="shrink-0 text-xs text-zinc-500">{formatTime(item.updated_at)}</div>
        </div>
      ))}
    </div>
  );
}

export function GatewayPanel({ overview }: { overview: ConsoleOverview }) {
  const gateway = gatewaySummary(overview);
  if (!gateway) return <EmptyLine label="No model gateway status" />;
  const metrics = [
    ["Live", gateway.liveHealth.replaceAll("_", " ")],
    ["Profiles", gateway.profileCount === null ? "n/a" : formatNumber(gateway.profileCount)],
    ["Providers", gateway.providerCount === null ? "n/a" : formatNumber(gateway.providerCount)],
    ["Hit Rate", formatPercent(gateway.cacheHitRate)],
    ["Hits", gateway.cacheHits === null ? "n/a" : formatNumber(gateway.cacheHits)],
    ["Misses", gateway.cacheMisses === null ? "n/a" : formatNumber(gateway.cacheMisses)],
  ];
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <span className={`rounded-md border px-2 py-1 text-xs ${statusClass(gateway.status)}`}>
          {gateway.status}
        </span>
        <span className="truncate text-xs text-zinc-500">{gateway.message}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-md border border-zinc-100 bg-zinc-50 p-3">
            <div className="text-[0.66rem] font-semibold uppercase tracking-[0.12em] text-zinc-500">
              {label}
            </div>
            <div className="mt-1 truncate text-sm font-medium text-zinc-950">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ApprovalRows({
  approvals,
  onRespond,
  responding,
}: {
  approvals: ConsoleApproval[];
  onRespond: (approval: ConsoleApproval, decision: string) => void;
  responding: string | null;
}) {
  if (!approvals.length) return <EmptyLine label="No pending approvals" />;
  return (
    <div className="divide-y divide-zinc-100">
      {approvals.map((approval) => (
        <div key={approval.id} className="py-3">
          <div className="flex items-center justify-between gap-3">
            <span className="rounded-md border border-amber-400 bg-amber-50 px-2 py-1 text-xs text-amber-800">
              {approval.urgency}
            </span>
            <span className="truncate text-xs text-zinc-500">{approval.run_id}</span>
          </div>
          <div className="mt-2 text-sm font-medium text-zinc-950">{approval.question}</div>
          <div className="mt-1 text-xs text-zinc-500">
            {approval.options.join(" / ") || approval.type}
          </div>
          {approval.options.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {approval.options.map((option) => {
                const active = responding === `${approval.id}:${option}`;
                return (
                  <button
                    key={option}
                    type="button"
                    disabled={responding !== null}
                    onClick={() => onRespond(approval, option)}
                    className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-950 shadow-sm hover:border-blue-400 hover:text-blue-800 disabled:cursor-wait disabled:opacity-60"
                  >
                    {active ? "Sending" : option}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function RunRows({ runs }: { runs: ConsoleRun[] }) {
  if (!runs.length) return <EmptyLine label="No recent run activity" />;
  return (
    <div className="divide-y divide-zinc-100">
      {runs.map((run, index) => (
        <div key={`${run.seq ?? index}:${run.run_id ?? "run"}`} className="grid grid-cols-[1fr_auto] gap-3 py-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-zinc-950">
              {run.run_id ?? run.parent_run_id ?? "untracked"}
            </div>
            <div className="truncate text-xs text-zinc-500">
              {run.actor} · {run.verb ?? run.action_type}
            </div>
          </div>
          <div className="text-right">
            <span className={`rounded-md border px-2 py-1 text-xs ${statusClass(run.status)}`}>
              {run.status}
            </span>
            <div className="mt-1 text-xs text-zinc-500">{formatTime(run.ts)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ModelTable({ overview }: { overview: ConsoleOverview }) {
  if (!overview.models.length) return <EmptyLine label="No model calls yet" />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[42rem] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-xs uppercase tracking-[0.12em] text-zinc-500">
            <th className="py-2 pr-4 font-semibold">Model</th>
            <th className="py-2 pr-4 font-semibold">Runtime</th>
            <th className="py-2 pr-4 text-right font-semibold">Calls</th>
            <th className="py-2 pr-4 text-right font-semibold">Tokens</th>
            <th className="py-2 pr-4 text-right font-semibold">Cost</th>
            <th className="py-2 text-right font-semibold">Latency</th>
          </tr>
        </thead>
        <tbody>
          {overview.models.map((model) => (
            <tr key={`${model.provider}:${model.model}:${model.runtime}`} className="border-b border-zinc-100">
              <td className="py-3 pr-4">
                <div className="font-medium text-zinc-950">{model.model}</div>
                <div className="text-xs text-zinc-500">
                  {model.provider}{model.profile ? ` · ${model.profile}` : ""}
                </div>
              </td>
              <td className="py-3 pr-4 text-zinc-600">{model.runtime}</td>
              <td className="py-3 pr-4 text-right text-zinc-950">{formatNumber(model.calls)}</td>
              <td className="py-3 pr-4 text-right text-zinc-950">{formatNumber(model.tokens)}</td>
              <td className="py-3 pr-4 text-right text-zinc-950">{formatMicros(model.cost_micros)}</td>
              <td className="py-3 text-right text-zinc-950">
                {model.avg_latency_ms === null ? "n/a" : `${model.avg_latency_ms}ms`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EmptyLine({ label }: { label: string }) {
  return <div className="py-6 text-sm text-zinc-500">{label}</div>;
}

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-md border border-zinc-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-zinc-500">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}
