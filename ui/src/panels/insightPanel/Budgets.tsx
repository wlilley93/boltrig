import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { BudgetItem, BudgetPolicyRequest } from "@/api/types";
import { useIdentity } from "@/identity";
import { FetchError, Field, Select } from "@/panels/ux";
import {
  ArmConfirm,
  PendingHumanCard,
  useControlMutation,
} from "@/panels/uxFlow";
import { useFetch } from "@/useFetch";

import { money, pct } from "./formatting";

const ADMIN_ROLES = new Set(["superadmin", "org-admin", "admin"]);
const SCOPE_OPTIONS = [
  { value: "tenant", label: "Organisation" },
  { value: "department", label: "Department" },
  { value: "workflow", label: "Workflow" },
];
const WINDOW_OPTIONS = [
  { value: "run", label: "Per run" },
  { value: "daily", label: "Daily" },
  { value: "monthly", label: "Monthly" },
];

function useBudgetMutations(reload: () => void) {
  const [message, setMessage] = useState<string | null>(null);
  const upsert = useControlMutation({
    verb: "control.budget.upsert",
    onApplied: () => {
      setMessage("Budget policy approved and applied.");
      reload();
    },
  });
  const reset = useControlMutation({
    verb: "control.budget.reset",
    onApplied: () => {
      setMessage("Budget usage reset approved and applied.");
      reload();
    },
  });
  return { upsert, reset, message, setMessage };
}

function BudgetPolicyForm({
  tenant,
  mutation,
  editingBudget,
}: {
  tenant: string;
  mutation: ReturnType<typeof useControlMutation>;
  editingBudget: BudgetItem | null;
}) {
  const [scopeType, setScopeType] = useState<BudgetItem["scope_type"]>("tenant");
  const [scopeId, setScopeId] = useState(tenant);
  const [windowName, setWindowName] = useState<BudgetItem["window"]>("monthly");
  const [tokenLimit, setTokenLimit] = useState("");
  const [costLimit, setCostLimit] = useState("");
  const [hardStop, setHardStop] = useState(true);

  useEffect(() => {
    if (editingBudget === null) return;
    const budget = editingBudget;
    setScopeType(budget.scope_type);
    setScopeId(budget.id);
    setWindowName(budget.window);
    setTokenLimit(budget.token_limit?.toString() ?? "");
    setCostLimit(
      budget.cost_limit_micros === null
        ? ""
        : (budget.cost_limit_micros / 1_000_000).toString(),
    );
    setHardStop(budget.hard_stop);
  }, [editingBudget]);

  const tokenValue = tokenLimit.trim() === "" ? undefined : Number(tokenLimit);
  const costValue = costLimit.trim() === "" ? undefined : Number(costLimit);
  const valid =
    scopeId.trim() !== "" &&
    (tokenValue !== undefined || costValue !== undefined) &&
    (tokenValue === undefined || (Number.isInteger(tokenValue) && tokenValue >= 0)) &&
    (costValue === undefined || (Number.isFinite(costValue) && costValue >= 0));

  async function save() {
    if (!valid) return;
    const params: BudgetPolicyRequest = {
      scope_type: scopeType,
      scope_id: scopeId.trim(),
      hard_stop: hardStop,
      window: windowName,
    };
    if (tokenValue !== undefined) params.token_limit = tokenValue;
    if (costValue !== undefined) {
      params.cost_limit_micros = Math.round(costValue * 1_000_000);
    }
    await mutation.invoke({ ...params });
  }

  return (
    <div className="budget-policy">
      <div className="budget-policy__head">
        <div>
          <strong>Budget policy</strong>
          <p className="ux-hint">Changes pause for human approval before taking effect.</p>
          <p className="notice warn">
            Enforcement currently covers spawned agent work at organisation and department scope.
            Workflow scope and window values are policy metadata; usage resets are
            operator-triggered. Realtime voice and direct paid-adapter usage are not debited.
          </p>
        </div>
      </div>
      <div className="form__grid budget-policy__grid">
        <Field label="Scope">
          <Select
            value={scopeType}
            ariaLabel="Budget scope"
            onChange={(value) => {
              const next = value as BudgetItem["scope_type"];
              setScopeType(next);
              if (next === "tenant") setScopeId(tenant);
            }}
            options={SCOPE_OPTIONS}
          />
        </Field>
        <Field label="Scope id" required>
          <input
            aria-label="Budget scope id"
            value={scopeId}
            disabled={scopeType === "tenant"}
            onChange={(event) => setScopeId(event.target.value)}
            placeholder={scopeType === "workflow" ? "workflow id" : "department id"}
          />
        </Field>
        <Field
          label="Window tag"
          hint="Recorded with the policy. Counters reset only when an operator requests Reset usage."
        >
          <Select
            value={windowName}
            ariaLabel="Budget window"
            onChange={(value) => setWindowName(value as BudgetItem["window"])}
            options={WINDOW_OPTIONS}
          />
        </Field>
        <Field label="Token limit" hint="Leave blank to meter cost only.">
          <input
            aria-label="Token limit"
            type="number"
            min="0"
            step="1"
            value={tokenLimit}
            onChange={(event) => setTokenLimit(event.target.value)}
          />
        </Field>
        <Field label="Cost limit (USD)" hint="Stored precisely as integer micros.">
          <input
            aria-label="Cost limit (USD)"
            type="number"
            min="0"
            step="0.01"
            value={costLimit}
            onChange={(event) => setCostLimit(event.target.value)}
          />
        </Field>
        <label className="budget-policy__toggle">
          <input
            type="checkbox"
            checked={hardStop}
            onChange={(event) => setHardStop(event.target.checked)}
          />
          <span>
            {scopeType === "workflow"
              ? "Stored hard-stop flag (not enforced)"
              : "Stop spawned agent work at the limit"}
          </span>
        </label>
      </div>
      <div className="form__actions">
        <button
          type="button"
          className="btn btn--primary"
          disabled={!valid || mutation.busy || mutation.pending !== null}
          onClick={() => void save()}
        >
          {mutation.busy ? "Requesting..." : "Request policy change"}
        </button>
        {!valid && <span className="ux-hint">Set a scope and at least one valid limit.</span>}
      </div>
    </div>
  );
}

function BudgetRow({
  budget,
  onEdit,
  reset,
}: {
  budget: BudgetItem;
  onEdit: (budget: BudgetItem) => void;
  reset: ReturnType<typeof useControlMutation>;
}) {
  const tokenPercent = pct(budget.spent_tokens, budget.token_limit);
  const costPercent = pct(budget.spent_micros, budget.cost_limit_micros);
  const worst = Math.max(tokenPercent ?? 0, costPercent ?? 0);

  async function resetUsage() {
    await reset.invoke({
      scope_type: budget.scope_type,
      scope_id: budget.id,
      reason: "Operator reset from browser console",
      reset_tokens: true,
      reset_cost: true,
    });
  }

  return (
    <div className="budget-row">
      <div className="budget-row__head">
        <div className="kv">
          <code className="tag">{budget.scope_type}</code>
          <strong>{budget.id}</strong>
          <span className="muted">{budget.window} tag · manual reset</span>
          {budget.scope_type === "workflow" ? (
            <span className="badge" title="No runtime consumer debits workflow scopes yet.">
              stored only
            </span>
          ) : budget.hard_stop && (
            <span
              className="badge badge--conseq-high"
              title="Spawned agent work stops at the limit."
            >
              spawned-work hard stop
            </span>
          )}
        </div>
        <div className="kv">
          <button type="button" className="btn btn--sm" onClick={() => onEdit(budget)}>
            Edit
          </button>
          <ArmConfirm
            label="Reset usage"
            armLabel={<>Reset both usage counters for <code>{budget.id}</code>? Limits stay unchanged.</>}
            confirmLabel="Confirm reset"
            tone="consequence"
            busyLabel="Requesting..."
            disabled={reset.pending !== null}
            onConfirm={resetUsage}
          />
        </div>
      </div>
      <div
        className="budget-bar"
        title={`${worst}% of the tightest limit used`}
        role="progressbar"
        aria-valuenow={worst}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${budget.id} budget: ${worst}% used`}
      >
        <span
          className={`budget-bar__fill ${worst >= 90 ? "is-down" : worst >= 70 ? "is-warn" : ""}`}
          style={{ width: `${worst}%` }}
        />
      </div>
      <div className="kv budget-row__metrics">
        {budget.token_limit !== null && (
          <span className="muted">
            tokens {budget.spent_tokens.toLocaleString()} / {budget.token_limit.toLocaleString()}
          </span>
        )}
        {budget.cost_limit_micros !== null && (
          <span className="muted">
            cost {money(budget.spent_micros)} / {money(budget.cost_limit_micros)}
          </span>
        )}
      </div>
    </div>
  );
}

export function Budgets() {
  const identity = useIdentity();
  const canManage = ADMIN_ROLES.has(identity.role);
  const budgets = useFetch(() => api.budgets(), []);
  const list = budgets.data?.budgets ?? [];
  const mutations = useBudgetMutations(budgets.reload);
  const [editingBudget, setEditingBudget] = useState<BudgetItem | null>(null);

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Budgets</h3>
        <button
          className={`btn${canManage ? "" : " btn--primary"}`}
          onClick={() => budgets.reload()}
        >
          {canManage ? "Refresh" : "Refresh budgets"}
        </button>
      </div>
      <div className="list-card__body">
        {canManage && (
          <BudgetPolicyForm
            tenant={identity.tenant}
            mutation={mutations.upsert}
            editingBudget={editingBudget}
          />
        )}
        {mutations.message && <p className="ok">{mutations.message}</p>}
        {(mutations.upsert.error ?? mutations.reset.error) && (
          <p className="error">{mutations.upsert.error ?? mutations.reset.error}</p>
        )}
        {mutations.upsert.pending && (
          <PendingHumanCard
            hitlRequestId={mutations.upsert.pending.id}
            noun="control"
            verb="control.budget.upsert"
            sentParams={mutations.upsert.pending.params}
            onApplied={mutations.upsert.onPendingApplied}
            onDenied={mutations.upsert.onPendingDenied}
            onReset={mutations.upsert.resetPending}
          />
        )}
        {mutations.reset.pending && (
          <PendingHumanCard
            hitlRequestId={mutations.reset.pending.id}
            noun="control"
            verb="control.budget.reset"
            sentParams={mutations.reset.pending.params}
            onApplied={mutations.reset.onPendingApplied}
            onDenied={mutations.reset.onPendingDenied}
            onReset={mutations.reset.resetPending}
          />
        )}
        {budgets.loading && !budgets.data && <p className="muted">Loading...</p>}
        <FetchError error={budgets.error} status={budgets.errorStatus} onRetry={budgets.reload} />
        {!budgets.loading && !budgets.error && list.length === 0 && (
          <p className="muted">No budgets set. Add one above to cap token or cost spend.</p>
        )}
        {list.map((budget) => (
          <BudgetRow
            key={`${budget.scope_type}:${budget.id}`}
            budget={budget}
            onEdit={setEditingBudget}
            reset={mutations.reset}
          />
        ))}
      </div>
    </div>
  );
}
