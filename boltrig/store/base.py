"""The Store protocol - the kernel's only persistence seam.

The kernel depends on this Protocol, never on a concrete DB. ``InMemoryStore``
satisfies it for dev/tests; a Postgres-backed store (schema in ``schema.sql``)
satisfies the same Protocol for production. Tenant isolation (SEC-08) is a
contract of every method: an id lookup is always scoped by ``tenant_id``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from boltrig.models import (
    AdapterRecord,
    AiConfig, AuditEvent,
    AuditRollupAnchor, Budget, BudgetWindowRef,
    Channel, ChannelBinding, ChannelDeliveryReceipt,
    ChannelOutboxMessage, ChannelPairing, ConfigRevision,
    HITLRequest,
    MemoryErasure,
    MemoryEvent,
    MemoryFact,
    MemoryIngestion,
    MemoryItem,
    MemoryProjectionStatus,
    NotificationPref,
    Organisation,
    OrgMember,
    PersonalAccessToken,
    PersonalAgent,
    HITLResponse,
    SecurityEvent,
    Workspace,
    WorkspaceMember,
    TenantPermissions,
    TwoFactorChallenge,
    User,
    UserInvitation,
    UserSession,
    UserSetting,
    UserTotp,
    WorkflowDefinition,
    WorkItem,
    WorkStatus,
)
from boltrig.models.work import RunCheckpoint
from .guarded_writes import GuardedWritesContract
from .idempotency_contract import IdempotencyStoreContract
from .budget_policy import BudgetPolicyContract
from .capabilities import CapabilityStoreContract
from .realtime_call_contract import RealtimeCallStoreContract
from .password_reset_contract import PasswordResetStoreContract
from .permanent_fleet import PermanentFleetStoreContract
from .birth_profiles import BirthProfileStoreContract
from .background_jobs import BackgroundJobStoreContract
from .audit_read_contract import AuditReadContract
from .workflow_trigger_contract import WorkflowTriggerStoreContract
from .workflow_schedule_contract import WorkflowScheduleStoreContract
from .authored_definitions_contract import AuthoredDefinitionStoreContract
from .eval_cases import EvalCaseStoreContract
from .execution_search_contract import ExecutionSearchContract
from .credential_references import CredentialReferenceContract
from .ai_key_proposals import AiKeyProposalStoreContract
from .channel_gateway_contract import ChannelGatewayStateContract
from .conversation_contract import ConversationStoreContract
from .mcp_lifecycle import McpLifecycleStoreContract
from .model_endpoint_contract import ModelEndpointStoreContract
# List pages clamp to MAX_WORK_PAGE/DEFAULT_WORK_PAGE so growing tenants stay bounded.
# limit=None on the store keeps the legacy
# full-slice contract for internal callers (e.g. the own-data export) that must
# see every row, and is never reachable from the /v1/work HTTP surface.
MAX_WORK_PAGE = 500
DEFAULT_WORK_PAGE = 100
# The structured-memory list reads (M9-memory / SEC-009): the caller may ask for
# a page size but the server caps it, and a batch ingest is capped by item count.
MAX_MEMORY_LIST = 200
MAX_INGEST_ITEMS = 100
# The observability audit reads (console/cost/telemetry/audit-search) push the
# department/workspace run-scope predicate INTO the query and clamp the page
# here, so a growing audit table is never pulled into memory wholesale and
# filtered in Python (same SEC-69 bounding idiom as MAX_WORK_PAGE).
MAX_OBSERVABILITY_PAGE = 10_000


def clamp_work_page(limit: int) -> int:
    """Clamp a caller-supplied work-list page size into [1, MAX_WORK_PAGE]."""
    return max(1, min(int(limit), MAX_WORK_PAGE))


def clamp_observability_page(limit: int) -> int:
    """Clamp an observability audit-read page into [1, MAX_OBSERVABILITY_PAGE]."""
    return max(1, min(int(limit), MAX_OBSERVABILITY_PAGE))


def clamp_memory_list(limit: int) -> int:
    """Clamp a caller-supplied memory-list page size into [1, MAX_MEMORY_LIST]."""
    return max(1, min(int(limit), MAX_MEMORY_LIST))

@runtime_checkable
class Store(BudgetPolicyContract, PermanentFleetStoreContract, BirthProfileStoreContract,
            BackgroundJobStoreContract, AuditReadContract, IdempotencyStoreContract, GuardedWritesContract,
            CapabilityStoreContract, RealtimeCallStoreContract, PasswordResetStoreContract,
            WorkflowTriggerStoreContract, WorkflowScheduleStoreContract,
            AuthoredDefinitionStoreContract,
            EvalCaseStoreContract, ExecutionSearchContract,
            CredentialReferenceContract, AiKeyProposalStoreContract,
            ChannelGatewayStateContract, ConversationStoreContract,
            McpLifecycleStoreContract, ModelEndpointStoreContract, Protocol):
    # --- permissions ---
    async def get_tenant_permissions(self, tenant_id: str) -> TenantPermissions: ...

    # --- libraries ---
    async def upsert_adapter(self, adapter: AdapterRecord) -> None: ...
    async def get_adapter(self, tenant_id: str, adapter_id: str) -> AdapterRecord | None: ...
    async def list_adapters(self, tenant_id: str) -> list[AdapterRecord]: ...
    async def delete_adapter(self, tenant_id: str, adapter_id: str) -> None: ...
    async def upsert_workflow(self, wf: WorkflowDefinition) -> None: ...
    async def list_workflows(self, tenant_id: str) -> list[WorkflowDefinition]: ...
    # Observability-only rows feed stats; write failure never voids execution.
    async def record_workflow_run(self, tenant_id: str, workflow_id: str, run_id: str, status: str) -> None: ...
    async def list_workflow_run_ids(self, tenant_id: str, workflow_id: str, limit: int = 100) -> list[str]: ...
    async def workflow_run_stats(self, tenant_id: str) -> list[dict[str, Any]]: ...
    # --- work items ---
    async def create_work_item(self, item: WorkItem) -> None: ...
    async def get_work_item(
        self, tenant_id: str, item_id: str,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> WorkItem | None: ...
    async def get_work_item_by_run_id(
        self, tenant_id: str, run_id: str,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> WorkItem | None: ...
    async def update_work_item(self, item: WorkItem) -> None: ...
    # Conditional work-item write ([2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001
    # D1). Writes only if the row still carries the lease the caller was GIVEN AT
    # CLAIM, and returns whether it wrote. The predicate is evaluated by the
    # backend in the same statement as the update: a read-then-write check in the
    # caller cannot decide a read-then-write race. The expected tuple must be the
    # one minted at claim and carried to the writing body, never one that body
    # re-read - a CAS whose expectation is re-derived at body start has the same
    # defect as no CAS at all.
    #
    # D9, the honest limit: this makes the RECORD single-writer. It does NOT make
    # execution exactly-once. A worker that lost its lease is still RUNNING - it
    # has already called out to models, adapters and the world - and all this
    # fence does is stop it landing its answer on top of the winner's. Anything
    # relying on a step running once must be idempotent in its own right. Do not
    # let a later docstring, doc or release note upgrade "single-writer" into
    # "exactly-once": the two are not the same guarantee and never will be.
    async def update_work_item_if_leased(
        self,
        item: WorkItem,
        *,
        lease_owner: str | None,
        lease_expires_at: datetime | None,
    ) -> bool: ...
    async def transition_work_item_status(
        self, tenant_id: str, item_id: str, *, expected: WorkStatus, new_status: WorkStatus
    ) -> bool: ...
    # The status CAS with payload: also clears the lease and stamps ``result``
    # in the SAME conditional write, so a sweeper settling an item can carry its
    # cancel reason without the read-then-write window of update_work_item.
    async def transition_work_item_settled(
        self,
        tenant_id: str,
        item_id: str,
        *,
        expected: WorkStatus,
        new_status: WorkStatus,
        result: dict[str, object],
    ) -> bool: ...
    async def list_work_items(
        self,
        tenant_id: str,
        status: WorkStatus | None = None,
        parent_id: str | None = None,
        departments: list[str] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> list[WorkItem]:
        # M7 / SEC-69: keyset paging uses stable id ordering and a clamped limit.
        # ``limit=None`` is the trusted full slice; workspace enforcement keeps an
        # omitted filter distinct from an external org-wide-only ``None`` scope.
        ...
    # Batch lookup by id OR hatchet_run_id in ONE query - the console prefetch
    # that keeps per-request HITL visibility checks O(1) queries instead of one
    # work-item read per pending request. Tenant-scoped (SEC-08).
    async def list_work_items_by_refs(
        self, tenant_id: str, refs: list[str]
    ) -> list[WorkItem]: ...
    # The /v1/runs listing (SEC-69): the RunScope predicate (department +
    # enforced-workspace visibility, and the hidden-wins rule that a run ref
    # owned by ANY out-of-scope item hides the row) is pushed INTO the query
    # under the same clamped keyset page as list_work_items, instead of loading
    # the whole work table to compute the scope in Python.
    async def list_run_items_scoped(
        self,
        tenant_id: str,
        *,
        departments: list[str] | None = None,
        workspace_id: str | None = None,
        owner: str | None = None,
        on_behalf_of: str | None = None,
        label: str | None = None,
        source: str | None = None,
        external_ref: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> list[WorkItem]: ...
    # atomic pending -> in_flight claim with a lease: one winner per item across
    # concurrent claimers; an expired lease is reclaimable; attempts increments
    # per claim (US-FLT-05). Mirrors the consume_hitl CAS shape.
    async def claim_work_item(
        self, tenant_id: str, worker_id: str, lease_seconds: int
    ) -> WorkItem | None: ...
    # atomic capped fan-out counter shared across workers (US-EXE-07): True and
    # the whole increment applied when value + n <= cap, False (nothing applied)
    # otherwise.
    async def try_increment_fanout(
        self, tenant_id: str, tree_id: str, counter: str, n: int, cap: int
    ) -> bool: ...
    # durable per-step run checkpoints - the resume seam for the pump (Beat 4).
    async def upsert_checkpoint(
        self,
        tenant_id: str,
        run_id: str,
        step: str,
        status: str,
        output: dict[str, Any] | None = None,
        hitl_request_id: str | None = None,
    ) -> None: ...
    async def list_checkpoints(self, tenant_id: str, run_id: str) -> list[RunCheckpoint]: ...

    # --- server-side run cancellation ([2026] VJS-COUNTY 6) ------------------
    # A cooperative, owner-only cancel signal keyed by run id. The route writes
    # the request THROUGH this narrow seam (owner-only + audited at the route,
    # mirroring rename/regenerate); the pump consults ``is_run_cancel_requested``
    # at each step boundary and stops BEFORE dispatching the next verb, never
    # interrupting an in-flight adapter call (D2/D3). A marker row, NOT a broad
    # mutable run table; idempotent (a re-request is a no-op, the first requester
    # stands). Durable: a restart re-detects the request and re-writes the
    # terminal CANCELLED state, so a cancelled run is never resurrected. Tenant-
    # scoped (SEC-08).
    async def request_run_cancel(self, tenant_id: str, run_id: str, requested_by: str) -> None: ...
    async def is_run_cancel_requested(self, tenant_id: str, run_id: str) -> bool: ...

    # --- hitl ---
    async def create_hitl_request(self, req: HITLRequest) -> None: ...
    async def get_hitl_request(self, tenant_id: str, req_id: str) -> HITLRequest | None: ...
    async def list_pending_hitl(self, tenant_id: str) -> list[HITLRequest]: ...
    async def list_answered_hitl(self, tenant_id: str) -> list[HITLRequest]: ...
    async def list_hitl_requests_for_requester(
        self,
        tenant_id: str,
        requested_by: str,
        statuses: list[str],
        *,
        limit: int = 20,
    ) -> list[HITLRequest]: ...
    async def answer_hitl(self, resp: HITLResponse) -> HITLRequest | None: ...
    async def get_hitl_response(self, tenant_id: str, request_id: str) -> HITLResponse | None: ...
    # atomic ANSWERED -> CONSUMED; True only for the caller that won the CAS (SEC-14).
    async def consume_hitl(self, tenant_id: str, request_id: str) -> bool: ...
    # atomic PENDING -> TIMED_OUT (timeout enforcement, SEC-14); True only for the
    # caller that won the CAS, so a concurrent answer never gets clobbered.
    async def expire_hitl(self, tenant_id: str, request_id: str) -> bool: ...

    # --- audit (hash chain head + append + query) ---
    async def audit_head(self, tenant_id: str) -> tuple[int, str | None]: ...
    async def audit_append(self, event: AuditEvent) -> None: ...
    # The durable audit outbox (SEC-16): an append that faulted durably defers
    # its (already-scrubbed, chain-field-free) payload; the janitor drains it.
    async def audit_outbox_enqueue(
        self, tenant_id: str, payload: dict[str, Any], append_error: str | None
    ) -> None: ...
    async def audit_outbox_due(
        self, tenant_id: str, now: datetime, limit: int = 100
    ) -> list[Any]: ...
    async def audit_outbox_delete(self, outbox_id: int) -> None: ...
    async def audit_outbox_mark_failed(
        self, outbox_id: int, append_error: str, next_retry_at: datetime
    ) -> None: ...
    async def audit_query(
        self, tenant_id: str, run_id: str | None = None, limit: int = 200
    ) -> list[AuditEvent]: ...
    # Scoped observability read (console/cost/telemetry/audit-search): the
    # WorkItem-derived RunScope predicate (visible/hidden run ids by department
    # + workspace) and the event-row workspace filter are applied INSIDE the
    # query, before the clamped LIMIT, so the route never loads-then-filters a
    # tenant-wide slice. ``departments=None`` is the unrestricted (org-admin)
    # scope; ``workspace_id`` is the caller's ACTIVE workspace (org-wide rows
    # plus that workspace's rows, fail-closed); ``match_parent`` folds
    # parent_run_id into the run refs (the two-arg RunScope.permits shape).
    # Ascending, tail-bounded like audit_query.
    async def audit_query_scoped(
        self,
        tenant_id: str,
        *,
        departments: list[str] | None = None,
        workspace_id: str | None = None,
        match_parent: bool = False,
        run_id: str | None = None,
        limit: int = 200,
    ) -> list[AuditEvent]: ...
    # ascending verification pages (rows with seq > after_seq, oldest first, up to
    # limit): verify() re-derives the WHOLE chain through these (SEC-168).
    async def audit_scan(
        self, tenant_id: str, after_seq: int, limit: int
    ) -> list[AuditEvent]: ...

    # --- security event stream ([2026] VJS-COUNTY 9, D3): its OWN hash chain ---
    async def security_head(self, tenant_id: str) -> tuple[int, str | None]: ...
    async def security_append(self, event: SecurityEvent) -> None: ...
    async def security_query(
        self, tenant_id: str, event_type: str | None = None, limit: int = 200
    ) -> list[SecurityEvent]: ...
    async def security_scan(
        self, tenant_id: str, after_seq: int, limit: int
    ) -> list[SecurityEvent]: ...

    # --- audit rollup anchors ([2026] VJS-COUNTY 9, D4) ---
    async def add_audit_anchor(self, anchor: AuditRollupAnchor) -> None: ...
    async def latest_audit_anchor(
        self, tenant_id: str, workspace_id: str | None = None
    ) -> AuditRollupAnchor | None: ...
    async def list_audit_anchors(        self, tenant_id: str, workspace_id: str | None = None, limit: int = 200
    ) -> list[AuditRollupAnchor]: ...

    # --- budgets ---
    async def get_budget(
        self,
        tenant_id: str,
        scope_id: str,
        *,
        run_id: str | None = None,
        at: datetime | None = None,
    ) -> Budget | None: ...
    async def list_budgets(
        self,
        tenant_id: str,
        *,
        run_id: str | None = None,
        at: datetime | None = None,
    ) -> list[Budget]: ...
    # Post-run cost true-up (FR-COST-03, audit M14): apply a SIGNED delta to the
    # scope's accumulators atomically (FOR UPDATE in postgres, under the lock in
    # memory), each floored at 0. Unlike a reserve this never gates on the
    # hard stop - it corrects the ledger for a call that already ran. A scope with
    # no budget row is a no-op (unmetered), the same as a reserve.
    async def reconcile_budget(
        self,
        tenant_id: str,
        window: BudgetWindowRef,
        delta_tokens: int,
        delta_micros: int,
    ) -> None: ...
    # Transactional multi-scope reserve (audit H4, engine-plan Phase 6, FR-COST-05):
    # debit EVERY scope in ``reservations`` (each a (scope_id, tokens, micros)
    # triple) in ONE all-or-nothing step. Either every hard-stop scope has headroom
    # and all are debited (returning their exact window references), or the first
    # hard-stop scope with no headroom aborts and NONE is debited (returns None).
    # Postgres
    # locks every scope's row FOR UPDATE in a deterministic order (sorted by
    # scope_id, so concurrent reserves on overlapping scopes cannot deadlock) and
    # re-checks each hard stop under the lock; memory applies the same semantics
    # under its no-await lock. A scope with no budget row is a no-op (unmetered),
    # This closes the partial-debit window the retired per-scope debit loop left
    # open: scope A debited, scope B refuses, A stays charged for a call that never
    # ran. That loop (``consume_budget``) is gone as of 2026-07-26 - it had had no
    # caller since reserve_budgets_atomic replaced it, while six docstrings across
    # the three store files still anchored their semantics on it.
    async def reserve_budgets_atomic(
        self,
        tenant_id: str,
        reservations: list[tuple[str, int, int]],
        *,
        run_id: str | None = None,
        at: datetime | None = None,
    ) -> tuple[BudgetWindowRef, ...] | None: ...

    # --- Round Three: versioned config, eval, customisation, memory ---
    async def add_config_revision(self, rev: ConfigRevision) -> ConfigRevision: ...
    async def list_config_revisions(
        self, tenant_id: str, kind: str, ref: str
    ) -> list[ConfigRevision]: ...
    async def get_config_revision(self, tenant_id: str, rev_id: int) -> ConfigRevision | None: ...
    async def upsert_notification_pref(self, pref: NotificationPref) -> None: ...
    async def list_notification_prefs(self, tenant_id: str) -> list[NotificationPref]: ...
    async def upsert_personal_agent(self, agent: PersonalAgent) -> None: ...
    async def get_personal_agent(self, tenant_id: str, user_id: str) -> PersonalAgent | None: ...
    async def delete_personal_agent(self, tenant_id: str, user_id: str) -> bool: ...

    # --- Channels (Channels feature, decision 0003) --------------------------
    async def upsert_channel(self, channel: "Channel") -> None: ...
    async def get_channel(self, tenant_id: str, channel_id: str) -> "Channel | None": ...
    # Cross-tenant lookup by the unguessable channel id: the inbound path resolves
    # the tenant from the channel BEFORE any tenant is bound (like get_pat_by_hash).
    async def get_channel_by_id(self, channel_id: str) -> "Channel | None": ...
    async def list_channels(self, tenant_id: str) -> list["Channel"]: ...
    async def delete_channel(self, tenant_id: str, channel_id: str) -> None: ...
    async def upsert_channel_binding(self, binding: "ChannelBinding") -> None: ...
    async def get_channel_binding(
        self, tenant_id: str, channel_id: str, external_user_id: str
    ) -> "ChannelBinding | None": ...
    async def list_channel_bindings(
        self, tenant_id: str, channel_id: str
    ) -> list["ChannelBinding"]: ...
    async def delete_channel_binding(self, tenant_id: str, binding_id: str) -> None: ...
    async def create_channel_pairing(self, pairing: "ChannelPairing") -> None: ...
    async def get_channel_pairing_by_code(
        self, tenant_id: str, channel_id: str, code_hash: str
    ) -> "ChannelPairing | None": ...
    # Atomic pending -> consumed CAS (single-use pairing, mirrors consume_hitl).
    async def consume_channel_pairing(self, tenant_id: str, pairing_id: str) -> bool: ...
    # The pending pairing for a sender (for wrong-code lockout; the lookup is by
    # sender, not code, so a bad code still finds the row to increment attempts).
    async def get_pending_pairing_for_sender(
        self, tenant_id: str, channel_id: str, external_user_id: str
    ) -> "ChannelPairing | None": ...
    # Increment attempts; auto-expire (lockout) once the cap is hit. Returns the
    # updated pairing, or None if it no longer exists / is not pending.
    async def bump_channel_pairing_attempts(
        self, tenant_id: str, pairing_id: str, *, cap: int
    ) -> "ChannelPairing | None": ...
    # --- Channel durability (decision 0003, Phase 2) -------------------------
    # Atomic record-and-check replay dedup (M3/SEC-66): True on the FIRST
    # sighting of (channel, delivery), False on a replay within the TTL window.
    async def record_channel_delivery(
        self, tenant_id: str, channel_id: str, delivery_id: str, *, ttl_seconds: int
    ) -> bool: ...
    # The durable outbound hand-off for socket-class channels: the kernel
    # enqueues, the sidecar claims (leased, one winner - mirrors claim_work_item)
    # and settles with ack (terminal) or fail (backoff retry, terminal at the
    # attempt cap). ack/fail are CAS'd on the lease owner.
    async def enqueue_channel_outbox(self, message: "ChannelOutboxMessage") -> None: ...
    async def claim_channel_outbox(
        self, tenant_id: str, channel_ids: list[str], worker_id: str,
        lease_seconds: int, limit: int,
    ) -> list["ChannelOutboxMessage"]: ...
    async def ack_channel_outbox(
        self, tenant_id: str, message_id: str, worker_id: str
    ) -> bool: ...
    async def fail_channel_outbox(
        self, tenant_id: str, message_id: str, worker_id: str, error: str | None,
        *, max_attempts: int, backoff_seconds: int,
    ) -> bool: ...
    # Caller-safe delivery lifecycle. These reads never return payload,
    # credential or gateway lease fields. Manual retry is an exact terminal
    # failed -> queued CAS; automatic gateway retry remains the owner of every
    # non-terminal row.
    async def list_channel_delivery_receipts(
        self, tenant_id: str, channel_id: str, limit: int = 50
    ) -> list["ChannelDeliveryReceipt"]: ...
    async def get_channel_delivery_receipt(
        self, tenant_id: str, channel_id: str, message_id: str
    ) -> "ChannelDeliveryReceipt | None": ...
    async def retry_terminal_channel_delivery(
        self, tenant_id: str, channel_id: str, message_id: str,
        expected_updated_at: datetime,
    ) -> "ChannelDeliveryReceipt | None": ...
    async def add_memory_item(self, item: MemoryItem) -> None: ...
    async def query_memory(
        self, tenant_id: str, owner_scopes: list[str], kind: str | None = None, limit: int = 20
    ) -> list[MemoryItem]: ...

    # --- Round Five: structured memory governance (facts/ingestions/erasures) ---
    async def add_memory_fact(self, fact: MemoryFact) -> None: ...
    async def get_memory_fact(self, tenant_id: str, fact_id: str) -> MemoryFact | None: ...
    async def list_memory_facts(
        self, tenant_id: str, owner_scopes: list[str], kind: str | None = None, limit: int = 50
    ) -> list[MemoryFact]: ...
    async def delete_memory_fact(self, tenant_id: str, fact_id: str) -> None: ...
    async def add_memory_ingestion(self, ing: MemoryIngestion) -> None: ...
    async def update_memory_ingestion(self, ing: MemoryIngestion) -> None: ...
    async def list_memory_ingestions(
        self, tenant_id: str, limit: int = 50
    ) -> list[MemoryIngestion]: ...
    async def get_memory_ingestion_by_source(
        self, tenant_id: str, source_kind: str, source_ref: str
    ) -> MemoryIngestion | None: ...
    async def list_idle_conversations(
        self, tenant_id: str, idle_before: Any, *, limit: int = 50
    ) -> list[Any]: ...
    async def count_pending_distillation(self, tenant_id: str, idle_before: Any) -> int: ...
    async def add_memory_erasure(self, er: MemoryErasure) -> None: ...
    async def list_memory_erasures(
        self, tenant_id: str, limit: int = 50
    ) -> list[MemoryErasure]: ...
    async def upsert_memory_projection_status(self, status: MemoryProjectionStatus) -> None: ...
    async def list_memory_projection_statuses(
        self, tenant_id: str, fact_id: str | None = None, limit: int = 50
    ) -> list[MemoryProjectionStatus]: ...

    # --- Typed memory planes (decision 0029): slots, versions, gate events ---
    async def get_active_memory_fact(
        self, tenant_id: str, memory_key: str
    ) -> MemoryFact | None: ...
    async def list_active_subject_facts(
        self,
        tenant_id: str,
        owner_scopes: list[str],
        subject_type: str,
        subject_id: str,
        limit: int = 64,
    ) -> list[MemoryFact]: ...
    async def list_memory_slot_history(
        self, tenant_id: str, memory_key: str, limit: int = 50
    ) -> list[MemoryFact]: ...
    async def list_memory_candidates(
        self, tenant_id: str, owner_scopes: list[str], limit: int = 50
    ) -> list[MemoryFact]: ...
    async def update_memory_fact(self, fact: MemoryFact) -> None: ...
    async def add_memory_event(self, event: MemoryEvent) -> None: ...
    async def list_memory_events(
        self,
        tenant_id: str,
        *,
        memory_id: str | None = None,
        memory_key: str | None = None,
        limit: int = 100,
    ) -> list[MemoryEvent]: ...

    # --- Round Four: users + provisioning (USR), tokens (PAT), settings, sessions ---
    async def upsert_user(self, user: User) -> None: ...
    async def get_user(self, tenant_id: str, user_id: str) -> User | None: ...
    async def list_users(self, tenant_id: str) -> list[User]: ...
    async def add_pat(self, pat: PersonalAccessToken) -> None: ...
    async def get_pat(self, tenant_id: str, pat_id: str) -> PersonalAccessToken | None: ...
    async def get_pat_by_hash(self, token_hash: str) -> PersonalAccessToken | None: ...
    async def list_pats(self, tenant_id: str, user_id: str) -> list[PersonalAccessToken]: ...
    async def update_pat(self, pat: PersonalAccessToken) -> None: ...
    async def add_invitation(self, inv: UserInvitation) -> None: ...
    async def get_invitation(self, tenant_id: str, inv_id: str) -> UserInvitation | None: ...
    async def list_invitations(self, tenant_id: str) -> list[UserInvitation]: ...
    async def find_pending_invitation(
        self, tenant_id: str, email: str
    ) -> UserInvitation | None: ...
    # First-party invite acceptance must claim the bearer BEFORE it performs any
    # account, credential or tenancy mutation.  Lookup + expiry + pending-state
    # transition therefore live in one store operation; returning the claimed
    # snapshot gives the sole winner the immutable authority it may materialise.
    async def claim_invitation_by_token_hash(
        self, tenant_id: str, token_hash: str, now: Any
    ) -> UserInvitation | None: ...
    # Atomic single-use consume: flip a still-pending invitation to 'accepted' and
    # return True only for the caller that won the CAS (mirrors consume_hitl), so a
    # token can be redeemed exactly once even under concurrency (D1).
    async def consume_invitation(self, tenant_id: str, inv_id: str) -> bool: ...
    async def update_invitation(self, inv: UserInvitation) -> None: ...
    # First-party password credentials ([2026] VJS-COUNTY 7, D4). The argon2id hash
    # is kept APART from the user identity row (never in the User dataclass, so it
    # cannot leak through a user view/export). Only the hash is stored; there is no
    # getter that returns anything reversible. Mirrors the set_credential_ref seam.
    async def set_password_credential(
        self, tenant_id: str, user_id: str, password_hash: str
    ) -> None: ...
    async def get_password_credential(self, tenant_id: str, user_id: str) -> str | None: ...
    async def upsert_user_setting(self, setting: UserSetting) -> None: ...
    async def list_user_settings(self, tenant_id: str, user_id: str) -> list[UserSetting]: ...
    async def add_session(self, session: UserSession) -> None: ...
    async def list_sessions(self, tenant_id: str, user_id: str) -> list[UserSession]: ...
    async def get_session(self, tenant_id: str, session_id: str) -> UserSession | None: ...
    # First-party session login ([2026] VJS-COUNTY 7, D2): resolve a live session by
    # the sha256 of its cookie secret, tenant-scoped (the console tenant is bound
    # first) so it is RLS-safe; constant-time compare in memory.
    async def get_session_by_token_hash(
        self, tenant_id: str, token_hash: str
    ) -> UserSession | None: ...
    async def update_session(self, session: UserSession) -> None: ...

    # --- TOTP two-factor ([2026] VJS-COUNTY 10) ------------------------------
    # D1/D3: a user's TOTP enrolment row, kept APART from the identity row (like the
    # password credential). The base32 secret itself is NOT here - it is SEALED in
    # credential_refs and referenced by ``secret_ref``; this row only carries the ref
    # + the ``enrolled`` flag. Tenant-scoped (SEC-08). set is an upsert (begin-enroll
    # then verify-enroll flip); delete is the disable path.
    async def set_user_totp(self, totp: UserTotp) -> None: ...
    async def get_user_totp(self, tenant_id: str, user_id: str) -> UserTotp | None: ...
    async def delete_user_totp(self, tenant_id: str, user_id: str) -> None: ...
    # D2: one-time recovery-code HASHES (never the plaintext). set_recovery_codes
    # REPLACES the whole set (enrol / regenerate); consume_recovery_code is an atomic
    # single-use CAS (flip an unused hash to used, returning True only for the winner)
    # so a code is redeemable exactly once; count_active_recovery_codes is the unused
    # count; clear removes them (disable). All tenant-scoped.
    async def set_recovery_codes(
        self, tenant_id: str, user_id: str, code_hashes: list[str]
    ) -> None: ...
    async def consume_recovery_code(self, tenant_id: str, user_id: str, code_hash: str) -> bool: ...
    async def count_active_recovery_codes(self, tenant_id: str, user_id: str) -> int: ...
    async def clear_recovery_codes(self, tenant_id: str, user_id: str) -> None: ...
    # D3: the pending login second-factor challenge. Stored by the sha256 of its
    # token; get resolves it (tenant-scoped), consume is an atomic single-use CAS
    # (delete-if-present, True only for the winner) so a challenge issues exactly one
    # session. No access rides on the challenge itself.
    async def add_two_factor_challenge(self, challenge: TwoFactorChallenge) -> None: ...
    async def get_two_factor_challenge(
        self, tenant_id: str, token_hash: str
    ) -> TwoFactorChallenge | None: ...
    async def consume_two_factor_challenge(self, tenant_id: str, token_hash: str) -> bool: ...

    # --- Org -> workspace tenancy ([2026] VJS-COUNTY 8) ----------------------
    # D1: the ORGANISATION is the tenant boundary - an org's id IS the tenant_id
    # (one org per tenant_id). create_org inserts idempotently (a repeat is a
    # no-op); get/list/update are tenant-scoped like every other read. RLS stays
    # keyed on tenant_id (unchanged). ``ensure_default_org`` (the module helper in
    # boltrig.identity.tenancy) sits on top of these for the backfill.
    async def create_org(self, org: Organisation) -> None: ...
    async def get_org(self, tenant_id: str) -> Organisation | None: ...
    async def list_orgs(self) -> list[Organisation]: ...
    async def update_org(self, org: Organisation) -> None: ...

    # D2 (schema only this phase): a WORKSPACE belongs to an org (tenant_id) and is
    # tenant-scoped. create/get/update are keyed on (tenant_id, workspace id);
    # list_workspaces enumerates the org's workspaces. No workspace_id is added to
    # any existing resource table yet.
    async def create_workspace(self, workspace: Workspace) -> None: ...
    async def get_workspace(self, tenant_id: str, workspace_id: str) -> Workspace | None: ...
    async def list_workspaces(self, tenant_id: str) -> list[Workspace]: ...
    async def update_workspace(self, workspace: Workspace) -> None: ...

    # D3: org + workspace membership. Both are tenant-scoped (SEC-08). A workspace
    # member's ``role`` MUST be one of models.tenancy.WORKSPACE_ROLES - the store
    # rejects an out-of-set role (SchemaValidationError) so an invalid per-workspace
    # role can never be persisted. The ``*_for_user`` reads are the membership
    # queries switching will later use (they still only ever return rows inside the
    # bound tenant).
    async def add_org_member(self, member: OrgMember) -> None: ...
    async def remove_org_member(self, tenant_id: str, user_id: str) -> None: ...
    async def list_org_members(self, tenant_id: str) -> list[OrgMember]: ...
    async def list_orgs_for_user(self, tenant_id: str, user_id: str) -> list[Organisation]: ...
    # Cross-tenant identity ([2026] VJS-COUNTY 11, D2): the single-membership lookup
    # the resolver + the org SWITCH use to RE-AUTHORIZE the caller against org_members
    # for the (candidate) active org. Tenant-scoped (SEC-08): only ever returns a row
    # inside the bound tenant (None otherwise, fail-closed), so a switch can never
    # trust a client-supplied org the caller is not actually a member of.
    async def get_org_member(self, tenant_id: str, user_id: str) -> OrgMember | None: ...
    # D1: the global email -> orgs membership INDEX. Keyed by the NORMALISED EMAIL
    # (identity), NOT tenant-fenced, because it is the PRE-TENANT lookup login uses to
    # learn which orgs an email belongs to before any tenant is bound - guarded exactly
    # like personal_access_tokens / channels (resolved by an identity key, not inside a
    # tenant). It holds no secret + no business data (only membership pointers) and is
    # never the authority: get_org_member re-checks the RLS-fenced org_members row for
    # each candidate. Kept in lockstep with org_members by add/remove_org_member, so it
    # never drifts. Returns the tenant_ids of the orgs the email is a member of.
    async def list_orgs_for_email(self, email: str) -> list[str]: ...
    async def add_workspace_member(self, member: WorkspaceMember) -> None: ...
    async def remove_workspace_member(
        self, tenant_id: str, workspace_id: str, user_id: str
    ) -> None: ...
    async def list_workspace_members(
        self, tenant_id: str, workspace_id: str
    ) -> list[WorkspaceMember]: ...
    # D11 (grant resolution): the cheap single-membership lookup the chokepoint uses
    # to resolve the caller's workspace role for the active workspace. Tenant-scoped:
    # only ever returns a row inside the bound tenant (None otherwise, fail-closed).
    async def get_workspace_member(
        self, tenant_id: str, workspace_id: str, user_id: str
    ) -> WorkspaceMember | None: ...
    async def list_workspaces_for_user(self, tenant_id: str, user_id: str) -> list[Workspace]: ...

    # D5 (per-org / workspace / user AI keys): ONE unified ``ai_configs`` table keyed
    # by (tenant_id, level, scope_id). Each row carries a provider/model selection and
    # a ``credential_ref`` - the id of a SEALED credential (in ``credential_refs``),
    # never the raw key. The store rejects an out-of-set ``level``
    # (SchemaValidationError) so an invalid level can never be persisted, mirroring the
    # workspace-role guard. All reads are tenant-scoped (SEC-08): they only ever return
    # rows inside the bound tenant, so a caller can never read another org/workspace's
    # AI key.
    async def set_ai_config(self, config: AiConfig) -> None: ...
    async def get_ai_config(
        self, tenant_id: str, level: str, scope_id: str, modality: str = "text"
    ) -> AiConfig | None: ...
    async def list_ai_configs(self, tenant_id: str) -> list[AiConfig]: ...
    async def delete_ai_config(
        self, tenant_id: str, level: str, scope_id: str, modality: str = "text"
    ) -> None: ...
