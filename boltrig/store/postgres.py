"""PostgreSQL-backed Store (asyncpg). Satisfies ``store.base.Store`` (P0-1).

Mirrors ``InMemoryStore`` method for method; only durability differs. Every query is scoped by
``tenant_id`` (SEC-08). JSONB columns round-trip as Python dict/list via a codec.
Alembic is authoritative for production upgrades; ``schema.sql`` is an explicit
fresh-database/test bootstrap used only when ``apply_schema=True``.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import asyncpg

from .effect_ledger_postgres import EffectLedgerStorePG
from .channels import ChannelStorePG
from .audit_stream import AuditStreamStorePG
from .run_records import RunRecordsStorePG
from .conversations import ConversationsStorePG
from .memory_planes import MemoryPlanesStorePG
from .tenancy import TenancyStorePG
from .user_accounts import UserAccountsStorePG
from .user_auth import UserAuthStorePG
from .tenant_permissions import TenantPermissionsStorePG
from .libraries import LibraryStorePG
from .config_revisions import ConfigRevisionStorePG
from .notifications import NotificationsStorePG, PersonalAgentsStorePG
from .ai_configs import AiConfigStorePG
from .channel_dedup import ChannelDedupStorePG
from .channel_outbox import ChannelOutboxStorePG
from .budget_policy import BudgetPolicyPG
from .budget_usage import BudgetUsagePG
from .capabilities import CapabilityStorePG
from .control_plane_reads import ControlPlaneReadsPG
from .distillation_reads import DistillationReadsPG
from .guarded_writes import GuardedWritesPG
from .hitl import HitlStorePG
from .idempotency import IdempotencyStorePG
from .observability_reads import ObservabilityReadsPG
from .password_resets import PasswordResetStorePG
from .permanent_fleet import PermanentFleetStorePG
from .birth_profiles import BirthProfileStorePG
from .background_jobs import BackgroundJobStorePG
from .work_items import WorkItemReadsPG
from .workflow_triggers import WorkflowTriggerStorePG
from .workflow_schedules import WorkflowScheduleStorePG
from .authored_definitions_postgres import AuthoredDefinitionStorePG
from .capability_routing import CapabilityRoutingStorePG
from .eval_cases import EvalCaseStorePG
from .credential_references import CredentialReferencePresencePG, CredentialRefsStorePG
from .ai_key_proposals import AiKeyProposalStorePG
from .mcp_lifecycle import McpLifecycleStorePG
from .model_endpoints_postgres import ModelEndpointStorePG
from .conversation_queue import ConversationQueueStorePG
from .conversation_binding_postgres import ConversationBindingStorePG
from .agent_mailbox_postgres import AgentMailboxStorePG
_SCHEMA = Path(__file__).with_name("schema.sql")
_RLS = Path(__file__).with_name("rls.sql")

# Tenant binding lives in tenant_scope; re-exported because callers import it from
# here. `X as X` is REQUIRED - mypy disallows implicit re-export, so a plain import
# is private to this module and every caller fails typecheck (broke CI 2026-07-31).
from .tenant_scope import (  # noqa: E402,F401
    _bind_tenant_from_argument as _bind_tenant_from_argument,
    _current_tenant as _current_tenant,
    _tenant_of as _tenant_of,
    bind_conn_to_tenant as bind_conn_to_tenant,
    bind_tenant_on_store_methods as bind_tenant_on_store_methods,
    pool_assumes_app_role as pool_assumes_app_role,
    set_current_tenant as set_current_tenant,
)


# The fence machinery (_apply_guc + the _RlsPool facade) lives in rls_pool.
# Re-exported because modules and tests import both from here.
from .rls_pool import _apply_guc, _RlsPool  # noqa: E402,F401  (deliberate re-export)


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
@bind_tenant_on_store_methods
class PostgresStore(
    EffectLedgerStorePG,
    ControlPlaneReadsPG,
    DistillationReadsPG,
    BudgetPolicyPG, BudgetUsagePG, WorkItemReadsPG, IdempotencyStorePG, GuardedWritesPG,
    HitlStorePG,
    AuditStreamStorePG,
    RunRecordsStorePG,
    ConversationsStorePG,
    MemoryPlanesStorePG,
    TenancyStorePG,
    UserAccountsStorePG,
    UserAuthStorePG,
    TenantPermissionsStorePG, LibraryStorePG,
    ConfigRevisionStorePG, NotificationsStorePG, PersonalAgentsStorePG,
    CredentialRefsStorePG,
    AiConfigStorePG,
    PermanentFleetStorePG,
    BirthProfileStorePG,
    BackgroundJobStorePG,
    ChannelStorePG, CapabilityStorePG, ObservabilityReadsPG,
    ChannelDedupStorePG, ChannelOutboxStorePG, PasswordResetStorePG,
    WorkflowTriggerStorePG, WorkflowScheduleStorePG,
    AuthoredDefinitionStorePG, CapabilityRoutingStorePG,
    EvalCaseStorePG,
    CredentialReferencePresencePG,
    AiKeyProposalStorePG,
    McpLifecycleStorePG,
    ModelEndpointStorePG, ConversationQueueStorePG, ConversationBindingStorePG,
    AgentMailboxStorePG,
):
    """asyncpg-backed Store. Domain methods live in partial mixins
    (e.g. ``ChannelStorePG``) to keep this file under the structural floor;
    composed here so the public method surface is one class."""
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        # Set by connect() when RLS is live AND boltrig_app exists; read by
        # with_tenant(), which does not go through _RlsPool._scoped.
        self._assume_app_role = False

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
            # RLS-live: every store call is tenant-scoped at the DB via the request
            # contextvar AND drops to the non-bypassing boltrig_app role. Probed once
            # here, not per call: a database that never ran rls.sql has no such role,
            # and the fact cannot change without a deployment.
            async with pool.acquire() as conn:
                store._assume_app_role = bool(await conn.fetchval(
                    "SELECT 1 FROM pg_roles WHERE rolname = 'boltrig_app'"))
            store._pool = _RlsPool(pool, assume_role=store._assume_app_role)
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
                # A SECOND path: with_tenant opens its own transaction and never
                # reaches _scoped, so it would stay unprotected while the convenience
                # calls were fenced. Same role switch, same reason.
                if self._assume_app_role:
                    await conn.execute("SET LOCAL ROLE boltrig_app")
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
                yield conn
