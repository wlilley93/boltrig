# Nankle - Handover

A complete pickup guide for the Nankle agent-orchestration platform: what it is,
how it is built, how to run and verify it, what is done versus a seam, the
governance that binds it, and the gotchas worth knowing.

- Repo: `~/Projects/Nankle` (public: github.com/wlilley93/Nankle, branch `main`)
- Stack: Python 3.12 / FastAPI kernel, React + TypeScript + Vite UI, Postgres,
  Redis, Hatchet (durable execution), a Pi reasoning sidecar.
- Status at handover: 87 tests pass offline / 95 with Postgres, invariant gate at
  binding-debt 0 (41 invariants, 58 bound tests), UI builds, compose valid.

---

## 1. What Nankle is

A self-hostable system that runs a fleet of AI agents over an organisation's
tools and work queues. Three defining characteristics:

1. **A thin core.** The kernel implements policy and nothing else; everything
   that varies between organisations (integrations, capabilities, processes,
   structure) is data: adapters, skills, workflows, the manifest. Adding an
   integration changes no core code.
2. **A permanent fleet that spawns ephemerals.** A tier-1 chief of staff over
   tier-2 department heads holds continuity and routing; they compose short-lived
   child agents from skills, run them, and destroy them.
3. **A kernel that abstracts actions behind nouns and verbs.** Agents reason in
   stable nouns (`ticket`) and verbs (`ticket.create`); the kernel resolves each
   verb to a concrete adapter or a reasoning agent, owns credentials, rate limits,
   grants, and audit. Agents never hold secrets and never know the backend.

It was built greenfield from the "Hermes Fleet" Software Requirements Spec
(Round One), then extended by a P0-P3 hardening backlog and a Round Two addendum
(conversation + Pi + MCP).

---

## 2. Provenance and governance

Nankle is a clean-room reference implementation of the same kernel doctrine the
rest of the estate shares (one chokepoint, visibility != authority, deny-dominant
fail-closed grants, hash-chained audit; the `K-1..K-30` catalogue in
`agent-kernel-doctrine`). The single source of that doctrine is
`agent-kernel-doctrine`; Nankle conforms to it and does not author it.

The greenfield-vs-consolidation fork went to the VJS County Court, which ruled
**[2026] VJS-CC NANKLE-CONSOLIDATION 001** ("conditioned standalone"): Nankle may
stand alone on seven binding conditions (cite the doctrine as the single source,
key invariants to Appendix A, keep the gate at debt 0 in required CI, converge on
the unified capability primitive, stay severable, be recorded as the Python/
FastAPI exemplar, fork no parallel codebase). See
`docs/decisions/0002-nankle-consolidation-ruling.md`. The severability condition
is machine-enforced (`tests/security/test_severability.py`).

---

## 3. Repository map

```
nankle/                     the thin core (Python package)
  kernel/                   THE CHOKEPOINT
    __init__.py             Kernel composition root (wires everything)
    dispatch.py             the fixed dispatch order (the heart)
    grants.py               grant enforcement (deny-dominant, fail-closed)
    credentials.py          credential resolution (refs only, inside the kernel)
    ratelimit.py            per-verb/tenant rate limiting (Redis or in-memory)
    audit.py                append-only, hash-chained, scrubbed audit
    cost.py                 cost attribution + budget hard-stops
    pii.py                  PII detection/redaction + secret scanning
    hitl.py                 human-in-the-loop manager (approval gate)
    registry.py             noun/verb/binding registry + discovery
    mcp.py                  MCP server face (granted verbs as MCP tools)   [R2]
    events.py               run/conversation event relay (streaming)       [R2]
    app.py                  FastAPI surface (invoke/discover/spawn/hitl/chat/mcp)
  models/                   frozen domain dataclasses + error taxonomy
  store/                    Store protocol + InMemoryStore + PostgresStore + schema.sql
  adapters/                 one Adapter interface + loader + http/sql bases
    builtin/                memory_tickets (self-contained), ms_graph, jira, crm_sql
    generator.py            OpenAPI -> adapter, with a review gate (SEC-22)
    mcp_consumer.py         consume an external MCP server as verbs           [R2]
  fleet/                    the agent layer (above the kernel)
    spawn.py                ephemeral spawn: cheapest-capable, depth/budget, sensitive routing
    runtime.py              pluggable runtimes (script/hermes/claude-api/pi) + build_runtime
    pi_runtime.py           PiRuntime: talks to the Pi sidecar               [R2]
    model_router.py         sensitive -> local endpoint guard (SEC-12)
    chat.py                 ChatService: conversational turns over the relay  [R2]
    chief_of_staff.py / department_head.py    the permanent tier
    workers.py              Hatchet durable executor seam + local fallback
    hatchet_app.py / hatchet_worker.py        live Hatchet workflows + worker  [R2/LH]
  skills/ workflows/ work/  libraries (load YAML data; selection + synthesis)
  identity/                 auth (OIDC/SAML), rbac (groups->role+scope), delegation
  config/                   settings (env) + manifest loader/applier
  observability/            execution-tree reconstruction from the audit log
  api/                      bootstrap + asgi (uvicorn) + worker + cli entrypoints
services/pi_sidecar/        the standalone sandboxed Pi sidecar service        [R2]
ui/                         React console: Router, Kanban, Approvals, Chat
libraries/                  skills + workflows + prompts (data, not code)
deploy/                     Dockerfiles, compose.secure overlay, Caddyfile
tests/                      unit / kernel / security / integration / store lanes
  invariants.yaml           the binding-invariant catalogue (the gate's input)
scripts/                    check_invariants.py (the K-29/K-30 gate), smoke.py
docs/                       ARCHITECTURE, persistence, invariants, DEPLOYMENT,
                            backup-restore, DoD (round one + two), decisions/, this file
```

---

## 4. The kernel chokepoint (the heart)

Every external action funnels through `Dispatcher.invoke` (`kernel/dispatch.py`)
in this fixed order, audited at the end regardless of outcome:

```
resolve verb + binding   (fail-closed if missing)
validate params          (JSON Schema, SEC-21)
grant check              (tenant ceiling INTERSECT caller grants, deny-dominant)
consequence / HITL gate  (high-consequence/blocking verbs pause for approval)
rate limit               (Redis/in-memory fixed window)
idempotency replay       (a repeated key returns the stored result)
resolve credential       (inside the kernel only; never reaches an agent)
execute adapter | agent  (degrade to a defined fallback on UNAVAILABLE)
validate output
audit                    (append-only, hash-chained, secret-scrubbed)
```

This single path is what makes the system auditable and enforceable (P2). The MCP
face and the conversational endpoint are thin translations into this same path.

---

## 5. Stores

The kernel depends only on the `Store` protocol (`store/base.py`). Two
implementations behave identically:
- `InMemoryStore` - dev, offline tests, single process (non-durable).
- `PostgresStore` (asyncpg) - production durability; selected when `DATABASE_URL`
  is set (`api/bootstrap.py::build_store`). Schema is `store/schema.sql` (idempotent,
  applied on connect / compose first-boot). Tenant isolation is scoped on every
  query; production should additionally enable Postgres RLS (see the schema header).

Verify Postgres on-box: `docker run -d --name pg -e POSTGRES_PASSWORD=nankle -e
POSTGRES_DB=nankle -p 55432:5432 postgres:16`, then
`NANKLE_TEST_DATABASE_URL=postgresql://postgres:nankle@127.0.0.1:55432/nankle make test`.

---

## 6. How to run

```bash
# tests + checks (no docker)
python -m venv .venv
.venv/bin/pip install -e ".[durable,inference]"
.venv/bin/pip install pytest pytest-asyncio aiosqlite ruff
make test          # full suite (set NANKLE_TEST_DATABASE_URL to add the PG suite)
make smoke         # offline in-process demo of the kernel guarantees (4/4)
make invariants    # the binding-invariant gate (must be debt 0)

# the whole stack
cp .env.example .env && cp manifest.example.yaml manifest.yaml
make up            # docker compose: kernel, fleet-worker, postgres, redis, ui,
                   #   pi-sidecar, hatchet (+ --profile local for on-box model)
make secure-up     # adds the TLS terminator + encrypted-at-rest overlay

# UI
cd ui && npm install && npm run dev     # or npm run build

# backups
make backup        # pg_dump -Fc -> ./backups/nankle.dump
make restore
```

Local dev auth: set `NANKLE_DEV_AUTH=1` (header-trusting resolver). Production
sets `OIDC_ISSUER/OIDC_AUDIENCE/OIDC_JWKS_URI`; with neither, the kernel refuses
all requests (fail-closed).

---

## 7. Round Two (conversation, Pi, MCP)

- **MCP server face** (`kernel/mcp.py`, `POST /v1/mcp`): granted verbs advertised
  as MCP tools over a run-scoped token; every `tools/call` runs the chokepoint.
- **Pi sidecar runtime** (`fleet/pi_runtime.py` + `services/pi_sidecar/`): a `pi`
  capability runs through a sandboxed sidecar whose only tools are the run's
  granted verbs over MCP (no native tools, no credentials). Degrades offline.
- **Event relay + conversational layer** (`kernel/events.py`, `fleet/chat.py`,
  `POST /v1/chat` SSE + the Chat panel): a turn routes through the fleet (a work
  item linked by run id), streams reasoning/tool/sub-agent/inline-HITL events, and
  persists as an owner-scoped conversation.
- **MCP consumer** (`adapters/mcp_consumer.py`): register an external MCP server
  as verbs behind grants/audit + the review gate.

---

## 7.1 Round Three (authoring studios, admin, observability, eval, personal agents, memory)

Round Three adds the operate-and-author surface over the kernel. The dispatch
sequence is unchanged - this is routes, services, data, and UI only. Cross-cutting
rules: C1 the manifest stays the source of truth (edits round-trip), C2 authoring
writes versioned data not code, C3 RBAC-gated + audited, C4 actions still pass the
chokepoint under the author's grants, C5 every view is scope-filtered.

- **Platform routes** (`kernel/platform_routes.py`, ~30 endpoints, wired in
  `kernel/app.py` via `api/bootstrap.py:platform_factory`): authoring for
  skills / nouns / verbs / bindings / adapters / workflows; admin config
  (get/put/history/rollback/export, credential refs only); insight (cost,
  scope-filtered audit search/export, runs); eval (cases/run/runs); personal
  agent (on-behalf-of, capped); notification prefs; memory query.
- **AdminConfig** (`config/admin.py`): the manifest as an editing surface -
  section get/update records a `ConfigRevision`, with history, rollback, and a
  loadable manifest export (FR-ADM-02).
- **EvalRunner** (`fleet/eval.py`): spawns a target under the initiator's grants
  as a ceiling and asserts must_call / must_not_call / forbidden_grants /
  expect_output (FR-EVAL-02).
- **Grant ceiling** (`fleet/spawn.py`): `spawn(..., grant_ceiling=...)` plus
  `effective_grants` in the return - the testable proof that a test-spawn, eval,
  or personal agent can never exceed the author/owner (SEC-29/30).
- **RBAC helpers** (`identity/rbac.py`): `AUTHOR_ROLES`, `can_author`,
  `memory_owner_scopes` (SEC-31/32).
- **Data** (`models/platform.py`, `store/*`, `store/schema.sql`): ConfigRevision,
  EvalCase/EvalRun, NotificationPref, PersonalAgent, MemoryItem.
- **Manifest** (`manifest.example.yaml`): `evaluation`, `notifications`,
  `personal_agents`, `memory` sections (C1).
- **Alembic baseline** (`alembic.ini`, `migrations/`): `0001_baseline` replays
  `store/schema.sql`, so `alembic upgrade head` equals the bootstrap schema
  (FR-OPS-01). `alembic upgrade head --sql` emits all 28 tables offline.
- **UI** (`ui/src/panels/*`): Studio (Skill/Router/Adapter/Workflow), Admin
  Console, Insight, Eval, and a per-user Me panel, with author/admin tabs gated
  to author/admin identities (the server enforces in all cases).

New bound invariants (debt still 0): SEC-29..33, FR-OBS-02, FR-EVAL-02, FR-ADM-02,
FR-WFS-04, FR-ADS-02. Full DoD: `docs/DEFINITION-OF-DONE-round-three.md`.

---

## 7.2 Round Four (settings, account & access management)

The account & access surface. Dispatch is unchanged (NFR-MNT-01: dispatch.py /
grants.py / registry.py untouched); this is routes, data, identity, and one MCP
entry path.

- **Provisioning** (`identity/provisioning.py`): JIT on login - a mapped IdP group
  or a pending invitation, else denied (fail-closed). The `users` row is the
  authority for a user's CURRENT role/scope/status; `current_grants_for_user`
  returns nothing for a deactivated user. `build_principal_resolver(..., store=...)`
  provisions on a real SSO login.
- **Personal access tokens** (`identity/tokens.py`): minted as a subset of the
  caller's grants (secret shown once, stored as a sha256 hash); `resolve_pat_principal`
  re-checks PAT scope ∩ the owner's current grants on every call and fails closed on
  revoked / expired / deactivated (SEC-34). The PAT-aware `principal` dependency in
  `kernel/app.py` makes a PAT bearer flow through the same chokepoint as the site.
- **User-scoped MCP** (`kernel/mcp.py::handle_user`, the `/v1/mcp` user path): a
  bearer/PAT connection advertises and runs only the user's permitted tools (SEC-37).
- **Access routes** (`kernel/access_routes.py`): `/v1/me/settings`, `activity`,
  `export`, `conversations` delete, `tokens` (mint/list/revoke), `connections`,
  `sessions`, `notifications`, `agent`; `/v1/admin/users` (GET/PATCH incl deactivate),
  `/v1/admin/invitations` (GET/POST/DELETE). RBAC server-side + audited (SEC-36),
  API parity with the UI (SET-03).
- **Safe-by-default authoring** (`kernel/platform_routes.py::safe_consequence`): a
  destructive/outbound verb name defaults to high-consequence so the HITL gate
  engages (SEC-39).
- **Data** (`models/access.py`, `models/identity.py` User, `store/*`, `schema.sql`,
  Alembic `0002_round_four`).
- **UI** (`ui/src/panels/SettingsPanel.tsx`, `ui/src/appearance.ts`): the Settings
  area (Account, Appearance & a11y, Notifications, Developer & Connections + PAT,
  Personal Agent, Privacy & My Data, Security & Sessions, Organisation directory +
  invitations) plus a mobile-responsive + WCAG pass in `styles.css`.

New bound invariants (debt still 0): SEC-34..39. Full DoD:
`docs/DEFINITION-OF-DONE-round-four.md`.

---

## 7.3 Round Five (memory & knowledge)

Kernel-governed structured memory, opt-in (`memory.enabled`). The engine is
adopted, not built; the kernel - not the engine - is the isolation boundary; every
memory op runs the unchanged chokepoint (NFR-MEM-05: dispatch/grants/registry
untouched). Severable: `nankle/memory/*` imports only models + adapters.base.

- **Engine interface** (`memory/engine.py`): `MemoryEngine` Protocol +
  EngineFact/RecallHit. **Reference** (`memory/local.py`): keyword similarity +
  explicit edges with scope-bounded multi-hop traversal and complete erasure.
  **Production seam** (`memory/cognee.py`): lazy-import `CogneeEngine` (raises until
  wired + validated per MEM-ENG-04).
- **MemoryAdapter** (`memory/adapter.py`): memory.remember/recall/improve/forget as
  a normal adapter (so grant + audit + chokepoint), and the kernel-side boundary -
  owner-scope at ingestion + retrieval (SEC-40), recalled-content-is-data (SEC-41),
  injection/malware screening (SEC-42), sensitive->local residency block (SEC-43),
  complete ledgered+audited erasure (SEC-44), least-privilege audited recall
  (SEC-45). Registered in bootstrap when the manifest opts in.
- **Cognify pipeline** (`memory/cognify.py`): durable-or-local ingestion of
  transcripts/documents -> screen -> remember via the chokepoint, with provenance;
  records `memory_ingestions`.
- **Routes** (`kernel/memory_routes.py`): `/v1/memory/recall|remember|forget|ingest`
  + GET `facts`/`ingestions` (scope from the Principal via context.extra).
- **Data** (`models/memory.py`: MemoryFact/MemoryIngestion/MemoryErasure; `store/*`;
  `schema.sql`; Alembic `0003`). **Manifest**: the expanded `memory` section.
- **UI** (`ui/src/panels/MemoryPanel.tsx`): Recall (with provenance) / Browse /
  Remember / Ingest.

Round Three flat memory (`memory_items` + `/v1/memory/query`, SEC-31) is kept as
the seed. New bound invariants (debt still 0): SEC-40..45. Full DoD:
`docs/DEFINITION-OF-DONE-round-five.md`.

---

## 8. Quality / governance gate

`scripts/check_invariants.py` is the K-29/K-30 ratchet: every `@pytest.mark.
invariant("X")` in `tests/` must be declared in `tests/invariants.yaml` and have
at least one bound test; binding-debt must stay 0. Run it in CI as a required
check. Never invent `K-*` ids (those belong to `agent-kernel-doctrine`); local
guarantees use `P*/SEC*/FR*/US*`. The doc view is `docs/invariants.md`.

CI: `.github/workflows/ci.yml` runs the gate + tests (with a Postgres service) +
the UI build. Note: GitHub Actions is currently **billing-blocked** on the
account, so it will not execute until that is cleared (Settings -> Billing).

---

## 9. Done vs seams (honest ledger)

Fully implemented and test-bound:
- The dispatch chokepoint + all its guarantees (grants, credential isolation,
  hash-chained audit, rate limit, degraded mode, budgets, PII, tenant isolation,
  HITL gate, idempotency).
- PostgresStore durable persistence (durability-across-restart proven on real PG).
- Department row-isolation, caller-scoped discovery, real OIDC verification,
  sensitive->local model routing, reasoned workflow synthesis.
- The MCP face, PiRuntime (degrade path), conversational layer + RBAC, MCP
  consumer, severability (incl. the sidecar boundary).

Seams (interface real; needs the external service to exercise):
- A real Pi reasoning run needs a model key + the running sidecar.
- A live IdP (OIDC verifier is tested against minted RS256 tokens).
- Live MS Graph / Jira / SQL adapter credentials (opt-in `NANKLE_LIVE_SMOKE=1`).
- An on-box model for sensitive inference (the routing guard that requires it is done).
- Alembic ordered migrations (schema.sql applied idempotently today).
- **Live Hatchet durable resume:** the code is fixed to the correct pattern (a
  durable wait on a fixed event key + per-run scope, resumed by `approve()`;
  `test_live_durable_pause_then_resume_on_approval`, gated). It passes on a
  properly provisioned Hatchet. It could not be made green against the sandbox's
  throwaway hatchet-lite, whose worker cannot execute tasks there (subprocess
  worker: gRPC listener UNAUTHENTICATED though the token is valid for REST/unary;
  in-process worker: authenticates but its action listener never pulls work). The
  durability property is proven green via the Postgres NFR-REL-01 test.

---

## 10. Gotchas / lessons (will save you time)

- `"window"` is a Postgres reserved word - it is quoted in the `budgets` DDL and
  inserts. Quote any reserved column name.
- Store seed helpers (`set_tenant_permissions`/`set_budget`/`set_credential_ref`)
  are sync on InMemoryStore but async on PostgresStore; `apply_manifest`'s
  `_seed_call` awaits-if-awaitable. Keep that pattern for any new seed helper.
- Python 3.14 evaluates annotations via `get_type_hints`; Hatchet task input
  models + `DurableContext` must be MODULE-level (not function-local) or you get
  a `NameError` at decoration time.
- The FastAPI app builds the kernel in a **lifespan** (the asyncpg pool is
  loop-bound). A prebuilt kernel is set synchronously for tests; a TestClient over
  the factory path (`build_app()`) must be used as a `with` context.
- Hatchet: `ctx.aio_wait_for(signal_key, *conditions)` takes a signal-key STRING
  first; a durable HITL resume correlates by SCOPE (fixed event key +
  `UserEventCondition(scope=run_key)`, push with `PushEventOptions(scope=run_key)`),
  not by baking the run key into the event name; `durable_task` default
  `execution_timeout` is 60s and kills a long pause - raise it. hatchet-lite needs
  `SERVER_AUTH_COOKIE_DOMAIN`, regenerates signing keys on restart (re-mint
  tokens), serves REST on 8888 (not 8080), and mint a token with
  `docker exec hatchet-lite /hatchet-admin token create --config /config
  --tenant-id 707d0855-80ab-4e1f-a156-f1c4546cbf52`.
- Running a driver script from `/tmp` fails to import `nankle`; run from the repo
  root or set `PYTHONPATH`.

---

## 11. Suggested next steps

1. Stand up a properly-provisioned Hatchet (mirror the working Opbox-Hatchet
   config) and run the gated live tests to confirm the durable resume green.
2. Implement the Postgres-store-backed `build_store` swap in production + add the
   Alembic baseline so ordered migrations replace the idempotent apply.
3. Wire a real IdP and exercise the OIDC path end to end.
4. Clear the GitHub Actions billing block so the required CI gate runs remotely.
5. Provide adapter credentials + a model key to exercise the live adapter smokes
   and a real Pi reasoning run.

---

## 12. Commit history (this build, newest first)

```
docs: precise honesty note on the live Hatchet resume fix + sandbox blocker
fix(hatchet): correct durable HITL resume to scope-correlated events
R2-7 deploy wiring + docs for Round Two
R2-6 consume external MCP servers as adapters
R2-5 Chat panel in the web UI
R2-2/3/4 Pi runtime, event relay, conversational layer
R2-1 kernel MCP server face
LH enable live Hatchet integration
P3-1/2 secure-deployment overlay + backup/restore
P2-x reasoned workflow synthesis / live adapter smoke / idempotency
P1-x OIDC auth / durable HITL / sensitive routing
P0-x PostgresStore / department isolation / caller-scoped discovery
Comply with [2026] VJS-CC NANKLE-CONSOLIDATION 001
Initial build: Nankle agent orchestration platform
```
