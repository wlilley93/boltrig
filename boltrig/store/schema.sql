-- Boltrig durable state (S6). PostgreSQL 16.
-- All tables carry tenant_id, created_at, updated_at. Timestamps are timezone-aware (UTC).
-- Tenant isolation (SEC-08, K-22) is enforced at the DB with FORCE ROW LEVEL SECURITY:
-- the app connects as a non-superuser, non-bypassing role and sets
--   SET app.tenant_id = '<tenant>'
-- per transaction; a null GUC yields zero rows (fail-closed).

-- pgvector: the native vector Memory Engine (PgVectorMemoryEngine) keeps its
-- graph/vector store in THIS Postgres (consolidation-faithful: no separate vector
-- DB). The extension must exist before any `vector` column below. Provisioned by
-- the pgvector/pgvector image; a no-op when already present.
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- 6.1 Registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nouns (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    description TEXT,
    schema      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS verbs (
    id            TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    noun_id       TEXT NOT NULL,
    description   TEXT,
    input_schema  JSONB NOT NULL,
    output_schema JSONB NOT NULL,
    consequence   TEXT NOT NULL DEFAULT 'low',        -- low | high (high -> may require HITL)
    identity_mode TEXT NOT NULL DEFAULT 'service-principal', -- service-principal | delegated
    degraded_mode JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, noun_id) REFERENCES nouns(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS verb_bindings (
    verb_id     TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    target_type TEXT NOT NULL,                          -- 'adapter' | 'agent'
    target_ref  TEXT NOT NULL,                          -- adapter id or agent type
    rate_limit  JSONB,                                  -- {per, max, scope}
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (verb_id, tenant_id)
);

-- ---------------------------------------------------------------------------
-- 6.2 Adapters, skills, capabilities, workflows, endpoints
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS adapters (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    version     TEXT NOT NULL,
    runtime     TEXT NOT NULL,                          -- http | sql | mq | file | script
    source      TEXT NOT NULL,                          -- generated | builtin | manual
    module_ref  TEXT NOT NULL,
    health      TEXT NOT NULL DEFAULT 'unknown',        -- ok | degraded | down | unknown
    spec_ref    TEXT,
    created_by  TEXT,
    activated   BOOLEAN NOT NULL DEFAULT false,         -- review gate (SEC-22)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS skills (
    id                   TEXT NOT NULL,
    tenant_id            TEXT NOT NULL,
    version              TEXT NOT NULL,                 -- semver
    prompt_fragment      TEXT NOT NULL,
    tool_grants          JSONB NOT NULL,
    context_requirements JSONB NOT NULL,                -- JSON Schema
    extends              TEXT,                          -- parent skill id
    locale               TEXT DEFAULT 'en',
    description          TEXT NOT NULL DEFAULT '',      -- the shelf label (when-to-use)
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id, version)
);

CREATE TABLE IF NOT EXISTS agent_capabilities (
    name             TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    runtime          TEXT NOT NULL,                     -- hermes | claude-api | script | go-binary
    model_endpoint   TEXT,
    supported_skills JSONB NOT NULL,                    -- patterns
    max_depth        INT NOT NULL,
    is_ephemeral     BOOLEAN NOT NULL,
    cost_tier        TEXT NOT NULL,                     -- cheap | standard | expensive
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS workflow_definitions (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    version     TEXT NOT NULL,
    source      TEXT NOT NULL,                          -- precreated | generated | learned
    definition  JSONB NOT NULL,
    intent_tags JSONB,
    origin_task TEXT,
    -- The WORKSPACE this workflow is scoped to ([2026] VJS-COUNTY 8, D2). NULL means
    -- ORG-WIDE (visible + runnable in every workspace of the org, exactly as today);
    -- a SET value scopes the workflow to that one workspace. RLS stays tenant_id-
    -- fenced (below); workspace scoping is an APPLICATION filter on top, because a
    -- NULL row must stay visible to every workspace and an RLS predicate on
    -- workspace_id would hide those org-wide rows.
    workspace_id TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id, version)
);
-- Scope lookups by (tenant_id, workspace_id) without hiding org-wide NULL rows.
CREATE INDEX IF NOT EXISTS workflow_definitions_ws_idx
    ON workflow_definitions (tenant_id, workspace_id);

-- Eval-gated reuse ranking ([2026] VJS-COUNTY 5). A ranking-only record keyed by
-- workflow id: a generated/learned workflow becomes a promotion CANDIDATE, is
-- PROMOTED once it passes its eval cases (through the chokepoint, under the
-- initiator ceiling), and DEMOTED if a later eval fails. It carries NO authority
-- column (no grant/scope/tier) - execution authority comes only from the caller
-- ceiling at dispatch; this only tunes how likely the workflow is to be reused.
CREATE TABLE IF NOT EXISTS workflow_promotions (
    workflow_id TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'candidate',       -- candidate | promoted | demoted
    score       DOUBLE PRECISION NOT NULL DEFAULT 0,      -- bounded reuse weight in [-1, 1]
    eval_run_id TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workflow_id)
);

CREATE TABLE IF NOT EXISTS model_endpoints (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,                          -- anthropic | openai | ollama | vllm
    base_url    TEXT,
    model       TEXT NOT NULL,
    fallback    TEXT,
    data_class  TEXT NOT NULL DEFAULT 'standard',       -- standard | sensitive
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

-- ---------------------------------------------------------------------------
-- 6.3 Work items (the fleet's kanban)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS work_items (
    id              TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_id       TEXT,
    intent          TEXT NOT NULL,
    confidence      DOUBLE PRECISION NOT NULL,          -- 0.0-1.0
    convergent      BOOLEAN NOT NULL,
    status          TEXT NOT NULL,                      -- pending|in_flight|blocked|awaiting_human|done|failed|cancelled
    owner_member    TEXT,
    parent_id       TEXT,
    hatchet_run_id  TEXT,
    depth           INT NOT NULL DEFAULT 0,
    on_behalf_of    TEXT,
    constraints     JSONB,
    raw             JSONB,
    lease_owner     TEXT,                                -- worker holding the claim (US-FLT-05)
    lease_expires_at TIMESTAMPTZ,                        -- past-due lease -> reclaimable
    attempts        INT NOT NULL DEFAULT 0,              -- claim count
    degraded        BOOLEAN NOT NULL DEFAULT false,      -- degraded honesty persisted (US-FLT-07)
    result          JSONB,                               -- terminal output of the run
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS work_items_status_idx ON work_items (tenant_id, status);
CREATE INDEX IF NOT EXISTS work_items_parent_idx ON work_items (parent_id);
-- Idempotent column adds for DBs created before Beat 3 durable delegation landed
-- (before the lease index, which references lease_expires_at).
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS lease_owner TEXT;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS attempts INT NOT NULL DEFAULT 0;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS degraded BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS result JSONB;
CREATE INDEX IF NOT EXISTS work_items_lease_idx ON work_items (tenant_id, status, lease_expires_at);

-- Beat 3: durable per-step run checkpoints (the resume seam for the pump).
CREATE TABLE IF NOT EXISTS run_checkpoints (
    tenant_id       TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    step            TEXT NOT NULL,
    status          TEXT NOT NULL,                       -- started | done | awaiting_human | failed
    output          JSONB,
    hitl_request_id TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id, step)
);

-- Beat 3: atomic fan-out counters shared across workers (US-EXE-07). A capped
-- conditional upsert either applies the whole increment or refuses it.
CREATE TABLE IF NOT EXISTS fanout_counters (
    tenant_id  TEXT NOT NULL,
    tree_id    TEXT NOT NULL,
    counter    TEXT NOT NULL,
    value      INT NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, tree_id, counter)
);

-- [2026] VJS-COUNTY 6: server-side run cancellation. A cooperative, owner-only
-- cancel signal keyed by run id - a marker row the pump consults at each step
-- boundary and stops BEFORE dispatching the next verb, NOT a broad mutable run
-- table. Idempotent (INSERT .. ON CONFLICT DO NOTHING). The terminal CANCELLED
-- state is written on the work item + a checkpoint in a finally, so a restart
-- re-detects this request and re-writes it - a cancelled run is never resurrected.
CREATE TABLE IF NOT EXISTS run_cancel_requests (
    tenant_id     TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id)
);

-- ---------------------------------------------------------------------------
-- 6.4 Human-in-the-loop
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hitl_requests (
    id           TEXT NOT NULL,
    tenant_id    TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    work_item_id TEXT,
    type         TEXT NOT NULL,                         -- approval | clarification | escalation
    urgency      TEXT NOT NULL,                         -- blocking | async
    context      TEXT NOT NULL,
    question     TEXT NOT NULL,
    options      JSONB,
    assignee     TEXT,
    status       TEXT NOT NULL,                         -- pending | answered | consumed | timed_out | escalated
    timeout_at   TIMESTAMPTZ,
    verb         TEXT,                                  -- SEC-14: the verb this approval gates
    requested_by TEXT,                                  -- SEC-14: who raised it (anti-self-approval)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
-- Idempotent column adds for DBs created before SEC-14 verb-binding landed.
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS verb TEXT;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS requested_by TEXT;

CREATE TABLE IF NOT EXISTS hitl_responses (
    id           TEXT NOT NULL,
    request_id   TEXT NOT NULL,
    tenant_id    TEXT NOT NULL,
    decision     TEXT NOT NULL,
    notes        TEXT,
    respondent   TEXT NOT NULL,
    responded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, id)
);

-- ---------------------------------------------------------------------------
-- 6.5 Identity, audit, cost
-- ---------------------------------------------------------------------------
-- NOTE: the authoritative `users` table (with role/scope/status/source, the Round
-- Four identity columns) is defined in section 6.x below. A stale minimal
-- duplicate used to sit here and, under CREATE TABLE IF NOT EXISTS, shadowed the
-- real one on a FRESH boot (schema.sql loads top-to-bottom), so a clean box got a
-- users table with no `role` column and the owner seed failed. Removed.

CREATE TABLE IF NOT EXISTS role_mappings (
    tenant_id   TEXT NOT NULL,
    idp_group   TEXT NOT NULL,
    role        TEXT NOT NULL,
    scope       JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, idp_group, role)
);

-- Operational audit. Append-only, hash-chained per tenant (SEC-16, K-19).
-- seq is per-tenant monotonic; hash chains to prev_hash. Bounded observability:
-- no raw secrets/payloads/identity are written here (K-20), enforced in the writer.
CREATE TABLE IF NOT EXISTS audit_log (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    seq           BIGINT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    run_id        TEXT,
    parent_run_id TEXT,
    actor         TEXT NOT NULL,
    actor_tier    TEXT,
    depth         INT,
    action_type   TEXT NOT NULL,
    noun          TEXT,
    verb          TEXT,
    target_adapter TEXT,
    on_behalf_of  TEXT,
    status        TEXT NOT NULL,
    latency_ms    INT,
    tokens_used   INT,
    cost_micros   BIGINT,
    skills_loaded JSONB,
    detail        JSONB,
    -- Opbox-depth enrichment ([2026] VJS-COUNTY 9, D1). ALL nullable + backfilled
    -- NULL: a pre-enrichment row canonicalises byte-for-byte as before and its hash
    -- stays valid (the writer folds a field into the hash only when non-None), so
    -- the existing chain is unchanged. Keys-only (K-20): never a secret here.
    ip_address    TEXT,
    user_agent    TEXT,
    resource      TEXT,
    resource_id   TEXT,
    workspace_id  TEXT,
    prev_hash     TEXT,
    hash          TEXT NOT NULL,
    UNIQUE (tenant_id, seq)
);
CREATE INDEX IF NOT EXISTS audit_ts_idx ON audit_log (tenant_id, ts);
CREATE INDEX IF NOT EXISTS audit_run_idx ON audit_log (run_id);
CREATE INDEX IF NOT EXISTS audit_ws_idx ON audit_log (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS audit_actor_idx ON audit_log (tenant_id, actor);

-- The distinct SecurityEvent stream ([2026] VJS-COUNTY 9, D3): its OWN
-- append-only, hash-chained table for security SIGNALS (login failures,
-- rate-limit trips, permission denials, MCP auth failures). Same chaining as
-- audit_log (UNIQUE(tenant_id, seq), prev_hash -> hash) but kept separate so
-- signals never dilute the action trail. Keys-only (K-20): detail is scrubbed and
-- a row never carries a secret / password / session token.
CREATE TABLE IF NOT EXISTS security_log (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    seq           BIGINT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    event_type    TEXT NOT NULL,   -- login_failure|rate_limit_trip|permission_denied|mcp_auth_failure
    reason        TEXT NOT NULL,
    actor         TEXT,
    actor_tier    TEXT,
    workspace_id  TEXT,
    ip_address    TEXT,
    user_agent    TEXT,
    resource      TEXT,
    resource_id   TEXT,
    on_behalf_of  TEXT,
    detail        JSONB,
    prev_hash     TEXT,
    hash          TEXT NOT NULL,
    UNIQUE (tenant_id, seq)
);
CREATE INDEX IF NOT EXISTS security_ts_idx ON security_log (tenant_id, ts);
CREATE INDEX IF NOT EXISTS security_type_idx ON security_log (tenant_id, event_type);

-- Periodic per-org/workspace ROLLUP ANCHOR over an audit-chain segment ([2026]
-- VJS-COUNTY 9, D4). rollup_root_hash is a deterministic digest over the segment
-- [seq_start, seq_end]. workspace_id NULL == an org-wide anchor over the tenant.
-- is_dev_fallback flags the LOCAL anchor (no external call); rfc3161_token / the
-- kms_signature are a clean seam left NULL until a Principal wires an external
-- TSA/KMS (never called live from the kernel).
CREATE TABLE IF NOT EXISTS audit_rollup_anchors (
    id               TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    workspace_id     TEXT,
    seq_start        BIGINT NOT NULL,
    seq_end          BIGINT NOT NULL,
    rollup_root_hash TEXT NOT NULL,
    anchored_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_dev_fallback  BOOLEAN NOT NULL DEFAULT true,
    rfc3161_token    TEXT,
    kms_signature    TEXT,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS audit_anchor_scope_idx
    ON audit_rollup_anchors (tenant_id, workspace_id, seq_end);

-- Idempotency keys for side-effecting verbs (NFR-REL-02, SEC-15).
CREATE TABLE IF NOT EXISTS idempotency_keys (
    tenant_id  TEXT NOT NULL,
    key        TEXT NOT NULL,
    result     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key)
);

CREATE TABLE IF NOT EXISTS budgets (
    id                TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    scope_type        TEXT NOT NULL,                    -- tenant | department | workflow
    token_limit       BIGINT,
    cost_limit_micros BIGINT,
    hard_stop         BOOLEAN NOT NULL DEFAULT true,
    "window"          TEXT NOT NULL DEFAULT 'run',      -- run | daily | monthly (quoted: reserved word)
    spent_tokens      BIGINT NOT NULL DEFAULT 0,
    spent_micros      BIGINT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

-- Secret references only - never plaintext secrets at rest (SEC-04, FR-SEC-02).
-- ``data`` holds the full reference dict the resolver consumes (store, ref, kind,
-- ...); the typed columns mirror it for queryability. No secret material here.
CREATE TABLE IF NOT EXISTS credential_refs (
    id          TEXT NOT NULL,                          -- "jira-oauth"
    tenant_id   TEXT NOT NULL,
    store       TEXT NOT NULL,                          -- vault | kms | docker-secret | env
    ref         TEXT NOT NULL,                          -- path/name in the external store
    data        JSONB,                                  -- the full reference dict (no secrets)
    expires_at  TIMESTAMPTZ,                            -- for rotation alerts (US-COST-04)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

-- The tenant permission ceiling (the role-derived GrantSet seeded from the
-- manifest). Caps every caller's grants (SEC-07, the K-2 intersection). Stored as
-- allow/deny verb-pattern arrays, never secret material.
CREATE TABLE IF NOT EXISTS tenant_permissions (
    tenant_id   TEXT PRIMARY KEY,
    allow       JSONB NOT NULL DEFAULT '[]'::jsonb,
    deny        JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Round Two: conversations (human<->fleet chat threads). Tenant + owner scoped
-- (SEC-25): only the owner and appropriately-scoped roles may read a thread.
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,                          -- owner
    title       TEXT,
    status      TEXT NOT NULL DEFAULT 'active',         -- active | closed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS conversations_user_idx ON conversations (tenant_id, user_id);

-- Round Three: versioned configuration & library edits (C1/C2/C3). Every in-app
-- authoring/admin change is recorded here so it round-trips to manifest/YAML and
-- is reversible (rollback). No secret values; payloads are config/library data.
CREATE TABLE IF NOT EXISTS config_revisions (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,    -- manifest_section|skill|workflow|noun|verb|binding|adapter
    ref         TEXT NOT NULL,
    version     TEXT NOT NULL,
    payload     JSONB NOT NULL,
    actor       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    rolled_back BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS config_revisions_idx ON config_revisions (tenant_id, kind, ref, created_at);

-- Round Three: evaluation harness (Epic EVAL)
CREATE TABLE IF NOT EXISTS eval_cases (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    target_kind TEXT NOT NULL,    -- skill | workflow | conversation
    target_ref  TEXT NOT NULL,
    input       JSONB NOT NULL,
    assertions  JSONB NOT NULL,
    labels      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS eval_runs (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    case_id     TEXT NOT NULL,
    passed      BOOLEAN,
    score       DOUBLE PRECISION,
    run_id      TEXT,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS eval_runs_case_idx ON eval_runs (tenant_id, case_id, created_at);

-- Round Three: notification preferences (Epic NOT)
CREATE TABLE IF NOT EXISTS notification_prefs (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    scope_kind  TEXT NOT NULL,    -- user | team
    scope_ref   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    channel     TEXT NOT NULL,
    target      TEXT,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (tenant_id, id)
);

-- Round Three: personal agents (Epic PA). Acts ONLY under the owner's delegated
-- permissions (SEC-30); holds no service-principal authority.
CREATE TABLE IF NOT EXISTS personal_agents (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    runtime     TEXT NOT NULL,
    skills      JSONB NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS personal_agents_user_idx ON personal_agents (tenant_id, user_id);

-- Channels (decision 0003). A governed connection to an external messaging
-- platform. This table is DELIBERATELY RLS-EXCLUDED (like personal_access_tokens):
-- the inbound path resolves the tenant from the unguessable channel id BEFORE any
-- tenant is bound. Credentials are references (SEC-04), never plaintext.
CREATE TABLE IF NOT EXISTS channels (
    id                 TEXT PRIMARY KEY,
    tenant_id          TEXT NOT NULL,
    platform           TEXT NOT NULL,          -- slack | discord | whatsapp | webhook | ...
    name               TEXT NOT NULL,
    transport          TEXT NOT NULL,          -- webhook | socket
    credential_ref     TEXT,
    config             JSONB NOT NULL DEFAULT '{}'::jsonb,
    unpaired_behavior  TEXT NOT NULL DEFAULT 'reject',  -- reject | ignore | pair
    enabled            BOOLEAN NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS channels_tenant_idx ON channels (tenant_id);

-- Channel bindings: a verified external sender mapped to an internal identity,
-- per tenant. RLS-scoped - tenant comes from the resolved channel, never the
-- message body (decision 0003).
CREATE TABLE IF NOT EXISTS channel_bindings (
    id                TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    channel_id        TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    platform          TEXT NOT NULL,
    external_user_id  TEXT NOT NULL,
    subject           TEXT NOT NULL,
    role              TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS channel_bindings_sender_idx
    ON channel_bindings (tenant_id, channel_id, external_user_id);

-- Channel pairings: one-time codes to bind an unknown sender. Hashed at rest
-- (SEC-05), TTL-bounded, lockout-guarded. RLS-scoped.
CREATE TABLE IF NOT EXISTS channel_pairings (
    id                TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    channel_id        TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    code_hash         TEXT NOT NULL,
    external_user_id  TEXT NOT NULL,
    subject           TEXT NOT NULL,
    role              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending | consumed | expired
    attempts          INTEGER NOT NULL DEFAULT 0,
    expires_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS channel_pairings_code_idx
    ON channel_pairings (tenant_id, channel_id, code_hash);

-- Round Three (optional): memory & knowledge (Epic MEM). owner_scope is the RBAC
-- boundary; sensitive memory follows sensitive-routing (SEC-31).
CREATE TABLE IF NOT EXISTS memory_items (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    owner_scope TEXT NOT NULL,    -- user:<id> | department:<name> | org
    kind        TEXT NOT NULL,    -- fact | summary | document_chunk
    content     TEXT NOT NULL,
    embedding   JSONB,
    source_ref  TEXT,
    data_class  TEXT NOT NULL DEFAULT 'standard',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS memory_scope_idx ON memory_items (tenant_id, owner_scope, kind);

-- Round Two (optional): external MCP servers Boltrig consumes as adapters
-- (US-MCP-03). Inert (pending_review) until activated through the review gate.
CREATE TABLE IF NOT EXISTS mcp_servers (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    url         TEXT NOT NULL,
    transport   TEXT NOT NULL,                          -- stdio | http
    credential  TEXT,                                   -- secret reference (refs only)
    status      TEXT NOT NULL DEFAULT 'pending_review', -- pending_review | active | disabled
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id              TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    role            TEXT NOT NULL,                      -- user | assistant | tool | system
    content         TEXT,
    run_id          TEXT,                               -- the fleet run this turn used
    hitl_request_id TEXT,                               -- set for an inline HITL prompt
    events          JSONB,                              -- structured render data
    attachments     JSONB,                              -- inline size-capped attachment records ([2026] VJS-COUNTY 3)
    superseded_by   TEXT,                               -- append-plus-supersede marker ([2026] VJS-COUNTY 4)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS conv_messages_idx ON conversation_messages (conversation_id, created_at);

-- Append-only DERIVED conversation summaries (long-conversation compaction). A
-- summary is a cheap derived view of a conversation's OLDER turns so the
-- continuity composer can send [summary + recent verbatim tail] past a threshold
-- instead of the whole history. DERIVED data, never a mutation of the frozen
-- conversation_messages record: this table is INSERT-only (a re-compaction
-- appends a new row covering more messages; no row is ever updated). up_to_message_id
-- is the split boundary (the last live message the summary covers). Tenant + owner
-- scoped via the parent conversation; RLS-scoped like the message table.
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id                TEXT NOT NULL,
    conversation_id   TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    up_to_message_id  TEXT NOT NULL,                     -- split boundary: last live message covered
    covered_count     INTEGER NOT NULL,                  -- number of live messages covered
    summary           TEXT NOT NULL,                     -- derived digest (DATA, never instructions)
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS conv_summaries_idx
    ON conversation_summaries (tenant_id, conversation_id, covered_count);

-- ===========================================================================
-- Round Four: users + provisioning (USR), personal access tokens (PAT),
-- per-user settings (SET), sessions. Tenant-isolated; RLS-ready like the rest.
-- ===========================================================================

-- Provisioned users (US-USR-01/03). The authority for a user's CURRENT role/
-- scope/status: a PAT re-checks against this and a deactivated user's access (and
-- tokens) stop working at once (SEC-34).
CREATE TABLE IF NOT EXISTS users (
    id            TEXT NOT NULL,          -- subject from the IdP
    tenant_id     TEXT NOT NULL,
    email         TEXT,
    display_name  TEXT,
    groups        TEXT[] NOT NULL DEFAULT '{}',
    role          TEXT NOT NULL DEFAULT 'none',
    scope         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        TEXT NOT NULL DEFAULT 'active',   -- active | deactivated
    source        TEXT NOT NULL DEFAULT 'idp',      -- idp | invitation
    source_group  TEXT,                             -- the IdP group that conferred the role
    last_seen_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS users_email_idx ON users (tenant_id, email);

-- Personal access tokens (SET-40 / PAT-*). Stored as a hash only; the secret is
-- shown once at creation. scope is a subset of the user's grants (SEC-34).
CREATE TABLE IF NOT EXISTS personal_access_tokens (
    id            TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL,
    scope         TEXT[] NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ,                       -- required + bounded in practice
    last_used_at  TIMESTAMPTZ,
    revoked       BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS pat_user_idx ON personal_access_tokens (tenant_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS pat_hash_idx ON personal_access_tokens (token_hash);

-- Admin invitations (US-USR-02). Pre-stages a role/scope for an identity. For SSO
-- it creates no password and grants no access until the invitee authenticates
-- (SEC-35). For first-party invite-only login ([2026] VJS-COUNTY 7, D1) it also
-- carries the sha256 of a single-use, expiring invite-token secret (token_hash;
-- the secret is shown once and never stored) that accept-invite consumes.
CREATE TABLE IF NOT EXISTS user_invitations (
    id             TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    email          TEXT NOT NULL,
    intended_role  TEXT NOT NULL,
    intended_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    invited_by     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | revoked | expired
    token_hash     TEXT,                             -- sha256 of a single-use invite token
    -- Org/workspace-scoped invites + provisioning ([2026] VJS-COUNTY 8, D6). All
    -- nullable + additive: a legacy invite leaves them NULL. workspace_id targets an
    -- EXISTING workspace (accept seats the invitee into it); provision_workspace_name
    -- asks accept to CREATE that workspace and seat the invitee as owner;
    -- provision_org_name (superadmin-only at creation) asks accept to provision a new org.
    workspace_id             TEXT,
    provision_workspace_name TEXT,
    provision_org_name       TEXT,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS invitations_email_idx ON user_invitations (tenant_id, email);
CREATE UNIQUE INDEX IF NOT EXISTS invitations_token_hash_idx
    ON user_invitations (token_hash) WHERE token_hash IS NOT NULL;

-- First-party password credentials ([2026] VJS-COUNTY 7, D4). Kept in its OWN
-- table, apart from the users identity row, so the argon2id hash never rides in a
-- user view/export. Stores ONLY the PHC-encoded hash (which embeds the per-user
-- salt); never a plaintext or reversible form. Tenant-isolated + RLS-scoped.
CREATE TABLE IF NOT EXISTS user_credentials (
    tenant_id     TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    password_hash TEXT NOT NULL,          -- argon2id PHC string ($argon2id$...)
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

-- Per-user settings/preferences (SET-*).
CREATE TABLE IF NOT EXISTS user_settings (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id, key)
);

-- Sessions (SET-70). For first-party login ([2026] VJS-COUNTY 7, D2/D6) a session
-- carries the sha256 of its cookie secret (token_hash; only the hash is stored,
-- mirroring the PAT pattern), a bounded expiry (expires_at) and a session-bound
-- CSRF token. Legacy directory rows leave these NULL.
CREATE TABLE IF NOT EXISTS user_sessions (
    id            TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    client        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ,
    revoked       BOOLEAN NOT NULL DEFAULT false,
    token_hash    TEXT,                             -- sha256 of the session cookie secret
    expires_at    TIMESTAMPTZ,                      -- bounded session lifetime
    csrf_token    TEXT,                             -- session-bound double-submit CSRF token
    active_workspace_id TEXT,                       -- active workspace hint ([2026] VJS-COUNTY 8, D4); re-authorized every request
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON user_sessions (tenant_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS sessions_token_hash_idx
    ON user_sessions (token_hash) WHERE token_hash IS NOT NULL;

-- ===========================================================================
-- Org -> workspace tenancy ([2026] VJS-COUNTY 8). The ORGANISATION is the tenant
-- boundary (D1): an organisation row's id IS the tenant_id (one org per tenant_id),
-- so RLS stays keyed on tenant_id and existing reads are unchanged. A WORKSPACE
-- belongs to an org (D2); org_members + workspace_members are the memberships (D3).
-- ADDITIVE: no existing resource table gains a workspace_id this phase.
-- ===========================================================================

-- D1: the organisation - id IS the tenant_id. slug is a unique url-safe handle.
CREATE TABLE IF NOT EXISTS organisations (
    id                 TEXT NOT NULL,   -- == tenant_id (one org per tenant_id)
    name               TEXT NOT NULL,
    slug               TEXT NOT NULL,
    settings           JSONB NOT NULL DEFAULT '{}'::jsonb,
    allow_own_ai_keys  BOOLEAN NOT NULL DEFAULT false,
    require_two_factor  BOOLEAN NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS organisations_slug_idx ON organisations (slug);

-- D2: a workspace belonging to an org (tenant_id). Tenant-scoped (RLS). No
-- workspace_id is added to any existing resource table this phase.
CREATE TABLE IF NOT EXISTS workspaces (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,          -- the owning organisation (== organisations.id)
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      TEXT NOT NULL DEFAULT 'active',   -- active | archived
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS workspaces_slug_idx ON workspaces (slug);

-- D3: organisation membership. One row per user per org; role is drawn from the
-- existing platform role vocabulary. Tenant-scoped (RLS).
CREATE TABLE IF NOT EXISTS org_members (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'member',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

-- D3: per-workspace membership. role is one of owner/admin/member/viewer/agent
-- (enforced in the store); permissions carries optional fine-grained overrides.
-- Tenant-scoped (RLS).
CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id  TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,        -- the owning org (workspaces.tenant_id)
    role          TEXT NOT NULL DEFAULT 'member',
    permissions   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS workspace_members_user_idx
    ON workspace_members (tenant_id, user_id);
CREATE INDEX IF NOT EXISTS workspace_members_ws_idx
    ON workspace_members (tenant_id, workspace_id);

-- D5: per-org / workspace / user AI keys. ONE unified table keyed by
-- (tenant_id, level, scope_id). level is org | workspace | user; scope_id is the
-- tenant_id (org), a workspace id (workspace) or a user id (user). The row holds a
-- provider/model selection and a credential_ref - the id of a SEALED credential in
-- credential_refs. THE RAW KEY IS NEVER STORED HERE (no plaintext key column): only
-- the reference, so a key can never leak through an AI-config read/export. The org
-- allow_own_ai_keys flag gates whether a workspace/user row is honoured. Tenant-
-- scoped (RLS).
CREATE TABLE IF NOT EXISTS ai_configs (
    tenant_id      TEXT NOT NULL,          -- the owning organisation (== organisations.id)
    level          TEXT NOT NULL,          -- org | workspace | user
    scope_id       TEXT NOT NULL,          -- org: tenant_id; workspace: workspace_id; user: user_id
    provider       TEXT NOT NULL,          -- 'anthropic' | 'openai' | 'hermes' | ... (selection)
    model          TEXT NOT NULL,          -- pinned model/version
    credential_ref TEXT NOT NULL,          -- id into credential_refs (the SEALED key); NEVER the raw key
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, level, scope_id)
);

-- ===========================================================================
-- Round Five: structured memory governance + provenance control plane (Epic MEM).
-- The swappable Memory Engine owns the graph/vector store; Boltrig governs scope,
-- provenance, ingestion runs and the erasure ledger. owner_scope is the RBAC
-- boundary the kernel enforces at ingestion AND retrieval (SEC-40). Opt-in.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS memory_facts (
    id            TEXT NOT NULL,            -- Boltrig id, mapped to the engine node id
    tenant_id     TEXT NOT NULL,
    owner_scope   TEXT NOT NULL,            -- user:<id> | department:<name> | org
    engine_ref    TEXT NOT NULL,            -- the engine's node/record identifier
    kind          TEXT NOT NULL,            -- entity | relationship | summary | document_chunk
    source_kind   TEXT NOT NULL,            -- conversation | document | verb_result | feedback
    source_ref    TEXT,
    data_class    TEXT NOT NULL DEFAULT 'standard',
    content       TEXT NOT NULL DEFAULT '',
    redacted      BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS memory_facts_scope_idx ON memory_facts (tenant_id, owner_scope, kind);
CREATE INDEX IF NOT EXISTS memory_facts_source_idx ON memory_facts (tenant_id, source_kind, source_ref);

CREATE TABLE IF NOT EXISTS memory_ingestions (
    id             TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    source_kind    TEXT NOT NULL,
    source_ref     TEXT NOT NULL,
    owner_scope    TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending|screening|cognifying|done|failed|rejected
    hatchet_run_id TEXT,
    facts_added    INT NOT NULL DEFAULT 0,
    screened       BOOLEAN NOT NULL DEFAULT false,
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS memory_erasures (
    id                 TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    requested_by       TEXT NOT NULL,
    target             TEXT NOT NULL,        -- a fact id, source_ref, subject, or scope
    scope              TEXT NOT NULL,
    engine_confirmed   BOOLEAN NOT NULL DEFAULT false,
    transcript_handled BOOLEAN NOT NULL DEFAULT false,
    facts_removed      INT NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, id)
);

-- ---------------------------------------------------------------------------
-- Native vector Memory Engine store (PgVectorMemoryEngine, MEM-ENG-02).
-- The engine OWNS these tables (the kernel governs scope/provenance via
-- memory_facts above). owner_scope is the isolation boundary every recall query
-- filters on in SQL; graph traversal loads only edges with BOTH endpoints in
-- scope, so a cross-scope edge is structurally unfollowable (SEC-40). The
-- embedding dimension (256) matches HashingEmbedder's DEFAULT_DIM; a deployment
-- changing it changes both here and in boltrig/memory/embeddings.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_vectors (
    tenant_id   TEXT NOT NULL,
    id          TEXT NOT NULL,
    owner_scope TEXT NOT NULL,            -- user:<id> | department:<name> | org
    kind        TEXT NOT NULL DEFAULT 'entity',
    content     TEXT NOT NULL DEFAULT '',
    data_class  TEXT NOT NULL DEFAULT 'standard',
    source_kind TEXT NOT NULL DEFAULT 'verb_result',
    source_ref  TEXT,
    embedding   vector(256),
    weight      DOUBLE PRECISION NOT NULL DEFAULT 0,  -- improve() reweighting; never scope/authority
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS memory_vectors_scope_idx ON memory_vectors (tenant_id, owner_scope, kind);

CREATE TABLE IF NOT EXISTS memory_vector_edges (
    tenant_id TEXT NOT NULL,
    src       TEXT NOT NULL,
    dst       TEXT NOT NULL,
    PRIMARY KEY (tenant_id, src, dst)
);
