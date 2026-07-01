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
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id, version)
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
    status          TEXT NOT NULL,                      -- pending|in_flight|blocked|awaiting_human|done|failed
    owner_member    TEXT,
    parent_id       TEXT,
    hatchet_run_id  TEXT,
    depth           INT NOT NULL DEFAULT 0,
    on_behalf_of    TEXT,
    constraints     JSONB,
    raw             JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS work_items_status_idx ON work_items (tenant_id, status);
CREATE INDEX IF NOT EXISTS work_items_parent_idx ON work_items (parent_id);

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
CREATE TABLE IF NOT EXISTS users (
    id           TEXT NOT NULL,
    tenant_id    TEXT NOT NULL,
    email        TEXT,
    display_name TEXT,
    groups       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

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
    prev_hash     TEXT,
    hash          TEXT NOT NULL,
    UNIQUE (tenant_id, seq)
);
CREATE INDEX IF NOT EXISTS audit_ts_idx ON audit_log (tenant_id, ts);
CREATE INDEX IF NOT EXISTS audit_run_idx ON audit_log (run_id);

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
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS conv_messages_idx ON conversation_messages (conversation_id, created_at);

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

-- Admin invitations (US-USR-02). Pre-stages a role/scope for an SSO identity;
-- creates no password and grants no access until the invitee authenticates (SEC-35).
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
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS invitations_email_idx ON user_invitations (tenant_id, email);

-- Per-user settings/preferences (SET-*).
CREATE TABLE IF NOT EXISTS user_settings (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id, key)
);

-- Sessions (SET-70).
CREATE TABLE IF NOT EXISTS user_sessions (
    id            TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    client        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ,
    revoked       BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON user_sessions (tenant_id, user_id);

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
