import { useEffect, useState } from "react";
import type {
  BudgetItem,
  ConversationSummary,
  CostResponse,
  ReadinessCheck,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { settingsEntry, type SettingsSection } from "../settingsSections";

// The settings pane. Six sections are drawn here on the console idiom; the four
// that already have a working surface (You, Organisation, Knowledge, Advanced)
// are rendered by their existing views rather than reimplemented, because
// redrawing a working credential or roster surface to change its frame is how
// you lose one.

function money(micros: number): string {
  return `£${(micros / 1_000_000).toFixed(2)}`;
}

export function SettingsGroup({ title, children }: {
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="settings-group">
      {title && <div className="console-section-title">{title}</div>}
      <div className="console-table">{children}</div>
    </div>
  );
}

export function SettingsRow({ title, desc, tech, control }: {
  title: string;
  desc?: string;
  tech?: string;
  control?: React.ReactNode;
}) {
  return (
    <div className="settings-row">
      <div className="settings-row-main">
        <div className="console-row-title">
          <span>{title}</span>
          {tech && <span className="console-tech">{tech}</span>}
        </div>
        {desc && <div className="settings-row-desc">{desc}</div>}
      </div>
      {control}
    </div>
  );
}

function SectionHead({ section }: { section: SettingsSection }) {
  const entry = settingsEntry(section);
  return (
    <div className="settings-head">
      <h1>{entry.title}</h1>
      <p>{entry.lead}</p>
    </div>
  );
}

// --- Spending ---------------------------------------------------------------

function SpendingSection() {
  const [budgets, setBudgets] = useState<BudgetItem[]>([]);
  const [cost, setCost] = useState<CostResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      client.budgets().catch(() => null),
      client.cost().catch(() => null),
    ]).then(([budgetResult, costResult]) => {
      if (cancelled) return;
      if (!budgetResult && !costResult) {
        setState("unavailable");
        return;
      }
      setBudgets(budgetResult?.budgets ?? []);
      setCost(costResult);
      setState("ready");
    });
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <SectionHead section="spend" />
      {state === "loading" && <p className="muted small">Reading what work has cost…</p>}
      {state === "unavailable" && (
        <p className="notice">Spending is not readable with your current role.</p>
      )}
      {state === "ready" && (
        <>
          <SettingsGroup title="What it has cost">
            <SettingsRow
              title="Total so far"
              desc="Every governed call this workspace has paid for, in the scope you may see."
              control={<span className="settings-value">{money(cost?.total_cost_micros ?? 0)}</span>}
            />
            {Object.entries(cost?.by_actor ?? {}).slice(0, 8).map(([actor, micros]) => (
              <SettingsRow key={actor} title={actor} tech="actor"
                control={<span className="settings-value">{money(micros)}</span>} />
            ))}
          </SettingsGroup>
          <SettingsGroup title="Ceilings">
            {budgets.length === 0 ? (
              <SettingsRow
                title="No ceiling is set"
                desc="Nothing stops spend in this workspace except the limits on each provider key."
              />
            ) : budgets.map((budget) => {
              const limit = budget.cost_limit_micros;
              const pct = limit ? Math.round((budget.spent_micros / limit) * 100) : null;
              return (
                <SettingsRow
                  key={budget.id}
                  title={`${budget.scope_type} · ${budget.window}`}
                  desc={budget.hard_stop
                    ? "Work stops when this ceiling is reached."
                    : "This ceiling is recorded but does not stop work."}
                  tech={budget.id}
                  control={(
                    <span className="settings-value">
                      {limit === null
                        ? `${money(budget.spent_micros)} spent, no ceiling`
                        : `${money(budget.spent_micros)} of ${money(limit)}${pct === null ? "" : ` · ${pct}%`}`}
                    </span>
                  )}
                />
              );
            })}
          </SettingsGroup>
        </>
      )}
    </>
  );
}

// --- Autonomy ---------------------------------------------------------------

function AutonomySection() {
  const [budgets, setBudgets] = useState<BudgetItem[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    void client.budgets()
      .then((result) => { if (!cancelled) setBudgets(result.budgets); })
      .catch(() => { if (!cancelled) setBudgets([]); });
    return () => { cancelled = true; };
  }, []);

  const hardStops = (budgets ?? []).filter((budget) => budget.hard_stop).length;
  return (
    <>
      <SectionHead section="autonomy" />
      <SettingsGroup title="What stops a run">
        <SettingsRow
          title="Every consequential verb asks first"
          desc="Approval is decided by the kernel against the workspace policy, not by this client. Nothing here can widen it."
          tech="hitl"
        />
        <SettingsRow
          title="Ceilings that actually stop work"
          desc="A ceiling without a hard stop is recorded and reported, but it does not halt a run."
          control={(
            <span className="settings-value">
              {budgets === null ? "…" : `${hardStops} of ${budgets.length}`}
            </span>
          )}
        />
        <SettingsRow
          title="Credentials never reach this client"
          desc="Tools, credentials, memory and approvals stay server-side, so an autonomy setting here cannot leak one."
        />
      </SettingsGroup>
      {/* The decided target draws a three-way posture chooser here. This build
          has no posture to set: approval is policy-driven per verb, and drawing
          a chooser that wrote nothing would be a control that lies. */}
      <p className="console-foot">
        The decided target offers a three-way posture here. This build has no posture to set:
        what stops a run is decided per verb by workspace policy, so the honest thing to show is
        what that policy currently does.
      </p>
    </>
  );
}

// --- Health -----------------------------------------------------------------

function HealthSection() {
  const [checks, setChecks] = useState<Record<string, ReadinessCheck> | null>(null);
  const [status, setStatus] = useState("");
  useEffect(() => {
    let cancelled = false;
    void client.readiness()
      .then((result) => {
        if (cancelled) return;
        setChecks(result.checks ?? {});
        setStatus(result.status ?? "");
      })
      .catch(() => { if (!cancelled) setChecks({}); });
    return () => { cancelled = true; };
  }, []);

  // The kernel reports a healthy check as "ready" OR "ok", and a check that is
  // switched off as "disabled". Treating only "ready" as healthy painted an ok
  // check red and counted it as failing.
  const healthy = (value: string) => value === "ready" || value === "ok";
  const entries = Object.entries(checks ?? {});
  const notReady = entries.filter(([, check]) => !healthy(check.status));
  return (
    <>
      <SectionHead section="health" />
      <SettingsGroup title="Right now">
        <SettingsRow
          title="Overall"
          desc={notReady.length === 0
            ? "Every required check is ready."
            : `${notReady.length} of ${entries.length} checks are not ready.`}
          control={(
            <span className="settings-state" data-tone={healthy(status) ? "ok" : "warn"}>
              {status || "…"}
            </span>
          )}
        />
      </SettingsGroup>
      {entries.length > 0 && (
        <SettingsGroup title="Each check">
          {entries.map(([name, check]) => (
            <SettingsRow
              key={name}
              title={name}
              desc={check.reason || (check.required ? "Required for this build" : "Optional")}
              control={(
                <span className="settings-state" data-tone={healthy(check.status)
                  ? "ok"
                  : check.required && check.status !== "disabled" ? "bad" : "warn"}>
                  {check.status}
                </span>
              )}
            />
          ))}
        </SettingsGroup>
      )}
    </>
  );
}

// --- Keyboard shortcuts -----------------------------------------------------

const SHORTCUTS: Array<[string, Array<[string, string, string]>]> = [
  ["Getting around", [
    ["New chat", "Start something new", "⌘N"],
    ["Search everything", "Chats, routines, agents, settings", "⌘K"],
    ["Show or hide the sidebar", "", "⌘B"],
  ]],
  ["In a conversation", [
    ["Send", "Send what you have written", "↵"],
    ["New line", "Without sending", "⇧↵"],
  ]],
];

function ShortcutsSection() {
  return (
    <>
      <SectionHead section="shortcuts" />
      {SHORTCUTS.map(([group, rows]) => (
        <SettingsGroup key={group} title={group}>
          {rows.map(([label, desc, keys]) => (
            <SettingsRow
              key={label}
              title={label}
              desc={desc || undefined}
              control={<kbd className="settings-key">{keys}</kbd>}
            />
          ))}
        </SettingsGroup>
      ))}
      <p className="console-foot">
        Only the shortcuts this build actually binds are listed. An unassigned key is not shown as
        though it worked.
      </p>
    </>
  );
}

// --- Overnight --------------------------------------------------------------

function OvernightSection() {
  return (
    <>
      <SectionHead section="overnight" />
      <SettingsGroup title="What this build does">
        <SettingsRow
          title="Nothing runs overnight yet"
          desc="Nightly consolidation is designed (decision 0023: rebuild-from-base, craft, register and diversity gates, promotion as an audited action) but no scheduler in this build starts it, and no endpoint reports it."
        />
        <SettingsRow
          title="Nothing is learned on its own"
          desc="A run becomes a routine only when you save it. No adapter is promoted without an audited action."
        />
      </SettingsGroup>
      <p className="console-foot">
        The decided target draws an Overnight screen with what changed, what it had to prove and what
        it practised on. That screen is drawn against a capability this build does not have, so this
        section says so rather than showing an empty week.
      </p>
    </>
  );
}

// --- Archived chats ---------------------------------------------------------

function ArchivedSection() {
  const [rows, setRows] = useState<ConversationSummary[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [busy, setBusy] = useState("");

  async function load() {
    try {
      const result = await client.conversations();
      setRows((result.conversations ?? []).filter((row) => row.status === "closed"));
      setState("ready");
    } catch {
      setState("unavailable");
    }
  }
  useEffect(() => { void load(); }, []);

  async function restore(id: string) {
    setBusy(id);
    try {
      await client.restoreMyConversation(id);
      await load();
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <SectionHead section="archived" />
      {state === "loading" && <p className="muted small">Loading archived chats…</p>}
      {state === "unavailable" && <p className="notice">Archived chats could not be read.</p>}
      {state === "ready" && (
        <SettingsGroup>
          {rows.length === 0 ? (
            <SettingsRow title="Nothing is archived" desc="Closed chats appear here during the recovery window." />
          ) : rows.map((row) => (
            <SettingsRow
              key={row.id}
              title={row.title || "Untitled task"}
              desc="Closed · retained during the recovery window"
              control={(
                <button
                  className="console-lifecycle"
                  disabled={busy === row.id}
                  onClick={() => void restore(row.id)}
                  type="button"
                >{busy === row.id ? "Bringing back…" : "Bring back"}</button>
              )}
            />
          ))}
        </SettingsGroup>
      )}
    </>
  );
}

export function SettingsSectionPane({ section }: { section: SettingsSection }) {
  if (section === "spend") return <SpendingSection />;
  if (section === "autonomy") return <AutonomySection />;
  if (section === "health") return <HealthSection />;
  if (section === "shortcuts") return <ShortcutsSection />;
  if (section === "overnight") return <OvernightSection />;
  if (section === "archived") return <ArchivedSection />;
  return null;
}
