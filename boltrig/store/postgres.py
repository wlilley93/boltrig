"""PostgreSQL-backed Store (asyncpg). Satisfies ``store.base.Store`` (P0-1).

Mirrors ``InMemoryStore`` method for method so the kernel cannot tell which store
it runs on; the only difference is durability. Every query is scoped by
``tenant_id`` (SEC-08). JSONB columns round-trip as Python dict/list via a codec.
Alembic is authoritative for production upgrades; ``schema.sql`` is an explicit
fresh-database/test bootstrap used only when ``apply_schema=True``.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
from pathlib import Path

import asyncpg

from .channels import ChannelStorePG
from .channel_dedup import ChannelDedupStorePG
from .channel_outbox import ChannelOutboxStorePG
from .budget_policy import BudgetPolicyPG
from .capabilities import CapabilityStorePG
from .guarded_writes import GuardedWritesPG
from .idempotency import IdempotencyStorePG
from .observability_reads import ObservabilityReadsPG
from .sealing import seal_ref, unseal_ref
from .work_items import WorkItemReadsPG, work_item_from_row
from .rows import (
    _adapter, _ai_config, _anchor, _audit, _binding, _budget, _checkpoint,
    _conversation, _endpoint, _eval_case, _eval_run, _hitl_req, _hitl_resp,
    _invitation, _mem_erasure, _mem_fact, _mem_ingestion, _mem_projection,
    _memory, _message, _notif, _noun, _org, _org_member, _pat, _personal,
    _revision, _security, _session, _setting, _skill, _summary, _tfa_challenge,
    _user, _user_totp, _verb, _workflow, _workflow_promotion, _workspace,
    _workspace_member,
)
from boltrig.models import (
    AdapterRecord,
    AuditEvent, AuditRollupAnchor,
    Budget,
    ConfigRevision, Conversation,
    ConversationMessage, ConversationStatus,
    ConversationSummary, EvalCase,
    EvalRun, MemoryItem,
    MemoryErasure,
    MemoryFact,
    MemoryIngestion,
    MemoryProjectionStatus,
    NotificationPref,
    PersonalAccessToken,
    PersonalAgent,
    TwoFactorChallenge,
    User,
    UserInvitation,
    UserSession,
    UserSetting,
    UserTotp,
    EMPTY_GRANTS,
    GrantSet,
    HITLRequest,
    HITLResponse,
    HITLStatus,
    ModelEndpoint,
    Noun,
    AI_CONFIG_LEVELS,
    AiConfig,
    Organisation,
    OrgMember,
    SecurityEvent,
    Skill,
    TenantPermissions,
    Verb,
    VerbBinding,
    WORKSPACE_ROLES,
    Workspace,
    WorkspaceMember,
    WorkflowDefinition,
    WorkflowPromotion,
    WorkItem,
)
from boltrig.models.errors import SchemaValidationError

_SCHEMA = Path(__file__).with_name("schema.sql")
_RLS = Path(__file__).with_name("rls.sql")

# RLS LIVE (opt-in): the active tenant for the current async context, set by the
# API per request (set_current_tenant). The _RlsPool reads it to scope every
# statement, so the opt-in RLS policies activate through the store's UNCHANGED
# method bodies - no per-method retrofit. Default off; the running app is
# unaffected until BOLTRIG_RLS is set and the app connects as boltrig_app.
_current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "boltrig_current_tenant", default=None
)


def set_current_tenant(tenant_id: str | None) -> None:
    """Bind the active tenant for RLS for this async context (the API calls this
    per request from the resolved Principal)."""
    _current_tenant.set(tenant_id)


async def _apply_guc(conn: asyncpg.Connection) -> None:
    """SET LOCAL app.tenant_id from the request context. An unset tenant becomes
    '' so the RLS predicate is never true (fail-closed, never wide-open)."""
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", _current_tenant.get() or "")


class _RlsPool:
    """An asyncpg-pool facade that runs every convenience call inside a transaction
    with app.tenant_id set from the request context. This is what makes RLS LIVE:
    the store's existing ``self._pool.fetch/fetchrow/execute`` calls become
    tenant-scoped at the DB without touching any method body. acquire()/close()
    pass through - the few explicit-transaction methods set the GUC themselves."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _scoped(self, op: str, query: str, *args):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn)
                return await getattr(conn, op)(query, *args)

    async def fetch(self, query, *args):
        return await self._scoped("fetch", query, *args)

    async def fetchrow(self, query, *args):
        return await self._scoped("fetchrow", query, *args)

    async def execute(self, query, *args):
        return await self._scoped("execute", query, *args)

    def acquire(self):
        return self._pool.acquire()

    async def close(self):
        await self._pool.close()


def normalize_dsn(dsn: str) -> str:
    """Accept a SQLAlchemy-style DSN ("postgresql+asyncpg://...") as well as a
    plain libpq one. asyncpg only understands "postgresql://" / "postgres://", so
    strip any "+driver" suffix from the scheme - the shipped .env.example uses the
    +asyncpg form, which would otherwise fail at connect time."""
    scheme, sep, rest = dsn.partition("://")
    if sep and "+" in scheme:
        return scheme.split("+", 1)[0] + "://" + rest
    return dsn


async def _init_conn(conn: asyncpg.Connection) -> None:
    # encode/decode JSONB as Python objects so dict/list params and columns just work
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


class PostgresStore(
    BudgetPolicyPG, WorkItemReadsPG, IdempotencyStorePG, GuardedWritesPG,
    ChannelStorePG, CapabilityStorePG, ObservabilityReadsPG,
    ChannelDedupStorePG, ChannelOutboxStorePG,
):
    """asyncpg-backed Store. Domain methods live in partial mixins
    (e.g. ``ChannelStorePG``) to keep this file under the structural floor;
    composed here so the public method surface is one class."""
    """A durable Store. Construct via ``await PostgresStore.connect(dsn)``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(
        cls, dsn: str, *, apply_schema: bool = True, rls: bool = False
    ) -> "PostgresStore":
        """Open the durable store.

        ``apply_schema`` is an explicit bootstrap/test convenience. Production
        application wiring always passes ``False`` and relies on Alembic, so a
        process restart can never mutate or silently advance the catalogue.
        """
        pool = await asyncpg.create_pool(
            normalize_dsn(dsn), init=_init_conn, min_size=1, max_size=10
        )
        store = cls(pool)
        if apply_schema:
            async with pool.acquire() as conn:
                await conn.execute(_SCHEMA.read_text(encoding="utf-8"))
        if rls:
            # activate RLS-live: every store call is now tenant-scoped at the DB
            # via the request contextvar. Connect as boltrig_app with apply_schema
            # False (an owner connection provisions the schema + rls.sql first).
            store._pool = _RlsPool(pool)
        return store

    async def close(self) -> None:
        await self._pool.close()

    async def readiness_snapshot(self) -> tuple[bool, tuple[str, ...]]:
        """Probe connectivity and return the exact applied Alembic heads.

        This deployment-level probe intentionally bypasses tenant RLS: both
        ``SELECT 1`` and ``alembic_version`` are global catalogue facts and carry
        no tenant data. The caller applies a short timeout and redacts exceptions.
        """
        async with self._pool.acquire() as conn:
            alive = await conn.fetchval("SELECT 1") == 1
            rows = await conn.fetch(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            )
        return alive, tuple(str(row["version_num"]) for row in rows)

    async def apply_rls(self) -> None:
        """Apply the opt-in RLS overlay (boltrig/store/rls.sql): the tenant-isolation
        policies + the least-privilege ``boltrig_app`` role. Idempotent. A deployment
        that wants DB-enforced isolation runs this, connects the app as ``boltrig_app``
        and uses :meth:`with_tenant` so ``app.tenant_id`` is set per transaction. NOT
        run by default - the owner-connected default path relies on the SQL-level
        ``WHERE tenant_id = $1`` filter every method already applies (SEC-08)."""
        async with self._pool.acquire() as conn:
            await conn.execute(_RLS.read_text(encoding="utf-8"))

    @contextlib.asynccontextmanager
    async def with_tenant(self, tenant_id: str):
        """Yield a connection bound to one tenant for RLS. Opens a transaction and
        sets ``app.tenant_id`` with ``SET LOCAL`` semantics (``set_config(.., true)``),
        so under the RLS policies every statement on the connection sees only that
        tenant's rows, and a write into any other tenant is rejected by WITH CHECK.
        A null GUC yields zero rows (fail-closed). This is the RLS-correct read/write
        path when connected as the non-bypassing ``boltrig_app`` role."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
                yield conn

    # --- registry ---------------------------------------------------------
    async def get_noun(self, tenant_id, noun_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM nouns WHERE tenant_id=$1 AND id=$2", tenant_id, noun_id
        )
        return _noun(row)

    async def get_verb(self, tenant_id, verb_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM verbs WHERE tenant_id=$1 AND id=$2", tenant_id, verb_id
        )
        return _verb(row)

    async def list_verbs(self, tenant_id, noun_id=None):
        if noun_id is None:
            rows = await self._pool.fetch("SELECT * FROM verbs WHERE tenant_id=$1", tenant_id)
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM verbs WHERE tenant_id=$1 AND noun_id=$2", tenant_id, noun_id
            )
        return [_verb(r) for r in rows]

    async def get_binding(self, tenant_id, verb_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM verb_bindings WHERE tenant_id=$1 AND verb_id=$2", tenant_id, verb_id
        )
        return _binding(row)

    async def upsert_noun(self, noun: Noun):
        await self._pool.execute(
            """INSERT INTO nouns (id, tenant_id, description, schema)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 description=EXCLUDED.description, schema=EXCLUDED.schema, updated_at=now()""",
            noun.id, noun.tenant_id, noun.description, noun.schema,
        )

    async def upsert_verb(self, verb: Verb):
        await self._pool.execute(
            """INSERT INTO verbs (id, tenant_id, noun_id, description, input_schema,
                                  output_schema, consequence, identity_mode, degraded_mode,
                                  idempotency_mode)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 noun_id=EXCLUDED.noun_id, description=EXCLUDED.description,
                 input_schema=EXCLUDED.input_schema, output_schema=EXCLUDED.output_schema,
                 consequence=EXCLUDED.consequence, identity_mode=EXCLUDED.identity_mode,
                 degraded_mode=EXCLUDED.degraded_mode,
                 idempotency_mode=EXCLUDED.idempotency_mode, updated_at=now()""",
            verb.id, verb.tenant_id, verb.noun_id, verb.description, verb.input_schema,
            verb.output_schema, verb.consequence.value, verb.identity_mode, verb.degraded_mode,
            verb.idempotency_mode.value,
        )

    async def upsert_binding(self, b: VerbBinding):
        rl = {"per": b.rate_limit.per, "max": b.rate_limit.max, "scope": b.rate_limit.scope} \
            if b.rate_limit else None
        await self._pool.execute(
            """INSERT INTO verb_bindings (verb_id, tenant_id, target_type, target_ref, rate_limit)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (verb_id, tenant_id) DO UPDATE SET
                 target_type=EXCLUDED.target_type, target_ref=EXCLUDED.target_ref,
                 rate_limit=EXCLUDED.rate_limit, updated_at=now()""",
            b.verb_id, b.tenant_id, b.target_type.value, b.target_ref, rl,
        )

    async def delete_noun(self, tenant_id, noun_id):
        await self._pool.execute(
            "DELETE FROM nouns WHERE tenant_id=$1 AND id=$2", tenant_id, noun_id
        )

    async def delete_verb(self, tenant_id, verb_id):
        await self._pool.execute(
            "DELETE FROM verbs WHERE tenant_id=$1 AND id=$2", tenant_id, verb_id
        )

    async def delete_binding(self, tenant_id, verb_id):
        await self._pool.execute(
            "DELETE FROM verb_bindings WHERE tenant_id=$1 AND verb_id=$2",
            tenant_id, verb_id,
        )

    # --- permissions ------------------------------------------------------
    async def get_tenant_permissions(self, tenant_id):
        row = await self._pool.fetchrow(
            "SELECT allow, deny FROM tenant_permissions WHERE tenant_id=$1", tenant_id
        )
        if row is None:
            return TenantPermissions(tenant_id, EMPTY_GRANTS)
        return TenantPermissions(
            tenant_id, GrantSet.of(list(row["allow"] or []), list(row["deny"] or []))
        )

    async def set_tenant_permissions(self, perms: TenantPermissions) -> None:
        await self._pool.execute(
            """INSERT INTO tenant_permissions (tenant_id, allow, deny)
               VALUES ($1,$2,$3)
               ON CONFLICT (tenant_id) DO UPDATE SET
                 allow=EXCLUDED.allow, deny=EXCLUDED.deny, updated_at=now()""",
            perms.tenant_id, list(perms.grants.allow), list(perms.grants.deny),
        )

    # --- libraries --------------------------------------------------------
    async def upsert_adapter(self, a: AdapterRecord):
        await self._pool.execute(
            """INSERT INTO adapters (id, tenant_id, version, runtime, source, module_ref,
                                     health, spec_ref, created_by, activated)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 version=EXCLUDED.version, runtime=EXCLUDED.runtime, source=EXCLUDED.source,
                 module_ref=EXCLUDED.module_ref, health=EXCLUDED.health,
                 spec_ref=EXCLUDED.spec_ref, created_by=EXCLUDED.created_by,
                 activated=EXCLUDED.activated, updated_at=now()""",
            a.id, a.tenant_id, a.version, a.runtime, a.source, a.module_ref,
            a.health.value, a.spec_ref, a.created_by, a.activated,
        )

    async def get_adapter(self, tenant_id, adapter_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM adapters WHERE tenant_id=$1 AND id=$2", tenant_id, adapter_id
        )
        return _adapter(row)

    async def list_adapters(self, tenant_id):
        rows = await self._pool.fetch("SELECT * FROM adapters WHERE tenant_id=$1", tenant_id)
        return [_adapter(r) for r in rows]

    async def delete_adapter(self, tenant_id, adapter_id):
        await self._pool.execute(
            "DELETE FROM adapters WHERE tenant_id=$1 AND id=$2", tenant_id, adapter_id
        )

    async def upsert_skill(self, s: Skill):
        await self._pool.execute(
            """INSERT INTO skills (id, tenant_id, version, prompt_fragment, tool_grants,
                                   context_requirements, extends, locale, description)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (tenant_id, id, version) DO UPDATE SET
                 prompt_fragment=EXCLUDED.prompt_fragment, tool_grants=EXCLUDED.tool_grants,
                 context_requirements=EXCLUDED.context_requirements, extends=EXCLUDED.extends,
                 locale=EXCLUDED.locale, description=EXCLUDED.description, updated_at=now()""",
            s.id, s.tenant_id, s.version, s.prompt_fragment, s.tool_grants,
            s.context_requirements, s.extends, s.locale, s.description,
        )

    async def get_skill(self, tenant_id, skill_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM skills WHERE tenant_id=$1 AND id=$2 ORDER BY version DESC LIMIT 1",
            tenant_id, skill_id,
        )
        return _skill(row)

    async def list_skills(self, tenant_id):
        # Latest version per skill id for the tenant (the shelf).
        rows = await self._pool.fetch(
            """SELECT DISTINCT ON (id) * FROM skills WHERE tenant_id=$1
               ORDER BY id, version DESC""",
            tenant_id,
        )
        return [_skill(r) for r in rows]

    async def upsert_workflow(self, w: WorkflowDefinition):
        await self._pool.execute(
            """INSERT INTO workflow_definitions (id, tenant_id, version, source, definition,
                                                 intent_tags, origin_task, workspace_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, id, version) DO UPDATE SET
                 source=EXCLUDED.source, definition=EXCLUDED.definition,
                 intent_tags=EXCLUDED.intent_tags, origin_task=EXCLUDED.origin_task,
                 workspace_id=EXCLUDED.workspace_id, updated_at=now()""",
            w.id, w.tenant_id, w.version, w.source.value, w.definition, w.intent_tags,
            w.origin_task, w.workspace_id,
        )

    async def list_workflows(self, tenant_id):
        # Latest version per workflow id (the shelf), mirroring list_skills and
        # the in-memory store, so callers matching a workflow by id never see
        # duplicate or stale versions.
        rows = await self._pool.fetch(
            """SELECT DISTINCT ON (id) * FROM workflow_definitions WHERE tenant_id=$1
               ORDER BY id, version DESC""",
            tenant_id,
        )
        return [_workflow(r) for r in rows]

    async def upsert_workflow_promotion(self, p: WorkflowPromotion):
        await self._pool.execute(
            """INSERT INTO workflow_promotions (workflow_id, tenant_id, state, score,
                                                eval_run_id, updated_at)
               VALUES ($1,$2,$3,$4,$5,now())
               ON CONFLICT (tenant_id, workflow_id) DO UPDATE SET
                 state=EXCLUDED.state, score=EXCLUDED.score,
                 eval_run_id=EXCLUDED.eval_run_id, updated_at=now()""",
            p.workflow_id, p.tenant_id, p.state.value, p.score, p.eval_run_id,
        )

    async def get_workflow_promotion(self, tenant_id, workflow_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM workflow_promotions WHERE tenant_id=$1 AND workflow_id=$2",
            tenant_id, workflow_id,
        )
        return _workflow_promotion(row)

    async def list_workflow_promotions(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM workflow_promotions WHERE tenant_id=$1", tenant_id
        )
        return [_workflow_promotion(r) for r in rows]

    # --- workflow run records (design brief 22.1, observability-only) -------
    async def record_workflow_run(self, tenant_id, workflow_id, run_id, status):
        # Insert/replace on the (tenant_id, run_id) PK. ON CONFLICT DO NOTHING
        # preserves the original started_at for a re-recorded run_id (idempotent
        # re-recording of the same run never bumps its start time forward).
        await self._pool.execute(
            """INSERT INTO workflow_run_records (tenant_id, workflow_id, run_id, status)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (tenant_id, run_id) DO NOTHING""",
            tenant_id, workflow_id, run_id, status,
        )

    async def list_workflow_run_ids(self, tenant_id, workflow_id, limit=100):
        rows = await self._pool.fetch(
            """SELECT run_id FROM workflow_run_records
               WHERE tenant_id=$1 AND workflow_id=$2
               ORDER BY started_at DESC LIMIT $3""",
            tenant_id,
            workflow_id,
            max(0, min(limit, 1000)),
        )
        return [row["run_id"] for row in rows]

    async def workflow_run_stats(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT workflow_id,
                      COUNT(*) AS run_count,
                      COUNT(*) FILTER (WHERE status='completed') AS success_count,
                      MAX(started_at) AS last_run_at
               FROM workflow_run_records
               WHERE tenant_id=$1
               GROUP BY workflow_id
               ORDER BY workflow_id""",
            tenant_id,
        )
        return [
            {"workflow_id": r["workflow_id"], "run_count": int(r["run_count"]),
             "success_count": int(r["success_count"]),
             "last_run_at": r["last_run_at"]}
            for r in rows
        ]

    async def upsert_model_endpoint(self, e: ModelEndpoint):
        await self._pool.execute(
            """INSERT INTO model_endpoints (id, tenant_id, kind, base_url, model, fallback, data_class)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 kind=EXCLUDED.kind, base_url=EXCLUDED.base_url, model=EXCLUDED.model,
                 fallback=EXCLUDED.fallback, data_class=EXCLUDED.data_class, updated_at=now()""",
            e.id, e.tenant_id, e.kind, e.base_url, e.model, e.fallback, e.data_class,
        )

    async def get_model_endpoint(self, tenant_id, ep_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM model_endpoints WHERE tenant_id=$1 AND id=$2", tenant_id, ep_id
        )
        return _endpoint(row)

    async def list_model_endpoints(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM model_endpoints WHERE tenant_id=$1 ORDER BY id", tenant_id
        )
        return [_endpoint(r) for r in rows]

    # --- work items -------------------------------------------------------
    async def create_work_item(self, w: WorkItem):
        await self._pool.execute(
            """INSERT INTO work_items (id, tenant_id, workspace_id, source, source_id, intent, confidence,
                                       convergent, status, owner_member, parent_id, hatchet_run_id,
                                       depth, on_behalf_of, constraints, raw, attempts, degraded,
                                       result, lease_owner, lease_expires_at, target, reply_route)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 workspace_id=EXCLUDED.workspace_id, source=EXCLUDED.source, source_id=EXCLUDED.source_id, intent=EXCLUDED.intent,
                 confidence=EXCLUDED.confidence, convergent=EXCLUDED.convergent,
                 status=EXCLUDED.status, owner_member=EXCLUDED.owner_member,
                 parent_id=EXCLUDED.parent_id, hatchet_run_id=EXCLUDED.hatchet_run_id,
                 depth=EXCLUDED.depth, on_behalf_of=EXCLUDED.on_behalf_of,
                 constraints=EXCLUDED.constraints, raw=EXCLUDED.raw,
                 attempts=EXCLUDED.attempts, degraded=EXCLUDED.degraded,
                 result=EXCLUDED.result, lease_owner=EXCLUDED.lease_owner,
                 lease_expires_at=EXCLUDED.lease_expires_at,
                 target=EXCLUDED.target, reply_route=EXCLUDED.reply_route, updated_at=now()""",
            w.id, w.tenant_id, w.workspace_id, w.source, w.source_id, w.intent, w.confidence, w.convergent,
            w.status.value, w.owner_member, w.parent_id, w.hatchet_run_id, w.depth,
            w.on_behalf_of, w.constraints, w.raw, w.attempts, w.degraded, w.result,
            w.lease_owner, w.lease_expires_at, w.target, w.reply_route,
        )

    async def update_work_item(self, item: WorkItem):
        await self.create_work_item(item)  # upsert

    async def transition_work_item_status(self, tenant_id, item_id, *, expected, new_status):
        # Conditional status write (CAS on the guarded status): a concurrent
        # transition that already moved the row matches 0 rows, so the loser
        # fails instead of silently overwriting the winner.
        row = await self._pool.fetchrow(
            """UPDATE work_items SET status=$4, updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND status=$3 RETURNING id""",
            tenant_id, item_id, expected.value, new_status.value,
        )
        return row is not None

    async def claim_work_item(self, tenant_id, worker_id, lease_seconds):
        # atomic pending -> in_flight claim with a lease (US-FLT-05): one
        # statement, FOR UPDATE SKIP LOCKED so concurrent claimers never block
        # or double-claim; an expired lease is reclaimable. RETURNING tells us
        # if we won (mirrors consume_hitl).
        row = await self._pool.fetchrow(
            """UPDATE work_items
               SET status='in_flight', lease_owner=$2,
                   lease_expires_at=now() + make_interval(secs => $3),
                   attempts=attempts+1, updated_at=now()
               WHERE tenant_id=$1 AND id IN (
                 SELECT id FROM work_items
                 WHERE tenant_id=$1 AND (status='pending'
                        OR (status='in_flight' AND lease_expires_at < now()))
                 ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
               )
               RETURNING *""",
            tenant_id, worker_id, float(lease_seconds),
        )
        return work_item_from_row(row)

    async def try_increment_fanout(self, tenant_id, tree_id, counter, n, cap):
        # atomic capped increment (US-EXE-07): the conditional upsert applies
        # the whole increment or none; no row returned means refused. The INSERT
        # arm has no WHERE, so an over-cap first increment is refused up front.
        if n > cap:
            return False
        row = await self._pool.fetchrow(
            """INSERT INTO fanout_counters (tenant_id, tree_id, counter, value)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (tenant_id, tree_id, counter) DO UPDATE
                 SET value = fanout_counters.value + EXCLUDED.value
                 WHERE fanout_counters.value + EXCLUDED.value <= $5
               RETURNING value""",
            tenant_id, tree_id, counter, n, cap,
        )
        return row is not None

    # --- run checkpoints (Beat 3 resume seam) ------------------------------
    async def upsert_checkpoint(
        self, tenant_id, run_id, step, status, output=None, hitl_request_id=None
    ):
        await self._pool.execute(
            """INSERT INTO run_checkpoints (tenant_id, run_id, step, status, output,
                                            hitl_request_id, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,now())
               ON CONFLICT (tenant_id, run_id, step) DO UPDATE SET
                 status=EXCLUDED.status, output=EXCLUDED.output,
                 hitl_request_id=EXCLUDED.hitl_request_id, updated_at=now()""",
            tenant_id, run_id, step, status, output, hitl_request_id,
        )

    async def list_checkpoints(self, tenant_id, run_id):
        rows = await self._pool.fetch(
            """SELECT * FROM run_checkpoints WHERE tenant_id=$1 AND run_id=$2
               ORDER BY updated_at, step""",
            tenant_id, run_id,
        )
        return [_checkpoint(r) for r in rows]

    # --- server-side run cancellation ([2026] VJS-COUNTY 6) ----------------
    async def request_run_cancel(self, tenant_id, run_id, requested_by):
        # Idempotent marker (D2): INSERT .. ON CONFLICT DO NOTHING, so a
        # re-request never overwrites the original requester. Durable across
        # restarts - the row is the backstop that stops a cancelled run being
        # resurrected (the pump re-detects it and re-writes CANCELLED).
        await self._pool.execute(
            """INSERT INTO run_cancel_requests (tenant_id, run_id, requested_by)
               VALUES ($1,$2,$3)
               ON CONFLICT (tenant_id, run_id) DO NOTHING""",
            tenant_id, run_id, requested_by,
        )

    async def is_run_cancel_requested(self, tenant_id, run_id):
        row = await self._pool.fetchrow(
            "SELECT 1 FROM run_cancel_requests WHERE tenant_id=$1 AND run_id=$2",
            tenant_id, run_id,
        )
        return row is not None

    # --- hitl -------------------------------------------------------------
    async def create_hitl_request(self, r: HITLRequest):
        await self._pool.execute(
            """INSERT INTO hitl_requests (id, tenant_id, run_id, work_item_id, type, urgency,
                                          context, question, options, assignee, status, timeout_at,
                                          verb, requested_by, requested_on_behalf_of, request_fingerprint, workspace_id, department_scope,
                                          secure, secure_purpose)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 status=EXCLUDED.status, updated_at=now()""",
            r.id, r.tenant_id, r.run_id, r.work_item_id, r.type.value, r.urgency.value,
            r.context, r.question, r.options, r.assignee, r.status.value, r.timeout_at,
            r.verb, r.requested_by, r.requested_on_behalf_of, r.request_fingerprint, r.workspace_id, r.department_scope,
            r.secure, r.secure_purpose,
        )

    async def consume_hitl(self, tenant_id, request_id):
        # atomic ANSWERED -> CONSUMED; RETURNING tells us if we won the CAS.
        row = await self._pool.fetchrow(
            """UPDATE hitl_requests SET status='consumed', updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND status='answered' RETURNING id""",
            tenant_id, request_id,
        )
        return row is not None

    async def expire_hitl(self, tenant_id, request_id):
        # atomic PENDING -> TIMED_OUT (SEC-14); RETURNING tells us if we won the
        # CAS, so a concurrently answered request is never clobbered.
        row = await self._pool.fetchrow(
            """UPDATE hitl_requests SET status='timed_out', updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND status='pending' RETURNING id""",
            tenant_id, request_id,
        )
        return row is not None

    async def get_hitl_request(self, tenant_id, req_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM hitl_requests WHERE tenant_id=$1 AND id=$2", tenant_id, req_id
        )
        return _hitl_req(row)

    async def list_pending_hitl(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM hitl_requests WHERE tenant_id=$1 AND status=$2",
            tenant_id, HITLStatus.PENDING.value,
        )
        return [_hitl_req(r) for r in rows]

    async def answer_hitl(self, resp: HITLResponse):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn)  # RLS-live: scope this explicit transaction
                row = await conn.fetchrow(
                    """UPDATE hitl_requests SET status=$3, updated_at=now()
                       WHERE tenant_id=$1 AND id=$2 AND status=$4 RETURNING *""",
                    resp.tenant_id, resp.request_id, HITLStatus.ANSWERED.value,
                    HITLStatus.PENDING.value,
                )
                if row is None:
                    return None
                await conn.execute(
                    """INSERT INTO hitl_responses (id, request_id, tenant_id, decision, notes,
                                                   respondent, responded_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7)
                       ON CONFLICT (tenant_id, id) DO NOTHING""",
                    resp.id, resp.request_id, resp.tenant_id, resp.decision, resp.notes,
                    resp.respondent, resp.responded_at,
                )
        return _hitl_req(row)

    async def get_hitl_response(self, tenant_id, request_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM hitl_responses WHERE tenant_id=$1 AND request_id=$2
               ORDER BY responded_at DESC LIMIT 1""",
            tenant_id, request_id,
        )
        return _hitl_resp(row)

    # --- audit ------------------------------------------------------------
    async def audit_head(self, tenant_id):
        row = await self._pool.fetchrow(
            "SELECT seq, hash FROM audit_log WHERE tenant_id=$1 ORDER BY seq DESC LIMIT 1",
            tenant_id,
        )
        if row is None:
            return (0, None)
        return (row["seq"], row["hash"])

    async def audit_append(self, e: AuditEvent):
        await self._pool.execute(
            """INSERT INTO audit_log (tenant_id, seq, ts, run_id, parent_run_id, actor, actor_tier,
                                      depth, action_type, noun, verb, target_adapter, on_behalf_of,
                                      status, latency_ms, tokens_used, cost_micros, skills_loaded,
                                      detail, ip_address, user_agent, resource, resource_id,
                                      workspace_id, prev_hash, hash)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,
                       $22,$23,$24,$25,$26)""",
            e.tenant_id, e.seq, e.ts, e.run_id, e.parent_run_id, e.actor, e.actor_tier, e.depth,
            e.action_type.value, e.noun, e.verb, e.target_adapter, e.on_behalf_of, e.status,
            e.latency_ms, e.tokens_used, e.cost_micros, e.skills_loaded, e.detail,
            e.ip_address, e.user_agent, e.resource, e.resource_id, e.workspace_id,
            e.prev_hash, e.hash,
        )

    async def audit_query(self, tenant_id, run_id=None, limit=200):
        if run_id is None:
            rows = await self._pool.fetch(
                "SELECT * FROM audit_log WHERE tenant_id=$1 ORDER BY seq DESC LIMIT $2",
                tenant_id, limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM audit_log WHERE tenant_id=$1 AND (run_id=$2 OR parent_run_id=$2)
                   ORDER BY seq DESC LIMIT $3""",
                tenant_id, run_id, limit,
            )
        return [_audit(r) for r in reversed(rows)]  # ascending, like InMemoryStore

    async def audit_scan(self, tenant_id, after_seq, limit):
        q = "SELECT * FROM audit_log WHERE tenant_id=$1 AND seq>$2 ORDER BY seq LIMIT $3"
        return [_audit(r) for r in await self._pool.fetch(q, tenant_id, after_seq, limit)]

    # --- security event stream ([2026] VJS-COUNTY 9, D3) ------------------
    async def security_head(self, tenant_id):
        row = await self._pool.fetchrow(
            "SELECT seq, hash FROM security_log WHERE tenant_id=$1 ORDER BY seq DESC LIMIT 1",
            tenant_id,
        )
        if row is None:
            return (0, None)
        return (row["seq"], row["hash"])

    async def security_append(self, e: SecurityEvent):
        await self._pool.execute(
            """INSERT INTO security_log (tenant_id, seq, ts, event_type, reason, actor, actor_tier,
                                         workspace_id, ip_address, user_agent, resource, resource_id,
                                         on_behalf_of, detail, prev_hash, hash)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
            e.tenant_id, e.seq, e.ts, e.event_type.value, e.reason, e.actor, e.actor_tier,
            e.workspace_id, e.ip_address, e.user_agent, e.resource, e.resource_id,
            e.on_behalf_of, e.detail, e.prev_hash, e.hash,
        )

    async def security_query(self, tenant_id, event_type=None, limit=200):
        if event_type is None:
            rows = await self._pool.fetch(
                "SELECT * FROM security_log WHERE tenant_id=$1 ORDER BY seq DESC LIMIT $2",
                tenant_id, limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM security_log WHERE tenant_id=$1 AND event_type=$2
                   ORDER BY seq DESC LIMIT $3""",
                tenant_id, event_type, limit,
            )
        return [_security(r) for r in reversed(rows)]  # ascending, like InMemoryStore

    async def security_scan(self, tenant_id, after_seq, limit):
        q = "SELECT * FROM security_log WHERE tenant_id=$1 AND seq>$2 ORDER BY seq LIMIT $3"
        return [_security(r) for r in await self._pool.fetch(q, tenant_id, after_seq, limit)]

    # --- audit rollup anchors ([2026] VJS-COUNTY 9, D4) -------------------
    async def add_audit_anchor(self, a: AuditRollupAnchor):
        await self._pool.execute(
            """INSERT INTO audit_rollup_anchors (id, tenant_id, workspace_id, seq_start, seq_end,
                                                 rollup_root_hash, anchored_at, is_dev_fallback,
                                                 rfc3161_token, kms_signature)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
            a.id, a.tenant_id, a.workspace_id, a.seq_start, a.seq_end, a.rollup_root_hash,
            a.anchored_at, a.is_dev_fallback, a.rfc3161_token, a.kms_signature,
        )

    async def latest_audit_anchor(self, tenant_id, workspace_id=None):
        # workspace_id NULL selects the ORG-WIDE anchor stream (IS NULL), not "any".
        row = await self._pool.fetchrow(
            """SELECT * FROM audit_rollup_anchors
               WHERE tenant_id=$1 AND workspace_id IS NOT DISTINCT FROM $2
               ORDER BY seq_end DESC LIMIT 1""",
            tenant_id, workspace_id,
        )
        return _anchor(row)

    async def list_audit_anchors(self, tenant_id, workspace_id=None, limit=200):
        if workspace_id is None:
            rows = await self._pool.fetch(
                """SELECT * FROM audit_rollup_anchors WHERE tenant_id=$1
                   ORDER BY seq_end DESC LIMIT $2""",
                tenant_id, limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM audit_rollup_anchors
                   WHERE tenant_id=$1 AND workspace_id=$2 ORDER BY seq_end DESC LIMIT $3""",
                tenant_id, workspace_id, limit,
            )
        return [_anchor(r) for r in reversed(rows)]  # ascending, like InMemoryStore

    # --- budgets ----------------------------------------------------------
    async def get_budget(self, tenant_id, scope_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM budgets WHERE tenant_id=$1 AND id=$2", tenant_id, scope_id
        )
        return _budget(row)

    async def list_budgets(self, tenant_id):
        rows = await self._pool.fetch("SELECT * FROM budgets WHERE tenant_id=$1", tenant_id)
        return [_budget(r) for r in rows]

    async def set_budget(self, b: Budget) -> None:
        """Compatibility alias; new callers use upsert_budget_policy."""
        await self.upsert_budget_policy(b)

    async def consume_budget(self, tenant_id, scope_id, tokens, micros):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn)  # RLS-live: scope this explicit transaction
                row = await conn.fetchrow(
                    """SELECT token_limit, cost_limit_micros, hard_stop, spent_tokens, spent_micros
                       FROM budgets WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
                    tenant_id, scope_id,
                )
                if row is None:
                    return True  # unmetered
                new_tokens = row["spent_tokens"] + max(0, tokens)
                new_micros = row["spent_micros"] + max(0, micros)
                over = (row["token_limit"] is not None and new_tokens > row["token_limit"]) or (
                    row["cost_limit_micros"] is not None and new_micros > row["cost_limit_micros"]
                )
                if over and row["hard_stop"]:
                    return False
                await conn.execute(
                    """UPDATE budgets SET spent_tokens=$3, spent_micros=$4, updated_at=now()
                       WHERE tenant_id=$1 AND id=$2""",
                    tenant_id, scope_id, new_tokens, new_micros,
                )
                return True

    async def reconcile_budget(self, tenant_id, scope_id, delta_tokens, delta_micros):
        """Post-run cost true-up (FR-COST-03, audit M14): apply a SIGNED delta to
        the scope's accumulators atomically (FOR UPDATE), each floored at 0. No
        hard-stop gate - this corrects the ledger for a call that already ran. No
        budget row -> no-op (unmetered), mirroring consume_budget."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn)  # RLS-live: scope this explicit transaction
                row = await conn.fetchrow(
                    """SELECT spent_tokens, spent_micros
                       FROM budgets WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
                    tenant_id, scope_id,
                )
                if row is None:
                    return  # unmetered
                new_tokens = max(0, row["spent_tokens"] + delta_tokens)
                new_micros = max(0, row["spent_micros"] + delta_micros)
                await conn.execute(
                    """UPDATE budgets SET spent_tokens=$3, spent_micros=$4, updated_at=now()
                       WHERE tenant_id=$1 AND id=$2""",
                    tenant_id, scope_id, new_tokens, new_micros,
                )

    async def reserve_budgets_atomic(self, tenant_id, reservations):
        """Transactional multi-scope reserve (audit H4, Phase 6, FR-COST-05):
        all-or-nothing debit across every scope in ONE transaction. Every scope's
        budget row is locked FOR UPDATE in a DETERMINISTIC order (sorted by
        scope_id), so two concurrent reserves on overlapping scopes always take the
        locks in the same order and cannot deadlock; each hard stop is re-checked
        under its lock. The moment a hard-stop scope has no headroom we return False
        BEFORE issuing any UPDATE, so the (write-empty) transaction commits nothing -
        no partial debit. Only when every scope has headroom do we apply all debits
        and return True. A scope with no budget row is a no-op (unmetered), mirroring
        consume_budget."""
        # Aggregate per scope (a scope named twice is locked + debited once, its
        # amounts summed). Negative amounts floor to 0 (a refund is reconcile's job).
        agg: dict[str, tuple[int, int]] = {}
        for scope_id, tokens, micros in reservations:
            t, m = agg.get(scope_id, (0, 0))
            agg[scope_id] = (t + max(0, tokens), m + max(0, micros))
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn)  # RLS-live: scope this explicit transaction
                planned: list[tuple[str, int, int]] = []
                # Lock in a stable order to avoid deadlock between concurrent reserves.
                for scope_id in sorted(agg):
                    tokens, micros = agg[scope_id]
                    row = await conn.fetchrow(
                        """SELECT token_limit, cost_limit_micros, hard_stop,
                                  spent_tokens, spent_micros
                           FROM budgets WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
                        tenant_id, scope_id,
                    )
                    if row is None:
                        continue  # unmetered scope -> skip (no-op)
                    new_tokens = row["spent_tokens"] + tokens
                    new_micros = row["spent_micros"] + micros
                    over = (
                        row["token_limit"] is not None and new_tokens > row["token_limit"]
                    ) or (
                        row["cost_limit_micros"] is not None
                        and new_micros > row["cost_limit_micros"]
                    )
                    if over and row["hard_stop"]:
                        # No UPDATE has run yet, so the transaction that now commits
                        # writes nothing - all-or-nothing holds with no partial debit.
                        return False
                    planned.append((scope_id, new_tokens, new_micros))
                for scope_id, new_tokens, new_micros in planned:
                    await conn.execute(
                        """UPDATE budgets SET spent_tokens=$3, spent_micros=$4,
                               updated_at=now()
                           WHERE tenant_id=$1 AND id=$2""",
                        tenant_id, scope_id, new_tokens, new_micros,
                    )
                return True

    # --- credential references (sealed at rest, SEC-04 - see store/sealing.py) ---
    async def get_credential_ref(self, tenant_id, cred_id):
        row = await self._pool.fetchrow(
            "SELECT data, store, ref FROM credential_refs WHERE tenant_id=$1 AND id=$2",
            tenant_id, cred_id,
        )
        if row is None:
            return None
        # A falsy-but-present data dict (e.g. a ref cleared to {}) round-trips as
        # written; only a NULL data column falls back to the store/ref pair.
        if row["data"] is not None:
            # Unseal transparently; legacy plaintext rows (no marker) pass through.
            return unseal_ref(row["data"])
        return {"store": row["store"], "ref": row["ref"]}

    async def set_credential_ref(self, tenant_id, cred_id, ref: dict) -> None:
        # Seal before persisting: credential_refs.data is ALWAYS an envelope
        # (ciphertext), never plaintext (SEC-04). The typed store/ref columns keep
        # the reference metadata (an env var name is not secret material).
        await self._pool.execute(
            """INSERT INTO credential_refs (id, tenant_id, store, ref, data, expires_at)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 store=EXCLUDED.store, ref=EXCLUDED.ref, data=EXCLUDED.data,
                 expires_at=EXCLUDED.expires_at, updated_at=now()""",
            cred_id, tenant_id, ref.get("store", "env"), ref.get("ref", ""), seal_ref(ref),
            ref.get("expires_at"),
        )

    async def delete_credential_ref(self, tenant_id: str, cred_id: str) -> None:
        await self._pool.execute(
            "DELETE FROM credential_refs WHERE tenant_id=$1 AND id=$2", tenant_id, cred_id
        )

    async def delete_credential_refs_for_run(self, tenant_id: str, run_id: str) -> int:
        # strpos prefix match (no LIKE wildcards to escape): only the run-scoped
        # secure-input ids minted as ``run:<run_id>:<purpose>`` (SEC-181).
        result = await self._pool.execute(
            "DELETE FROM credential_refs WHERE tenant_id=$1 AND strpos(id, $2) = 1",
            tenant_id, f"run:{run_id}:",
        )
        return int(result.rsplit(" ", 1)[-1])

    # --- conversations ---
    async def create_conversation(self, c: Conversation):
        await self._pool.execute(
            """INSERT INTO conversations (id, tenant_id, user_id, title, status, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            c.id, c.tenant_id, c.user_id, c.title, c.status.value, c.created_at, c.updated_at,
        )

    async def get_conversation(self, tenant_id, conv_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM conversations WHERE tenant_id=$1 AND id=$2", tenant_id, conv_id
        )
        return _conversation(row)

    async def list_conversations(self, tenant_id, user_id):
        rows = await self._pool.fetch(
            """SELECT * FROM conversations WHERE tenant_id=$1 AND user_id=$2
               ORDER BY updated_at DESC, id ASC""",
            tenant_id, user_id,
        )
        return [_conversation(r) for r in rows]

    async def list_conversations_page(self, tenant_id, user_id, *, limit, offset=0):
        # Owner scope (SEC-25) + stable ordering (updated_at DESC, id ASC tiebreak),
        # bounded by the resolved page size. Fetch limit+1 to learn whether a next
        # page exists without a second COUNT query; parameterised throughout.
        off = max(0, offset)
        rows = await self._pool.fetch(
            """SELECT * FROM conversations WHERE tenant_id=$1 AND user_id=$2
               ORDER BY updated_at DESC, id ASC
               LIMIT $3 OFFSET $4""",
            tenant_id, user_id, limit + 1, off,
        )
        has_more = len(rows) > limit
        items = [_conversation(r) for r in rows[:limit]]
        return items, (off + limit if has_more else None)

    async def search_conversations(self, tenant_id, user_id, query, *, limit, offset=0):
        # Owner-scoped substring search (US-CONV-10): the WHERE pins the caller's own
        # (tenant, user) rows, so another user's thread can never surface. A
        # conversation matches on its title OR a LIVE (superseded_by IS NULL,
        # [2026] VJS-COUNTY 4) message's content, so a superseded turn is never a live
        # hit. ``query`` is a BOUND parameter with LIKE metacharacters escaped (see
        # ``_like_escape`` + ESCAPE), so there is no SQL-injection or wildcard surface.
        # The snippet is the matched live message content, or NULL when only the title
        # matched (mirrors the in-memory store). Fetch limit+1 for the next offset.
        off = max(0, offset)
        pattern = f"%{_like_escape(query or '')}%"
        rows = await self._pool.fetch(
            r"""SELECT c.*,
                       CASE WHEN c.title ILIKE $3 ESCAPE '\' THEN NULL ELSE (
                         SELECT m.content FROM conversation_messages m
                          WHERE m.tenant_id = c.tenant_id AND m.conversation_id = c.id
                            AND m.superseded_by IS NULL
                            AND m.content ILIKE $3 ESCAPE '\'
                          ORDER BY m.created_at ASC
                          LIMIT 1
                       ) END AS matched_snippet
                  FROM conversations c
                 WHERE c.tenant_id = $1 AND c.user_id = $2
                   AND (
                         c.title ILIKE $3 ESCAPE '\'
                         OR EXISTS (
                              SELECT 1 FROM conversation_messages m
                               WHERE m.tenant_id = c.tenant_id
                                 AND m.conversation_id = c.id
                                 AND m.superseded_by IS NULL
                                 AND m.content ILIKE $3 ESCAPE '\'
                            )
                       )
                 ORDER BY c.updated_at DESC, c.id ASC
                 LIMIT $4 OFFSET $5""",
            tenant_id, user_id, pattern, limit + 1, off,
        )
        has_more = len(rows) > limit
        out = [(_conversation(r), r["matched_snippet"]) for r in rows[:limit]]
        return out, (off + limit if has_more else None)

    async def update_conversation(self, c: Conversation):
        await self._pool.execute(
            """UPDATE conversations SET title=$3, status=$4, updated_at=$5
               WHERE tenant_id=$1 AND id=$2""",
            c.tenant_id, c.id, c.title, c.status.value, c.updated_at,
        )

    async def add_message(self, m: ConversationMessage):
        await self._pool.execute(
            """INSERT INTO conversation_messages
               (id, conversation_id, tenant_id, role, content, run_id, hitl_request_id,
                events, attachments, superseded_by, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            m.id, m.conversation_id, m.tenant_id, m.role.value, m.content, m.run_id,
            m.hitl_request_id, m.events, m.attachments, m.superseded_by, m.created_at,
        )

    async def list_messages(self, tenant_id, conv_id):
        rows = await self._pool.fetch(
            """SELECT * FROM conversation_messages WHERE tenant_id=$1 AND conversation_id=$2
               ORDER BY created_at ASC""",
            tenant_id, conv_id,
        )
        return [_message(r) for r in rows]

    async def mark_message_superseded(self, tenant_id, message_id, superseded_by):
        # Marker-only ([2026] VJS-COUNTY 4, D3): the UPDATE touches superseded_by and
        # NOTHING else, so content/events/run_id/created_at are frozen. Tenant-scoped.
        await self._pool.execute(
            """UPDATE conversation_messages SET superseded_by=$3
               WHERE tenant_id=$1 AND id=$2""",
            tenant_id, message_id, superseded_by,
        )

    async def add_conversation_summary(self, s: ConversationSummary):
        # Append-only ([2026] VJS-COUNTY 4 keeps message content frozen): a summary
        # is DERIVED data INSERTED here; it never mutates a conversation_messages
        # row. A re-compaction appends a new row, so ON CONFLICT DO NOTHING keeps
        # the insert idempotent without ever overwriting.
        await self._pool.execute(
            """INSERT INTO conversation_summaries
               (id, conversation_id, tenant_id, up_to_message_id, covered_count,
                summary, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            s.id, s.conversation_id, s.tenant_id, s.up_to_message_id,
            s.covered_count, s.summary, s.created_at,
        )

    async def get_latest_conversation_summary(self, tenant_id, conversation_id):
        # The latest summary covers the most messages (widest boundary); break ties
        # by created_at so a re-compaction's fresh row wins.
        row = await self._pool.fetchrow(
            """SELECT * FROM conversation_summaries
               WHERE tenant_id=$1 AND conversation_id=$2
               ORDER BY covered_count DESC, created_at DESC
               LIMIT 1""",
            tenant_id, conversation_id,
        )
        return _summary(row)

    async def purge_closed_conversations(self, tenant_id, older_than):
        # M11 / SEC-74 right-to-erasure: HARD-DELETE CLOSED conversations past the
        # cutoff (updated_at is the close timestamp - the soft-close stamps it) and
        # their conversation_messages + derived conversation_summaries. Neither
        # child table carries an FK to conversations, so the child rows are deleted
        # explicitly first. The audit log is EXEMPT and never touched here (erasing
        # the SEC-16 hash chain would break tamper-evidence). Tenant-scoped (SEC-08).
        # One atomic transaction: a crash mid-purge cannot strand a conversation
        # whose messages/summaries are already erased.
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn)  # RLS-live: scope this explicit transaction
                rows = await conn.fetch(
                    """SELECT id FROM conversations
                       WHERE tenant_id=$1 AND status=$2 AND updated_at <= $3""",
                    tenant_id, ConversationStatus.CLOSED.value, older_than,
                )
                conv_ids = [r["id"] for r in rows]
                if not conv_ids:
                    return 0
                await conn.execute(
                    """DELETE FROM conversation_messages
                       WHERE tenant_id=$1 AND conversation_id = ANY($2::text[])""",
                    tenant_id, conv_ids,
                )
                await conn.execute(
                    """DELETE FROM conversation_summaries
                       WHERE tenant_id=$1 AND conversation_id = ANY($2::text[])""",
                    tenant_id, conv_ids,
                )
                await conn.execute(
                    """DELETE FROM conversations WHERE tenant_id=$1 AND id = ANY($2::text[])""",
                    tenant_id, conv_ids,
                )
                return len(conv_ids)

    # --- Round Three: config revisions ---
    async def add_config_revision(self, rev: ConfigRevision) -> ConfigRevision:
        row = await self._pool.fetchrow(
            """INSERT INTO config_revisions (tenant_id, kind, ref, version, payload, actor, rolled_back)
               VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id, created_at""",
            rev.tenant_id, rev.kind, rev.ref, rev.version, rev.payload, rev.actor, rev.rolled_back,
        )
        rev.id = row["id"]
        rev.created_at = row["created_at"]
        return rev

    async def list_config_revisions(self, tenant_id, kind, ref):
        rows = await self._pool.fetch(
            """SELECT * FROM config_revisions WHERE tenant_id=$1 AND kind=$2 AND ref=$3
               ORDER BY created_at DESC""",
            tenant_id, kind, ref,
        )
        return [_revision(r) for r in rows]

    async def get_config_revision(self, tenant_id, rev_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM config_revisions WHERE tenant_id=$1 AND id=$2", tenant_id, rev_id
        )
        return _revision(row)

    # --- eval ---
    async def upsert_eval_case(self, c: EvalCase):
        await self._pool.execute(
            """INSERT INTO eval_cases (id, tenant_id, target_kind, target_ref, input, assertions, labels)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 target_kind=EXCLUDED.target_kind, target_ref=EXCLUDED.target_ref,
                 input=EXCLUDED.input, assertions=EXCLUDED.assertions, labels=EXCLUDED.labels""",
            c.id, c.tenant_id, c.target_kind, c.target_ref, c.input, c.assertions, c.labels,
        )

    async def get_eval_case(self, tenant_id, case_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM eval_cases WHERE tenant_id=$1 AND id=$2", tenant_id, case_id
        )
        return _eval_case(row)

    async def list_eval_cases(self, tenant_id):
        rows = await self._pool.fetch("SELECT * FROM eval_cases WHERE tenant_id=$1", tenant_id)
        return [_eval_case(r) for r in rows]

    async def add_eval_run(self, r: EvalRun):
        await self._pool.execute(
            """INSERT INTO eval_runs (id, tenant_id, case_id, passed, score, run_id, detail)
               VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (tenant_id, id) DO NOTHING""",
            r.id, r.tenant_id, r.case_id, r.passed, r.score, r.run_id, r.detail,
        )

    async def list_eval_runs(self, tenant_id, case_id=None):
        if case_id is None:
            rows = await self._pool.fetch(
                "SELECT * FROM eval_runs WHERE tenant_id=$1 ORDER BY created_at DESC", tenant_id
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM eval_runs WHERE tenant_id=$1 AND case_id=$2 ORDER BY created_at DESC",
                tenant_id, case_id,
            )
        return [_eval_run(r) for r in rows]

    # --- notifications ---
    async def upsert_notification_pref(self, p: NotificationPref):
        await self._pool.execute(
            """INSERT INTO notification_prefs (id, tenant_id, scope_kind, scope_ref, event_type, channel, target, enabled)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 scope_kind=EXCLUDED.scope_kind, scope_ref=EXCLUDED.scope_ref,
                 event_type=EXCLUDED.event_type, channel=EXCLUDED.channel,
                 target=EXCLUDED.target, enabled=EXCLUDED.enabled""",
            p.id, p.tenant_id, p.scope_kind, p.scope_ref, p.event_type, p.channel,
            p.target, p.enabled,
        )

    async def list_notification_prefs(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM notification_prefs WHERE tenant_id=$1", tenant_id
        )
        return [_notif(r) for r in rows]

    # --- personal agents ---
    async def upsert_personal_agent(self, a: PersonalAgent):
        await self._pool.execute(
            """INSERT INTO personal_agents (id, tenant_id, user_id, runtime, skills, enabled)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 user_id=EXCLUDED.user_id, runtime=EXCLUDED.runtime,
                 skills=EXCLUDED.skills, enabled=EXCLUDED.enabled""",
            a.id, a.tenant_id, a.user_id, a.runtime, a.skills, a.enabled,
        )

    async def get_personal_agent(self, tenant_id, user_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM personal_agents WHERE tenant_id=$1 AND user_id=$2
               ORDER BY created_at DESC LIMIT 1""",
            tenant_id, user_id,
        )
        return _personal(row)

    async def delete_personal_agent(self, tenant_id, user_id):
        result = await self._pool.execute(
            "DELETE FROM personal_agents WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )
        return result != "DELETE 0"

    # --- memory ---
    async def add_memory_item(self, m: MemoryItem):
        await self._pool.execute(
            """INSERT INTO memory_items (id, tenant_id, owner_scope, kind, content, embedding, source_ref, data_class)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (tenant_id, id) DO NOTHING""",
            m.id, m.tenant_id, m.owner_scope, m.kind, m.content, m.embedding, m.source_ref,
            m.data_class,
        )

    async def query_memory(self, tenant_id, owner_scopes, kind=None, limit=20):
        if kind is None:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_items WHERE tenant_id=$1 AND owner_scope = ANY($2::text[])
                   ORDER BY created_at DESC LIMIT $3""",
                tenant_id, list(owner_scopes), limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_items WHERE tenant_id=$1 AND owner_scope = ANY($2::text[])
                   AND kind=$3 ORDER BY created_at DESC LIMIT $4""",
                tenant_id, list(owner_scopes), kind, limit,
            )
        return [_memory(r) for r in rows]

    # --- Round Five: structured memory governance ---
    async def add_memory_fact(self, f: MemoryFact):
        await self._pool.execute(
            """INSERT INTO memory_facts (id, tenant_id, owner_scope, engine_ref, kind,
                                         source_kind, source_ref, data_class, content, redacted)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 owner_scope=EXCLUDED.owner_scope, engine_ref=EXCLUDED.engine_ref,
                 kind=EXCLUDED.kind, source_kind=EXCLUDED.source_kind,
                 source_ref=EXCLUDED.source_ref, data_class=EXCLUDED.data_class,
                 content=EXCLUDED.content, redacted=EXCLUDED.redacted""",
            f.id, f.tenant_id, f.owner_scope, f.engine_ref, f.kind, f.source_kind,
            f.source_ref, f.data_class, f.content, f.redacted,
        )

    async def get_memory_fact(self, tenant_id, fact_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM memory_facts WHERE tenant_id=$1 AND id=$2", tenant_id, fact_id
        )
        return _mem_fact(row)

    async def list_memory_facts(self, tenant_id, owner_scopes, kind=None, limit=50):
        if kind is None:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_facts WHERE tenant_id=$1
                   AND owner_scope = ANY($2::text[]) ORDER BY created_at DESC LIMIT $3""",
                tenant_id, list(owner_scopes), limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_facts WHERE tenant_id=$1
                   AND owner_scope = ANY($2::text[]) AND kind=$3
                   ORDER BY created_at DESC LIMIT $4""",
                tenant_id, list(owner_scopes), kind, limit,
            )
        return [_mem_fact(r) for r in rows]

    async def delete_memory_fact(self, tenant_id, fact_id):
        await self._pool.execute(
            "DELETE FROM memory_facts WHERE tenant_id=$1 AND id=$2", tenant_id, fact_id
        )

    async def add_memory_ingestion(self, i: MemoryIngestion):
        await self._pool.execute(
            """INSERT INTO memory_ingestions (id, tenant_id, source_kind, source_ref,
                                              owner_scope, status, hatchet_run_id,
                                              facts_added, screened, detail, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 status=EXCLUDED.status, hatchet_run_id=EXCLUDED.hatchet_run_id,
                 facts_added=EXCLUDED.facts_added, screened=EXCLUDED.screened,
                 detail=EXCLUDED.detail""",
            i.id, i.tenant_id, i.source_kind, i.source_ref, i.owner_scope, i.status,
            i.hatchet_run_id, i.facts_added, i.screened, i.detail, i.created_at,
        )

    async def update_memory_ingestion(self, i: MemoryIngestion):
        await self.add_memory_ingestion(i)

    async def list_memory_ingestions(self, tenant_id, limit=50):
        rows = await self._pool.fetch(
            "SELECT * FROM memory_ingestions WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2",
            tenant_id, limit,
        )
        return [_mem_ingestion(r) for r in rows]

    async def add_memory_erasure(self, e: MemoryErasure):
        await self._pool.execute(
            """INSERT INTO memory_erasures (id, tenant_id, requested_by, target, scope,
                                            engine_confirmed, transcript_handled,
                                            facts_removed, created_at, completed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            e.id, e.tenant_id, e.requested_by, e.target, e.scope, e.engine_confirmed,
            e.transcript_handled, e.facts_removed, e.created_at, e.completed_at,
        )

    async def list_memory_erasures(self, tenant_id, limit=50):
        rows = await self._pool.fetch(
            "SELECT * FROM memory_erasures WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2",
            tenant_id, limit,
        )
        return [_mem_erasure(r) for r in rows]

    async def upsert_memory_projection_status(self, s: MemoryProjectionStatus):
        await self._pool.execute(
            """INSERT INTO memory_projection_statuses
               (id, tenant_id, projection_id, operation, status, fact_id, target,
                projection_ref, error, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 status=EXCLUDED.status, projection_ref=EXCLUDED.projection_ref,
                 error=EXCLUDED.error, updated_at=EXCLUDED.updated_at""",
            s.id, s.tenant_id, s.projection_id, s.operation, s.status, s.fact_id,
            s.target, s.projection_ref, s.error, s.created_at, s.updated_at,
        )

    async def list_memory_projection_statuses(self, tenant_id, fact_id=None, limit=50):
        if fact_id is None:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_projection_statuses WHERE tenant_id=$1
                   ORDER BY updated_at DESC LIMIT $2""",
                tenant_id, limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_projection_statuses
                   WHERE tenant_id=$1 AND fact_id=$2
                   ORDER BY updated_at DESC LIMIT $3""",
                tenant_id, fact_id, limit,
            )
        return [_mem_projection(r) for r in rows]

    # --- Round Four: users + provisioning (USR) ---
    async def upsert_user(self, u: User):
        await self._pool.execute(
            """INSERT INTO users (id, tenant_id, email, display_name, groups, role, scope,
                                  status, source, source_group, last_seen_at, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 email=EXCLUDED.email, display_name=EXCLUDED.display_name,
                 groups=EXCLUDED.groups, role=EXCLUDED.role, scope=EXCLUDED.scope,
                 status=EXCLUDED.status, source=EXCLUDED.source,
                 source_group=EXCLUDED.source_group, last_seen_at=EXCLUDED.last_seen_at""",
            u.id, u.tenant_id, u.email, u.display_name, u.groups, u.role, u.scope,
            u.status, u.source, u.source_group, u.last_seen_at, u.created_at,
        )

    async def get_user(self, tenant_id, user_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM users WHERE tenant_id=$1 AND id=$2", tenant_id, user_id
        )
        return _user(row)

    async def list_users(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM users WHERE tenant_id=$1 ORDER BY created_at DESC", tenant_id
        )
        return [_user(r) for r in rows]

    # --- personal access tokens (PAT, SEC-34) ---
    async def add_pat(self, p: PersonalAccessToken):
        await self._pool.execute(
            """INSERT INTO personal_access_tokens
               (id, tenant_id, user_id, name, token_hash, scope, created_at,
                expires_at, last_used_at, revoked)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            p.id, p.tenant_id, p.user_id, p.name, p.token_hash, p.scope, p.created_at,
            p.expires_at, p.last_used_at, p.revoked,
        )

    async def get_pat(self, tenant_id, pat_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM personal_access_tokens WHERE tenant_id=$1 AND id=$2",
            tenant_id, pat_id,
        )
        return _pat(row)

    async def get_pat_by_hash(self, token_hash):
        row = await self._pool.fetchrow(
            "SELECT * FROM personal_access_tokens WHERE token_hash=$1", token_hash
        )
        return _pat(row)

    async def list_pats(self, tenant_id, user_id):
        rows = await self._pool.fetch(
            """SELECT * FROM personal_access_tokens WHERE tenant_id=$1 AND user_id=$2
               ORDER BY created_at DESC""",
            tenant_id, user_id,
        )
        return [_pat(r) for r in rows]

    async def update_pat(self, p: PersonalAccessToken):
        await self._pool.execute(
            """UPDATE personal_access_tokens SET last_used_at=$3, revoked=$4
               WHERE tenant_id=$1 AND id=$2""",
            p.tenant_id, p.id, p.last_used_at, p.revoked,
        )

    # --- invitations (US-USR-02) ---
    async def add_invitation(self, inv: UserInvitation):
        await self._pool.execute(
            """INSERT INTO user_invitations
               (id, tenant_id, email, intended_role, intended_scope, invited_by,
                created_at, expires_at, status, token_hash,
                workspace_id, provision_workspace_name, provision_org_name)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            inv.id, inv.tenant_id, inv.email, inv.intended_role, inv.intended_scope,
            inv.invited_by, inv.created_at, inv.expires_at, inv.status, inv.token_hash,
            inv.workspace_id, inv.provision_workspace_name, inv.provision_org_name,
        )

    async def find_invitation_by_token_hash(self, tenant_id, token_hash):
        # First-party invite ([2026] VJS-COUNTY 7, D1): tenant-scoped (RLS-safe)
        # lookup of a still-pending invitation by its token hash.
        row = await self._pool.fetchrow(
            """SELECT * FROM user_invitations
               WHERE tenant_id=$1 AND status='pending' AND token_hash=$2""",
            tenant_id, token_hash,
        )
        return _invitation(row)

    async def consume_invitation(self, tenant_id, inv_id):
        # Atomic single-use consume (D1): pending -> accepted, True only for the
        # winner. RETURNING makes the CAS observable across concurrent redeemers.
        row = await self._pool.fetchrow(
            """UPDATE user_invitations SET status='accepted'
               WHERE tenant_id=$1 AND id=$2 AND status='pending'
               RETURNING id""",
            tenant_id, inv_id,
        )
        return row is not None

    # --- first-party password credentials ([2026] VJS-COUNTY 7, D4) ---
    async def set_password_credential(self, tenant_id, user_id, password_hash):
        await self._pool.execute(
            """INSERT INTO user_credentials (tenant_id, user_id, password_hash, updated_at)
               VALUES ($1,$2,$3, now())
               ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                 password_hash=EXCLUDED.password_hash, updated_at=now()""",
            tenant_id, user_id, password_hash,
        )

    async def get_password_credential(self, tenant_id, user_id):
        row = await self._pool.fetchrow(
            "SELECT password_hash FROM user_credentials WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )
        return None if row is None else row["password_hash"]

    # --- TOTP two-factor ([2026] VJS-COUNTY 10) ---
    async def set_user_totp(self, totp: UserTotp) -> None:
        await self._pool.execute(
            """INSERT INTO user_totp (tenant_id, user_id, secret_ref, enrolled, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5, now())
               ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                 secret_ref=EXCLUDED.secret_ref, enrolled=EXCLUDED.enrolled, updated_at=now()""",
            totp.tenant_id, totp.user_id, totp.secret_ref, totp.enrolled, totp.created_at,
        )

    async def get_user_totp(self, tenant_id, user_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM user_totp WHERE tenant_id=$1 AND user_id=$2", tenant_id, user_id
        )
        return _user_totp(row)

    async def delete_user_totp(self, tenant_id, user_id) -> None:
        await self._pool.execute(
            "DELETE FROM user_totp WHERE tenant_id=$1 AND user_id=$2", tenant_id, user_id
        )

    async def set_recovery_codes(self, tenant_id, user_id, code_hashes) -> None:
        # Replace the whole set atomically: clear then insert the fresh hashes.
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn)  # RLS-live: scope this explicit transaction
                await conn.execute(
                    "DELETE FROM user_recovery_codes WHERE tenant_id=$1 AND user_id=$2",
                    tenant_id, user_id,
                )
                for h in code_hashes:
                    await conn.execute(
                        """INSERT INTO user_recovery_codes (tenant_id, user_id, code_hash)
                           VALUES ($1,$2,$3)
                           ON CONFLICT (tenant_id, user_id, code_hash) DO NOTHING""",
                        tenant_id, user_id, h,
                    )

    async def consume_recovery_code(self, tenant_id, user_id, code_hash) -> bool:
        # Atomic single-use CAS: flip an unused hash to used, True only for the
        # winner (RETURNING makes it observable across concurrent redeemers).
        row = await self._pool.fetchrow(
            """UPDATE user_recovery_codes SET used_at=now()
               WHERE tenant_id=$1 AND user_id=$2 AND code_hash=$3 AND used_at IS NULL
               RETURNING code_hash""",
            tenant_id, user_id, code_hash,
        )
        return row is not None

    async def count_active_recovery_codes(self, tenant_id, user_id) -> int:
        row = await self._pool.fetchrow(
            """SELECT count(*) AS n FROM user_recovery_codes
               WHERE tenant_id=$1 AND user_id=$2 AND used_at IS NULL""",
            tenant_id, user_id,
        )
        return int(row["n"]) if row is not None else 0

    async def clear_recovery_codes(self, tenant_id, user_id) -> None:
        await self._pool.execute(
            "DELETE FROM user_recovery_codes WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )

    async def add_two_factor_challenge(self, challenge: TwoFactorChallenge) -> None:
        await self._pool.execute(
            """INSERT INTO two_factor_challenges (tenant_id, token_hash, user_id, expires_at, created_at)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (tenant_id, token_hash) DO NOTHING""",
            challenge.tenant_id, challenge.token_hash, challenge.user_id,
            challenge.expires_at, challenge.created_at,
        )

    async def get_two_factor_challenge(self, tenant_id, token_hash):
        row = await self._pool.fetchrow(
            "SELECT * FROM two_factor_challenges WHERE tenant_id=$1 AND token_hash=$2",
            tenant_id, token_hash,
        )
        return _tfa_challenge(row)

    async def consume_two_factor_challenge(self, tenant_id, token_hash) -> bool:
        # Atomic single-use: delete-if-present, True only for the winner.
        row = await self._pool.fetchrow(
            """DELETE FROM two_factor_challenges
               WHERE tenant_id=$1 AND token_hash=$2 RETURNING token_hash""",
            tenant_id, token_hash,
        )
        return row is not None

    async def get_invitation(self, tenant_id, inv_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM user_invitations WHERE tenant_id=$1 AND id=$2", tenant_id, inv_id
        )
        return _invitation(row)

    async def list_invitations(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM user_invitations WHERE tenant_id=$1 ORDER BY created_at DESC",
            tenant_id,
        )
        return [_invitation(r) for r in rows]

    async def find_pending_invitation(self, tenant_id, email):
        row = await self._pool.fetchrow(
            """SELECT * FROM user_invitations
               WHERE tenant_id=$1 AND status='pending' AND lower(email)=lower($2)
               ORDER BY created_at DESC LIMIT 1""",
            tenant_id, email,
        )
        return _invitation(row)

    async def update_invitation(self, inv: UserInvitation):
        await self._pool.execute(
            "UPDATE user_invitations SET status=$3 WHERE tenant_id=$1 AND id=$2",
            inv.tenant_id, inv.id, inv.status,
        )

    # --- per-user settings (SET-*) ---
    async def upsert_user_setting(self, s: UserSetting):
        await self._pool.execute(
            """INSERT INTO user_settings (tenant_id, user_id, key, value, updated_at)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (tenant_id, user_id, key) DO UPDATE SET
                 value=EXCLUDED.value, updated_at=EXCLUDED.updated_at""",
            s.tenant_id, s.user_id, s.key, s.value, s.updated_at,
        )

    async def list_user_settings(self, tenant_id, user_id):
        rows = await self._pool.fetch(
            "SELECT * FROM user_settings WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )
        return [_setting(r) for r in rows]

    # --- sessions (SET-70) ---
    async def add_session(self, s: UserSession):
        await self._pool.execute(
            """INSERT INTO user_sessions (id, tenant_id, user_id, client, created_at,
                                          last_seen_at, revoked, token_hash, expires_at,
                                          csrf_token, active_workspace_id, active_org_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            s.id, s.tenant_id, s.user_id, s.client, s.created_at, s.last_seen_at, s.revoked,
            s.token_hash, s.expires_at, s.csrf_token, s.active_workspace_id, s.active_org_id,
        )

    async def list_sessions(self, tenant_id, user_id):
        rows = await self._pool.fetch(
            """SELECT * FROM user_sessions WHERE tenant_id=$1 AND user_id=$2
               ORDER BY created_at DESC""",
            tenant_id, user_id,
        )
        return [_session(r) for r in rows]

    async def get_session(self, tenant_id, session_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM user_sessions WHERE tenant_id=$1 AND id=$2", tenant_id, session_id
        )
        return _session(row)

    async def get_session_by_token_hash(self, tenant_id, token_hash):
        # First-party session ([2026] VJS-COUNTY 7, D2): tenant-scoped (RLS-safe)
        # lookup of a session by its cookie-secret hash.
        row = await self._pool.fetchrow(
            "SELECT * FROM user_sessions WHERE tenant_id=$1 AND token_hash=$2",
            tenant_id, token_hash,
        )
        return _session(row)

    async def update_session(self, s: UserSession):
        # Carries the rotating secret hash / bounded expiry / CSRF token too (D6),
        # so a refresh (rotate_session) and a touch both persist through one path.
        await self._pool.execute(
            """UPDATE user_sessions SET client=$3, last_seen_at=$4, revoked=$5,
                                        token_hash=$6, expires_at=$7, csrf_token=$8,
                                        active_workspace_id=$9, active_org_id=$10
               WHERE tenant_id=$1 AND id=$2""",
            s.tenant_id, s.id, s.client, s.last_seen_at, s.revoked,
            s.token_hash, s.expires_at, s.csrf_token, s.active_workspace_id, s.active_org_id,
        )

    # --- Org -> workspace tenancy ([2026] VJS-COUNTY 8) ----------------------
    async def create_org(self, org: Organisation):
        # Idempotent create (D1): ON CONFLICT DO NOTHING so ensure_default_org is a
        # safe no-op for a tenant that already has its org. The org id IS the
        # tenant_id.
        await self._pool.execute(
            """INSERT INTO organisations
               (id, name, slug, settings, allow_own_ai_keys, require_two_factor,
                created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (id) DO NOTHING""",
            org.id, org.name, org.slug, org.settings,
            org.allow_own_ai_keys, org.require_two_factor, org.created_at, org.updated_at,
        )

    async def get_org(self, tenant_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM organisations WHERE id=$1", tenant_id
        )
        return _org(row)

    async def list_orgs(self):
        rows = await self._pool.fetch(
            "SELECT * FROM organisations ORDER BY created_at DESC"
        )
        return [_org(r) for r in rows]

    async def update_org(self, org: Organisation):
        await self._pool.execute(
            """UPDATE organisations SET name=$2, slug=$3, settings=$4,
                   allow_own_ai_keys=$5, require_two_factor=$6, updated_at=now()
               WHERE id=$1""",
            org.id, org.name, org.slug, org.settings,
            org.allow_own_ai_keys, org.require_two_factor,
        )

    async def create_workspace(self, workspace: Workspace):
        await self._pool.execute(
            """INSERT INTO workspaces
               (id, tenant_id, name, slug, settings, status, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            workspace.id, workspace.tenant_id, workspace.name, workspace.slug,
            workspace.settings, workspace.status,
            workspace.created_at, workspace.updated_at,
        )

    async def get_workspace(self, tenant_id, workspace_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM workspaces WHERE tenant_id=$1 AND id=$2",
            tenant_id, workspace_id,
        )
        return _workspace(row)

    async def list_workspaces(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM workspaces WHERE tenant_id=$1 ORDER BY created_at DESC",
            tenant_id,
        )
        return [_workspace(r) for r in rows]

    async def update_workspace(self, workspace: Workspace):
        await self._pool.execute(
            """UPDATE workspaces SET name=$3, slug=$4, settings=$5, status=$6,
                   updated_at=now()
               WHERE tenant_id=$1 AND id=$2""",
            workspace.tenant_id, workspace.id, workspace.name, workspace.slug,
            workspace.settings, workspace.status,
        )

    async def add_org_member(self, member: OrgMember):
        # Both writes commit or neither does (base.py's lockstep invariant): a
        # failure between the org_members row and the identity_orgs index would
        # otherwise leave a dangling switch candidate.
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn)  # RLS-live: scope this explicit transaction
                await conn.execute(
                    """INSERT INTO org_members (tenant_id, user_id, role, created_at)
                       VALUES ($1,$2,$3,$4)
                       ON CONFLICT (tenant_id, user_id) DO UPDATE SET role=EXCLUDED.role""",
                    member.tenant_id, member.user_id, member.role, member.created_at,
                )
                # Keep the global email -> orgs INDEX in lockstep ([2026] VJS-COUNTY 11, D1).
                # identity_orgs is RLS-EXCLUDED (the pre-tenant lookup, keyed by the normalised
                # email), so this write does not need the bound tenant and is safe under RLS.
                await conn.execute(
                    """INSERT INTO identity_orgs (email, tenant_id, role, created_at)
                       VALUES (lower($1),$2,$3,$4)
                       ON CONFLICT (email, tenant_id) DO UPDATE SET role=EXCLUDED.role""",
                    member.user_id, member.tenant_id, member.role, member.created_at,
                )

    async def remove_org_member(self, tenant_id, user_id):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn)  # RLS-live: scope this explicit transaction
                await conn.execute(
                    "DELETE FROM org_members WHERE tenant_id=$1 AND user_id=$2",
                    tenant_id, user_id,
                )
                # Drop the index pointer too so a revoked membership is no longer a switch
                # candidate (the resolver also fail-closes on the org_members re-check).
                await conn.execute(
                    "DELETE FROM identity_orgs WHERE email=lower($1) AND tenant_id=$2",
                    user_id, tenant_id,
                )

    async def get_org_member(self, tenant_id, user_id):
        # Tenant-scoped single-membership re-auth ([2026] VJS-COUNTY 11, D2).
        row = await self._pool.fetchrow(
            "SELECT * FROM org_members WHERE tenant_id=$1 AND user_id=$2",
            tenant_id, user_id,
        )
        return _org_member(row)

    async def list_orgs_for_email(self, email):
        # The pre-tenant email -> orgs index (D1): the tenant_ids an email is a member
        # of. Resolved by the normalised email key (RLS-EXCLUDED), like get_pat_by_hash.
        rows = await self._pool.fetch(
            "SELECT tenant_id FROM identity_orgs WHERE email=lower($1) ORDER BY tenant_id",
            email,
        )
        return [r["tenant_id"] for r in rows]

    async def list_org_members(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM org_members WHERE tenant_id=$1 ORDER BY created_at",
            tenant_id,
        )
        return [_org_member(r) for r in rows]

    async def list_orgs_for_user(self, tenant_id, user_id):
        # Tenant-scoped membership query (switching seam): only the bound tenant's
        # org, never another tenant's, joined through org_members.
        rows = await self._pool.fetch(
            """SELECT o.* FROM organisations o
               JOIN org_members m ON m.tenant_id = o.id
               WHERE m.tenant_id=$1 AND m.user_id=$2
               ORDER BY o.created_at DESC""",
            tenant_id, user_id,
        )
        return [_org(r) for r in rows]

    async def add_workspace_member(self, member: WorkspaceMember):
        # A per-workspace role must be one of the allowed set (D3): reject an
        # out-of-set role before it can be persisted.
        if member.role not in WORKSPACE_ROLES:
            raise SchemaValidationError(
                f"invalid workspace role: {member.role!r}",
                errors=[f"role must be one of {sorted(WORKSPACE_ROLES)}"],
            )
        await self._pool.execute(
            """INSERT INTO workspace_members
               (workspace_id, user_id, tenant_id, role, permissions, created_at)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (tenant_id, workspace_id, user_id) DO UPDATE SET
                 role=EXCLUDED.role, permissions=EXCLUDED.permissions""",
            member.workspace_id, member.user_id, member.tenant_id, member.role,
            member.permissions, member.created_at,
        )

    async def remove_workspace_member(self, tenant_id, workspace_id, user_id):
        await self._pool.execute(
            """DELETE FROM workspace_members
               WHERE tenant_id=$1 AND workspace_id=$2 AND user_id=$3""",
            tenant_id, workspace_id, user_id,
        )

    async def list_workspace_members(self, tenant_id, workspace_id):
        rows = await self._pool.fetch(
            """SELECT * FROM workspace_members
               WHERE tenant_id=$1 AND workspace_id=$2 ORDER BY created_at""",
            tenant_id, workspace_id,
        )
        return [_workspace_member(r) for r in rows]

    async def get_workspace_member(self, tenant_id, workspace_id, user_id):
        # Tenant-scoped single-membership lookup (D11): the WHERE binds tenant_id, so
        # it can never return another tenant's row (None when absent, fail-closed).
        row = await self._pool.fetchrow(
            """SELECT * FROM workspace_members
               WHERE tenant_id=$1 AND workspace_id=$2 AND user_id=$3""",
            tenant_id, workspace_id, user_id,
        )
        return _workspace_member(row)

    async def list_workspaces_for_user(self, tenant_id, user_id):
        # Tenant-scoped membership query (switching seam): only workspaces inside
        # the bound tenant the user belongs to.
        rows = await self._pool.fetch(
            """SELECT w.* FROM workspaces w
               JOIN workspace_members m
                 ON m.tenant_id = w.tenant_id AND m.workspace_id = w.id
               WHERE m.tenant_id=$1 AND m.user_id=$2
               ORDER BY w.created_at DESC""",
            tenant_id, user_id,
        )
        return [_workspace(r) for r in rows]

    # --- per-org/workspace/user AI keys ([2026] VJS-COUNTY 8, D5) -------------
    async def set_ai_config(self, config: AiConfig) -> None:
        # Reject an out-of-set level before it can be persisted (mirrors the
        # workspace-role guard). The row carries a credential_ref only, never a key.
        if config.level not in AI_CONFIG_LEVELS:
            raise SchemaValidationError(
                f"invalid ai-config level: {config.level!r}",
                errors=[f"level must be one of {sorted(AI_CONFIG_LEVELS)}"],
            )
        await self._pool.execute(
            """INSERT INTO ai_configs
               (tenant_id, level, scope_id, provider, model, credential_ref,
                base_url, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,now())
               ON CONFLICT (tenant_id, level, scope_id) DO UPDATE SET
                 provider=EXCLUDED.provider, model=EXCLUDED.model,
                 credential_ref=EXCLUDED.credential_ref,
                 base_url=EXCLUDED.base_url, updated_at=now()""",
            config.tenant_id, config.level, config.scope_id, config.provider,
            config.model, config.credential_ref, config.base_url, config.created_at,
        )

    async def get_ai_config(self, tenant_id, level, scope_id):
        # Tenant-scoped: the WHERE binds tenant_id, so it can never return another
        # tenant's AI-config row (None when absent, fail-closed).
        row = await self._pool.fetchrow(
            """SELECT * FROM ai_configs
               WHERE tenant_id=$1 AND level=$2 AND scope_id=$3""",
            tenant_id, level, scope_id,
        )
        return _ai_config(row)

    async def list_ai_configs(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM ai_configs WHERE tenant_id=$1 ORDER BY level, scope_id",
            tenant_id,
        )
        return [_ai_config(r) for r in rows]

    async def delete_ai_config(self, tenant_id, level, scope_id):
        await self._pool.execute(
            "DELETE FROM ai_configs WHERE tenant_id=$1 AND level=$2 AND scope_id=$3",
            tenant_id, level, scope_id,
        )



def _like_escape(value: str) -> str:
    """Escape LIKE/ILIKE metacharacters so a user query is a pure substring match
    (US-CONV-10). Paired with ``ESCAPE '\\'`` in the SQL: a literal backslash,
    percent or underscore in the query is neutralised, so a caller can never turn a
    search term into a wildcard. This is substring hygiene; injection is already
    foreclosed because the value is a bound parameter, never interpolated."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
