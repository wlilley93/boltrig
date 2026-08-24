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
from .sealing import seal_ref, unseal_ref
from .work_items import WorkItemReadsPG
from .workflow_triggers import WorkflowTriggerStorePG
from .workflow_schedules import WorkflowScheduleStorePG
from .authored_definitions_postgres import AuthoredDefinitionStorePG
from .capability_routing import CapabilityRoutingStorePG
from .eval_cases import EvalCaseStorePG
from .credential_references import CredentialReferencePresencePG
from .ai_key_proposals import AiKeyProposalStorePG
from .mcp_lifecycle import McpLifecycleStorePG
from .model_endpoints_postgres import ModelEndpointStorePG
from .conversation_queue import ConversationQueueStorePG
from .conversation_binding_postgres import ConversationBindingStorePG
from .agent_mailbox_postgres import AgentMailboxStorePG
from .rows import (
    _adapter, _invitation, _notif, _personal,
    _revision, _session, _setting, _tfa_challenge,
    _user_totp, _workflow,
)
from boltrig.models import (
    AdapterRecord,
    ConfigRevision,
    NotificationPref,
    PersonalAgent,
    TwoFactorChallenge,
    UserInvitation,
    UserSession,
    UserSetting,
    UserTotp,
    EMPTY_GRANTS,
    GrantSet,
    TenantPermissions,
    WorkflowDefinition,
)
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
                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))  # RLS-live: scope this explicit transaction
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
