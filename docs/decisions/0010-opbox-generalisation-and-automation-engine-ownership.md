# 0010 - Opbox generalisation and automation engine ownership

- Status: accepted
- Date: 2026-07-04
- Court: VJS First Instance addendum, paired with decisions 0003 and 0009

## Context

The Opbox transition can move in two directions:

1. Use Boltrig as a pinned runtime behind Opbox's existing frontend/kernel.
2. Generalise useful Opbox agent-platform ideas back into Boltrig so future repos
   do not need Opbox-specific glue.

The second direction raises a different risk: Opbox already owns workflow
automation, cron/Hatchet resume, workflow runs, and `agenttask` lifecycle. Boltrig
also has workflow/runtime primitives. If both engines try to own scheduling,
state, retries, pause/resume, and completion for the same workflow, the system can
double-run tasks, lose resumes, split audit, and create conflicting truth.

## Questions Presented

1. May Boltrig generalise Opbox concepts into reusable platform features?
2. May Opbox and Boltrig both own automation execution in one deployed tenant?
3. Is drainer migration the same as automation-engine migration?
4. Can automation be migrated piecemeal?

## Answers

1. **Yes, but only as generic platform contracts.** Generalise the patterns, not
   Opbox business tables or product-specific semantics.
2. **No.** For a given workflow domain in a deployed tenant, there is one
   automation engine of record. Scheduling, run state, pause/resume, retries,
   ownership, and audit must not be split across competing engines.
3. **No.** A drainer is a worker/executor for queued agent work. It can be
   replaced while Opbox remains the workflow engine. That is not the same as
   making Boltrig own workflow definitions and workflow runs.
4. **Yes, but only at explicit boundaries.** You may route selected task labels
   or selected whole workflow domains to a different engine. You must not split a
   single workflow run's state machine across two engines.

## Decision

Boltrig will generalise Opbox-derived lessons into reusable contracts:

- host-agent communications facade
- prompt/profile fixture packs and golden tasks
- external host-kernel MCP mode
- approval continuation
- host-owned conversation mode
- queue worker/drainer profile
- billing/usage event contract
- tool catalog drift checks
- auth bridge separating request gate credentials from execution credentials
- operator runbook and observability conventions

Boltrig will **not** absorb Opbox as business logic, duplicate Opbox workflow
tables, or compete with Opbox's workflow engine inside the same deployment.

For Opbox specifically:

- During the pinned-runtime transition, Opbox remains the automation engine of
  record.
- Phase 2 frontend consolidation may move agent-facing UI into the Opbox
  Automations tab, but that is an information-architecture change, not an engine
  ownership change.
- Boltrig may replace `agent-chat`.
- Boltrig may replace the `agent.run` drainer after parity.
- Boltrig does not own workflow definitions, workflow runs, schedules, cron,
  Hatchet resume, or workflow audit unless a later full engine migration is
  explicitly ordered.

## Binding Conditions

1. One workflow engine of record per workflow domain.
2. One scheduler/resume authority per workflow domain.
3. One audit source of truth per business action.
4. A Boltrig drainer must speak the host queue contract; it must not invent its
   own task lifecycle beside Opbox's `agenttask` lifecycle.
5. A later full automation-engine migration must move whole workflow domains, not
   half of one workflow run.
6. Reverse generalisation must produce Boltrig contracts, fixtures, and adapters,
   not hard-coded Opbox tables or feature assumptions.
7. Rollback must restore the prior engine/worker boundary without repairing
   split workflow state.

## Consequences

- The current migration remains safe: chat first, drainer second, automation
  engine ownership unchanged.
- Future Boltrig repos benefit from Opbox's mature patterns without inheriting
  Opbox's product database.
- If we later want Boltrig to own automations, that is a separate all-engine
  migration decision, not a side effect of replacing the drainer.
