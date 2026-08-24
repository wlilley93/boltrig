"""In-memory Store implementation.

Used by tests and dev as the reference Store; PostgreSQL must behave identically.
Tenant scoping is enforced on every method (keys are ``(tenant_id, id)`` tuples).
"""

from __future__ import annotations
from dataclasses import replace
from datetime import datetime
from threading import Lock

from .channels import ChannelStoreMem
from .audit_stream import AuditStreamStoreMem
from .run_records import RunRecordsStoreMem
from .conversations import ConversationsStoreMem
from .channel_dedup import ChannelDedupStoreMem
from .channel_outbox import ChannelOutboxStoreMem
from .budget_policy import BudgetPolicyMem
from .distillation_reads_memory import DistillationReadsMem
from .budget_usage import BudgetUsageMem
from .capabilities import CapabilityStoreMem
from .guarded_writes import GuardedWritesMem
from .hitl import HitlStoreMem
from .idempotency import IdempotencyStoreMem
from .observability_reads import ObservabilityReadsMem
from .password_resets import PasswordResetStoreMem
from .permanent_fleet import PermanentFleetStoreMem
from .birth_profiles import BirthProfileStoreMem
from .background_jobs import BackgroundJobStoreMem
from .sealing import seal_ref, unseal_ref
from .work_items import WorkItemReadsMem
from .workflow_triggers import WorkflowTriggerStoreMem
from .workflow_schedules import WorkflowScheduleStoreMem
from .authored_definitions_memory import AuthoredDefinitionStoreMem
from .capability_routing import CapabilityRoutingStoreMem
from .eval_cases import EvalCaseStoreMem
from .credential_references import CredentialReferencePresenceMem
from .ai_key_proposals import AiKeyProposalStoreMem
from .mcp_lifecycle import McpLifecycleStoreMem
from .model_endpoints_memory import ModelEndpointStoreMem
from .conversation_queue import ConversationQueueStoreMem
from .conversation_binding_memory import ConversationBindingStoreMem
from .agent_mailbox_memory import AgentMailboxStoreMem
from .effect_ledger_memory import EffectLedgerStoreMem
from boltrig.models import (
    AgentCapability,
    AuditEvent,
    AuditRollupAnchor,
    Budget,
    BudgetWindowRef,
    Channel,
    ChannelBinding,
    ChannelGatewayLease,
    ChannelGatewayStatus,
    ChannelOutboxMessage,
    ChannelPairing,
    ConfigRevision,
    Conversation,
    ConversationMessage,
    ConversationSummary,
    EMPTY_GRANTS,
    EvalCase,
    EvalRun,
    MemoryItem,
    NotificationPref,
    PersonalAccessToken,
    PersonalAgent,
    PermanentFleetObservation,
    BirthProfileReceipt,
    HITLRequest,
    HITLResponse,
    MemoryErasure,
    MemoryEvent,
    MemoryFact,
    MemoryIngestion,
    MemoryProjectionStatus,
    AI_CONFIG_LEVELS,
    AI_CONFIG_MODALITIES,
    AiConfig,
    Organisation,
    OrgMember,
    SecurityEvent,
    TenantPermissions,
    TwoFactorChallenge,
    User,
    UserInvitation,
    UserSession,
    UserSetting,
    UserTotp,
    WORKSPACE_ROLES,
    Workspace,
    WorkspaceMember,
    WorkflowDefinition,
    WorkItem,
    utcnow,
)
from boltrig.models.errors import SchemaValidationError
from boltrig.models.work import RunCheckpoint


def _norm_email_key(value) -> str:
    """Normalise an identity key (the email == user_id in the first-party flow) so
    the global email -> orgs index is case/space-insensitive, matching the login
    normalisation ([2026] VJS-COUNTY 11)."""
    return value.strip().lower() if isinstance(value, str) else ""


class InMemoryStore(
    EffectLedgerStoreMem,
    DistillationReadsMem,
    BudgetPolicyMem,
    BudgetUsageMem,
    WorkItemReadsMem,
    IdempotencyStoreMem,
    GuardedWritesMem,
    HitlStoreMem,
    AuditStreamStoreMem,
    RunRecordsStoreMem,
    ConversationsStoreMem,
    ChannelStoreMem,
    CapabilityStoreMem,
    PermanentFleetStoreMem,
    BirthProfileStoreMem,
    BackgroundJobStoreMem,
    ObservabilityReadsMem,
    ChannelDedupStoreMem,
    ChannelOutboxStoreMem,
    PasswordResetStoreMem,
    WorkflowTriggerStoreMem,
    WorkflowScheduleStoreMem,
    AuthoredDefinitionStoreMem,
    CapabilityRoutingStoreMem,
    EvalCaseStoreMem,
    CredentialReferencePresenceMem,
    AiKeyProposalStoreMem,
    McpLifecycleStoreMem,
    ModelEndpointStoreMem,
    ConversationQueueStoreMem,
    ConversationBindingStoreMem,
    AgentMailboxStoreMem,
):
    """In-memory Store composed from domain partial mixins for offline use and tests."""

    def __init__(self) -> None:
        self._init_authored_definition_state()
        self._init_capability_routing_state()
        self._init_ai_key_proposal_state()
        self._init_background_job_state()
        self._init_mcp_lifecycle_state()
        self._init_model_endpoint_state()
        self._init_conversation_queue_state()
        self._init_conversation_binding_state()
        self._init_agent_mailbox_state()
        self._init_execution_state()
        self._init_account_state()

    def _init_execution_state(self) -> None:
        self._perms: dict[str, TenantPermissions] = {}
        self._caps: dict[tuple[str, str, str], AgentCapability] = {}  # capability_key()
        self._workflows: dict[tuple[str, str, str], WorkflowDefinition] = {}
        # Design brief 22.1: workflow runs keyed by (tenant_id, run_id), one row per execute.
        # Read aggregated by workflow_run_stats to feed the automations home
        # cards with real persisted statistics.
        self._workflow_runs: dict[tuple[str, str], tuple[str, str, datetime]] = {}
        self._work: dict[tuple[str, str], WorkItem] = {}
        self._hitl: dict[tuple[str, str], HITLRequest] = {}
        self._hitl_resp: dict[tuple[str, str], HITLResponse] = {}
        self._audit: dict[str, list[AuditEvent]] = {}
        # [2026] VJS-COUNTY 9, D3/D4: the distinct security-signal chain (per tenant)
        # + the audit rollup anchors (per tenant, newest last). Both tenant-keyed so
        # tenant stays the isolation boundary.
        self._security: dict[str, list[SecurityEvent]] = {}
        self._anchors: dict[str, list[AuditRollupAnchor]] = {}
        self._budgets: dict[tuple[str, str], Budget] = {}
        self._budget_usage: dict[tuple[str, str, str], tuple[BudgetWindowRef, int, int]] = {}
        self._idem: dict[tuple[str, str], dict] = {}
        self._creds: dict[tuple[str, str], dict] = {}
        self._convs: dict[tuple[str, str], Conversation] = {}
        # Restore and hard purge share this lifecycle lock. InMemoryStore is used
        # from TestClient and retention threads as well as one asyncio loop, so a
        # threading lock (with no await while held) is the correct primitive.
        self._conversation_lifecycle_lock = Lock()
        self._messages: dict[str, list[ConversationMessage]] = {}
        # Append-only derived compaction summaries, keyed by conversation id.
        self._summaries: dict[str, list[ConversationSummary]] = {}
        self._revisions: list[ConfigRevision] = []
        self._rev_seq = 0

    def _init_account_state(self) -> None:
        self._permanent_fleet_observations: dict[tuple[str, str], PermanentFleetObservation] = {}
        self._birth_profile_receipts: dict[tuple[str, str, str], BirthProfileReceipt] = {}
        self._eval_cases: dict[tuple[str, str], EvalCase] = {}
        self._eval_runs: list[EvalRun] = []
        self._notif: dict[tuple[str, str], NotificationPref] = {}
        self._personal: dict[tuple[str, str], PersonalAgent] = {}
        self._memory: list[MemoryItem] = []
        # Round Five: structured memory governance (facts/ingestions/erasures).
        self._mem_facts: dict[tuple[str, str], MemoryFact] = {}
        self._mem_ingest: dict[tuple[str, str], MemoryIngestion] = {}
        self._mem_erase: list[MemoryErasure] = []
        self._mem_projection: dict[tuple[str, str], MemoryProjectionStatus] = {}
        # Typed memory planes (decision 0029): the `MemoryEvent` twin.
        self._mem_events: dict[tuple[str, str], MemoryEvent] = {}
        # Round Four: users, tokens, invitations, settings, sessions.
        self._users: dict[tuple[str, str], User] = {}
        self._pats: dict[tuple[str, str], PersonalAccessToken] = {}
        self._invites: dict[tuple[str, str], UserInvitation] = {}
        self._settings: dict[tuple[str, str, str], UserSetting] = {}
        self._sessions: dict[tuple[str, str], UserSession] = {}
        # First-party password credentials ([2026] VJS-COUNTY 7, D4): kept apart
        # from the user identity row so the hash never rides in a User view/export.
        self._password_creds: dict[tuple[str, str], str] = {}
        # TOTP two-factor ([2026] VJS-COUNTY 10): the enrolment row (secret_ref +
        # enrolled), the one-time recovery-code hashes (hash -> used flag, per user),
        # and the pending pre-session login challenges (by token hash). The base32
        # secret itself lives SEALED in self._creds (credential_refs), never here.
        self._totp: dict[tuple[str, str], UserTotp] = {}
        self._recovery: dict[tuple[str, str], dict[str, bool]] = {}
        self._tfa_challenges: dict[tuple[str, str], TwoFactorChallenge] = {}
        # Channels (decision 0003): channels keyed by id (cross-tenant lookup on
        # the inbound path), bindings + pairings keyed per-tenant.
        self._channels: dict[str, Channel] = {}
        self._chan_bindings: dict[tuple[str, str], ChannelBinding] = {}
        self._chan_pairings: dict[tuple[str, str], ChannelPairing] = {}
        self._chan_gateway_status: dict[tuple[str, str], ChannelGatewayStatus] = {}
        self._chan_gateway_leases: dict[tuple[str, str], ChannelGatewayLease] = {}
        # Phase 2 durability: replay-dedup markers keyed (tenant, channel,
        # delivery) -> expiry, and the socket-class outbound hand-off.
        self._chan_deliveries: dict[tuple[str, str, str], datetime] = {}
        self._chan_outbox: dict[tuple[str, str], ChannelOutboxMessage] = {}
        # Beat 3: durable delegation (checkpoints keyed (tenant, run, step),
        # fan-out counters keyed (tenant, tree, counter)).
        self._checkpoints: dict[tuple[str, str, str], RunCheckpoint] = {}
        self._fanout: dict[tuple[str, str, str], int] = {}
        # [2026] VJS-COUNTY 6: cooperative run-cancel markers keyed (tenant, run)
        # -> the requester. A marker row, never a mutable run table.
        self._cancels: dict[tuple[str, str], str] = {}
        # [2026] VJS-COUNTY 8: org -> workspace tenancy. Orgs keyed by tenant_id
        # (id == tenant_id), workspaces keyed (tenant, workspace_id), memberships
        # keyed by their PKs. Additive; tenant_id stays the isolation key.
        self._orgs: dict[str, Organisation] = {}
        self._workspaces: dict[tuple[str, str], Workspace] = {}
        self._org_members: dict[tuple[str, str], OrgMember] = {}
        # Keyed by (tenant_id, workspace_id, user_id). tenant_id is NOT optional:
        # workspace ids are unique only WITHIN an org (workspaces PK is
        # (tenant_id, id)) and provisioning mints the SAME id `ws_default` for
        # every org, so a (workspace_id, user_id) key collides across tenants by
        # construction and one org's membership write lands on another's row.
        self._workspace_members: dict[tuple[str, str, str], WorkspaceMember] = {}
        # [2026] VJS-COUNTY 11, D1: the global email -> orgs membership INDEX. Keyed by
        # the normalised email (NOT tenant-fenced): email -> {tenant_id: role}. It is
        # the pre-tenant lookup login reads to enumerate an email's orgs; kept in
        # lockstep with _org_members by add/remove_org_member. Holds only membership
        # pointers, never a secret or business data.
        self._identity_orgs: dict[str, dict[str, str]] = {}
        # [2026] VJS-COUNTY 8, D5: per-org/workspace/user AI keys. Keyed
        # (tenant, level, scope_id); each value carries a credential_ref, never a raw
        # key. Tenant stays the isolation key.
        self._ai_configs: dict[tuple[str, str, str, str], AiConfig] = {}

    # --- permissions ---
    async def get_tenant_permissions(self, tenant_id):
        return self._perms.get(tenant_id, TenantPermissions(tenant_id, EMPTY_GRANTS))

    def set_tenant_permissions(self, perms: TenantPermissions) -> None:
        """Seeding helper (manifest load / tests). Not part of the runtime contract."""
        self._perms[perms.tenant_id] = perms

    # --- libraries ---
    async def upsert_adapter(self, adapter):
        self._adapters[(adapter.tenant_id, adapter.id)] = adapter

    async def get_adapter(self, tenant_id, adapter_id):
        return self._adapters.get((tenant_id, adapter_id))

    async def list_adapters(self, tenant_id):
        return [a for (t, _), a in self._adapters.items() if t == tenant_id]

    async def delete_adapter(self, tenant_id, adapter_id):
        self._adapters.pop((tenant_id, adapter_id), None)
        self._delete_mcp_lifecycle_state(tenant_id, adapter_id)

    async def upsert_workflow(self, wf):
        # Versioned like Postgres (PK tenant+id+version): every version is kept.
        self._workflows[(wf.tenant_id, wf.id, wf.version)] = wf

    async def list_workflows(self, tenant_id):
        # Latest version per workflow id (the shelf), mirroring list_skills and
        # the PG DISTINCT ON (id) ... ORDER BY id, version DESC.
        latest: dict[str, WorkflowDefinition] = {}
        for (t, wid, _), w in self._workflows.items():
            if t == tenant_id and (wid not in latest or w.version > latest[wid].version):
                latest[wid] = w
        return list(latest.values())

    # --- credential references (sealed at rest, SEC-04 - see store/sealing.py) ---
    async def get_credential_ref(self, tenant_id, cred_id):
        ref = self._creds.get((tenant_id, cred_id))
        # Unseal transparently; legacy plaintext rows (no marker) pass through.
        return unseal_ref(ref) if ref is not None else None

    async def set_credential_ref(self, tenant_id: str, cred_id: str, ref: dict) -> None:
        self._creds[(tenant_id, cred_id)] = seal_ref(ref)

    async def delete_credential_ref(self, tenant_id: str, cred_id: str) -> None:
        self._creds.pop((tenant_id, cred_id), None)

    async def delete_credential_refs_for_run(self, tenant_id: str, run_id: str) -> int:
        prefix = f"run:{run_id}:"
        doomed = [key for key in self._creds if key[0] == tenant_id and key[1].startswith(prefix)]
        for key in doomed:
            del self._creds[key]
        return len(doomed)

    # --- Round Three: config revisions ---
    async def add_config_revision(self, rev):
        self._rev_seq += 1
        rev.id = self._rev_seq
        self._revisions.append(rev)
        return rev

    async def list_config_revisions(self, tenant_id, kind, ref):
        return [
            r
            for r in self._revisions
            if r.tenant_id == tenant_id and r.kind == kind and r.ref == ref
        ]

    async def get_config_revision(self, tenant_id, rev_id):
        return next(
            (r for r in self._revisions if r.tenant_id == tenant_id and r.id == rev_id), None
        )

    # --- notifications ---
    async def upsert_notification_pref(self, pref):
        self._notif[(pref.tenant_id, pref.id)] = pref

    async def list_notification_prefs(self, tenant_id):
        return [p for (t, _), p in self._notif.items() if t == tenant_id]

    # --- personal agents ---
    async def upsert_personal_agent(self, agent):
        self._personal[(agent.tenant_id, agent.user_id)] = agent

    async def get_personal_agent(self, tenant_id, user_id):
        return self._personal.get((tenant_id, user_id))

    async def delete_personal_agent(self, tenant_id, user_id):
        return self._personal.pop((tenant_id, user_id), None) is not None

    # --- memory (scope-filtered, SEC-31) ---
    async def add_memory_item(self, item):
        self._memory.append(item)

    async def query_memory(self, tenant_id, owner_scopes, kind=None, limit=20):
        scopes = set(owner_scopes)
        out = [
            m
            for m in self._memory
            if m.tenant_id == tenant_id
            and m.owner_scope in scopes
            and (kind is None or m.kind == kind)
        ]
        # newest-first, matching the Postgres ORDER BY created_at DESC contract.
        return sorted(out, key=lambda m: m.created_at, reverse=True)[:limit]

    # --- Round Five: structured memory governance ---
    async def add_memory_fact(self, fact):
        self._mem_facts[(fact.tenant_id, fact.id)] = fact

    async def get_memory_fact(self, tenant_id, fact_id):
        return self._mem_facts.get((tenant_id, fact_id))

    async def list_memory_facts(self, tenant_id, owner_scopes, kind=None, limit=50):
        scopes = set(owner_scopes)
        out = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id and f.owner_scope in scopes and (kind is None or f.kind == kind)
        ]
        return sorted(out, key=lambda f: f.created_at, reverse=True)[:limit]

    async def delete_memory_fact(self, tenant_id, fact_id):
        self._mem_facts.pop((tenant_id, fact_id), None)

    async def add_memory_ingestion(self, ing):
        self._mem_ingest[(ing.tenant_id, ing.id)] = ing

    async def update_memory_ingestion(self, ing):
        self._mem_ingest[(ing.tenant_id, ing.id)] = ing

    async def get_memory_ingestion_by_source(self, tenant_id, source_kind, source_ref):
        hits = [
            i
            for (t, _), i in self._mem_ingest.items()
            if t == tenant_id and i.source_kind == source_kind and i.source_ref == source_ref
        ]
        return max(hits, key=lambda i: i.created_at) if hits else None

    async def list_memory_ingestions(self, tenant_id, limit=50):
        out = [i for (t, _), i in self._mem_ingest.items() if t == tenant_id]
        return sorted(out, key=lambda i: i.created_at, reverse=True)[:limit]

    async def add_memory_erasure(self, er):
        self._mem_erase.append(er)

    async def list_memory_erasures(self, tenant_id, limit=50):
        out = [e for e in self._mem_erase if e.tenant_id == tenant_id]
        return sorted(out, key=lambda e: e.created_at, reverse=True)[:limit]

    async def upsert_memory_projection_status(self, status):
        key = (status.tenant_id, status.id)
        previous = self._mem_projection.get(key)
        self._mem_projection[key] = (
            replace(status, created_at=previous.created_at) if previous is not None else status
        )

    async def list_memory_projection_statuses(self, tenant_id, fact_id=None, limit=50):
        out = [
            s
            for (t, _), s in self._mem_projection.items()
            if t == tenant_id and (fact_id is None or s.fact_id == fact_id)
        ]
        return sorted(out, key=lambda s: s.updated_at, reverse=True)[:limit]

    # --- Typed memory planes (decision 0029) ---
    async def get_active_memory_fact(self, tenant_id, memory_key):
        # Newest non-expired active wins in the twin, mirroring the DB's
        # one-active index plus the expiry filter (MEM-TYP-01: an expired
        # value is history, not the current truth).
        now = utcnow()
        hits = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id
            and f.memory_key == memory_key
            and f.status == "active"
            and (f.valid_to is None or f.valid_to > now)
        ]
        return max(hits, key=lambda f: (f.version, f.created_at)) if hits else None

    async def list_active_subject_facts(
        self, tenant_id, owner_scopes, subject_type, subject_id, limit=64
    ):
        scopes = set(owner_scopes)
        prefix = f"{subject_type}::{subject_id}::"
        out = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id
            and f.owner_scope in scopes
            and f.memory_key is not None
            and f.memory_key.startswith(prefix)
            and f.status == "active"
            and (f.valid_to is None or f.valid_to > utcnow())
        ]
        return sorted(out, key=lambda f: f.created_at, reverse=True)[:limit]

    async def list_memory_slot_history(self, tenant_id, memory_key, limit=50):
        out = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id and f.memory_key == memory_key
        ]
        return sorted(out, key=lambda f: f.version, reverse=True)[:limit]

    async def list_memory_candidates(self, tenant_id, owner_scopes, limit=50):
        scopes = set(owner_scopes)
        out = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id and f.owner_scope in scopes and f.status == "candidate"
        ]
        return sorted(out, key=lambda f: f.created_at, reverse=True)[:limit]

    async def update_memory_fact(self, fact):
        self._mem_facts[(fact.tenant_id, fact.id)] = fact

    async def add_memory_event(self, event):
        self._mem_events[(event.tenant_id, event.id)] = event

    async def list_memory_events(self, tenant_id, *, memory_id=None, memory_key=None, limit=100):
        out = [
            e
            for (t, _), e in self._mem_events.items()
            if t == tenant_id
            and (memory_id is None or e.memory_id == memory_id)
            and (memory_key is None or e.memory_key == memory_key)
        ]
        return sorted(out, key=lambda e: e.created_at, reverse=True)[:limit]

    # --- Round Four: users + provisioning (USR) ---
    async def upsert_user(self, user):
        self._users[(user.tenant_id, user.id)] = user

    async def get_user(self, tenant_id, user_id):
        return self._users.get((tenant_id, user_id))

    async def list_users(self, tenant_id):
        return [u for (t, _), u in self._users.items() if t == tenant_id]

    # --- personal access tokens (PAT, SEC-34) ---
    async def add_pat(self, pat):
        # Insert-if-absent (mirrors the PG ON CONFLICT (tenant_id, id) DO NOTHING).
        self._pats.setdefault((pat.tenant_id, pat.id), pat)

    async def get_pat(self, tenant_id, pat_id):
        return self._pats.get((tenant_id, pat_id))

    async def get_pat_by_hash(self, token_hash):
        # The secret carries identity; lookup is by hash across tenants (the hash
        # is globally unique). Constant-time compare so the lookup does not leak a
        # hash prefix via timing (CRYPTO-04).
        import hmac as _hmac

        for pat in self._pats.values():
            if _hmac.compare_digest(pat.token_hash, token_hash):
                return pat
        return None

    async def list_pats(self, tenant_id, user_id):
        return [p for (t, _), p in self._pats.items() if t == tenant_id and p.user_id == user_id]

    async def update_pat(self, pat):
        # Narrow writer (mirrors the PG UPDATE): only last_used_at + revoked are
        # ever written back; a missing row is a no-op, never an insert.
        existing = self._pats.get((pat.tenant_id, pat.id))
        if existing is not None:
            existing.last_used_at = pat.last_used_at
            existing.revoked = pat.revoked

    # --- invitations (US-USR-02) ---
    async def add_invitation(self, inv):
        # Insert-if-absent (mirrors the PG ON CONFLICT (tenant_id, id) DO NOTHING).
        self._invites.setdefault((inv.tenant_id, inv.id), inv)

    async def get_invitation(self, tenant_id, inv_id):
        return self._invites.get((tenant_id, inv_id))

    async def list_invitations(self, tenant_id):
        return [i for (t, _), i in self._invites.items() if t == tenant_id]

    async def find_pending_invitation(self, tenant_id, email):
        target = email.strip().lower()
        matches = [
            inv
            for (t, _), inv in self._invites.items()
            if t == tenant_id and inv.status == "pending" and inv.email.strip().lower() == target
        ]
        # Newest first, matching the PG ORDER BY created_at DESC LIMIT 1.
        return max(matches, key=lambda i: i.created_at, default=None)

    async def claim_invitation_by_token_hash(self, tenant_id, token_hash, now):
        """Atomically claim one pending, unexpired first-party invite bearer."""
        import hmac as _hmac

        for (t, _), inv in self._invites.items():
            if (
                t == tenant_id
                and inv.status == "pending"
                and inv.token_hash
                and _hmac.compare_digest(inv.token_hash, token_hash)
                and (inv.expires_at is None or inv.expires_at > now)
            ):
                inv.status = "accepted"
                return replace(inv)
        return None

    async def consume_invitation(self, tenant_id, inv_id):
        # Atomic single-use consume (mirrors consume_hitl): pending -> accepted,
        # True only for the winner. The in-memory store is single-threaded per
        # event loop, so the read-modify-write is already atomic.
        inv = self._invites.get((tenant_id, inv_id))
        if inv is None or inv.status != "pending":
            return False
        inv.status = "accepted"
        return True

    async def update_invitation(self, inv):
        # Narrow writer (mirrors the PG UPDATE): only status is ever written
        # back; a missing row is a no-op, never an insert.
        existing = self._invites.get((inv.tenant_id, inv.id))
        if existing is not None:
            existing.status = inv.status

    # --- first-party password credentials ([2026] VJS-COUNTY 7, D4) ---
    async def set_password_credential(self, tenant_id, user_id, password_hash):
        self._password_creds[(tenant_id, user_id)] = password_hash

    async def get_password_credential(self, tenant_id, user_id):
        return self._password_creds.get((tenant_id, user_id))

    # --- TOTP two-factor ([2026] VJS-COUNTY 10) ---
    async def set_user_totp(self, totp: UserTotp) -> None:
        self._totp[(totp.tenant_id, totp.user_id)] = totp

    async def get_user_totp(self, tenant_id, user_id):
        return self._totp.get((tenant_id, user_id))

    async def delete_user_totp(self, tenant_id, user_id) -> None:
        self._totp.pop((tenant_id, user_id), None)

    async def set_recovery_codes(self, tenant_id, user_id, code_hashes) -> None:
        # Replace the whole set; each hash starts unused (False).
        self._recovery[(tenant_id, user_id)] = {h: False for h in code_hashes}

    async def consume_recovery_code(self, tenant_id, user_id, code_hash) -> bool:
        # Atomic single-use (mirrors consume_invitation): only an unused matching
        # hash flips to used (True) and returns True. A missing or already-used hash
        # returns False (fail-closed). The read-modify-write does not await, so it is
        # atomic on the single-threaded event loop.
        codes = self._recovery.get((tenant_id, user_id))
        if not codes or codes.get(code_hash) is not False:
            return False
        codes[code_hash] = True
        return True

    async def count_active_recovery_codes(self, tenant_id, user_id) -> int:
        codes = self._recovery.get((tenant_id, user_id)) or {}
        return sum(1 for used in codes.values() if not used)

    async def clear_recovery_codes(self, tenant_id, user_id) -> None:
        self._recovery.pop((tenant_id, user_id), None)

    async def add_two_factor_challenge(self, challenge: TwoFactorChallenge) -> None:
        self._tfa_challenges[(challenge.tenant_id, challenge.token_hash)] = challenge

    async def get_two_factor_challenge(self, tenant_id, token_hash):
        return self._tfa_challenges.get((tenant_id, token_hash))

    async def consume_two_factor_challenge(self, tenant_id, token_hash) -> bool:
        # Atomic single-use: delete-if-present, True only for the winner (the pop is
        # a single non-awaiting op, atomic on the single-threaded event loop).
        return self._tfa_challenges.pop((tenant_id, token_hash), None) is not None

    # --- per-user settings (SET-*) ---
    async def upsert_user_setting(self, setting):
        self._settings[(setting.tenant_id, setting.user_id, setting.key)] = setting

    async def list_user_settings(self, tenant_id, user_id):
        return [s for (t, u, _), s in self._settings.items() if t == tenant_id and u == user_id]

    # --- sessions (SET-70) ---
    async def add_session(self, session):
        # Insert-if-absent (mirrors the PG ON CONFLICT (tenant_id, id) DO NOTHING).
        self._sessions.setdefault((session.tenant_id, session.id), session)

    async def list_sessions(self, tenant_id, user_id):
        return [
            s for (t, _), s in self._sessions.items() if t == tenant_id and s.user_id == user_id
        ]

    async def get_session(self, tenant_id, session_id):
        return self._sessions.get((tenant_id, session_id))

    async def get_session_by_token_hash(self, tenant_id, token_hash):
        # First-party session ([2026] VJS-COUNTY 7, D2): match a session by its
        # cookie-secret hash, constant-time, tenant-scoped.
        import hmac as _hmac

        for (t, _), s in self._sessions.items():
            if t == tenant_id and s.token_hash and _hmac.compare_digest(s.token_hash, token_hash):
                return s
        return None

    async def update_session(self, session):
        self._sessions[(session.tenant_id, session.id)] = session

    # --- Org -> workspace tenancy ([2026] VJS-COUNTY 8) ----------------------
    async def create_org(self, org):
        # Idempotent (mirrors the add_* ON CONFLICT DO NOTHING contract): a repeat
        # create for an existing tenant_id is a no-op, so ensure_default_org is safe
        # to call on every boot. The org id IS the tenant_id (D1).
        self._orgs.setdefault(org.id, org)

    async def get_org(self, tenant_id):
        return self._orgs.get(tenant_id)

    async def list_orgs(self):
        # Cross-tenant enumeration for the control plane (no tenant is bound at the
        # backfill). Not reachable from a tenant-scoped HTTP surface.
        return list(self._orgs.values())

    async def update_org(self, org):
        org.updated_at = utcnow()
        self._orgs[org.id] = org

    async def create_workspace(self, workspace):
        self._workspaces[(workspace.tenant_id, workspace.id)] = workspace

    async def get_workspace(self, tenant_id, workspace_id):
        return self._workspaces.get((tenant_id, workspace_id))

    async def list_workspaces(self, tenant_id):
        return [w for (t, _), w in self._workspaces.items() if t == tenant_id]

    async def update_workspace(self, workspace):
        workspace.updated_at = utcnow()
        self._workspaces[(workspace.tenant_id, workspace.id)] = workspace

    async def add_org_member(self, member):
        self._org_members[(member.tenant_id, member.user_id)] = member
        # Keep the global email -> orgs INDEX in lockstep ([2026] VJS-COUNTY 11, D1):
        # the email (== user_id in the first-party flow) is now a member of this org.
        email = _norm_email_key(member.user_id)
        self._identity_orgs.setdefault(email, {})[member.tenant_id] = member.role

    async def remove_org_member(self, tenant_id, user_id):
        self._org_members.pop((tenant_id, user_id), None)
        # Drop the index pointer too so a revoked membership is no longer a switch
        # candidate (the resolver also fail-closes on the org_members re-check).
        email = _norm_email_key(user_id)
        orgs = self._identity_orgs.get(email)
        if orgs is not None:
            orgs.pop(tenant_id, None)
            if not orgs:
                self._identity_orgs.pop(email, None)

    async def get_org_member(self, tenant_id, user_id):
        # Tenant-scoped single-membership re-auth ([2026] VJS-COUNTY 11, D2): only the
        # bound tenant's row, None otherwise (fail-closed).
        return self._org_members.get((tenant_id, user_id))

    async def list_orgs_for_email(self, email):
        # The pre-tenant email -> orgs index (D1): the tenant_ids the email is a member
        # of. Cross-tenant BY KEY (the normalised email), like get_pat_by_hash - never
        # inside a tenant fence. Deterministic order so a default pick is stable.
        return sorted(self._identity_orgs.get(_norm_email_key(email), {}).keys())

    async def list_org_members(self, tenant_id):
        return [m for (t, _), m in self._org_members.items() if t == tenant_id]

    async def list_orgs_for_user(self, tenant_id, user_id):
        # The membership query switching will later use. Still tenant-scoped: it
        # only ever returns the bound tenant's org, never another tenant's.
        out = []
        for (t, u), _m in self._org_members.items():
            if t == tenant_id and u == user_id:
                org = self._orgs.get(t)
                if org is not None:
                    out.append(org)
        return out

    async def add_workspace_member(self, member):
        # A per-workspace role must be one of the allowed set (D3): reject an
        # out-of-set role so it can never be persisted.
        if member.role not in WORKSPACE_ROLES:
            raise SchemaValidationError(
                f"invalid workspace role: {member.role!r}",
                errors=[f"role must be one of {sorted(WORKSPACE_ROLES)}"],
            )
        self._workspace_members[(member.tenant_id, member.workspace_id, member.user_id)] = member

    async def remove_workspace_member(self, tenant_id, workspace_id, user_id):
        self._workspace_members.pop((tenant_id, workspace_id, user_id), None)

    async def list_workspace_members(self, tenant_id, workspace_id):
        return [
            m
            for (t, w, _), m in self._workspace_members.items()
            if t == tenant_id and w == workspace_id
        ]

    async def get_workspace_member(self, tenant_id, workspace_id, user_id):
        # Tenant-scoped single-membership lookup (D11): only return the row when it
        # is inside the bound tenant, else None (fail-closed, never crosses tenants).
        return self._workspace_members.get((tenant_id, workspace_id, user_id))

    async def list_workspaces_for_user(self, tenant_id, user_id):
        # Tenant-scoped: only workspaces in the bound tenant whose id the user is a
        # member of. Never crosses a tenant boundary.
        out = []
        for (t, w, u), _m in self._workspace_members.items():
            if t == tenant_id and u == user_id:
                ws = self._workspaces.get((tenant_id, w))
                if ws is not None:
                    out.append(ws)
        return out

    # --- per-org/workspace/user AI keys ([2026] VJS-COUNTY 8, D5) -------------
    async def set_ai_config(self, config: AiConfig) -> None:
        # Reject an out-of-set level (mirrors the workspace-role guard) so an invalid
        # level can never be persisted. The row stores a credential_ref, never a key.
        if config.level not in AI_CONFIG_LEVELS:
            raise SchemaValidationError(
                f"invalid ai-config level: {config.level!r}",
                errors=[f"level must be one of {sorted(AI_CONFIG_LEVELS)}"],
            )
        if config.modality not in AI_CONFIG_MODALITIES:
            raise SchemaValidationError(
                f"invalid ai-config modality: {config.modality!r}",
                errors=[f"modality must be one of {sorted(AI_CONFIG_MODALITIES)}"],
            )
        config.updated_at = utcnow()
        self._ai_configs[(config.tenant_id, config.level, config.scope_id, config.modality)] = (
            config
        )

    async def get_ai_config(self, tenant_id, level, scope_id, modality="text"):
        # Tenant-scoped: the key includes tenant_id, so a lookup under another tenant
        # never returns this tenant's row (fail-closed, never crosses the boundary).
        return self._ai_configs.get((tenant_id, level, scope_id, modality))

    async def list_ai_configs(self, tenant_id):
        return [c for (t, _, _, _), c in self._ai_configs.items() if t == tenant_id]

    async def delete_ai_config(self, tenant_id, level, scope_id, modality="text"):
        self._ai_configs.pop((tenant_id, level, scope_id, modality), None)
