-- Boltrig RLS overlay (SEC-08 / K-22 / SEC-65): defence-in-depth tenant isolation
-- enforced AT THE DATABASE, plus a least-privilege application role.
--
-- OPT-IN. This is NOT part of the default schema.sql boot. The default deployment
-- connects as the table owner and relies on the SQL-level `WHERE tenant_id = $1`
-- filter every store method already applies. A deployment that wants the DB to be
-- the belt-and-suspenders fence adopts RLS by:
--   1. running this file (idempotent),
--   2. connecting the app as the non-bypassing `boltrig_app` role,
--   3. setting `app.tenant_id` per transaction - PostgresStore.with_tenant() does
--      exactly this (SET LOCAL via set_config(..., true)).
-- A null GUC makes the policy predicate NULL -> never true -> zero rows, so an
-- un-scoped connection is fail-closed, never wide-open.
--
-- Idempotent: safe to run repeatedly.

-- 1. Least-privilege role: NOSUPERUSER + NOBYPASSRLS (so RLS actually binds it),
--    no DDL rights, no login until ops sets a password (ALTER ROLE ... LOGIN
--    PASSWORD ...). DML only.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'boltrig_app') THEN
    CREATE ROLE boltrig_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO boltrig_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO boltrig_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO boltrig_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO boltrig_app;

-- 1b. The blanket grant above would otherwise let a compromised app role rewrite
--     or erase the append-only tamper-evident tables (the SEC-16 hash chains).
--     No code path ever UPDATEs or DELETEs them (a config rollback INSERTS a new
--     config_revisions row), so strip write-back rights and leave SELECT/INSERT.
DO $$
DECLARE
  t text;
  append_only text[] := ARRAY[
    'audit_log', 'security_log', 'config_revisions', 'execution_events'
  ];
BEGIN
  FOREACH t IN ARRAY append_only LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'public' AND table_name = t
    ) THEN
      EXECUTE format('REVOKE UPDATE, DELETE ON %I FROM boltrig_app', t);
    END IF;
  END LOOP;
END
$$;

-- 2. Enable + FORCE RLS with one tenant-isolation policy per tenant-scoped table.
--    FORCE so even the table owner is bound (defence-in-depth, not only the app
--    role). USING gates reads/updates/deletes; WITH CHECK gates inserts/updates,
--    so a row can never be written into a tenant other than the active GUC.
--
--    personal_access_tokens is DELIBERATELY EXCLUDED: PAT authentication resolves
--    a token by its hash BEFORE the tenant is known (a legitimate cross-tenant
--    read), so it keeps its own SQL-level + constant-time-compare guard. The
--    channels table is EXCLUDED for the same reason (decision 0003): the inbound
--    path resolves the tenant from the unguessable channel id before any tenant
--    is bound. channel_bindings + channel_pairings ARE scoped (below).
--
--    identity_orgs is EXCLUDED for the same reason ([2026] VJS-COUNTY 11, D1): it
--    is the pre-tenant email -> orgs index login resolves by the normalised email
--    (identity) BEFORE any tenant is bound, so it cannot sit inside a tenant fence.
--    It holds no secret + no business data (only membership pointers) and is never
--    the authority - every access decision re-checks the RLS-fenced org_members row
--    for the bound tenant, so excluding it opens no cross-tenant data path.
DO $$
DECLARE
  t text;
  scoped text[] := ARRAY[
    'nouns','verbs','verb_bindings','adapters','skills','agent_capabilities',
    'workflow_definitions','model_endpoints','work_items','hitl_requests',
    'hitl_responses','users','role_mappings','audit_log','idempotency_keys',
    -- [2026] VJS-COUNTY 9: the distinct security-signal chain + the audit rollup
    -- anchors. Both carry a real tenant_id, so the generic tenant_id policy fences
    -- them (a null GUC -> zero rows, fail-closed) exactly like audit_log.
    'security_log','audit_rollup_anchors',
    -- The audit outbox (SEC-16 durable deferral): tenant-scoped like audit_log
    -- itself; its rows are DELETED by the drain, so unlike the append-only
    -- chains it keeps the app role's full grant set.
    'audit_outbox',
    'budgets','budget_usage','credential_refs','tenant_permissions','conversations',
    'config_revisions','permanent_fleet_observations','birth_profile_receipts',
    'background_job_receipts',
    'eval_cases','eval_runs','notification_prefs',
    'personal_agents','memory_items','mcp_servers','mcp_probe_receipts',
    'conversation_messages','conversation_steer_queue',
    'conversation_summaries',
    'user_invitations','user_credentials','password_reset_tokens',
    'user_settings','user_sessions','memory_facts',
    -- TOTP two-factor ([2026] VJS-COUNTY 10): all three carry a tenant_id column, so
    -- the generic tenant_id policy binds them (the sealed secret lives in the already-
    -- scoped credential_refs table, not here).
    'user_totp','user_recovery_codes','two_factor_challenges',
    'memory_ingestions','memory_erasures','memory_projection_statuses',
    'memory_vectors','memory_vector_edges','memory_events',
    'channel_bindings','channel_pairings','channel_gateway_status',
    'channel_gateway_leases',
    'run_checkpoints','fanout_counters',
    'run_cancel_requests',
    -- Decision 0003 Phase 2: durable intake dedup markers + the socket-class
    -- outbound hand-off. Both carry a real tenant_id resolved from the VERIFIED
    -- channel before the write, so the generic tenant_id policy fences them.
    'channel_deliveries','channel_outbox',
    'workflow_triggers','workflow_trigger_deliveries',
    'workflow_schedules','workflow_schedule_occurrences',
    'realtime_calls','realtime_call_events',
    'device_enrollments','devices','device_roots','device_leases',
    'camera_bindings','camera_leases',
    'integration_catalogue','integration_connections',
    -- Org -> workspace tenancy ([2026] VJS-COUNTY 8). These three carry a real
    -- tenant_id column, so the generic tenant_id policy binds them. organisations
    -- is handled separately below (its isolation column is id, which IS tenant_id).
    'workspaces','org_members','workspace_members',
    -- D5: per-org/workspace/user AI keys - tenant_id-scoped like the rest (the raw
    -- key is not here; it lives in the RLS-fenced credential_refs table).
    'ai_configs','ai_key_secret_proposals',
    -- Workflow run records (design brief 22.1): tenant-scoped observability rows
    -- fed by execute_workflow. Same generic tenant_id policy binds them.
    'workflow_run_records',
    -- Execution ledger + grant leases + model-proxy grants + capability
    -- attestations + root decisions + runtime identities + codex bindings
    -- (migrations 0026-0032). Every one carries a real tenant_id, so the generic
    -- tenant_id policy fences it (a null GUC -> zero rows, fail-closed) exactly
    -- like the rows above. NOTE `channels` is NOT in this set even though it
    -- carries a tenant_id: it is resolved by its unguessable id BEFORE the tenant
    -- is bound (decision 0003, the inbound webhook path), so it stays a documented
    -- exclusion in the block above alongside personal_access_tokens/identity_orgs.
    'execution_root_runs','execution_phases','execution_work_items',
    'execution_assignments','execution_results','execution_verifications',
    'execution_commands','execution_events','execution_outbox',
    'runtime_identities','codex_thread_bindings','codex_turn_bindings',
    'codex_item_bindings','root_engine_decisions','grant_leases',
    'grant_authority_snapshots','grant_lease_cancelled_assignments',
    'grant_lease_cancelled_roots','model_proxy_grants',
    'model_proxy_grant_cancelled_roots','model_proxy_grant_cancelled_phases',
    'model_proxy_grant_cancelled_assignments','model_proxy_grant_cancelled_cells',
    'capability_attestation_sets','capability_attestation_entries',
    -- Decision 0015: originals live outside Postgres, but every catalogue,
    -- access, search, provider, job and projection row remains tenant-fenced.
    'knowledge_uploads','knowledge_blobs','knowledge_assets',
    'knowledge_source_occurrences','knowledge_revisions',
    'knowledge_representations','knowledge_segments','knowledge_embeddings',
    'knowledge_asset_access',
    'knowledge_providers','knowledge_projection_statuses','knowledge_jobs',
    'knowledge_projection_outbox',
    -- Immutable artifact bytes and metadata share one owner/workspace-scoped row;
    -- tenant RLS remains the database backstop under the application fence.
    'artifacts'
  ];
BEGIN
  FOREACH t IN ARRAY scoped LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'public' AND table_name = t
    ) THEN
      EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
      EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
      EXECUTE format(
        'CREATE POLICY tenant_isolation ON %I '
        'USING (tenant_id = current_setting(''app.tenant_id'', true)) '
        'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
        t
      );
    END IF;
  END LOOP;
END
$$;

-- 3. organisations ([2026] VJS-COUNTY 8, D1): the org row's id IS the tenant_id
--    (one org per tenant_id), so its isolation column is `id`, not `tenant_id`.
--    Same fail-closed FORCE-RLS shape as the generic loop, keyed on id. A null GUC
--    yields zero rows. Kept separate because the generic policy predicate names
--    tenant_id, a column organisations deliberately does not have.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'organisations'
  ) THEN
    ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE organisations FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON organisations;
    CREATE POLICY tenant_isolation ON organisations
      USING (id = current_setting('app.tenant_id', true))
      WITH CHECK (id = current_setting('app.tenant_id', true));
  END IF;
END
$$;
