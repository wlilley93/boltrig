import { useEffect, useState } from "react";
import type { BudgetItem, CostResponse } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { money, shortDate } from "./format";
import { SectionHead } from "./SectionHead";
import { SettingsGroup, SettingsRow } from "./rowKit";

// Spending on the design's composition: one card of what it has cost and the
// labelled meters per ceiling, one card of where it went, and the reservation
// explainer. The design also draws a plan row, a balance with a top-up
// button, and a weekly window — no plan, balance, payment or weekly-window
// concept exists in the SDK or kernel, so those are omitted rather than
// rendered as controls that lie. Attribution is per actor because that is
// what /v1/cost measures; it is not dressed up as a weekly per-routine list.

const WINDOW_LABEL: Record<BudgetItem["window"], string> = {
  run: "Each run",
  daily: "Today",
  monthly: "This month",
};

function meterLabel(budget: BudgetItem): string {
  const window = WINDOW_LABEL[budget.window] ?? budget.window;
  return budget.scope_type === "tenant" ? window : `${window} · ${budget.scope_type}`;
}

function Meter({ budget }: { budget: BudgetItem }) {
  const limit = budget.cost_limit_micros ?? 0;
  const pct = limit > 0 ? Math.min(100, Math.round((budget.spent_micros / limit) * 100)) : 0;
  const reset = shortDate(budget.window_ends_at);
  const note = [
    budget.hard_stop
      ? "Work stops when this ceiling is reached"
      : "Recorded and reported, but does not stop work",
    reset ? `Resets ${reset}` : "",
  ].filter(Boolean).join(" · ");
  return (
    <div className="settings-meter">
      <div className="settings-meter-head">
        <span className="settings-meter-label">{meterLabel(budget)}</span>
        <span className="settings-meter-used">{money(budget.spent_micros)}</span>
        <span className="settings-meter-cap">of {money(limit)}</span>
      </div>
      <div aria-hidden className="settings-meter-track">
        <div className="settings-meter-fill" data-hot={pct > 85} style={{ width: `${pct}%` }} />
      </div>
      <span className="settings-meter-note">{note}</span>
    </div>
  );
}

export function SpendingSection({ head = true }: { head?: boolean }) {
  const [budgets, setBudgets] = useState<BudgetItem[]>([]);
  const [cost, setCost] = useState<CostResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  // Each read fails on its own. A failed read is an unknown, never a zero and
  // never "no ceiling is set"; and a failure is only attributed to the
  // viewer's role when the server actually said 403.
  const [budgetsRead, setBudgetsRead] = useState(false);
  const [costRead, setCostRead] = useState(false);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const forbidden = (reason: unknown) =>
      typeof reason === "object" && reason !== null && "status" in reason
        && (reason as { status?: number }).status === 403;
    void Promise.allSettled([client.budgets(), client.cost()])
      .then(([budgetResult, costResult]) => {
        if (cancelled) return;
        if (budgetResult.status === "rejected" && costResult.status === "rejected") {
          setDenied(forbidden(budgetResult.reason) || forbidden(costResult.reason));
          setState("unavailable");
          return;
        }
        if (budgetResult.status === "fulfilled") {
          setBudgets(budgetResult.value.budgets ?? []);
          setBudgetsRead(true);
        }
        if (costResult.status === "fulfilled") {
          setCost(costResult.value);
          setCostRead(true);
        }
        setState("ready");
      });
    return () => { cancelled = true; };
  }, []);

  if (state === "loading") {
    return (
      <>
        {head && <SectionHead section="spend" />}
        <p className="muted small">Reading what work has cost…</p>
      </>
    );
  }
  if (state === "unavailable") {
    return (
      <>
        {head && <SectionHead section="spend" />}
        <p className="notice">
          {denied
            ? "Spending is not readable with your current role."
            : "Spending could not be read just now. This says nothing about what has been spent."}
        </p>
      </>
    );
  }

  const metered = budgets.filter((budget) => budget.cost_limit_micros !== null);
  const unmetered = budgets.filter((budget) => budget.cost_limit_micros === null);
  const actors = Object.entries(cost?.by_actor ?? {}).sort(([, a], [, b]) => b - a);
  const shown = actors.slice(0, 6);
  const rest = actors.slice(6).reduce((sum, [, micros]) => sum + micros, 0);

  return (
    <>
      {head && <SectionHead section="spend" />}

      <SettingsGroup title="What it has cost">
        <SettingsRow
          control={
            <span className="settings-value">
              {costRead ? money(cost?.total_cost_micros ?? 0) : "not readable"}
            </span>
          }
          desc={costRead
            ? "Every governed call this workspace has paid for, in the scope you may see."
            : "The total could not be read just now, so none is stated."}
          title="Total so far"
        />
        {!budgetsRead && (
          <SettingsRow
            desc="Ceilings could not be read just now. Whether one is set is unknown here."
            title="Ceilings unavailable"
          />
        )}
        {budgetsRead && budgets.length === 0 && (
          <SettingsRow
            desc="Nothing stops spend in this workspace except the limits on each provider key."
            title="No ceiling is set"
          />
        )}
        {metered.map((budget) => <Meter budget={budget} key={budget.id} />)}
        {unmetered.map((budget) => (
          <SettingsRow
            control={<span className="settings-value">{money(budget.spent_micros)} spent, no ceiling</span>}
            desc={budget.token_limit !== null
              ? "This ceiling counts tokens, not money."
              : "Recorded spend without a money ceiling."}
            key={budget.id}
            tech={budget.id}
            title={meterLabel(budget)}
          />
        ))}
      </SettingsGroup>

      {actors.length > 0 && (
        <SettingsGroup
          eyebrow
          foot="Attributed per actor since the record began, in the scope you may see. The kernel keeps no weekly window, so none is drawn."
          title="Where it went"
        >
          {shown.map(([actor, micros]) => (
            <SettingsRow
              control={<span className="settings-value">{money(micros)}</span>}
              key={actor}
              tech="actor"
              title={actor}
            />
          ))}
          {rest > 0 && (
            <SettingsRow
              control={<span className="settings-value">{money(rest)}</span>}
              title="Everything else"
            />
          )}
        </SettingsGroup>
      )}

      <p className="console-foot">
        Every run reserves its ceiling before it starts and gives back what it did not use, so
        nothing can quietly overspend. A ceiling with a hard stop halts new work when it is
        reached; one without is recorded and reported but stops nothing.
      </p>
    </>
  );
}
