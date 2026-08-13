import { useEffect, useState } from "react";
import type {
  AdapterHealth,
  BudgetItem,
  ReadinessCheck,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { money } from "./format";
import { SettingsGroup, SettingsRow, ToneRow, type Tone } from "./rowKit";

// Health as the decided target draws it: a computed headline instead of a
// static title, three stat cards, the readiness checks in plain words, the
// kernel's adapter health, and a boundaries card of limits this build
// actually has. Every number on this screen is a measurement the SDK
// returns; where the target draws a figure the SDK cannot provide (runs
// today, lifetime action totals), the card is relabelled to what is
// measurable rather than dressed up.

// The kernel reports a healthy check as "ready" OR "ok", and a check that is
// switched off as "disabled". Treating only "ready" as healthy painted an ok
// check red and counted it as failing.
const healthy = (value: string) => value === "ready" || value === "ok";

// Plain-language names for the kernel's known readiness checks (see
// boltrig/api/readiness.py). Unknown checks fall back to their raw name so a
// new check is never silently dropped or mislabelled.
const CHECK_COPY: Record<string, { title: string; sub: string }> = {
  postgres: { title: "Where everything is kept", sub: "The store that holds runs, approvals and the record" },
  redis: { title: "Coordination between parts", sub: "Coordinates background work" },
  migration: { title: "The storage schema", sub: "Storage is on the required version" },
  control_plane: { title: "Accounts and policy", sub: "Who may do what, decided server-side" },
  stack_tools: { title: "Acting in your systems", sub: "The tools boltrig uses to do real work" },
  hatchet: { title: "Background work", sub: "The runner for long and queued work" },
  model_gateway: { title: "Reaching the models", sub: "The gateway that does the thinking" },
  password_reset_delivery: { title: "Password reset delivery", sub: "How a reset actually reaches a person" },
};

function checkTone(check: ReadinessCheck): { tone: Tone; state: string } {
  if (healthy(check.status)) return { tone: "green", state: "fine" };
  if (check.status === "disabled") return { tone: "unknown", state: "switched off" };
  if (check.required) return { tone: "red", state: "not working" };
  return { tone: "amber", state: "struggling" };
}

const ADAPTER_TONE: Record<AdapterHealth, { tone: Tone; state: string }> = {
  ok: { tone: "green", state: "fine" },
  degraded: { tone: "amber", state: "struggling" },
  down: { tone: "red", state: "down" },
  unknown: { tone: "unknown", state: "unknown" },
};

// Limits of THIS build, each re-verified against the worker and kernel rather
// than copied from the design (whose list was written against another repo).
// Scheduling and ceiling edits exist here (AutomationView, Operate), so the
// design's rows about them are deliberately absent.
const BOUNDARIES: Array<[string, string, string]> = [
  ["A single autonomy dial", "Approval requirements are set per action by workspace policy", "by policy"],
  ["Weekly spending windows", "Budgets cover a run, a day or a month. There is no weekly window yet", "not yet"],
  ["Cost per routine", "Spend is attributed per actor today, not per routine", "not yet"],
  ["Overnight practice on its own", "Overnight practice must be started manually", "by hand"],
  ["Chats in projects", "Archived chats use one list; projects and folders are not available", "not yet"],
];

interface Readiness {
  status: string;
  checks: Record<string, ReadinessCheck>;
}

export function HealthSection({ head = true }: { head?: boolean }) {
  const [readiness, setReadiness] = useState<Readiness | null | "unavailable">(null);
  const [adapters, setAdapters] = useState<Record<string, AdapterHealth> | null>(null);
  const [pending, setPending] = useState<number | null>(null);
  const [budgets, setBudgets] = useState<BudgetItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (typeof client.readiness === "function") {
      void client.readiness()
        .then((result) => {
          if (cancelled) return;
          setReadiness({ status: result.status ?? "", checks: result.checks ?? {} });
        })
        .catch(() => { if (!cancelled) setReadiness("unavailable"); });
    } else {
      setReadiness("unavailable");
    }
    if (typeof client.health === "function") {
      void client.health()
        .then((result) => { if (!cancelled) setAdapters(result.adapters ?? {}); })
        .catch(() => { /* adapter health stays unshown rather than invented */ });
    }
    if (typeof client.hitl === "function") {
      void client.hitl()
        .then((result) => { if (!cancelled) setPending((result.requests ?? []).length); })
        .catch(() => { /* a role that cannot read approval state shows a dash */ });
    }
    if (typeof client.budgets === "function") {
      void client.budgets()
        .then((result) => { if (!cancelled) setBudgets(result.budgets ?? []); })
        .catch(() => { /* the daily card says the ceiling is unreadable */ });
    }
    return () => { cancelled = true; };
  }, []);

  if (readiness === null) {
    return (
      <>
        {head && <HeadBlock headline="Checking what has to be working…" lead="" />}
      </>
    );
  }

  if (readiness === "unavailable") {
    return (
      <>
        {head && (
          <HeadBlock
            headline="Health could not be read"
            lead="Readiness could not be checked. Try again later."
          />
        )}
        <BoundariesCard />
      </>
    );
  }

  const entries = Object.entries(readiness.checks);
  const requiredFailing = entries
    .filter(([, check]) => check.required && !healthy(check.status) && check.status !== "disabled")
    .length;
  const optionalOff = entries
    .filter(([, check]) => !healthy(check.status) && (!check.required || check.status === "disabled"))
    .length;
  const healthyCount = entries.filter(([, check]) => healthy(check.status)).length;

  const headline = requiredFailing > 0
    ? `${requiredFailing} essential ${requiredFailing === 1 ? "check is" : "checks are"} not working`
    : "Everything essential is working";
  const lead = requiredFailing > 0
    ? "Work that depends on a failing check will stop."
    : optionalOff > 0
      ? `${optionalOff} optional ${optionalOff === 1 ? "check is" : "checks are"} off or degraded.`
      : "Every check is ready.";

  const daily = (budgets ?? []).find(
    (budget) => budget.window === "daily" && budget.cost_limit_micros !== null,
  );

  return (
    <>
      {head && <HeadBlock headline={headline} lead={lead} />}

      <div className="settings-stat-grid">
        <div className="settings-stat">
          <span className="settings-stat-label">Waiting on a person</span>
          <span className="settings-stat-value">{pending === null ? "—" : pending}</span>
          <span className="settings-stat-note">
            {pending === null ? "not readable with your role" : "approvals and questions in chat"}
          </span>
        </div>
        <div className="settings-stat">
          <span className="settings-stat-label">Checks passing</span>
          <span className="settings-stat-value">{healthyCount} of {entries.length}</span>
          <span className="settings-stat-note">required and optional together</span>
        </div>
        <div className="settings-stat">
          {daily ? (
            <>
              <span className="settings-stat-label">Spent today</span>
              <span className="settings-stat-value">{money(daily.spent_micros)}</span>
              <span className="settings-stat-note">of {money(daily.cost_limit_micros ?? 0)}{daily.hard_stop ? "" : " · does not stop work"}</span>
            </>
          ) : (
            <>
              <span className="settings-stat-label">Daily ceiling</span>
              <span className="settings-stat-value">{budgets === null ? "—" : "None"}</span>
              <span className="settings-stat-note">
                {budgets === null ? "not readable with your role" : "spend today is not bounded by a daily window"}
              </span>
            </>
          )}
        </div>
      </div>

      <SettingsGroup title="Everything that has to be working">
        {entries.map(([name, check]) => {
          const copy = CHECK_COPY[name];
          const { tone, state } = checkTone(check);
          return (
            <ToneRow
              key={name}
              state={state}
              sub={copy?.sub ?? check.reason ?? (check.required ? "Required" : "Optional")}
              tech={name}
              title={copy?.title ?? name}
              tone={tone}
            />
          );
        })}
        {entries.length === 0 && (
          <SettingsRow desc="No health checks were reported." title="Nothing to check" />
        )}
        {adapters && Object.entries(adapters).map(([key, value]) => {
          const label = key.includes("/") ? key.slice(key.indexOf("/") + 1) : key;
          const mapped = ADAPTER_TONE[value] ?? ADAPTER_TONE.unknown;
          return (
            <ToneRow
              key={`adapter:${key}`}
              state={mapped.state}
              sub="Last reported integration health"
              tech={key}
              title={`${label} adapter`}
              tone={mapped.tone}
            />
          );
        })}
      </SettingsGroup>

      <BoundariesCard />
    </>
  );
}

function HeadBlock({ headline, lead }: { headline: string; lead: string }) {
  return (
    <div className="settings-head">
      <h1>{headline}</h1>
      {lead && <p>{lead}</p>}
    </div>
  );
}

function BoundariesCard() {
  return (
    <SettingsGroup title="Current limits">
      {BOUNDARIES.map(([title, sub, state]) => (
        <ToneRow key={title} state={state} sub={sub} title={title} tone="unknown" />
      ))}
    </SettingsGroup>
  );
}
