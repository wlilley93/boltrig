-- Nankle durable state (S6). PostgreSQL 16.
-- All tables carry tenant_id, created_at, updated_at. Timestamps are timezone-aware (UTC).
-- Tenant isolation (SEC-08, K-22) is enforced at the DB with FORCE ROW LEVEL SECURITY:
-- the app connects as a non-superuser, non-bypassing role and sets
--   SET app.tenant_id = '<tenant>'
-- per transaction; a null GUC yields zero rows (fail-closed).

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
    status       TEXT NOT NULL,                         -- pending | answered | timed_out | escalated
    timeout_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

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

-- Round Two (optional): external MCP servers Nankle consumes as adapters
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
