"""In-memory Store implementation.

Used by tests and dev as the reference Store; PostgreSQL must behave identically.
Tenant scoping is enforced on every method (keys are ``(tenant_id, id)`` tuples).
"""

from __future__ import annotations
from datetime import datetime
from threading import Lock

from .channels import ChannelStoreMem
from .audit_stream import AuditStreamStoreMem
from .run_records import RunRecordsStoreMem
from .conversations import ConversationsStoreMem
from .memory_planes import MemoryPlanesStoreMem
from .tenancy import TenancyStoreMem
from .user_accounts import UserAccountsStoreMem
from .user_auth import UserAuthStoreMem
from .tenant_permissions import TenantPermissionsStoreMem
from .libraries import LibraryStoreMem
from .config_revisions import ConfigRevisionStoreMem
from .notifications import NotificationsStoreMem, PersonalAgentsStoreMem
from .ai_configs import AiConfigStoreMem
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
from .work_items import WorkItemReadsMem
from .workflow_triggers import WorkflowTriggerStoreMem
from .workflow_schedules import WorkflowScheduleStoreMem
from .authored_definitions_memory import AuthoredDefinitionStoreMem
from .capability_routing import CapabilityRoutingStoreMem
from .eval_cases import EvalCaseStoreMem
from .credential_references import CredentialReferencePresenceMem, CredentialRefsStoreMem
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
    Workspace,
    WorkspaceMember,
    WorkflowDefinition,
    WorkItem,
)
from boltrig.models.work import RunCheckpoint




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
    MemoryPlanesStoreMem,
    TenancyStoreMem,
    UserAccountsStoreMem,
    UserAuthStoreMem,
    TenantPermissionsStoreMem, LibraryStoreMem,
    ConfigRevisionStoreMem, NotificationsStoreMem, PersonalAgentsStoreMem,
    CredentialRefsStoreMem,
    AiConfigStoreMem,
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
