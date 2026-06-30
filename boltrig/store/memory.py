"""In-memory Store implementation.

Used by tests and single-process dev. It is the reference implementation of the
Store contract: a Postgres-backed store must behave identically. Tenant scoping
is enforced on every method (keys are ``(tenant_id, id)`` tuples).
"""

from __future__ import annotations

from dataclasses import replace

from boltrig.models import (
    AdapterRecord,
    AgentCapability,
    AuditEvent,
    Budget,
    ConfigRevision,
    Conversation,
    ConversationMessage,
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
    Skill,
    TenantPermissions,
    User,
    UserInvitation,
    UserSession,
    UserSetting,
    Verb,
    VerbBinding,
    WorkflowDefinition,
    WorkItem,
)


class InMemoryStore:
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

    async def list_work_items(self, tenant_id, status=None, parent_id=None, departments=None):
        out = [w for (t, _), w in self._work.items() if t == tenant_id]
        if status is not None:
            out = [w for w in out if w.status == status]
        if parent_id is not None:
            out = [w for w in out if w.parent_id == parent_id]
        if departments is not None:  # row-level department scope (US-IAM-02)
            allowed = set(departments)
            out = [w for w in out if w.owner_member in allowed]
        return out

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

    # --- idempotency ---
    async def idempotency_get(self, tenant_id, key):
        return self._idem.get((tenant_id, key))

    async def idempotency_put(self, tenant_id, key, result):
        self._idem.setdefault((tenant_id, key), result)

    # --- credential references ---
    async def get_credential_ref(self, tenant_id, cred_id):
        return self._creds.get((tenant_id, cred_id))

    def set_credential_ref(self, tenant_id: str, cred_id: str, ref: dict) -> None:
        self._creds[(tenant_id, cred_id)] = ref

    # --- conversations ---
    async def create_conversation(self, conv):
        self._convs[(conv.tenant_id, conv.id)] = conv

    async def get_conversation(self, tenant_id, conv_id):
        return self._convs.get((tenant_id, conv_id))

    async def list_conversations(self, tenant_id, user_id):
        out = [
            c for (t, _), c in self._convs.items()
            if t == tenant_id and c.user_id == user_id
        ]
        return sorted(out, key=lambda c: c.updated_at, reverse=True)

    async def update_conversation(self, conv):
        self._convs[(conv.tenant_id, conv.id)] = conv

    async def add_message(self, message):
        self._messages.setdefault(message.conversation_id, []).append(message)

    async def list_messages(self, tenant_id, conv_id):
        return [m for m in self._messages.get(conv_id, []) if m.tenant_id == tenant_id]

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

    async def update_invitation(self, inv):
        self._invites[(inv.tenant_id, inv.id)] = inv

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

    async def update_session(self, session):
        self._sessions[(session.tenant_id, session.id)] = session
