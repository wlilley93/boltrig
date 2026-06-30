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

-- 2. Enable + FORCE RLS with one tenant-isolation policy per tenant-scoped table.
--    FORCE so even the table owner is bound (defence-in-depth, not only the app
--    role). USING gates reads/updates/deletes; WITH CHECK gates inserts/updates,
--    so a row can never be written into a tenant other than the active GUC.
--
--    personal_access_tokens is DELIBERATELY EXCLUDED: PAT authentication resolves
--    a token by its hash BEFORE the tenant is known (a legitimate cross-tenant
--    read), so it keeps its own SQL-level + constant-time-compare guard.
DO $$
DECLARE
  t text;
  scoped text[] := ARRAY[
    'nouns','verbs','verb_bindings','adapters','skills','agent_capabilities',
    'workflow_definitions','model_endpoints','work_items','hitl_requests',
    'hitl_responses','users','role_mappings','audit_log','idempotency_keys',
    'budgets','credential_refs','tenant_permissions','conversations',
    'config_revisions','eval_cases','eval_runs','notification_prefs',
    'personal_agents','memory_items','mcp_servers','conversation_messages',
    'user_invitations','user_settings','user_sessions','memory_facts',
    'memory_ingestions','memory_erasures','memory_vectors','memory_vector_edges'
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
