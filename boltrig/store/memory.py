"""In-memory Store implementation.

Used by tests and single-process dev. It is the reference implementation of the
Store contract: a Postgres-backed store must behave identically. Tenant scoping
is enforced on every method (keys are ``(tenant_id, id)`` tuples).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from .base import clamp_work_page
from .channels import ChannelStoreMem
from boltrig.models import (
    AdapterRecord,
    AgentCapability,
    AuditEvent,
    Budget,
    Channel,
    ChannelBinding,
    ChannelPairing,
    ConfigRevision,
    Conversation,
    ConversationMessage,
    ConversationStatus,
    ConversationSummary,
    EMPTY_GRANTS,
    EvalCase,
    EvalRun,
    MemoryItem,
    NotificationPref,
    PersonalAccessToken,
    PersonalAgent,
    HITLRequest,
    HITLResponse,
    HITLStatus,
    MemoryErasure,
    MemoryFact,
    MemoryIngestion,
    ModelEndpoint,
    Noun,
    Organisation,
    OrgMember,
    Skill,
    TenantPermissions,
    User,
    UserInvitation,
    UserSession,
    UserSetting,
    Verb,
    VerbBinding,
    WORKSPACE_ROLES,
    Workspace,
    WorkspaceMember,
    WorkflowDefinition,
    WorkflowPromotion,
    WorkItem,
    WorkStatus,
    utcnow,
)
from boltrig.models.errors import SchemaValidationError
from boltrig.models.work import RunCheckpoint


class InMemoryStore(ChannelStoreMem):
    """In-memory Store (offline + test). Domain methods live in partial mixins
    (e.g. ``ChannelStoreMem``), composed here for one public method surface."""
    """A complete, async, dict-backed Store. Satisfies ``store.base.Store``."""

    def __init__(self) -> None:
        self._nouns: dict[tuple[str, str], Noun] = {}
        self._verbs: dict[tuple[str, str], Verb] = {}
        self._bindings: dict[tuple[str, str], VerbBinding] = {}
        self._perms: dict[str, TenantPermissions] = {}
        self._adapters: dict[tuple[str, str], AdapterRecord] = {}
        self._skills: dict[tuple[str, str], Skill] = {}
        self._caps: dict[tuple[str, str], AgentCapability] = {}
        self._workflows: dict[tuple[str, str], WorkflowDefinition] = {}
        self._workflow_promotions: dict[tuple[str, str], WorkflowPromotion] = {}
        self._endpoints: dict[tuple[str, str], ModelEndpoint] = {}
        self._work: dict[tuple[str, str], WorkItem] = {}
        self._hitl: dict[tuple[str, str], HITLRequest] = {}
        self._hitl_resp: dict[tuple[str, str], HITLResponse] = {}
        self._audit: dict[str, list[AuditEvent]] = {}
        self._budgets: dict[tuple[str, str], Budget] = {}
        self._idem: dict[tuple[str, str], dict] = {}
        self._creds: dict[tuple[str, str], dict] = {}
        self._convs: dict[tuple[str, str], Conversation] = {}
        self._messages: dict[str, list[ConversationMessage]] = {}
        # Append-only derived compaction summaries, keyed by conversation id.
        self._summaries: dict[str, list[ConversationSummary]] = {}
        self._revisions: list[ConfigRevision] = []
        self._rev_seq = 0
        self._eval_cases: dict[tuple[str, str], EvalCase] = {}
        self._eval_runs: list[EvalRun] = []
        self._notif: dict[tuple[str, str], NotificationPref] = {}
        self._personal: dict[tuple[str, str], PersonalAgent] = {}
        self._memory: list[MemoryItem] = []
        # Round Five: structured memory governance (facts/ingestions/erasures).
        self._mem_facts: dict[tuple[str, str], MemoryFact] = {}
        self._mem_ingest: dict[tuple[str, str], MemoryIngestion] = {}
        self._mem_erase: list[MemoryErasure] = []
        # Round Four: users, tokens, invitations, settings, sessions.
        self._users: dict[tuple[str, str], User] = {}
        self._pats: dict[tuple[str, str], PersonalAccessToken] = {}
        self._invites: dict[tuple[str, str], UserInvitation] = {}
        self._settings: dict[tuple[str, str, str], UserSetting] = {}
        self._sessions: dict[tuple[str, str], UserSession] = {}
        # First-party password credentials ([2026] VJS-COUNTY 7, D4): kept apart
        # from the user identity row so the hash never rides in a User view/export.
        self._password_creds: dict[tuple[str, str], str] = {}
        # Channels (decision 0003): channels keyed by id (cross-tenant lookup on
        # the inbound path), bindings + pairings keyed per-tenant.
        self._channels: dict[str, Channel] = {}
        self._chan_bindings: dict[tuple[str, str], ChannelBinding] = {}
        self._chan_pairings: dict[tuple[str, str], ChannelPairing] = {}
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
        self._workspace_members: dict[tuple[str, str], WorkspaceMember] = {}

    # --- registry ---
    async def get_noun(self, tenant_id, noun_id):
        return self._nouns.get((tenant_id, noun_id))

    async def get_verb(self, tenant_id, verb_id):
        return self._verbs.get((tenant_id, verb_id))

    async def list_verbs(self, tenant_id, noun_id=None):
        out = [v for (t, _), v in self._verbs.items() if t == tenant_id]
        if noun_id is not None:
            out = [v for v in out if v.noun_id == noun_id]
        return out

    async def get_binding(self, tenant_id, verb_id):
        return self._bindings.get((tenant_id, verb_id))

    async def upsert_noun(self, noun):
        self._nouns[(noun.tenant_id, noun.id)] = noun

    async def upsert_verb(self, verb):
        self._verbs[(verb.tenant_id, verb.id)] = verb

    async def upsert_binding(self, binding):
        self._bindings[(binding.tenant_id, binding.verb_id)] = binding

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

    async def upsert_skill(self, skill):
        self._skills[(skill.tenant_id, skill.id)] = skill

    async def get_skill(self, tenant_id, skill_id):
        return self._skills.get((tenant_id, skill_id))

    async def list_skills(self, tenant_id):
        return [s for (t, _), s in self._skills.items() if t == tenant_id]

    async def upsert_capability(self, cap):
        self._caps[(cap.tenant_id, cap.name)] = cap

    async def list_capabilities(self, tenant_id):
        return [c for (t, _), c in self._caps.items() if t == tenant_id]

    async def upsert_workflow(self, wf):
        self._workflows[(wf.tenant_id, wf.id)] = wf

    async def list_workflows(self, tenant_id):
        return [w for (t, _), w in self._workflows.items() if t == tenant_id]

    async def upsert_workflow_promotion(self, promotion):
        self._workflow_promotions[(promotion.tenant_id, promotion.workflow_id)] = promotion

    async def get_workflow_promotion(self, tenant_id, workflow_id):
        return self._workflow_promotions.get((tenant_id, workflow_id))

    async def list_workflow_promotions(self, tenant_id):
        return [p for (t, _), p in self._workflow_promotions.items() if t == tenant_id]

    async def upsert_model_endpoint(self, ep):
        self._endpoints[(ep.tenant_id, ep.id)] = ep

    async def get_model_endpoint(self, tenant_id, ep_id):
        return self._endpoints.get((tenant_id, ep_id))

    # --- work items ---
    async def create_work_item(self, item):
        self._work[(item.tenant_id, item.id)] = item

    async def get_work_item(self, tenant_id, item_id):
        return self._work.get((tenant_id, item_id))

    async def update_work_item(self, item):
        self._work[(item.tenant_id, item.id)] = item

    async def list_work_items(
        self, tenant_id, status=None, parent_id=None, departments=None,
        limit=None, cursor=None,
    ):
        out = [w for (t, _), w in self._work.items() if t == tenant_id]
        if status is not None:
            out = [w for w in out if w.status == status]
        if parent_id is not None:
            out = [w for w in out if w.parent_id == parent_id]
        if departments is not None:  # row-level department scope (US-IAM-02)
            allowed = set(departments)
            out = [w for w in out if w.owner_member in allowed]
        # Keyset pagination on the stable id (M7 / SEC-69): order by id, drop
        # everything up to and including the cursor, then take the clamped page.
        # Mirrors the Postgres ORDER BY id / id > cursor / LIMIT contract.
        out.sort(key=lambda w: w.id)
        if cursor is not None:
            out = [w for w in out if w.id > cursor]
        if limit is not None:
            out = out[: clamp_work_page(limit)]
        return out

    async def claim_work_item(self, tenant_id, worker_id, lease_seconds):
        # atomic pending -> in_flight claim with a lease (US-FLT-05). No await
        # between the scan and the write, so it is atomic under cooperative
        # scheduling (mirrors consume_hitl). Insertion order stands in for the
        # Postgres ORDER BY created_at (oldest first).
        now = utcnow()
        for (t, _), item in self._work.items():
            if t != tenant_id:
                continue
            claimable = item.status == WorkStatus.PENDING or (
                item.status == WorkStatus.IN_FLIGHT
                and item.lease_expires_at is not None
                and item.lease_expires_at < now
            )
            if not claimable:
                continue
            item.status = WorkStatus.IN_FLIGHT
            item.lease_owner = worker_id
            item.lease_expires_at = now + timedelta(seconds=lease_seconds)
            item.attempts += 1
            return item
        return None

    async def try_increment_fanout(self, tenant_id, tree_id, counter, n, cap):
        # atomic capped increment (US-EXE-07): all-or-nothing, no await between
        # the read and the write.
        key = (tenant_id, tree_id, counter)
        new_value = self._fanout.get(key, 0) + n
        if new_value > cap:
            return False
        self._fanout[key] = new_value
        return True

    # --- run checkpoints (Beat 3 resume seam) ---
    async def upsert_checkpoint(
        self, tenant_id, run_id, step, status, output=None, hitl_request_id=None
    ):
        self._checkpoints[(tenant_id, run_id, step)] = RunCheckpoint(
            tenant_id=tenant_id, run_id=run_id, step=step, status=status,
            output=output, hitl_request_id=hitl_request_id, updated_at=utcnow(),
        )

    async def list_checkpoints(self, tenant_id, run_id):
        out = [
            c for (t, r, _), c in self._checkpoints.items()
            if t == tenant_id and r == run_id
        ]
        # oldest-first with a step tiebreak, matching the Postgres ORDER BY.
        return sorted(out, key=lambda c: (c.updated_at, c.step))

    # --- server-side run cancellation ([2026] VJS-COUNTY 6) ---
    async def request_run_cancel(self, tenant_id, run_id, requested_by):
        # Idempotent marker (D2): the first request wins, a re-request is a no-op
        # so the original requester is never overwritten. Durable for the process
        # lifetime (the Postgres row is durable across restarts).
        self._cancels.setdefault((tenant_id, run_id), requested_by)

    async def is_run_cancel_requested(self, tenant_id, run_id):
        return (tenant_id, run_id) in self._cancels

    # --- hitl ---
    async def create_hitl_request(self, req):
        self._hitl[(req.tenant_id, req.id)] = req

    async def get_hitl_request(self, tenant_id, req_id):
        return self._hitl.get((tenant_id, req_id))

    async def list_pending_hitl(self, tenant_id):
        return [
            r
            for (t, _), r in self._hitl.items()
            if t == tenant_id and r.status == HITLStatus.PENDING
        ]

    async def answer_hitl(self, resp):
        self._hitl_resp[(resp.tenant_id, resp.id)] = resp
        req = self._hitl.get((resp.tenant_id, resp.request_id))
        if req is None:
            return None
        req.status = HITLStatus.ANSWERED
        return req

    async def get_hitl_response(self, tenant_id, request_id):
        for resp in self._hitl_resp.values():
            if resp.tenant_id == tenant_id and resp.request_id == request_id:
                return resp
        return None

    async def consume_hitl(self, tenant_id, request_id):
        # atomic ANSWERED -> CONSUMED (single-use). No await between the check and
        # the write, so it is atomic under cooperative scheduling.
        req = self._hitl.get((tenant_id, request_id))
        if req is None or req.status != HITLStatus.ANSWERED:
            return False
        req.status = HITLStatus.CONSUMED
        return True

    # --- audit ---
    async def audit_head(self, tenant_id):
        chain = self._audit.get(tenant_id, [])
        if not chain:
            return (0, None)
        last = chain[-1]
        return (last.seq or 0, last.hash)

    async def audit_append(self, event):
        self._audit.setdefault(event.tenant_id, []).append(event)

    async def audit_query(self, tenant_id, run_id=None, limit=200):
        chain = list(self._audit.get(tenant_id, []))
        if run_id is not None:
            chain = [e for e in chain if e.run_id == run_id or e.parent_run_id == run_id]
        return chain[-limit:]

    # --- budgets ---
    async def get_budget(self, tenant_id, scope_id):
        return self._budgets.get((tenant_id, scope_id))

    def set_budget(self, budget: Budget) -> None:
        self._budgets[(budget.tenant_id, budget.id)] = budget

    async def list_budgets(self, tenant_id):
        return [b for (t, _), b in self._budgets.items() if t == tenant_id]

    async def consume_budget(self, tenant_id, scope_id, tokens, micros):
        """Reserve budget. Returns False (without spending) if a hard-stop budget
        would be exceeded; True otherwise. The read-modify-write has no await
        between steps, so it is atomic under cooperative scheduling."""
        b = self._budgets.get((tenant_id, scope_id))
        if b is None:
            return True  # no budget configured for this scope -> unmetered
        new_tokens = b.spent_tokens + max(0, tokens)
        new_micros = b.spent_micros + max(0, micros)
        over = (b.token_limit is not None and new_tokens > b.token_limit) or (
            b.cost_limit_micros is not None and new_micros > b.cost_limit_micros
        )
        if over and b.hard_stop:
            return False
        self._budgets[(tenant_id, scope_id)] = replace(
            b, spent_tokens=new_tokens, spent_micros=new_micros
        )
        return True

    async def reconcile_budget(self, tenant_id, scope_id, delta_tokens, delta_micros):
        """Post-run cost true-up (FR-COST-03): apply a SIGNED delta to the scope,
        each accumulator floored at 0. No hard-stop gate (this corrects a call that
        already ran). No budget row for the scope -> no-op. The read-modify-write
        has no await between steps, so it is atomic under cooperative scheduling
        (mirrors consume_budget)."""
        b = self._budgets.get((tenant_id, scope_id))
        if b is None:
            return  # no budget configured for this scope -> unmetered
        new_tokens = max(0, b.spent_tokens + delta_tokens)
        new_micros = max(0, b.spent_micros + delta_micros)
        self._budgets[(tenant_id, scope_id)] = replace(
            b, spent_tokens=new_tokens, spent_micros=new_micros
        )

    async def reserve_budgets_atomic(self, tenant_id, reservations):
        """Transactional multi-scope reserve (audit H4, Phase 6, FR-COST-05):
        all-or-nothing debit across every scope in ``reservations``. Compute every
        debit first; if ANY hard-stop scope lacks headroom, apply NONE and return
        False; otherwise apply them all and return True. A scope with no budget row
        is a no-op (unmetered), mirroring consume_budget. The whole compute-then-apply
        has no await between steps, so it is atomic under cooperative scheduling - two
        concurrent reserves can never interleave into a partial debit."""
        # Aggregate per scope so a scope named twice is locked and debited once
        # (its amounts summed), matching the postgres FOR UPDATE that locks a row
        # once. Negative amounts are floored to 0 (a refund is reconcile's job).
        agg: dict[str, tuple[int, int]] = {}
        for scope_id, tokens, micros in reservations:
            t, m = agg.get(scope_id, (0, 0))
            agg[scope_id] = (t + max(0, tokens), m + max(0, micros))
        # Phase 1: compute every debit + hard-stop check; touch nothing yet.
        planned: list[tuple[str, Budget, int, int]] = []
        for scope_id, (tokens, micros) in agg.items():
            b = self._budgets.get((tenant_id, scope_id))
            if b is None:
                continue  # unmetered scope -> skip (no-op)
            new_tokens = b.spent_tokens + tokens
            new_micros = b.spent_micros + micros
            over = (b.token_limit is not None and new_tokens > b.token_limit) or (
                b.cost_limit_micros is not None and new_micros > b.cost_limit_micros
            )
            if over and b.hard_stop:
                return False  # all-or-nothing: nothing has been applied
            planned.append((scope_id, b, new_tokens, new_micros))
        # Phase 2: apply every debit (no await above, so this is atomic).
        for scope_id, b, new_tokens, new_micros in planned:
            self._budgets[(tenant_id, scope_id)] = replace(
                b, spent_tokens=new_tokens, spent_micros=new_micros
            )
        return True

    # --- idempotency ---
    async def idempotency_get(self, tenant_id, key):
        return self._idem.get((tenant_id, key))

    async def idempotency_put(self, tenant_id, key, result):
        self._idem.setdefault((tenant_id, key), result)

    # --- credential references ---
    async def get_credential_ref(self, tenant_id, cred_id):
        return self._creds.get((tenant_id, cred_id))

    async def set_credential_ref(self, tenant_id: str, cred_id: str, ref: dict) -> None:
        self._creds[(tenant_id, cred_id)] = ref

    # --- conversations ---
    async def create_conversation(self, conv):
        self._convs[(conv.tenant_id, conv.id)] = conv

    async def get_conversation(self, tenant_id, conv_id):
        return self._convs.get((tenant_id, conv_id))

    async def list_conversations(self, tenant_id, user_id):
        return self._owned_conversations(tenant_id, user_id)

    def _owned_conversations(self, tenant_id, user_id):
        # Owner scope (SEC-25) + stable ordering: updated_at DESC with an id ASC
        # tiebreak. Python's sort is stable, so sorting by id first then by
        # updated_at (reverse) leaves ties ordered by ascending id deterministically.
        out = [
            c for (t, _), c in self._convs.items()
            if t == tenant_id and c.user_id == user_id
        ]
        out.sort(key=lambda c: c.id)
        out.sort(key=lambda c: c.updated_at, reverse=True)
        return out

    @staticmethod
    def _page(rows, limit, offset):
        # A stable window over an already-ordered list: the slice plus the next
        # offset (None once the list is exhausted). Mirrors the postgres LIMIT/OFFSET.
        start = max(0, offset)
        window = rows[start:start + limit]
        nxt = start + limit if start + limit < len(rows) else None
        return window, nxt

    async def list_conversations_page(self, tenant_id, user_id, *, limit, offset=0):
        return self._page(self._owned_conversations(tenant_id, user_id), limit, offset)

    async def search_conversations(self, tenant_id, user_id, query, *, limit, offset=0):
        # Owner-scoped substring search (US-CONV-10): only the caller's own
        # conversations are ever considered, so another user's thread can never
        # surface. A conversation matches on its title OR any LIVE (non-superseded,
        # [2026] VJS-COUNTY 4) message content; the snippet is the matched live
        # message content, or None when only the title matched.
        needle = (query or "").casefold()
        matches: list[tuple] = []
        for conv in self._owned_conversations(tenant_id, user_id):
            snippet = None
            if not needle or (conv.title and needle in conv.title.casefold()):
                matches.append((conv, None))
                continue
            for m in self._messages.get(conv.id, []):
                if (
                    m.tenant_id == tenant_id
                    and m.superseded_by is None  # a superseded turn is never a live hit
                    and m.content
                    and needle in m.content.casefold()
                ):
                    snippet = m.content
                    break
            if snippet is not None:
                matches.append((conv, snippet))
        return self._page(matches, limit, offset)

    async def update_conversation(self, conv):
        self._convs[(conv.tenant_id, conv.id)] = conv

    async def add_message(self, message):
        self._messages.setdefault(message.conversation_id, []).append(message)

    async def list_messages(self, tenant_id, conv_id):
        return [m for m in self._messages.get(conv_id, []) if m.tenant_id == tenant_id]

    async def mark_message_superseded(self, tenant_id, message_id, superseded_by):
        # Marker-only ([2026] VJS-COUNTY 4, D3): set superseded_by and NOTHING else,
        # so content/events/run_id/created_at stay immutable. Tenant-scoped.
        for msgs in self._messages.values():
            for m in msgs:
                if m.tenant_id == tenant_id and m.id == message_id:
                    m.superseded_by = superseded_by
                    return

    async def add_conversation_summary(self, summary):
        # Append-only ([2026] VJS-COUNTY 4 keeps message content frozen): a summary
        # is derived data, INSERTED here and never mutating any message row.
        self._summaries.setdefault(summary.conversation_id, []).append(summary)

    async def get_latest_conversation_summary(self, tenant_id, conversation_id):
        rows = [
            s for s in self._summaries.get(conversation_id, [])
            if s.tenant_id == tenant_id
        ]
        if not rows:
            return None
        # The latest summary covers the most messages (widest boundary); break ties
        # by created_at so a re-compaction's fresh row wins.
        return max(rows, key=lambda s: (s.covered_count, s.created_at))

    async def purge_closed_conversations(self, tenant_id, older_than):
        # M11 / SEC-74: hard-erase CLOSED conversations past the cutoff plus their
        # messages AND their derived summaries; audit rows are elsewhere and never
        # touched. Tenant-scoped.
        doomed = [
            c for (t, _), c in self._convs.items()
            if t == tenant_id
            and c.status == ConversationStatus.CLOSED
            and c.updated_at <= older_than
        ]
        for conv in doomed:
            self._convs.pop((conv.tenant_id, conv.id), None)
            self._messages.pop(conv.id, None)
            self._summaries.pop(conv.id, None)
        return len(doomed)

    # --- Round Three: config revisions ---
    async def add_config_revision(self, rev):
        self._rev_seq += 1
        rev.id = self._rev_seq
        self._revisions.append(rev)
        return rev

    async def list_config_revisions(self, tenant_id, kind, ref):
        return [
            r for r in self._revisions
            if r.tenant_id == tenant_id and r.kind == kind and r.ref == ref
        ]

    async def get_config_revision(self, tenant_id, rev_id):
        return next(
            (r for r in self._revisions if r.tenant_id == tenant_id and r.id == rev_id), None
        )

    # --- eval ---
    async def upsert_eval_case(self, case):
        self._eval_cases[(case.tenant_id, case.id)] = case

    async def get_eval_case(self, tenant_id, case_id):
        return self._eval_cases.get((tenant_id, case_id))

    async def list_eval_cases(self, tenant_id):
        return [c for (t, _), c in self._eval_cases.items() if t == tenant_id]

    async def add_eval_run(self, run):
        self._eval_runs.append(run)

    async def list_eval_runs(self, tenant_id, case_id=None):
        out = [r for r in self._eval_runs if r.tenant_id == tenant_id]
        out = [r for r in out if case_id is None or r.case_id == case_id]
        # newest-first, matching Postgres ORDER BY created_at DESC.
        return sorted(out, key=lambda r: r.created_at, reverse=True)

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

    # --- memory (scope-filtered, SEC-31) ---
    async def add_memory_item(self, item):
        self._memory.append(item)

    async def query_memory(self, tenant_id, owner_scopes, kind=None, limit=20):
        scopes = set(owner_scopes)
        out = [
            m for m in self._memory
            if m.tenant_id == tenant_id and m.owner_scope in scopes
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
            f for (t, _), f in self._mem_facts.items()
            if t == tenant_id and f.owner_scope in scopes
            and (kind is None or f.kind == kind)
        ]
        return sorted(out, key=lambda f: f.created_at, reverse=True)[:limit]

    async def delete_memory_fact(self, tenant_id, fact_id):
        self._mem_facts.pop((tenant_id, fact_id), None)

    async def add_memory_ingestion(self, ing):
        self._mem_ingest[(ing.tenant_id, ing.id)] = ing

    async def update_memory_ingestion(self, ing):
        self._mem_ingest[(ing.tenant_id, ing.id)] = ing

    async def list_memory_ingestions(self, tenant_id, limit=50):
        out = [i for (t, _), i in self._mem_ingest.items() if t == tenant_id]
        return sorted(out, key=lambda i: i.created_at, reverse=True)[:limit]

    async def add_memory_erasure(self, er):
        self._mem_erase.append(er)

    async def list_memory_erasures(self, tenant_id, limit=50):
        out = [e for e in self._mem_erase if e.tenant_id == tenant_id]
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
        self._pats[(pat.tenant_id, pat.id)] = pat

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
        return [
            p for (t, _), p in self._pats.items()
            if t == tenant_id and p.user_id == user_id
        ]

    async def update_pat(self, pat):
        self._pats[(pat.tenant_id, pat.id)] = pat

    # --- invitations (US-USR-02) ---
    async def add_invitation(self, inv):
        self._invites[(inv.tenant_id, inv.id)] = inv

    async def get_invitation(self, tenant_id, inv_id):
        return self._invites.get((tenant_id, inv_id))

    async def list_invitations(self, tenant_id):
        return [i for (t, _), i in self._invites.items() if t == tenant_id]

    async def find_pending_invitation(self, tenant_id, email):
        target = email.strip().lower()
        for (t, _), inv in self._invites.items():
            if t == tenant_id and inv.status == "pending" and inv.email.strip().lower() == target:
                return inv
        return None

    async def find_invitation_by_token_hash(self, tenant_id, token_hash):
        # First-party invite ([2026] VJS-COUNTY 7, D1): match a still-pending
        # invitation by its token hash, constant-time so the hash is not leaked by
        # timing. Tenant-scoped (the console tenant is bound by the caller).
        import hmac as _hmac

        for (t, _), inv in self._invites.items():
            if (
                t == tenant_id
                and inv.status == "pending"
                and inv.token_hash
                and _hmac.compare_digest(inv.token_hash, token_hash)
            ):
                return inv
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
        self._invites[(inv.tenant_id, inv.id)] = inv

    # --- first-party password credentials ([2026] VJS-COUNTY 7, D4) ---
    async def set_password_credential(self, tenant_id, user_id, password_hash):
        self._password_creds[(tenant_id, user_id)] = password_hash

    async def get_password_credential(self, tenant_id, user_id):
        return self._password_creds.get((tenant_id, user_id))

    # --- per-user settings (SET-*) ---
    async def upsert_user_setting(self, setting):
        self._settings[(setting.tenant_id, setting.user_id, setting.key)] = setting

    async def list_user_settings(self, tenant_id, user_id):
        return [
            s for (t, u, _), s in self._settings.items()
            if t == tenant_id and u == user_id
        ]

    # --- sessions (SET-70) ---
    async def add_session(self, session):
        self._sessions[(session.tenant_id, session.id)] = session

    async def list_sessions(self, tenant_id, user_id):
        return [
            s for (t, _), s in self._sessions.items()
            if t == tenant_id and s.user_id == user_id
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
        return [
            w for (t, _), w in self._workspaces.items() if t == tenant_id
        ]

    async def update_workspace(self, workspace):
        workspace.updated_at = utcnow()
        self._workspaces[(workspace.tenant_id, workspace.id)] = workspace

    async def add_org_member(self, member):
        self._org_members[(member.tenant_id, member.user_id)] = member

    async def remove_org_member(self, tenant_id, user_id):
        self._org_members.pop((tenant_id, user_id), None)

    async def list_org_members(self, tenant_id):
        return [
            m for (t, _), m in self._org_members.items() if t == tenant_id
        ]

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
        self._workspace_members[(member.workspace_id, member.user_id)] = member

    async def remove_workspace_member(self, tenant_id, workspace_id, user_id):
        m = self._workspace_members.get((workspace_id, user_id))
        if m is not None and m.tenant_id == tenant_id:
            self._workspace_members.pop((workspace_id, user_id), None)

    async def list_workspace_members(self, tenant_id, workspace_id):
        return [
            m for (w, _), m in self._workspace_members.items()
            if w == workspace_id and m.tenant_id == tenant_id
        ]

    async def list_workspaces_for_user(self, tenant_id, user_id):
        # Tenant-scoped: only workspaces in the bound tenant whose id the user is a
        # member of. Never crosses a tenant boundary.
        out = []
        for (w, u), m in self._workspace_members.items():
            if u == user_id and m.tenant_id == tenant_id:
                ws = self._workspaces.get((tenant_id, w))
                if ws is not None:
                    out.append(ws)
        return out
