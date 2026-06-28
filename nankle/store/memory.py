"""In-memory Store implementation.

Used by tests and single-process dev. It is the reference implementation of the
Store contract: a Postgres-backed store must behave identically. Tenant scoping
is enforced on every method (keys are ``(tenant_id, id)`` tuples).
"""

from __future__ import annotations

from dataclasses import replace

from nankle.models import (
    AdapterRecord,
    AgentCapability,
    AuditEvent,
    Budget,
    Conversation,
    ConversationMessage,
    EMPTY_GRANTS,
    HITLRequest,
    HITLResponse,
    HITLStatus,
    ModelEndpoint,
    Noun,
    Skill,
    TenantPermissions,
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
