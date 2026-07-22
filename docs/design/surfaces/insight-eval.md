# Insight and Eval surfaces: ratified specification

Status: **ratified 2026-07-21**. Routes: `#/insight` and `#/eval`. This closes the
observability IA gate in the Enhancement Charter.

## 1. Mental model

Insight answers three operator questions in order:

1. **Overview:** What ran, what did it cost, and is anything outside posture?
2. **Audit:** What exactly happened, in order, under which actor and run?
3. **Budgets:** What limits govern spend, and where is usage approaching them?

Eval answers two engineering questions:

1. **Run cases:** Does a saved case pass now, and which grants did its run actually receive?
2. **Create case:** What repeatable behavior and permission boundary should be tested?

These are task modes inside two existing deck surfaces. Insight and Eval remain separate because
one observes production truth while the other intentionally executes a test. They share run links,
scope language, status badges, and the kernel's event truth.

## 2. Insight contract

Overview is the calm default. Cost and recent runs are visible together; run ids open the global
run drawer. **Refresh** is the one primary action.

Audit contains the filter form and result table. **Search** is the one primary action. Results are
scope-filtered, use human column labels, show relative time with absolute time on hover, link run
ids, and place the complete event inside an Inspect disclosure. Export is secondary and faithfully
renders server denial.

Budgets contains the scoped budget list and, for authorised operators, one typed policy editor.
Budget usage uses warning and failure tones, never consequence amber. Amber appears only on the
governed `control.budget.*` request and PendingHumanCard. A viewer gets **Refresh budgets** as the
one primary action; an operator gets **Request policy change**.

The editor must state the current enforcement boundary: the fleet spawner applies organisation and
department budgets to spawned agent work. Workflow scope and window values are persisted policy
metadata, not automatic enforcement or rollover; counter reset is an explicit governed operation.

## 3. Eval contract

Run cases is the default. A person selects a saved case, presses **Run case**, sees pass or fail,
score, a RunLink, effective grants, and inspectable structured detail. History rows link to the
same run drawer. No raw run id is presented as dead text when a run exists.

Create case is a separate mode with one **Request case change** primary. Target kind is segmented;
target is a considered picker; forbidden grants are guided chips. Case input defaults to `{}` and
is available only through JsonDisclosure because the target-specific schema is not guaranteed.
Assertions expose the supported forbidden-grants control first and keep full JSON advanced. Any
invalid JSON blocks submission. The consequence-high save copy and approval flow follow D6-D7.

## 4. State and accessibility contract

Each task mode follows P24 precedence and keeps stale data through refresh. Status is always label
plus tone. Runs, actors, verbs, case ids, and grants are mono. Tables support compact density and
horizontal overflow. Every mode exposes one primary control at rest. Reduced motion removes all
decorative transitions without hiding live state.

## 5. Chat parity

| UI action | Verb path | Chat phrasing | Status |
|---|---|---|---|
| Search audit | shared `GET /v1/audit/search` read | "Show denied ticket actions by Alex this week." | exists |
| Export audit | shared scoped export route | "Export the audit events in my scope." | exists |
| Set budget | `control.budget.upsert` | "Set a hard-stop budget for the support department." | exists for spawned work at organisation and department scope |
| Reset budget usage | `control.budget.reset` | "Reset support's usage counters." | exists; rollover is manual |
| Create or update eval case | `control.eval_case.upsert` | "Create a regression case for triage that must never use ticket.delete." | exists |
| Run eval case | `POST /v1/eval/run`, with the target execution routed through kernel verbs | "Run the safe-triage evaluation case." | console exists; first-class chat verb is a parity dependency |

## 6. Acceptance

- Insight defaults to a quiet Overview and Eval defaults to Run cases.
- Every run id is a RunLink when the id is in scope.
- Budget warning colour is never confused with HITL consequence colour.
- Budget scope and window seams are stated beside the policy editor.
- Eval effective grants remain visible beside the result.
- Arbitrary input and assertion JSON are advanced disclosures, never primary controls.
- Each task mode has exactly one primary action and faithful denied, error, empty, and ready states.
