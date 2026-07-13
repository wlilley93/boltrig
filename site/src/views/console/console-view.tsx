"use client";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchOverview, loadSettings, respondApproval, saveSettings } from "./client";
import {
  ApprovalRows,
  ComponentRows,
  EmptyLine,
  GatewayPanel,
  ModelTable,
  Panel,
  RunRows,
  Stat,
} from "./components";
import {
  formatMicros,
  formatNumber,
  formatTime,
  platformSummary,
} from "./format";
import type {
  ConsoleApproval,
  ConsoleOverview,
  ConsoleSettings,
} from "./types";

const emptySettings: ConsoleSettings = { apiBase: "", bearerToken: "" };

export function ConsoleView() {
  const [settings, setSettings] = useState<ConsoleSettings>(emptySettings);
  const [draft, setDraft] = useState<ConsoleSettings>(emptySettings);
  const [overview, setOverview] = useState<ConsoleOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConnection, setShowConnection] = useState(false);
  const [responding, setResponding] = useState<string | null>(null);

  const loadWith = useCallback(async (nextSettings: ConsoleSettings) => {
    setLoading(true);
    setError(null);
    try {
      setOverview(await fetchOverview(nextSettings));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Console API failed");
      setShowConnection(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const load = useCallback(() => loadWith(settings), [loadWith, settings]);

  useEffect(() => {
    const stored = loadSettings();
    setSettings(stored);
    setDraft(stored);
    void loadWith(stored);
  }, [loadWith]);

  useEffect(() => {
    const timer = window.setInterval(() => void loadWith(settings), 30_000);
    return () => window.clearInterval(timer);
  }, [loadWith, settings]);

  const stats = useMemo(() => {
    if (!overview) return null;
    const runtimeCount = overview.platform.components.length + overview.platform.runtimes.length;
    return {
      platform: platformSummary(overview),
      runtimeCount,
      spend: formatMicros(overview.cost.total_cost_micros),
      approvals: formatNumber(overview.counts.pending_approvals),
      events: formatNumber(overview.counts.visible_events),
    };
  }, [overview]);

  function submitSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    saveSettings(draft);
    setSettings(draft);
    void loadWith(draft);
  }

  async function respond(approval: ConsoleApproval, decision: string) {
    setResponding(`${approval.id}:${decision}`);
    setError(null);
    try {
      await respondApproval(settings, approval.id, decision);
      await loadWith(settings);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval API failed");
    } finally {
      setResponding(null);
    }
  }

  return (
    <main className="min-h-screen bg-[#f6f7f4] text-zinc-950">
      <div className="fixed inset-x-0 top-0 z-30 h-20 bg-[#10141f]" />
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 pb-10 pt-24 md:px-6">
        <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-normal text-zinc-950">Boltrig Console</h1>
            <div className="mt-2 text-sm text-zinc-600">
              {overview
                ? `${overview.tenant_id} · ${overview.workspace_id ?? "all workspaces"} · ${formatTime(overview.generated_at)}`
                : "Waiting for console overview"}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void load()}
              className="rounded-md border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-950 shadow-sm hover:bg-zinc-50"
            >
              {loading ? "Refreshing" : "Refresh"}
            </button>
            <button
              type="button"
              onClick={() => setShowConnection((value) => !value)}
              className="rounded-md border border-blue-500 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-800 shadow-sm hover:bg-blue-100"
            >
              Connection
            </button>
          </div>
        </header>

        {showConnection && (
          <form onSubmit={submitSettings} className="grid gap-3 rounded-md border border-zinc-200 bg-white p-4 shadow-sm md:grid-cols-[1fr_1fr_auto]">
            <label className="text-sm font-medium text-zinc-700">
              API base
              <input
                value={draft.apiBase}
                onChange={(event) => setDraft({ ...draft, apiBase: event.target.value })}
                placeholder="https://api.example.com"
                className="mt-1 block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-950 outline-none focus:border-blue-500"
              />
            </label>
            <label className="text-sm font-medium text-zinc-700">
              Bearer token
              <input
                value={draft.bearerToken}
                onChange={(event) => setDraft({ ...draft, bearerToken: event.target.value })}
                placeholder="token"
                type="password"
                className="mt-1 block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-950 outline-none focus:border-blue-500"
              />
            </label>
            <button
              type="submit"
              className="self-end rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700"
            >
              Save
            </button>
          </form>
        )}

        {error && (
          <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        )}

        {overview && stats && (
          <>
            <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Stat label="Platform" value={stats.platform} sub={`${stats.runtimeCount} status rows`} />
              <Stat label="Spend" value={stats.spend} sub="visible scoped cost" />
              <Stat label="Approvals" value={stats.approvals} sub="pending human decisions" />
              <Stat label="Activity" value={stats.events} sub="visible audit rows" />
            </section>

            <section className="grid gap-5 lg:grid-cols-[1fr_1fr]">
              <Panel title="Runtime Status">
                <ComponentRows items={[...overview.platform.components, ...overview.platform.runtimes]} />
              </Panel>
              <Panel title="Model Gateway">
                <GatewayPanel overview={overview} />
              </Panel>
            </section>

            <Panel title="Approvals">
              <ApprovalRows
                approvals={overview.approvals}
                onRespond={(approval, decision) => void respond(approval, decision)}
                responding={responding}
              />
            </Panel>

            <Panel title="Model Usage">
              <ModelTable overview={overview} />
            </Panel>

            <section className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
              <Panel title="Recent Activity">
                <RunRows runs={overview.recent_runs} />
              </Panel>
              <Panel title="Budgets">
                {overview.budgets.length ? (
                  <div className="divide-y divide-zinc-100">
                    {overview.budgets.map((budget) => (
                      <div key={`${budget.scope_type}:${budget.id}`} className="py-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-medium text-zinc-950">{budget.id}</div>
                          <div className="text-xs text-zinc-500">{budget.scope_type} · {budget.window}</div>
                        </div>
                        <div className="mt-2 h-2 rounded-sm bg-zinc-100">
                          <div
                            className="h-2 rounded-sm bg-blue-500"
                            style={{
                              width: `${Math.min(
                                100,
                                budget.cost_limit_micros
                                  ? (budget.spent_micros / budget.cost_limit_micros) * 100
                                  : 0,
                              )}%`,
                            }}
                          />
                        </div>
                        <div className="mt-2 text-xs text-zinc-500">
                          {formatMicros(budget.spent_micros)} / {budget.cost_limit_micros ? formatMicros(budget.cost_limit_micros) : "uncapped"}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyLine label="No budgets configured" />
                )}
              </Panel>
            </section>
          </>
        )}
      </div>
    </main>
  );
}
