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
    is_active   BOOLEAN NOT NULL DEFAULT true,
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
    idempotency_mode TEXT NOT NULL DEFAULT 'cacheable', -- cacheable | disabled
    degraded_mode JSONB,
    is_active     BOOLEAN NOT NULL DEFAULT true,
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

-- Decision 0021: reviewed integration presentation data is separate from the
-- executable adapter registry. Certification/auth metadata is explicit data;
-- tenant connection rows carry only a credential reference, never material.
CREATE TABLE IF NOT EXISTS integration_catalogue (
    id              TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    label           TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN (
                      'communications','work','storage_design','crm_sales',
                      'finance','analytics_operations','browser')),
    transport       TEXT NOT NULL CHECK (transport IN (
                      'rest','mcp','channel_gateway','browser')),
    auth            JSONB NOT NULL DEFAULT '[]'::jsonb,
    description     TEXT NOT NULL,
    certification   TEXT NOT NULL DEFAULT 'uncertified' CHECK (certification IN (
                      'uncertified','certifying','certified','suspended')),
    adapter_id      TEXT,
    secret_contract JSONB,
    setup_copy      TEXT,
    access_copy     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS integration_connections (
    id                 TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    integration_id     TEXT NOT NULL,
    adapter_id         TEXT NOT NULL,
    label              TEXT NOT NULL,
    health             TEXT NOT NULL DEFAULT 'pending' CHECK (health IN (
                         'pending','ok','degraded','down','revoked')),
    credential_ref     TEXT,
    credential_owned   BOOLEAN NOT NULL DEFAULT false,
    accounts           JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_checked_at    TIMESTAMPTZ,
    revoked_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, integration_id)
      REFERENCES integration_catalogue(tenant_id, id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS integration_connections_integration_idx
  ON integration_connections(tenant_id, integration_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS integration_connections_one_active_adapter_idx
  ON integration_connections(tenant_id, adapter_id)
  WHERE health <> 'revoked';

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
    is_active            BOOLEAN NOT NULL DEFAULT true,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id, version)
);

CREATE TABLE IF NOT EXISTS agent_capabilities (
    name             TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    runtime          TEXT NOT NULL,                     -- codex | script (decision 0012)
    model_endpoint   TEXT,
    supported_skills JSONB NOT NULL,                    -- patterns
    max_depth        INT NOT NULL,
    is_ephemeral     BOOLEAN NOT NULL,
    cost_tier        TEXT NOT NULL,                     -- cheap | standard | expensive
    vision_model_endpoint TEXT,
    model_routes    JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Scoped-declarative reconciliation ([2026] LEXBY LOG-2026-07-17): is_active is
    -- the soft-active flag (list_capabilities returns only active rows, so a
    -- deactivated capability can never be selected); source is provenance -
    -- 'manifest' rows are reconciled declaratively, 'control-plane' grants only ever
    -- added. The 'control-plane' default is the fail-safe backfill for unknown rows.
    is_active        BOOLEAN NOT NULL DEFAULT true,
    source           TEXT NOT NULL DEFAULT 'control-plane'
                         CHECK (source IN ('manifest', 'control-plane')),
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

CREATE TABLE IF NOT EXISTS model_endpoints (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,                          -- anthropic | openai | ollama | vllm
    base_url    TEXT,
    model       TEXT NOT NULL,
    fallback    TEXT,
    data_class  TEXT NOT NULL DEFAULT 'standard',       -- standard | sensitive
    modalities  JSONB NOT NULL DEFAULT '["text"]'::jsonb,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,           -- reversible governed withdrawal
    revision    BIGINT NOT NULL DEFAULT 1,               -- approved mutation generation
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
    workspace_id    TEXT,                                -- originating active workspace (NULL = org-wide)
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
    target          TEXT,                                -- channel addressing: NULL/'cos' = tier-1 CoS (decision 0003 Phase 2)
    reply_route     JSONB,                               -- {"channel_id","thread","sender"} for round-trip replies
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS work_items_status_idx ON work_items (tenant_id, status);
CREATE INDEX IF NOT EXISTS work_items_workspace_idx ON work_items (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS work_items_parent_idx ON work_items (parent_id);
CREATE INDEX IF NOT EXISTS work_items_hatchet_run_idx ON work_items (tenant_id, hatchet_run_id);
-- Idempotent column adds for DBs created before Beat 3 durable delegation landed
-- (before the lease index, which references lease_expires_at).
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS lease_owner TEXT;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS attempts INT NOT NULL DEFAULT 0;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS degraded BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS result JSONB;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS workspace_id TEXT;
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
    type         TEXT NOT NULL,                         -- approval | clarification | escalation | question
    urgency      TEXT NOT NULL,                         -- blocking | async
    context      TEXT NOT NULL,
    question     TEXT NOT NULL,
    options      JSONB,
    assignee     TEXT,
    status       TEXT NOT NULL,                         -- pending | answered | consumed | timed_out | escalated
    timeout_at   TIMESTAMPTZ,
    verb         TEXT,                                  -- SEC-14: the verb this approval gates
    requested_by TEXT,                                  -- SEC-14: who raised it (anti-self-approval)
    requested_on_behalf_of TEXT,                        -- SEC-14: delegated initiator identity
    request_fingerprint TEXT,                           -- SEC-14: exact canonical request binding
    action_digest TEXT,                                 -- exact noun+verb+validated params for post-dispatch materialisation
    workspace_id TEXT,                                  -- SEC-141: originating workspace (NULL = org-wide)
    department_scope JSONB,                             -- SEC-141: originating department ids
    secure       BOOLEAN NOT NULL DEFAULT false,        -- SEC-181: secure-input question (answer is sealed, never recorded)
    secure_purpose TEXT,                                -- SEC-181: bounded purpose label (only when secure)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
-- Idempotent column adds for DBs created before SEC-14 verb-binding landed.
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS verb TEXT;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS requested_by TEXT;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS requested_on_behalf_of TEXT;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS request_fingerprint TEXT;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS action_digest TEXT;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS workspace_id TEXT;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS department_scope JSONB;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS secure BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS secure_purpose TEXT;

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
CREATE INDEX IF NOT EXISTS audit_actor_page_idx ON audit_log (tenant_id, actor, seq DESC);
CREATE INDEX IF NOT EXISTS audit_behalf_page_idx ON audit_log (tenant_id, on_behalf_of, seq DESC);

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
    tenant_id       TEXT NOT NULL,
    key             TEXT NOT NULL,
    actor           TEXT NOT NULL,
    on_behalf_of    TEXT,
    workspace_id    TEXT,
    noun            TEXT NOT NULL,
    verb            TEXT NOT NULL,
    request_hash    TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (
        status IN ('claimed', 'executing', 'completed', 'uncertain', 'uncacheable')
    ),
    owner_token     TEXT,
    lease_expires_at TIMESTAMPTZ,
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
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
    spent_tokens      BIGINT NOT NULL DEFAULT 0,        -- legacy; live usage is budget_usage
    spent_micros      BIGINT NOT NULL DEFAULT 0,        -- legacy; live usage is budget_usage
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS budget_usage (
    tenant_id          TEXT NOT NULL,
    scope_id           TEXT NOT NULL,
    window_key         TEXT NOT NULL,
    window_started_at  TIMESTAMPTZ NOT NULL,
    window_ends_at     TIMESTAMPTZ,
    reset_generation   BIGINT NOT NULL DEFAULT 0 CHECK (reset_generation >= 0),
    spent_tokens       BIGINT NOT NULL DEFAULT 0 CHECK (spent_tokens >= 0),
    spent_micros       BIGINT NOT NULL DEFAULT 0 CHECK (spent_micros >= 0),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, scope_id, window_key),
    FOREIGN KEY (tenant_id, scope_id)
        REFERENCES budgets(tenant_id, id) ON DELETE CASCADE,
    CHECK (window_ends_at IS NULL OR window_ends_at > window_started_at)
);
CREATE INDEX IF NOT EXISTS budget_usage_current_idx
    ON budget_usage (tenant_id, scope_id, window_started_at DESC);

-- Secret references only - never plaintext secrets at rest (SEC-04, FR-SEC-02).
-- ``data`` holds the reference dict the resolver consumes, SEALED at the store
-- seam (boltrig/store/sealing.py): a versioned envelope {"sealed": "v1", "ct":
-- <fernet token>} whose ciphertext is the reference dict. Legacy plaintext rows
-- (no "sealed" marker) still read; any write re-seals. The typed columns mirror
-- the reference metadata (an env var name, not secret material).
CREATE TABLE IF NOT EXISTS credential_refs (
    id          TEXT NOT NULL,                          -- "jira-oauth"
    tenant_id   TEXT NOT NULL,
    store       TEXT NOT NULL,                          -- vault | kms | docker-secret | env
    ref         TEXT NOT NULL,                          -- path/name in the external store
    data        JSONB,                                  -- the SEALED reference envelope (ciphertext)
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
    origin      TEXT NOT NULL DEFAULT 'user'
                CHECK (origin IN ('user','routine')),
    source_ref  TEXT,
    source_run_id TEXT,
    companion_id TEXT CHECK (companion_id IS NULL OR companion_id IN ('familiar','jarvis')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS conversations_user_idx ON conversations (tenant_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS conversations_routine_run_idx
    ON conversations (tenant_id, source_run_id)
    WHERE origin='routine' AND source_run_id IS NOT NULL;

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

-- A worker's secret-free acknowledgement that it constructed one exact
-- permanent-fleet generation.  Desired state remains the versioned
-- config_revisions row; this table is observation only.
CREATE TABLE IF NOT EXISTS permanent_fleet_observations (
    tenant_id       TEXT NOT NULL,
    worker_id       TEXT NOT NULL
                    CHECK (worker_id ~ '^[A-Za-z0-9._:-]{1,128}$'),
    generation      TEXT NOT NULL
                    CHECK (generation ~ '^pf_[a-f0-9]{24}$'),
    status          TEXT NOT NULL CHECK (status IN ('applied','degraded')),
    apply_mode      TEXT NOT NULL DEFAULT 'startup_snapshot'
                    CHECK (apply_mode = 'startup_snapshot'),
    applied_fields  JSONB NOT NULL DEFAULT '[]'::jsonb,
    inactive_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, worker_id),
    CONSTRAINT permanent_fleet_observation_array_shape CHECK (
      jsonb_typeof(applied_fields) = 'array'
      AND jsonb_typeof(inactive_fields) = 'array'
    )
);
CREATE INDEX IF NOT EXISTS permanent_fleet_observed_idx
  ON permanent_fleet_observations (tenant_id, observed_at DESC);

-- Redacted startup composition per boot instance.  Identities are opaque
-- digests over random boot entropy; no host name, path, URL, credential ref,
-- owner data or secret is stored here.  Expiry marks evidence stale and never
-- acts as a process heartbeat or a replica inventory.
CREATE TABLE IF NOT EXISTS birth_profile_receipts (
    tenant_id                TEXT NOT NULL,
    process_kind             TEXT NOT NULL
                             CHECK (process_kind IN ('api','fleet','hatchet')),
    instance_identity        TEXT NOT NULL
                             CHECK (instance_identity ~ '^bi_[a-f0-9]{24}$'),
    manifest_generation      TEXT NOT NULL
                             CHECK (manifest_generation ~ '^mf_[a-f0-9]{24}$'),
    addon_set_identity       TEXT NOT NULL
                             CHECK (addon_set_identity ~ '^as_[a-f0-9]{24}$'),
    codex_provider_identity  TEXT NOT NULL
                             CHECK (
                               codex_provider_identity = 'cp_off_v1'
                               OR codex_provider_identity ~ '^cp_[a-f0-9]{24}$'
                             ),
    codex_provider_state     TEXT NOT NULL
                             CHECK (codex_provider_state IN ('off','configured')),
    sensitive_role_identity  TEXT NOT NULL
                             CHECK (
                               sensitive_role_identity = 'sr_absent_v1'
                               OR sensitive_role_identity ~ '^sr_[a-f0-9]{24}$'
                             ),
    sensitive_role_state     TEXT NOT NULL
                             CHECK (sensitive_role_state IN ('absent','configured')),
    receipt_kind             TEXT NOT NULL DEFAULT 'startup_snapshot'
                             CHECK (receipt_kind = 'startup_snapshot'),
    observed_at              TIMESTAMPTZ NOT NULL,
    expires_at               TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, process_kind, instance_identity),
    CONSTRAINT birth_profile_codex_shape CHECK (
      (codex_provider_state = 'off' AND codex_provider_identity = 'cp_off_v1')
      OR
      (codex_provider_state = 'configured'
       AND codex_provider_identity ~ '^cp_[a-f0-9]{24}$')
    ),
    CONSTRAINT birth_profile_sensitive_shape CHECK (
      (sensitive_role_state = 'absent'
       AND sensitive_role_identity = 'sr_absent_v1')
      OR
      (sensitive_role_state = 'configured'
       AND sensitive_role_identity ~ '^sr_[a-f0-9]{24}$')
    ),
    CONSTRAINT birth_profile_expiry_bounded CHECK (
      expires_at > observed_at
      AND expires_at <= observed_at + interval '1 hour'
    )
);
CREATE INDEX IF NOT EXISTS birth_profile_receipts_observed_idx
  ON birth_profile_receipts (tenant_id, observed_at DESC);

-- Bounded attempt history for maintenance loops owned by the fleet process.
-- The random process identity carries no host metadata.  These rows are not a
-- heartbeat and cannot prove liveness or complete replica coverage.
CREATE TABLE IF NOT EXISTS background_job_receipts (
    tenant_id                 TEXT NOT NULL,
    job_name                  TEXT NOT NULL
                              CHECK (job_name IN ('hitl_expiry','retention','distillation',
                                                  'anchor','workflow_scheduler','pump', 'reflection')),
    process_instance_identity TEXT NOT NULL
                              CHECK (
                                process_instance_identity
                                ~ '^bjp_[a-f0-9]{24}$'
                              ),
    interval_seconds          INTEGER NOT NULL
                              CHECK (
                                interval_seconds >= 1
                                AND interval_seconds <= 604800
                              ),
    last_attempt_at           TIMESTAMPTZ NOT NULL,
    last_success_at           TIMESTAMPTZ,
    last_failure_at           TIMESTAMPTZ,
    last_outcome              TEXT NOT NULL
                              CHECK (last_outcome IN ('succeeded','failed')),
    failure_code              TEXT,
    last_item_count           INTEGER NOT NULL DEFAULT 0
                              CHECK (
                                last_item_count >= 0
                                AND last_item_count <= 1000000
                              ),
    receipt_kind              TEXT NOT NULL
                              DEFAULT 'attempt_history_not_liveness'
                              CHECK (
                                receipt_kind = 'attempt_history_not_liveness'
                              ),
    PRIMARY KEY (
      tenant_id,job_name,process_instance_identity
    ),
    CONSTRAINT background_job_timestamp_shape CHECK (
      (last_success_at IS NULL OR last_success_at <= last_attempt_at)
      AND
      (last_failure_at IS NULL OR last_failure_at <= last_attempt_at)
    ),
    CONSTRAINT background_job_outcome_shape CHECK (
      (
        last_outcome='succeeded'
        AND last_success_at=last_attempt_at
        AND failure_code IS NULL
      )
      OR
      (
        last_outcome='failed'
        AND last_failure_at=last_attempt_at
        AND failure_code='sweep_failed'
      )
    )
);
CREATE INDEX IF NOT EXISTS background_job_receipts_attempt_idx
  ON background_job_receipts (tenant_id,job_name,last_attempt_at DESC);

-- Round Three: evaluation harness (Epic EVAL)
CREATE TABLE IF NOT EXISTS eval_cases (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    target_kind TEXT NOT NULL,    -- skill | workflow | conversation
    target_ref  TEXT NOT NULL,
    input       JSONB NOT NULL,
    assertions  JSONB NOT NULL,
    labels      JSONB,
    is_active   BOOLEAN NOT NULL DEFAULT true,
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

-- Secret-free desired/observed evidence from the severed socket gateway.
-- This is operational evidence, not authority: the authored Channel row remains
-- the desired state and the gateway token's explicit channel set remains its
-- ceiling.
CREATE TABLE IF NOT EXISTS channel_gateway_status (
    tenant_id         TEXT NOT NULL,
    channel_id        TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    gateway_id        TEXT NOT NULL,
    desired_revision  TEXT NOT NULL,
    observed_revision TEXT NOT NULL,
    status            TEXT NOT NULL,
    reason_code       TEXT,
    observed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, channel_id)
);
CREATE INDEX IF NOT EXISTS channel_gateway_status_observed_idx
  ON channel_gateway_status (tenant_id, observed_at DESC);

-- Durable per-channel gateway ownership fence. The token lease id is
-- kernel-private and never projected through the browser-safe channel view.
CREATE TABLE IF NOT EXISTS channel_gateway_leases (
    tenant_id        TEXT NOT NULL,
    channel_id       TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    gateway_id       TEXT NOT NULL,
    owner_lease_id   TEXT NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, channel_id)
);
CREATE INDEX IF NOT EXISTS channel_gateway_leases_expiry_idx
  ON channel_gateway_leases (tenant_id, lease_expires_at);

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

-- Channel deliveries: durable replay-dedup markers for channel intake
-- (decision 0003 Phase 2, M3/SEC-66). One row per seen (channel, delivery_id);
-- TTL-bounded, evicted opportunistically on write. RLS-scoped.
CREATE TABLE IF NOT EXISTS channel_deliveries (
    tenant_id         TEXT NOT NULL,
    channel_id        TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    delivery_id       TEXT NOT NULL,
    seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, channel_id, delivery_id)
);
CREATE INDEX IF NOT EXISTS channel_deliveries_expiry_idx
    ON channel_deliveries (tenant_id, expires_at);

-- Approved event-source bindings for stored workflows. Webhook bearer material
-- is hash-only and shown once; channel bindings reuse the independently signed
-- channel ingress. The grant snapshot is a ceiling, never a durable grant.
CREATE TABLE IF NOT EXISTS workflow_triggers (
    id             TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    workflow_id    TEXT NOT NULL,
    workspace_id   TEXT,
    name           TEXT NOT NULL,
    source         TEXT NOT NULL CHECK (source IN ('webhook','channel')),
    owner_id       TEXT NOT NULL,
    grant_allow    JSONB NOT NULL DEFAULT '[]'::jsonb,
    grant_deny     JSONB NOT NULL DEFAULT '[]'::jsonb,
    channel_id     TEXT REFERENCES channels(id) ON DELETE CASCADE,
    secret_hash    TEXT,
    enabled        BOOLEAN NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,workflow_id,name),
    CONSTRAINT workflow_trigger_shape CHECK (
      (source='webhook' AND channel_id IS NULL
        AND secret_hash ~ '^[0-9a-f]{64}$')
      OR
      (source='channel' AND channel_id IS NOT NULL AND secret_hash IS NULL)
    ),
    CONSTRAINT workflow_trigger_grants_arrays CHECK (
      jsonb_typeof(grant_allow)='array' AND jsonb_typeof(grant_deny)='array'
    )
);
CREATE INDEX IF NOT EXISTS workflow_triggers_workflow_idx
  ON workflow_triggers(tenant_id,workflow_id,created_at,id);
CREATE INDEX IF NOT EXISTS workflow_triggers_channel_idx
  ON workflow_triggers(tenant_id,channel_id,enabled)
  WHERE source='channel';

-- One immutable receipt per trigger + source event. The digest is derived from
-- the source event id; payload bodies and raw ids are not retained here.
CREATE TABLE IF NOT EXISTS workflow_trigger_deliveries (
    tenant_id           TEXT NOT NULL,
    trigger_id          TEXT NOT NULL,
    source_event_digest TEXT NOT NULL,
    status              TEXT NOT NULL,
    authority_subject   TEXT,
    run_id              TEXT,
    hitl_request_id     TEXT,
    reason              TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,trigger_id,source_event_digest),
    FOREIGN KEY (tenant_id,trigger_id)
      REFERENCES workflow_triggers(tenant_id,id) ON DELETE CASCADE,
    CONSTRAINT workflow_trigger_event_digest_sha256
      CHECK (source_event_digest ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS workflow_trigger_deliveries_recent_idx
  ON workflow_trigger_deliveries(tenant_id,trigger_id,created_at DESC);

-- Canonical active workflow schedule desired state. The captured subject and
-- grant arrays are only a revocable ceiling: the scheduler re-authorizes the
-- current User and workspace membership before every occurrence.
CREATE TABLE IF NOT EXISTS workflow_schedules (
    tenant_id          TEXT NOT NULL,
    workflow_id        TEXT NOT NULL,
    workspace_id       TEXT,
    cron               TEXT NOT NULL,
    timezone           TEXT NOT NULL,
    authority_subject  TEXT,
    grant_allow        JSONB NOT NULL DEFAULT '[]'::jsonb,
    grant_deny         JSONB NOT NULL DEFAULT '[]'::jsonb,
    observed_status    TEXT NOT NULL DEFAULT 'pending'
                       CHECK (observed_status IN (
                         'pending','active','needs_action',
                         'unavailable','degraded'
                       )),
    observed_reason    TEXT,
    next_due_at        TIMESTAMPTZ,
    last_scheduled_for TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    observed_at        TIMESTAMPTZ,
    PRIMARY KEY (tenant_id,workflow_id),
    CONSTRAINT workflow_schedule_grants_arrays CHECK (
      jsonb_typeof(grant_allow)='array' AND jsonb_typeof(grant_deny)='array'
    )
);
CREATE INDEX IF NOT EXISTS workflow_schedules_due_idx
  ON workflow_schedules(tenant_id,next_due_at,workflow_id);

-- One durable logical run identity per due occurrence. Claims are atomic and
-- lease-fenced across replicas; terminal rows survive unschedule/restart.
CREATE TABLE IF NOT EXISTS workflow_schedule_occurrences (
    tenant_id        TEXT NOT NULL,
    workflow_id      TEXT NOT NULL,
    scheduled_for    TIMESTAMPTZ NOT NULL,
    run_id           TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN (
                       'claimed','retryable','queued','succeeded','failed'
                     )),
    lease_owner      TEXT,
    lease_expires_at TIMESTAMPTZ,
    engine_run_id    TEXT,
    reason           TEXT,
    attempts         INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    workflow_sha256  TEXT,
    schedule_sha256  TEXT,
    claimed_at       TIMESTAMPTZ,
    enqueued_at      TIMESTAMPTZ,
    outcome_at       TIMESTAMPTZ,
    manual_retries   INTEGER NOT NULL DEFAULT 0,
    last_retry_at    TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,workflow_id,scheduled_for),
    UNIQUE (tenant_id,run_id),
    CONSTRAINT workflow_schedule_occurrence_manual_retries
      CHECK (manual_retries >= 0),
    CONSTRAINT workflow_schedule_occurrence_lease_shape CHECK (
      (status='claimed' AND lease_owner IS NOT NULL
                        AND lease_expires_at IS NOT NULL)
      OR
      (status<>'claimed' AND lease_owner IS NULL
                         AND lease_expires_at IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS workflow_schedule_occurrences_claim_idx
  ON workflow_schedule_occurrences(
    tenant_id,status,lease_expires_at,scheduled_for
  );

-- Channel outbox: the durable outbound hand-off for socket-class channels
-- (decision 0003 Phase 2). The kernel enqueues; the severed sidecar claims
-- (leased, one winner - the work_items claim shape), delivers over its held
-- platform connection, then acks (terminal) or fails (backoff-gated retry,
-- terminal 'failed' at the attempt cap). RLS-scoped; the payload carries no
-- credential (platform secrets are connect-time injected into the sidecar).
CREATE TABLE IF NOT EXISTS channel_outbox (
    id                TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    channel_id        TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending | in_flight | delivered | failed
    attempts          INTEGER NOT NULL DEFAULT 0,
    lease_owner       TEXT,
    lease_expires_at  TIMESTAMPTZ,
    next_attempt_at   TIMESTAMPTZ,
    last_error        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS channel_outbox_claim_idx
    ON channel_outbox (tenant_id, channel_id, status, created_at);

-- Decision 0021: durable realtime-call metadata and normalized events. Provider
-- media never enters these tables. The bearer column contains only a sha256
-- digest and is cleared atomically on the first successful gateway claim.
CREATE TABLE IF NOT EXISTS realtime_calls (
    id                       TEXT NOT NULL,
    tenant_id                TEXT NOT NULL,
    conversation_id          TEXT NOT NULL,
    owner_id                 TEXT NOT NULL,
    channel_id               TEXT REFERENCES channels(id) ON DELETE SET NULL,
    status                   TEXT NOT NULL,
    participants             JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_context             JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider_class           TEXT NOT NULL DEFAULT 'realtime_voice',
    run_id                   TEXT,
    agent_profile_id         TEXT,
    model_profile_id         TEXT,
    media_token_hash         TEXT,
    media_token_expires_at   TIMESTAMPTZ,
    started_at               TIMESTAMPTZ,
    ended_at                 TIMESTAMPTZ,
    unavailable_reason       TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, conversation_id)
      REFERENCES conversations(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS realtime_calls_owner_idx
  ON realtime_calls(tenant_id, owner_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS realtime_calls_media_claim_idx
  ON realtime_calls(tenant_id, media_token_hash)
  WHERE media_token_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS realtime_call_events (
    id               TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    call_id          TEXT NOT NULL,
    type             TEXT NOT NULL,
    participant_id   TEXT,
    payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, call_id)
      REFERENCES realtime_calls(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS realtime_call_events_call_idx
  ON realtime_call_events(tenant_id, call_id, created_at, id);

-- Decision 0021 desktop device boundary. Enrollment/session tokens and claim
-- tokens are digest-only. Leases are immutable exact-action envelopes whose
-- one approval id and issued->claimed->settled lifecycle are database-fenced.
CREATE TABLE IF NOT EXISTS device_enrollments (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
    label TEXT NOT NULL, authorization_code_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL, consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,authorization_code_hash),
    CONSTRAINT device_enrollment_hash_sha256
      CHECK (authorization_code_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
    label TEXT NOT NULL, public_key TEXT NOT NULL,
    public_key_fingerprint TEXT NOT NULL, lease_verify_key_id TEXT NOT NULL,
    availability_mode TEXT NOT NULL DEFAULT 'unlocked_session',
    presence TEXT NOT NULL DEFAULT 'offline',
    session_token_hash TEXT, session_expires_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,session_token_hash),
    CONSTRAINT device_availability_mode_valid
      CHECK (availability_mode IN ('unlocked_session')),
    CONSTRAINT device_presence_valid
      CHECK (presence IN ('offline','online','locked','revoked')),
    CONSTRAINT device_session_hash_sha256
      CHECK (session_token_hash IS NULL OR session_token_hash ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS devices_owner_idx
  ON devices(tenant_id,owner_id,created_at);
CREATE TABLE IF NOT EXISTS device_roots (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, device_id TEXT NOT NULL,
    label TEXT NOT NULL, scope TEXT NOT NULL,
    command_enabled BOOLEAN NOT NULL DEFAULT false,
    git_enabled BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), revoked_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,id,device_id),
    CONSTRAINT device_root_scope_valid CHECK (scope IN ('read','read_write')),
    FOREIGN KEY (tenant_id,device_id) REFERENCES devices(tenant_id,id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS device_roots_device_idx
  ON device_roots(tenant_id,device_id,created_at);
CREATE TABLE IF NOT EXISTS device_leases (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, device_id TEXT NOT NULL,
    root_id TEXT NOT NULL, owner_id TEXT NOT NULL, verb TEXT NOT NULL,
    action JSONB NOT NULL, action_digest TEXT NOT NULL,
    approval_id TEXT NOT NULL, issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL, signature TEXT NOT NULL,
    signing_key_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'issued',
    claim_token_hash TEXT, claim_expires_at TIMESTAMPTZ,
    claimed_at TIMESTAMPTZ, settled_at TIMESTAMPTZ, receipt JSONB,
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,approval_id),
    CONSTRAINT device_lease_verb_valid
      CHECK (verb IN (
        'device.file.list','device.file.read','device.file.write',
        'device.command.run'
      )),
    CONSTRAINT device_lease_status_valid
      CHECK (status IN ('issued','claimed','completed','failed','expired')),
    CONSTRAINT device_lease_action_object
      CHECK (jsonb_typeof(action) = 'object'),
    CONSTRAINT device_lease_digest_sha256
      CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT device_lease_claim_hash_sha256
      CHECK (claim_token_hash IS NULL OR claim_token_hash ~ '^[0-9a-f]{64}$'),
    FOREIGN KEY (tenant_id,device_id) REFERENCES devices(tenant_id,id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,root_id,device_id)
      REFERENCES device_roots(tenant_id,id,device_id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,approval_id) REFERENCES hitl_requests(tenant_id,id)
      ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS device_leases_pending_idx
  ON device_leases(tenant_id,device_id,status,issued_at);

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

-- External MCP lifecycle is durable independently of the runtime adapter
-- instance. url/transport/credential are nullable legacy registration fields;
-- current registration authority remains the governed adapters/credential_refs
-- rows. Probe evidence below deliberately stores no credential or raw error.
CREATE TABLE IF NOT EXISTS mcp_servers (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    url         TEXT,
    transport   TEXT,
    credential  TEXT,
    status      TEXT NOT NULL DEFAULT 'inactive'
                CONSTRAINT mcp_servers_status_check
                CHECK (status IN ('inactive', 'active', 'retired')),
    config_revision BIGINT NOT NULL DEFAULT 1
                CONSTRAINT mcp_servers_config_revision_check
                CHECK (config_revision >= 1),
    last_known_tools JSONB NOT NULL DEFAULT '[]'::jsonb
                CONSTRAINT mcp_servers_tools_array_check
                CHECK (jsonb_typeof(last_known_tools) = 'array'),
    tools_observed_at TIMESTAMPTZ,
    retired_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT mcp_servers_retired_at_check CHECK (
      (status = 'retired' AND retired_at IS NOT NULL)
      OR (status <> 'retired' AND retired_at IS NULL)
    ),
    PRIMARY KEY (tenant_id, id),
    CONSTRAINT mcp_servers_adapter_fkey
      FOREIGN KEY (tenant_id, id) REFERENCES adapters(tenant_id, id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS mcp_servers_lifecycle_idx
  ON mcp_servers (tenant_id, status, id);

CREATE TABLE IF NOT EXISTS mcp_probe_receipts (
    tenant_id   TEXT NOT NULL,
    server_id   TEXT NOT NULL,
    probe_id    TEXT NOT NULL,
    outcome     TEXT NOT NULL CHECK (outcome IN ('succeeded', 'failed')),
    failure_code TEXT CHECK (
      failure_code IS NULL OR failure_code IN (
        'credential_unavailable', 'egress_denied', 'transport_unavailable',
        'protocol_invalid', 'discovery_invalid', 'unexpected_failure'
      )
    ),
    observed_at TIMESTAMPTZ NOT NULL,
    tool_count  INTEGER NOT NULL CHECK (tool_count BETWEEN 0 AND 500),
    receipt_kind TEXT NOT NULL DEFAULT 'content_free_probe_attempt'
                 CHECK (receipt_kind = 'content_free_probe_attempt'),
    CHECK (
      (outcome = 'succeeded' AND failure_code IS NULL)
      OR (outcome = 'failed' AND failure_code IS NOT NULL)
    ),
    PRIMARY KEY (tenant_id, server_id, probe_id),
    FOREIGN KEY (tenant_id, server_id) REFERENCES mcp_servers(tenant_id, id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS mcp_probe_receipts_recent_idx
  ON mcp_probe_receipts (tenant_id, server_id, observed_at DESC, probe_id DESC);

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

-- Mutable scheduling metadata for otherwise frozen queued user messages. The
-- message row remains the durable content authority; this projection controls
-- only which pending steer the next serial turn claims.
CREATE TABLE IF NOT EXISTS conversation_steer_queue (
    tenant_id       TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    queue_position  BIGINT NOT NULL CHECK (queue_position > 0),
    claimed_run_id  TEXT,
    enqueued_at     TIMESTAMPTZ NOT NULL,
    claimed_at      TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, message_id),
    FOREIGN KEY (tenant_id, conversation_id)
      REFERENCES conversations(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, message_id)
      REFERENCES conversation_messages(tenant_id, id) ON DELETE CASCADE,
    CHECK ((claimed_run_id IS NULL) = (claimed_at IS NULL))
);
CREATE INDEX IF NOT EXISTS conversation_steer_queue_pending_idx
  ON conversation_steer_queue
  (tenant_id, conversation_id, queue_position, enqueued_at, message_id)
  WHERE claimed_run_id IS NULL;

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
    -- Forced rotation of a PROVISIONING credential ([2026] VJS-COUNTY 8, D7).
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
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
CREATE UNIQUE INDEX IF NOT EXISTS invitations_one_pending_email_idx
    ON user_invitations (tenant_id, lower(email)) WHERE status = 'pending';
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

-- Password recovery (SEC-AUTH-RECOVERY-01). One row per recoverable identity
-- means issuing a new token invalidates the previous token. The bearer secret is
-- never stored: token_hash is its SHA-256 digest. Consumption and all dependent
-- credential/session writes happen in one store statement.
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    token_hash  TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, user_id),
    CONSTRAINT password_reset_token_hash_sha256
      CHECK (token_hash ~ '^[0-9a-f]{64}$')
);
CREATE UNIQUE INDEX IF NOT EXISTS password_reset_token_hash_idx
    ON password_reset_tokens (token_hash);

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
    active_org_id TEXT,                             -- active ORG hint ([2026] VJS-COUNTY 11, D2); the ONE active tenant, re-authorized against org_members every request
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON user_sessions (tenant_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS sessions_token_hash_idx
    ON user_sessions (token_hash) WHERE token_hash IS NOT NULL;

-- TOTP two-factor ([2026] VJS-COUNTY 10). Kept in their OWN tables, apart from the
-- users identity row (like user_credentials), so no 2FA secret rides in a user
-- view/export. Tenant-isolated + RLS-scoped (see rls.sql).
--
-- D1: the TOTP enrolment row. The base32 shared secret is NOT stored here: it is
-- SEALED in credential_refs (envelope-encrypted at the store seam, see
-- boltrig/store/sealing.py) and referenced by secret_ref (the same sealed seam the
-- channel signing secret + per-org AI keys use). Only the ref + the enrolled flag
-- live here. enrolled is false for a begun-but-unconfirmed enrolment, true only
-- after a verify-enroll code confirms the authenticator (D3).
CREATE TABLE IF NOT EXISTS user_totp (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    secret_ref  TEXT NOT NULL,          -- id into credential_refs (the SEALED secret); NEVER the secret
    enrolled    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

-- D2: one-time recovery codes, stored ONLY as sha256 hashes (never plaintext). Each
-- is single-use (used_at flips once, atomically) and is a FALLBACK for a lost
-- authenticator, never a bypass of the factor.
CREATE TABLE IF NOT EXISTS user_recovery_codes (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    code_hash   TEXT NOT NULL,          -- sha256 of a recovery code; NEVER the code
    used_at     TIMESTAMPTZ,            -- single-use: set once when redeemed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id, code_hash)
);

-- D3: the pending pre-session login challenge. Minted after the password verifies
-- when 2FA is due; carries NO access on its own (no session issued) - only a follow-
-- up TOTP/recovery-code verify against it issues the session. Only the sha256 of the
-- token is stored; it is short-lived (expires_at) and single-use (deleted on use).
CREATE TABLE IF NOT EXISTS two_factor_challenges (
    tenant_id   TEXT NOT NULL,
    token_hash  TEXT NOT NULL,          -- sha256 of the challenge token; NEVER the token
    user_id     TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, token_hash)
);
CREATE INDEX IF NOT EXISTS tfa_challenges_user_idx
    ON two_factor_challenges (tenant_id, user_id);

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
    -- tenant_id is part of the KEY, not merely a column. workspace ids are unique
    -- only WITHIN an org (see the workspaces PK above) and provisioning mints the
    -- same id `ws_default` for every org, so a (workspace_id, user_id) key
    -- collides across orgs BY CONSTRUCTION: one org's membership upsert would
    -- land on another org's row and silently rewrite that user's role there.
    -- Migration 0038.
    PRIMARY KEY (tenant_id, workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS workspace_members_user_idx
    ON workspace_members (tenant_id, user_id);
CREATE INDEX IF NOT EXISTS workspace_members_ws_idx
    ON workspace_members (tenant_id, workspace_id);

-- ===========================================================================
-- Cross-tenant identity ([2026] VJS-COUNTY 11). Identity is anchored on the
-- normalised EMAIL: the shared credential + 2FA are held ONCE at the identity
-- realm (the session/console tenant, keyed by email) and this table is the
-- global email -> orgs membership index login reads to learn which orgs an email
-- belongs to BEFORE any tenant is bound.
--
-- DELIBERATELY RLS-EXCLUDED (like personal_access_tokens + channels): it is the
-- pre-tenant lookup, resolved by the normalised email (identity), so it cannot
-- live inside a tenant fence. It holds NO secret and NO business data - only
-- (email, tenant_id, role) membership POINTERS. It is NOT an authority: every
-- access decision still re-checks the RLS-fenced org_members row for the bound
-- tenant (this index only ENUMERATES candidate orgs). Kept in lockstep with
-- org_members by add_org_member / remove_org_member so it never drifts. A leak of
-- this table would reveal only which orgs an email is in, never any org's data.
CREATE TABLE IF NOT EXISTS identity_orgs (
    email       TEXT NOT NULL,          -- normalised identity email (the shared anchor)
    tenant_id   TEXT NOT NULL,          -- an org the email is a member of (== organisations.id)
    role        TEXT NOT NULL DEFAULT 'member',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (email, tenant_id)
);
CREATE INDEX IF NOT EXISTS identity_orgs_email_idx ON identity_orgs (email);

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
    provider       TEXT NOT NULL,          -- 'anthropic' | 'openai' | ... (selection)
    model          TEXT NOT NULL,          -- pinned model/version
    credential_ref TEXT NOT NULL,          -- id into credential_refs (the SEALED key); NEVER the raw key
    base_url       TEXT,                   -- OPTIONAL provider host the config routes to (NULL => use the endpoint's own); routing metadata, never a secret
    modality       TEXT NOT NULL DEFAULT 'text', -- text = main API route; vision = optional vision route
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, level, scope_id, modality)
);

-- Short-lived AI-key intake. Secret material is envelope-sealed in the
-- credential_refs row named by secret_ref; this proposal contains only bounded
-- routing metadata, a one-way digest and caller/approval bindings.
CREATE TABLE IF NOT EXISTS ai_key_secret_proposals (
    id                     TEXT NOT NULL
                           CHECK (id ~ '^akp_[a-f0-9]{32}$'),
    tenant_id              TEXT NOT NULL,
    requested_by           TEXT NOT NULL,
    requested_on_behalf_of TEXT,
    workspace_id           TEXT,
    level                  TEXT NOT NULL
                           CHECK (level IN ('org','workspace','user')),
    scope_id               TEXT NOT NULL,
    provider               TEXT NOT NULL,
    model                  TEXT NOT NULL,
    base_url               TEXT,
    modality               TEXT NOT NULL DEFAULT 'text',
    secret_ref             TEXT,
    secret_digest          TEXT NOT NULL
                           CHECK (secret_digest ~ '^[a-f0-9]{64}$'),
    status                 TEXT NOT NULL DEFAULT 'pending'
                           CHECK (status IN (
                             'pending','consumed','rejected','expired','invalidated'
                           )),
    approval_id            TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at             TIMESTAMPTZ NOT NULL,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at            TIMESTAMPTZ,
    PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,approval_id)
      REFERENCES hitl_requests(tenant_id,id),
    CONSTRAINT ai_key_secret_proposal_bounded_expiry CHECK (
      expires_at > created_at
      AND expires_at <= created_at + interval '15 minutes'
    ),
    CONSTRAINT ai_key_secret_proposal_state_shape CHECK (
      (status='pending' AND secret_ref IS NOT NULL AND consumed_at IS NULL)
      OR
      (status='consumed' AND secret_ref IS NULL AND consumed_at IS NOT NULL)
      OR
      (status IN ('rejected','expired','invalidated')
       AND secret_ref IS NULL AND consumed_at IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS ai_key_secret_proposals_requester_idx
    ON ai_key_secret_proposals (
      tenant_id,requested_by,requested_on_behalf_of,created_at DESC
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

CREATE TABLE IF NOT EXISTS memory_projection_statuses (
    id             TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    projection_id  TEXT NOT NULL,
    operation      TEXT NOT NULL CHECK (operation IN ('remember', 'forget')),
    status         TEXT NOT NULL CHECK (
        (operation = 'remember' AND status IN ('pending', 'written', 'failed'))
        OR (operation = 'forget' AND status IN ('pending', 'deleted', 'delete_failed'))
    ),
    fact_id        TEXT,
    target         TEXT,
    projection_ref TEXT,
    error          TEXT,
    enqueue_attempts INTEGER NOT NULL DEFAULT 0,
    operation_attempts INTEGER NOT NULL DEFAULT 0,
    max_operation_attempts INTEGER NOT NULL DEFAULT 1,
    first_attempt_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    failure_code TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    CONSTRAINT memory_projection_enqueue_attempts_check
      CHECK (enqueue_attempts BETWEEN 0 AND 1),
    CONSTRAINT memory_projection_operation_attempts_check
      CHECK (
        max_operation_attempts BETWEEN 1 AND 5
        AND operation_attempts BETWEEN 0 AND max_operation_attempts
      ),
    CONSTRAINT memory_projection_failure_code_check
      CHECK (
        failure_code IS NULL OR failure_code IN (
          'enqueue_failed',
          'projection_operation_failed',
          'projection_not_configured',
          'invalid_projection_result'
        )
      )
);
CREATE INDEX IF NOT EXISTS memory_projection_statuses_fact_idx
    ON memory_projection_statuses (tenant_id, fact_id, projection_id);

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

-- Workflow run records (design brief 22.1): one row per workflow execution,
-- recorded after a successful execute. Feeds the automations home cards with
-- REAL run stats (run_count, success_count, last_run_at) per workflow. This is
-- observability-only: a write failure is swallowed by the route so it can NEVER
-- break workflow execution. Tenant-scoped (SEC-08); RLS-listed in rls.sql.
CREATE TABLE IF NOT EXISTS workflow_run_records (
    tenant_id  TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    status     TEXT NOT NULL,                       -- completed | failed | paused | ...
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id)
);
CREATE INDEX IF NOT EXISTS workflow_run_records_wf_idx
    ON workflow_run_records (tenant_id, workflow_id);

CREATE TABLE IF NOT EXISTS execution_root_runs (
    tenant_id               TEXT NOT NULL,
    workspace_id            TEXT NOT NULL,
    root_run_id             TEXT NOT NULL,
    requested_by_user_id    TEXT NOT NULL,
    objective_digest        TEXT NOT NULL,
    profile                 JSONB NOT NULL,
    policy_generation       INT NOT NULL,
    status                  TEXT NOT NULL,
    cancellation            JSONB,
    final_synthesis_digest  TEXT,
    version                 INT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner            TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id)
);

CREATE TABLE IF NOT EXISTS execution_phases (
    tenant_id           TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    root_run_id         TEXT NOT NULL,
    id                  TEXT NOT NULL,
    ordinal             INT NOT NULL,
    name                TEXT NOT NULL,
    objective_digest    TEXT NOT NULL,
    mode                TEXT NOT NULL,
    profile             JSONB NOT NULL,
    skills              JSONB NOT NULL,
    policy_generation   INT NOT NULL,
    dependencies        JSONB NOT NULL,
    retry               JSONB NOT NULL,
    status              TEXT NOT NULL,
    terminal_outcome    JSONB,
    version             INT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
);

CREATE TABLE IF NOT EXISTS execution_work_items (
    tenant_id               TEXT NOT NULL,
    workspace_id            TEXT NOT NULL,
    root_run_id             TEXT NOT NULL,
    id                      TEXT NOT NULL,
    phase_id                TEXT NOT NULL,
    ordinal                 INT NOT NULL,
    intent_digest           TEXT NOT NULL,
    dependencies            JSONB NOT NULL,
    parent_id               TEXT,
    requires_verification   BOOLEAN NOT NULL,
    status                  TEXT NOT NULL,
    version                 INT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner            TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
);

CREATE TABLE IF NOT EXISTS execution_assignments (
    tenant_id               TEXT NOT NULL,
    workspace_id            TEXT NOT NULL,
    root_run_id             TEXT NOT NULL,
    id                      TEXT NOT NULL,
    phase_id                TEXT NOT NULL,
    work_item_id            TEXT NOT NULL,
    runtime_identity_id     TEXT NOT NULL,
    attempt                 INT NOT NULL,
    profile                 JSONB NOT NULL,
    skills                  JSONB NOT NULL,
    authority               JSONB NOT NULL,
    lease                   JSONB,
    attestation_set         JSONB,
    replaces_assignment_id  TEXT,
    status                  TEXT NOT NULL,
    version                 INT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner            TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
);

CREATE TABLE IF NOT EXISTS execution_results (
    tenant_id           TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    root_run_id         TEXT NOT NULL,
    id                  TEXT NOT NULL,
    phase_id            TEXT NOT NULL,
    work_item_id        TEXT NOT NULL,
    assignment_id       TEXT NOT NULL,
    output_digest       TEXT NOT NULL,
    status              TEXT NOT NULL,
    evidence            JSONB NOT NULL,
    findings            JSONB NOT NULL,
    blockers            JSONB NOT NULL,
    handoffs            JSONB NOT NULL,
    usage               JSONB NOT NULL,
    completed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
);

CREATE TABLE IF NOT EXISTS execution_verifications (
    tenant_id           TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    root_run_id         TEXT NOT NULL,
    id                  TEXT NOT NULL,
    phase_id            TEXT NOT NULL,
    work_item_id        TEXT NOT NULL,
    result_id           TEXT NOT NULL,
    status              TEXT NOT NULL,
    evidence_digest     TEXT NOT NULL,
    checks              JSONB NOT NULL,
    verified_by         JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
);

CREATE TABLE IF NOT EXISTS execution_commands (
    tenant_id           TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    root_run_id         TEXT NOT NULL,
    command_id          TEXT NOT NULL,
    request_digest      TEXT NOT NULL,
    aggregate_kind      TEXT NOT NULL,
    aggregate_id        TEXT NOT NULL,
    status              TEXT NOT NULL,
    previous_version    INT,
    resulting_version   INT,
    submitted           JSONB NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, command_id)
);

CREATE TABLE IF NOT EXISTS execution_events (
    tenant_id           TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    root_run_id         TEXT NOT NULL,
    sequence            BIGINT NOT NULL,
    event_id            TEXT NOT NULL,
    aggregate_kind      TEXT NOT NULL,
    aggregate_id        TEXT NOT NULL,
    kind                TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL,
    correlation_id      TEXT NOT NULL,
    causation_command_id TEXT,
    source_owner        TEXT NOT NULL,
    source_sequence     BIGINT,
    payload             JSONB NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, sequence)
);

CREATE TABLE IF NOT EXISTS execution_outbox (
    tenant_id           TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    root_run_id         TEXT NOT NULL,
    id                  TEXT NOT NULL,
    event_sequence      BIGINT NOT NULL,
    destination         TEXT NOT NULL,
    delivery_key        TEXT NOT NULL,
    status              TEXT NOT NULL,
    attempts            INT NOT NULL DEFAULT 0,
    claim_owner         TEXT,
    claimed_at          TIMESTAMPTZ,
    claim_expires_at    TIMESTAMPTZ,
    available_at        TIMESTAMPTZ NOT NULL,
    requested_available_at TIMESTAMPTZ NOT NULL,
    intent_ordinal      INT NOT NULL,
    delivered_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
);

CREATE TABLE IF NOT EXISTS runtime_identities (
    tenant_id           TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    id                  TEXT NOT NULL,
    principal_user_id   TEXT NOT NULL,
    status              TEXT NOT NULL,
    generation          INT NOT NULL,
    profile             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, workspace_id, id)
);

CREATE TABLE IF NOT EXISTS codex_thread_bindings (
    tenant_id                   TEXT NOT NULL,
    workspace_id                TEXT NOT NULL,
    root_run_id                 TEXT NOT NULL,
    phase_id                    TEXT NOT NULL,
    assignment_id               TEXT NOT NULL,
    runtime_identity_id         TEXT NOT NULL,
    kind                        TEXT NOT NULL,
    thread_id                   TEXT NOT NULL,
    native_parent_thread_id     TEXT,
    bound_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                TEXT NOT NULL DEFAULT 'boltrig',
    runtime_source_owner        TEXT NOT NULL DEFAULT 'codex',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, thread_id)
);

CREATE TABLE IF NOT EXISTS codex_turn_bindings (
    tenant_id                   TEXT NOT NULL,
    workspace_id                TEXT NOT NULL,
    root_run_id                 TEXT NOT NULL,
    thread_id                   TEXT NOT NULL,
    kind                        TEXT NOT NULL,
    turn_id                     TEXT NOT NULL,
    native_parent_turn_id       TEXT,
    bound_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                TEXT NOT NULL DEFAULT 'boltrig',
    runtime_source_owner        TEXT NOT NULL DEFAULT 'codex',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, thread_id, turn_id)
);

CREATE TABLE IF NOT EXISTS codex_item_bindings (
    tenant_id                   TEXT NOT NULL,
    workspace_id                TEXT NOT NULL,
    root_run_id                 TEXT NOT NULL,
    thread_id                   TEXT NOT NULL,
    turn_id                     TEXT NOT NULL,
    kind                        TEXT NOT NULL,
    item_id                     TEXT NOT NULL,
    native_parent_item_id       TEXT,
    bound_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                TEXT NOT NULL DEFAULT 'boltrig',
    runtime_source_owner        TEXT NOT NULL DEFAULT 'codex',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, thread_id, turn_id, item_id)
);

CREATE TABLE IF NOT EXISTS root_engine_decisions (
    tenant_id               TEXT NOT NULL,
    workspace_id            TEXT NOT NULL,
    root_run_id             TEXT NOT NULL,
    workload                TEXT NOT NULL,
    compatibility           TEXT NOT NULL,
    policy_generation       INT NOT NULL,
    policy_digest           TEXT NOT NULL,
    route                   TEXT NOT NULL,
    execution_result_source TEXT NOT NULL,
    reason_code             TEXT NOT NULL,
    canary_bucket           INT,
    decision_digest         TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner            TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id)
);

CREATE TABLE IF NOT EXISTS grant_leases (
    lease_id                          TEXT NOT NULL,
    tenant_id                         TEXT NOT NULL,
    workspace_id                      TEXT NOT NULL,
    root_run_id                       TEXT NOT NULL,
    phase_id                          TEXT NOT NULL,
    assignment_id                     TEXT NOT NULL,
    issue_operation_id                TEXT NOT NULL,
    token_digest                      TEXT NOT NULL,
    authority_evaluation_id           TEXT NOT NULL,
    authority_evaluation_digest       TEXT NOT NULL,
    authority_policy_generation       BIGINT NOT NULL,
    permitted_verbs                   JSONB NOT NULL,
    issued_at                         TIMESTAMPTZ NOT NULL,
    expires_at                        TIMESTAMPTZ NOT NULL,
    max_ttl_seconds                   INT NOT NULL,
    expected_current_lease_generation BIGINT,
    lease_generation                  BIGINT NOT NULL,
    status                            TEXT NOT NULL,
    revoked_at                        TIMESTAMPTZ,
    revocation_reason                 TEXT,
    created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                      TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (lease_id)
);

CREATE TABLE IF NOT EXISTS grant_authority_snapshots (
    tenant_id                     TEXT NOT NULL,
    workspace_id                  TEXT NOT NULL,
    root_run_id                   TEXT NOT NULL,
    phase_id                      TEXT NOT NULL,
    assignment_id                 TEXT NOT NULL,
    authority_evaluation_id       TEXT NOT NULL,
    authority_evaluation_digest   TEXT NOT NULL,
    authority_policy_generation   BIGINT NOT NULL,
    permitted_verbs               JSONB NOT NULL,
    installed_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                  TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
);

CREATE TABLE IF NOT EXISTS grant_lease_cancelled_assignments (
    tenant_id       TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    root_run_id     TEXT NOT NULL,
    phase_id        TEXT NOT NULL,
    assignment_id   TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason          TEXT NOT NULL,
    engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
);

CREATE TABLE IF NOT EXISTS grant_lease_cancelled_roots (
    tenant_id       TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    root_run_id     TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason          TEXT NOT NULL,
    engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id)
);

CREATE TABLE IF NOT EXISTS model_proxy_grants (
    grant_id                     TEXT NOT NULL,
    tenant_id                    TEXT NOT NULL,
    workspace_id                 TEXT NOT NULL,
    root_run_id                  TEXT NOT NULL,
    phase_id                     TEXT NOT NULL,
    assignment_id                TEXT NOT NULL,
    cell_id                      TEXT NOT NULL,
    pid                          BIGINT NOT NULL,
    pid_start_ticks              BIGINT NOT NULL,
    boot_id                      TEXT NOT NULL,
    pid_namespace_inode          BIGINT NOT NULL,
    cgroup_identity_digest       TEXT NOT NULL,
    model_id                     TEXT NOT NULL,
    model_policy_digest          TEXT NOT NULL,
    budget_id                    TEXT NOT NULL,
    max_input_tokens             BIGINT NOT NULL,
    max_output_tokens            BIGINT NOT NULL,
    max_total_tokens             BIGINT NOT NULL,
    max_cost_micros              BIGINT NOT NULL,
    budget_policy_digest         TEXT NOT NULL,
    bearer_digest                TEXT NOT NULL,
    startup_request_digest       TEXT NOT NULL,
    issued_at                    TIMESTAMPTZ NOT NULL,
    expires_at                   TIMESTAMPTZ NOT NULL,
    generation                   BIGINT NOT NULL,
    status                       TEXT NOT NULL,
    revoked_at                   TIMESTAMPTZ,
    revocation_reason            TEXT,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                 TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (grant_id)
);

CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_roots (
    tenant_id       TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    root_run_id     TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason          TEXT NOT NULL,
    engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id)
);

CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_phases (
    tenant_id       TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    root_run_id     TEXT NOT NULL,
    phase_id        TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason          TEXT NOT NULL,
    engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id)
);

CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_assignments (
    tenant_id       TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    root_run_id     TEXT NOT NULL,
    phase_id        TEXT NOT NULL,
    assignment_id   TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason          TEXT NOT NULL,
    engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
);

CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_cells (
    tenant_id                TEXT NOT NULL,
    workspace_id             TEXT NOT NULL,
    root_run_id              TEXT NOT NULL,
    phase_id                 TEXT NOT NULL,
    assignment_id            TEXT NOT NULL,
    cell_id                  TEXT NOT NULL,
    pid                      BIGINT NOT NULL,
    pid_start_ticks          BIGINT NOT NULL,
    boot_id                  TEXT NOT NULL,
    pid_namespace_inode      BIGINT NOT NULL,
    cgroup_identity_digest   TEXT NOT NULL,
    cancelled_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason                   TEXT NOT NULL,
    engine_owner             TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (
        tenant_id, workspace_id, root_run_id, phase_id, assignment_id,
        cell_id, pid, pid_start_ticks, boot_id, pid_namespace_inode,
        cgroup_identity_digest
    )
);

CREATE TABLE IF NOT EXISTS capability_attestation_sets (
    tenant_id                     TEXT NOT NULL,
    workspace_id                  TEXT NOT NULL,
    root_run_id                   TEXT NOT NULL,
    phase_id                      TEXT NOT NULL,
    assignment_id                 TEXT NOT NULL,
    authority_evaluation_id       TEXT NOT NULL,
    authority_evaluation_digest   TEXT NOT NULL,
    authority_policy_generation   BIGINT NOT NULL,
    catalog_generation            BIGINT NOT NULL,
    catalog_digest                TEXT NOT NULL,
    set_digest                    TEXT NOT NULL,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                  TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
);

CREATE TABLE IF NOT EXISTS capability_attestation_entries (
    tenant_id           TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    root_run_id         TEXT NOT NULL,
    phase_id            TEXT NOT NULL,
    assignment_id       TEXT NOT NULL,
    verb_id             TEXT NOT NULL,
    definition_digest   TEXT NOT NULL,
    effect_class        TEXT NOT NULL,
    consequence         TEXT NOT NULL,
    engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (
        tenant_id, workspace_id, root_run_id, phase_id, assignment_id, verb_id
    ),
    FOREIGN KEY (
        tenant_id, workspace_id, root_run_id, phase_id, assignment_id
    ) REFERENCES capability_attestation_sets (
        tenant_id, workspace_id, root_run_id, phase_id, assignment_id
    ) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Codex-native Knowledge fabric (decision 0015)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_uploads (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT,
    title TEXT NOT NULL, filename TEXT NOT NULL, media_type TEXT NOT NULL,
    owner_scope TEXT NOT NULL, source_kind TEXT NOT NULL, source_ref TEXT,
    staged_key TEXT, digest TEXT, byte_size BIGINT,
    status TEXT NOT NULL CHECK (status IN ('begun','staged','committed')),
    asset_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS knowledge_blobs (
    tenant_id TEXT NOT NULL, digest TEXT NOT NULL, object_key TEXT NOT NULL,
    byte_size BIGINT NOT NULL, media_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,digest), UNIQUE (tenant_id,object_key)
);
CREATE TABLE IF NOT EXISTS knowledge_assets (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT,
    title TEXT NOT NULL, filename TEXT NOT NULL, asset_type TEXT NOT NULL,
    owner_scope TEXT NOT NULL, current_revision_id TEXT NOT NULL,
    source_kind TEXT NOT NULL, source_ref TEXT, deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS knowledge_source_occurrences (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, asset_id TEXT NOT NULL,
    source_kind TEXT NOT NULL, external_id TEXT NOT NULL, external_path TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,asset_id) REFERENCES knowledge_assets(tenant_id,id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS knowledge_source_occurrences_asset_idx
  ON knowledge_source_occurrences(tenant_id,asset_id,observed_at);
CREATE TABLE IF NOT EXISTS knowledge_revisions (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, asset_id TEXT NOT NULL,
    blob_digest TEXT NOT NULL, version INT NOT NULL, media_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,asset_id,version),
    FOREIGN KEY (tenant_id,asset_id) REFERENCES knowledge_assets(tenant_id,id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,blob_digest) REFERENCES knowledge_blobs(tenant_id,digest)
      ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS knowledge_representations (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, revision_id TEXT NOT NULL,
    kind TEXT NOT NULL, format TEXT NOT NULL, generator TEXT NOT NULL,
    generator_version TEXT NOT NULL, content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,revision_id) REFERENCES knowledge_revisions(tenant_id,id)
      ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS knowledge_segments (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, asset_id TEXT NOT NULL,
    revision_id TEXT NOT NULL, representation_id TEXT NOT NULL,
    sequence INT NOT NULL, text TEXT NOT NULL, locator JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    search_vector TSVECTOR GENERATED ALWAYS AS
      (to_tsvector('simple',coalesce(text,''))) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,representation_id,sequence),
    FOREIGN KEY (tenant_id,asset_id) REFERENCES knowledge_assets(tenant_id,id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,revision_id) REFERENCES knowledge_revisions(tenant_id,id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,representation_id)
      REFERENCES knowledge_representations(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS knowledge_segments_search_idx
  ON knowledge_segments USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS knowledge_segments_asset_idx
  ON knowledge_segments(tenant_id,asset_id,sequence);
CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL, model_provider TEXT NOT NULL, model_name TEXT NOT NULL,
    model_version TEXT NOT NULL, dimensions INT NOT NULL, distance_metric TEXT NOT NULL,
    vector vector(256) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,subject_id,model_provider,model_name,model_version),
    FOREIGN KEY (tenant_id,subject_id) REFERENCES knowledge_segments(tenant_id,id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS knowledge_embeddings_subject_idx
  ON knowledge_embeddings(tenant_id,subject_type,subject_id);
CREATE TABLE IF NOT EXISTS knowledge_asset_access (
    tenant_id TEXT NOT NULL, asset_id TEXT NOT NULL, scope TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,asset_id,scope),
    FOREIGN KEY (tenant_id,asset_id) REFERENCES knowledge_assets(tenant_id,id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS knowledge_asset_access_scope_idx
  ON knowledge_asset_access(tenant_id,scope,asset_id);
CREATE TABLE IF NOT EXISTS knowledge_providers (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, display_name TEXT NOT NULL,
    role TEXT NOT NULL, enabled BOOLEAN NOT NULL, bundled BOOLEAN NOT NULL,
    health TEXT NOT NULL, status TEXT NOT NULL, last_error TEXT, config JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS knowledge_projection_statuses (
    tenant_id TEXT NOT NULL, provider_id TEXT NOT NULL, subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL, operation TEXT NOT NULL, status TEXT NOT NULL,
    projection_ref TEXT, error TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,provider_id,subject_id,operation),
    FOREIGN KEY (tenant_id,provider_id) REFERENCES knowledge_providers(tenant_id,id)
      ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS knowledge_jobs (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
    subject_id TEXT NOT NULL, status TEXT NOT NULL, detail JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS knowledge_projection_outbox (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, provider_id TEXT NOT NULL,
    subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, operation TEXT NOT NULL,
    payload JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE INDEX IF NOT EXISTS knowledge_projection_outbox_pending_idx
  ON knowledge_projection_outbox(tenant_id,status,created_at);

-- Immutable Worker artifacts. Bytes are content-addressed and never named by a
-- native/server path; the only public surface is owner/workspace-scoped reads.
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
    workspace_id TEXT, conversation_id TEXT, run_id TEXT, work_item_id TEXT,
    name TEXT NOT NULL, digest TEXT NOT NULL, media_type TEXT NOT NULL,
    size BIGINT NOT NULL, revision INT NOT NULL,
    previous_revision_id TEXT, provenance JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), content BYTEA NOT NULL,
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,previous_revision_id),
    CONSTRAINT artifact_name_safe CHECK (
      octet_length(name) BETWEEN 1 AND 255
      AND name NOT IN ('.','..') AND name !~ '[\\/]'
      AND name !~ '[[:cntrl:]]'
    ),
    CONSTRAINT artifact_digest_sha256 CHECK (digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT artifact_media_type_valid CHECK (
      media_type ~ '^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$'
    ),
    CONSTRAINT artifact_size_bounded CHECK (
      size BETWEEN 0 AND 104857600 AND octet_length(content)=size
    ),
    CONSTRAINT artifact_revision_valid CHECK (
      revision BETWEEN 1 AND 1000000
      AND ((revision=1) = (previous_revision_id IS NULL))
    ),
    CONSTRAINT artifact_provenance_valid CHECK (
      jsonb_typeof(provenance)='object'
      AND provenance->>'kind' IN ('agent','tool','workflow','call','system')
    ),
    FOREIGN KEY (tenant_id,workspace_id)
      REFERENCES workspaces(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,conversation_id)
      REFERENCES conversations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,previous_revision_id)
      REFERENCES artifacts(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS artifacts_owner_created_idx
  ON artifacts(tenant_id,owner_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS artifacts_conversation_idx
  ON artifacts(tenant_id,owner_id,conversation_id,created_at DESC,id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS artifacts_revision_idx
  ON artifacts(
    tenant_id,owner_id,COALESCE(workspace_id,''),
    COALESCE(conversation_id,''),name,revision
  );

-- Generic native UVC camera bindings and semantic leases. These rows are
-- deliberately separate from device roots: no path, argv, command, or HID
-- fallback can enter a camera lease.
CREATE TABLE IF NOT EXISTS camera_bindings (
    tenant_id TEXT NOT NULL, device_id TEXT NOT NULL, camera_id TEXT NOT NULL,
    descriptor_fingerprint TEXT NOT NULL, owner_id TEXT NOT NULL,
    connection_state TEXT NOT NULL, ptz_get_state TEXT NOT NULL,
    ptz_set_state TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
    manufacturer TEXT, product TEXT, transport TEXT NOT NULL DEFAULT 'uvc_libusb',
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,device_id,camera_id),
    CONSTRAINT camera_binding_fingerprint_sha256 CHECK (descriptor_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT camera_binding_connection_valid CHECK (connection_state IN ('connected','disconnected','permission_required','unknown')),
    CONSTRAINT camera_binding_get_state_valid CHECK (ptz_get_state IN ('unknown','advertised','readable','writable','proven','unsupported','invalid_descriptor')),
    CONSTRAINT camera_binding_set_state_valid CHECK (ptz_set_state IN ('unknown','advertised','readable','writable','proven','unsupported','invalid_descriptor')),
    CONSTRAINT camera_binding_capabilities_object CHECK (jsonb_typeof(capabilities)='object'),
    CONSTRAINT camera_binding_evidence_array CHECK (jsonb_typeof(evidence)='array'),
    FOREIGN KEY (tenant_id,device_id) REFERENCES devices(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS camera_bindings_owner_idx
  ON camera_bindings(tenant_id,owner_id,device_id,camera_id);
CREATE TABLE IF NOT EXISTS camera_leases (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, device_id TEXT NOT NULL,
    camera_id TEXT NOT NULL, owner_id TEXT NOT NULL, verb TEXT NOT NULL,
    action JSONB NOT NULL, action_digest TEXT NOT NULL, approval_id TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
    signature TEXT NOT NULL, signing_key_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'issued', claim_token_hash TEXT,
    claim_expires_at TIMESTAMPTZ, claimed_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ, receipt JSONB,
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,approval_id),
    CONSTRAINT camera_lease_verb_valid CHECK (verb IN ('camera.ptz.get','camera.ptz.set')),
    CONSTRAINT camera_lease_status_valid CHECK (status IN ('issued','claimed','completed','failed','expired')),
    CONSTRAINT camera_lease_action_object CHECK (jsonb_typeof(action)='object'),
    CONSTRAINT camera_lease_digest_sha256 CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT camera_lease_claim_hash_sha256 CHECK (claim_token_hash IS NULL OR claim_token_hash ~ '^[0-9a-f]{64}$'),
    FOREIGN KEY (tenant_id,device_id,camera_id) REFERENCES camera_bindings(tenant_id,device_id,camera_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,approval_id) REFERENCES hitl_requests(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS camera_leases_pending_idx ON camera_leases(tenant_id,device_id,status,issued_at);
