# PROPOSAL: a native tables surface in Boltrig

- Status: deferred (parked by the Principal on 2026-08-22 in favour of
  hardening the hosted client/server shape; nothing here is scheduled)
- Date: 2026-08-22
- Related: `docs/SPEC-capability-doctrine.md` (canonical capabilities,
  mapping packs), decisions 0029 (typed memory planes), 0030 (Opbox surfaces
  built on the web SDK), 0031 (Opbox ships as a plugin), 0035 (presence equals
  provisioning), 0037 (per-run capability projection budget), 0034 (Files /
  tiptap deferred)

## Why this file exists

The question "can a Boltrig agent add to or see Opbox Tables when Opbox is
not installed?" has the answer no, and the reason is a real gap rather than a
wiring gap: Boltrig has no generic user-data store. This page records the
design that was worked out when the question was asked so it is not lost. It
is a proposal, not a plan.

## The gap, measured 2026-08-22

- Opbox Tables live in Opbox's own Postgres (Prisma `Table`, `TableColumn`,
  `TableRow`, satellites) and are reached by agents only through Opbox's MCP
  door (`src/lib/mcp/tool-catalog.ts`, `tables` family). Boltrig's
  `boltrig/capabilities/packs/opbox.yaml` is dormant until an Opbox door is
  registered and maps only the matter domain; `boltrig/addons/opbox.py` is
  inert without `BOLTRIG_ADDONS=opbox`; `McpConsumerAdapter` fails closed
  without a registered door and bearer.
- Boltrig's own schema (`boltrig/store/schema.sql`, 137 tables at head 0084)
  has no records/collections/key-value store beyond per-user
  `user_settings`. `document.*` verbs are Microsoft Graph, `contact.*` is a
  read-scoped reference SQL adapter over an external `contacts` table,
  `ticket.*` is an in-process dict. The nearest stores are `artifacts`
  (files with revisions), `knowledge_*` (documents plus vault) and
  `memory_*` (governed memory).
- Chat history is a ledger, not a dataset: `conversations` and
  `conversation_messages` (tool events and attachments inline as JSONB,
  append-plus-supersede, owner-scoped, 30-day purge of closed threads). A
  tables surface should be able to receive from it (rows written during a
  turn with `run_id` / `conversation_id` provenance), never re-house it.

## The design, if it is ever built

1. Physical model: adopt the Opbox kernel's fact-per-cell schema, not the
   Prisma JSON blob. `data_table` / `data_column` / `data_row` / `data_fact`
   (opbox-kernel `migrations/0026_data_plane.sql`): stable `column.key`
   separate from display name; row = identity plus order plus archive; one
   fact per (row, column); `is_computed` GENERATED so formula, link, lookup
   and rollup columns structurally hold no fact; per-cell PII encryption and
   locks as typed columns. Translate into Boltrig conventions: composite
   `PRIMARY KEY (tenant_id, id)`, nullable `workspace_id` through
   `boltrig/store/workspace_scope.py`, an `owner_scope` string as memory and
   knowledge use, an entry in the `scoped` array of `boltrig/store/rls.sql`,
   a raw-SQL Alembic revision, the `EXPECTED_ALEMBIC_HEAD` bump, a frozen
   dataclass plus store contract with Postgres and in-memory implementations.
   The schema-parity and RLS-coverage tests enforce all of this.
2. Cell edits as fact versions, not in-place updates: append a new fact and
   mark the old one superseded; the current view reads the latest. This keeps
   the house pattern (chat, memory) and yields row revisions for free.
3. Verb surface: one builtin adapter (`boltrig/adapters/builtin/tables.py`)
   whose `describe()` returns `VerbSpec`s with `noun_id="table"` and
   level-1 `implements` names (`table.row.create@1` and so on), registered by
   one line in `boltrig/api/bootstrap.py`; no kernel change. A v1 family of
   about twelve verbs: `table.create/get/list/archive/delete`,
   `column.add/update/delete`, `row.create/get/list/patch/delete`,
   `row.bulk`, `cell.set`; `row.patch` with the operation vocabulary
   `set | unset | append | remove | increment | replace_text`.
   `mcp_resources()` exposing `boltrig://tables/{id}` for read-through (the
   knowledge adapter is the precedent). Satellites (comments, presence,
   webhooks, favourites, view sharing) stay out of v1 because of the
   128-tool offer cliff (decision 0037).
4. Consequence tiers (a decision for the Principal): reads low; additive row
   and cell writes low (reversible through versions, posture still applies);
   schema changes, `table.delete` and bulk delete high (HITL-gated).
5. Formula engine: a Python port of Opbox's pure recursive-descent engine
   (37 functions, no eval, depth cap, field-reference resolution exact name,
   then column id, then case-insensitive). FORMULA columns in v1; LINK,
   LOOKUP and ROLLUP later.
6. The doctrine payoff: one canonical capability, two providers. The dormant
   Opbox pack can map `opbox.get_table_rows` to `table.row.list@1` and so on,
   so with Opbox present the routing policy prefers the Opbox binding and the
   native store yields (and the Worker's Tables tab hides, the Agents-tab rule
   of decision 0035 in reverse); Boltrig-only deployments get the native
   store. Whether the native store yields or coexists in combined
   deployments is the one product decision in this proposal; the
   recommendation is yield.
7. UI: a `tables` route in `apps/worker/src/routes.ts`, a case in
   `AppRouteSurface.tsx`, a `ShellNav.tsx` primary item, a `CommandPalette.tsx`
   row; client methods in `sdks/web/src/client.ts` so Opbox can render the
   same surface natively (decision 0030).
8. Desktop: tables are server data; cloud tasks write them; local tasks
   cannot until the decision 0027 import/export contract exists.

## What the same substrate would buy beyond tables

- "Which users have the desktop installed and in how many instances" is
  already answerable from `devices` / `device_enrollments`; a read, not a
  build.
- A Boltrig-only Files tab (deferred by decision 0034) already has its
  backend in `artifacts` plus the knowledge vault; what is missing is UI.
- The `crm_sql` reference adapter could bind to a native contacts table.
- Routine outputs landing as rows, and structured working state for agents,
  which decision 0029 keeps out of memory.

## Incidental findings recorded while the design was worked out

- Opbox's AI/MCP table handlers wrote Prisma-direct while the HTTP routes go
  through the kernel seam; being fixed separately (branch
  `fix/ai-table-writes-via-kernel-seam` in the opbox frontend repo).
- The "kernel table verbs" wording in `PLAN-opbox-boltrig-merge-2026-08-17.md`
  and decision 0034 meant the `tables.*` (plural) family; corrected in place.
- The jellytot-apps `tables` template referenced in working notes is not
  present on the build box; only its build note exists.

## Decisions that would be needed before anyone builds

Noun name (`table` versus `record`), the consequence tiers in point 4, the
combined-deployment behaviour in point 6, whether computed columns ship in
v1, and, above all, whether a Boltrig-only customer exists who needs it. Per
decision 0034's logic, the revisit trigger is a paying Boltrig-only
deployment that needs tables.
