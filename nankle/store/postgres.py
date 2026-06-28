"""PostgreSQL-backed Store (asyncpg). Satisfies ``store.base.Store`` (P0-1).

Mirrors ``InMemoryStore`` method for method so the kernel cannot tell which store
it runs on; the only difference is durability. Every query is scoped by
``tenant_id`` (SEC-08). JSONB columns round-trip as Python dict/list via a codec.
Schema is ``schema.sql`` (the single source of truth); the DDL is idempotent so
``connect(apply_schema=True)`` is safe to run on every boot.
"""

from __future__ import annotations

import json
from pathlib import Path

import asyncpg

from nankle.models import (
    AdapterHealth,
    AdapterRecord,
    AgentCapability,
    ActionType,
    AuditEvent,
    Budget,
    Consequence,
    Conversation,
    ConversationMessage,
    ConversationStatus,
    MessageRole,
    EMPTY_GRANTS,
    GrantSet,
    HITLRequest,
    HITLResponse,
    HITLStatus,
    HITLType,
    ModelEndpoint,
    Noun,
    RateLimit,
    Skill,
    TargetType,
    TenantPermissions,
    Urgency,
    Verb,
    VerbBinding,
    WorkflowDefinition,
    WorkflowSource,
    WorkItem,
    WorkStatus,
)

_SCHEMA = Path(__file__).with_name("schema.sql")


async def _init_conn(conn: asyncpg.Connection) -> None:
    # encode/decode JSONB as Python objects so dict/list params and columns just work
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


class PostgresStore:
    """A durable Store. Construct via ``await PostgresStore.connect(dsn)``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, *, apply_schema: bool = True) -> "PostgresStore":
        pool = await asyncpg.create_pool(dsn, init=_init_conn, min_size=1, max_size=10)
        store = cls(pool)
        if apply_schema:
            async with pool.acquire() as conn:
                await conn.execute(_SCHEMA.read_text(encoding="utf-8"))
        return store

    async def close(self) -> None:
        await self._pool.close()

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
                                  output_schema, consequence, identity_mode, degraded_mode)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 noun_id=EXCLUDED.noun_id, description=EXCLUDED.description,
                 input_schema=EXCLUDED.input_schema, output_schema=EXCLUDED.output_schema,
                 consequence=EXCLUDED.consequence, identity_mode=EXCLUDED.identity_mode,
                 degraded_mode=EXCLUDED.degraded_mode, updated_at=now()""",
            verb.id, verb.tenant_id, verb.noun_id, verb.description, verb.input_schema,
            verb.output_schema, verb.consequence.value, verb.identity_mode, verb.degraded_mode,
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

    async def upsert_skill(self, s: Skill):
        await self._pool.execute(
            """INSERT INTO skills (id, tenant_id, version, prompt_fragment, tool_grants,
                                   context_requirements, extends, locale)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, id, version) DO UPDATE SET
                 prompt_fragment=EXCLUDED.prompt_fragment, tool_grants=EXCLUDED.tool_grants,
                 context_requirements=EXCLUDED.context_requirements, extends=EXCLUDED.extends,
                 locale=EXCLUDED.locale, updated_at=now()""",
            s.id, s.tenant_id, s.version, s.prompt_fragment, s.tool_grants,
            s.context_requirements, s.extends, s.locale,
        )

    async def get_skill(self, tenant_id, skill_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM skills WHERE tenant_id=$1 AND id=$2 ORDER BY version DESC LIMIT 1",
            tenant_id, skill_id,
        )
        return _skill(row)

    async def upsert_capability(self, c: AgentCapability):
        await self._pool.execute(
            """INSERT INTO agent_capabilities (name, tenant_id, runtime, model_endpoint,
                                               supported_skills, max_depth, is_ephemeral, cost_tier)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id, name) DO UPDATE SET
                 runtime=EXCLUDED.runtime, model_endpoint=EXCLUDED.model_endpoint,
                 supported_skills=EXCLUDED.supported_skills, max_depth=EXCLUDED.max_depth,
                 is_ephemeral=EXCLUDED.is_ephemeral, cost_tier=EXCLUDED.cost_tier, updated_at=now()""",
            c.name, c.tenant_id, c.runtime, c.model_endpoint, c.supported_skills,
            c.max_depth, c.is_ephemeral, c.cost_tier,
        )

    async def list_capabilities(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM agent_capabilities WHERE tenant_id=$1", tenant_id
        )
        return [_capability(r) for r in rows]

    async def upsert_workflow(self, w: WorkflowDefinition):
        await self._pool.execute(
            """INSERT INTO workflow_definitions (id, tenant_id, version, source, definition,
                                                 intent_tags, origin_task)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (tenant_id, id, version) DO UPDATE SET
                 source=EXCLUDED.source, definition=EXCLUDED.definition,
                 intent_tags=EXCLUDED.intent_tags, origin_task=EXCLUDED.origin_task, updated_at=now()""",
            w.id, w.tenant_id, w.version, w.source.value, w.definition, w.intent_tags, w.origin_task,
        )

    async def list_workflows(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM workflow_definitions WHERE tenant_id=$1", tenant_id
        )
        return [_workflow(r) for r in rows]

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

    # --- work items -------------------------------------------------------
    async def create_work_item(self, w: WorkItem):
        await self._pool.execute(
            """INSERT INTO work_items (id, tenant_id, source, source_id, intent, confidence,
                                       convergent, status, owner_member, parent_id, hatchet_run_id,
                                       depth, on_behalf_of, constraints, raw)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 source=EXCLUDED.source, source_id=EXCLUDED.source_id, intent=EXCLUDED.intent,
                 confidence=EXCLUDED.confidence, convergent=EXCLUDED.convergent,
                 status=EXCLUDED.status, owner_member=EXCLUDED.owner_member,
                 parent_id=EXCLUDED.parent_id, hatchet_run_id=EXCLUDED.hatchet_run_id,
                 depth=EXCLUDED.depth, on_behalf_of=EXCLUDED.on_behalf_of,
                 constraints=EXCLUDED.constraints, raw=EXCLUDED.raw, updated_at=now()""",
            w.id, w.tenant_id, w.source, w.source_id, w.intent, w.confidence, w.convergent,
            w.status.value, w.owner_member, w.parent_id, w.hatchet_run_id, w.depth,
            w.on_behalf_of, w.constraints, w.raw,
        )

    async def get_work_item(self, tenant_id, item_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM work_items WHERE tenant_id=$1 AND id=$2", tenant_id, item_id
        )
        return _work(row)

    async def update_work_item(self, item: WorkItem):
        await self.create_work_item(item)  # upsert

    async def list_work_items(self, tenant_id, status=None, parent_id=None, departments=None):
        clauses = ["tenant_id=$1"]
        args: list = [tenant_id]
        if status is not None:
            args.append(status.value)
            clauses.append(f"status=${len(args)}")
        if parent_id is not None:
            args.append(parent_id)
            clauses.append(f"parent_id=${len(args)}")
        if departments is not None:
            # row-level department scope (US-IAM-02). owner_member encodes the dept.
            args.append(list(departments))
            clauses.append(f"owner_member = ANY(${len(args)}::text[])")
        rows = await self._pool.fetch(
            f"SELECT * FROM work_items WHERE {' AND '.join(clauses)}", *args
        )
        return [_work(r) for r in rows]

    # --- hitl -------------------------------------------------------------
    async def create_hitl_request(self, r: HITLRequest):
        await self._pool.execute(
            """INSERT INTO hitl_requests (id, tenant_id, run_id, work_item_id, type, urgency,
                                          context, question, options, assignee, status, timeout_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 status=EXCLUDED.status, updated_at=now()""",
            r.id, r.tenant_id, r.run_id, r.work_item_id, r.type.value, r.urgency.value,
            r.context, r.question, r.options, r.assignee, r.status.value, r.timeout_at,
        )

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
                await conn.execute(
                    """INSERT INTO hitl_responses (id, request_id, tenant_id, decision, notes,
                                                   respondent, responded_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7)
                       ON CONFLICT (tenant_id, id) DO NOTHING""",
                    resp.id, resp.request_id, resp.tenant_id, resp.decision, resp.notes,
                    resp.respondent, resp.responded_at,
                )
                row = await conn.fetchrow(
                    """UPDATE hitl_requests SET status=$3, updated_at=now()
                       WHERE tenant_id=$1 AND id=$2 RETURNING *""",
                    resp.tenant_id, resp.request_id, HITLStatus.ANSWERED.value,
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
                                      detail, prev_hash, hash)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)""",
            e.tenant_id, e.seq, e.ts, e.run_id, e.parent_run_id, e.actor, e.actor_tier, e.depth,
            e.action_type.value, e.noun, e.verb, e.target_adapter, e.on_behalf_of, e.status,
            e.latency_ms, e.tokens_used, e.cost_micros, e.skills_loaded, e.detail,
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

    # --- budgets ----------------------------------------------------------
    async def get_budget(self, tenant_id, scope_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM budgets WHERE tenant_id=$1 AND id=$2", tenant_id, scope_id
        )
        return _budget(row)

    async def set_budget(self, b: Budget) -> None:
        await self._pool.execute(
            """INSERT INTO budgets (id, tenant_id, scope_type, token_limit, cost_limit_micros,
                                    hard_stop, "window", spent_tokens, spent_micros)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 scope_type=EXCLUDED.scope_type, token_limit=EXCLUDED.token_limit,
                 cost_limit_micros=EXCLUDED.cost_limit_micros, hard_stop=EXCLUDED.hard_stop,
                 "window"=EXCLUDED."window", updated_at=now()""",
            b.id, b.tenant_id, b.scope_type, b.token_limit, b.cost_limit_micros,
            b.hard_stop, b.window, b.spent_tokens, b.spent_micros,
        )

    async def consume_budget(self, tenant_id, scope_id, tokens, micros):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
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

    # --- idempotency ------------------------------------------------------
    async def idempotency_get(self, tenant_id, key):
        row = await self._pool.fetchrow(
            "SELECT result FROM idempotency_keys WHERE tenant_id=$1 AND key=$2", tenant_id, key
        )
        return row["result"] if row else None

    async def idempotency_put(self, tenant_id, key, result):
        await self._pool.execute(
            """INSERT INTO idempotency_keys (tenant_id, key, result) VALUES ($1,$2,$3)
               ON CONFLICT (tenant_id, key) DO NOTHING""",
            tenant_id, key, result,
        )

    # --- credential references -------------------------------------------
    async def get_credential_ref(self, tenant_id, cred_id):
        row = await self._pool.fetchrow(
            "SELECT data, store, ref FROM credential_refs WHERE tenant_id=$1 AND id=$2",
            tenant_id, cred_id,
        )
        if row is None:
            return None
        return row["data"] or {"store": row["store"], "ref": row["ref"]}

    async def set_credential_ref(self, tenant_id, cred_id, ref: dict) -> None:
        await self._pool.execute(
            """INSERT INTO credential_refs (id, tenant_id, store, ref, data, expires_at)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 store=EXCLUDED.store, ref=EXCLUDED.ref, data=EXCLUDED.data,
                 expires_at=EXCLUDED.expires_at, updated_at=now()""",
            cred_id, tenant_id, ref.get("store", "env"), ref.get("ref", ""), ref,
            ref.get("expires_at"),
        )

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
               ORDER BY updated_at DESC""",
            tenant_id, user_id,
        )
        return [_conversation(r) for r in rows]

    async def update_conversation(self, c: Conversation):
        await self._pool.execute(
            """UPDATE conversations SET title=$3, status=$4, updated_at=$5
               WHERE tenant_id=$1 AND id=$2""",
            c.tenant_id, c.id, c.title, c.status.value, c.updated_at,
        )

    async def add_message(self, m: ConversationMessage):
        await self._pool.execute(
            """INSERT INTO conversation_messages
               (id, conversation_id, tenant_id, role, content, run_id, hitl_request_id, events, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            m.id, m.conversation_id, m.tenant_id, m.role.value, m.content, m.run_id,
            m.hitl_request_id, m.events, m.created_at,
        )

    async def list_messages(self, tenant_id, conv_id):
        rows = await self._pool.fetch(
            """SELECT * FROM conversation_messages WHERE tenant_id=$1 AND conversation_id=$2
               ORDER BY created_at ASC""",
            tenant_id, conv_id,
        )
        return [_message(r) for r in rows]


# --- row -> dataclass mappers (None-safe) ---------------------------------
def _noun(r):
    return None if r is None else Noun(
        id=r["id"], tenant_id=r["tenant_id"], description=r["description"] or "",
        schema=r["schema"] or {},
    )


def _verb(r):
    if r is None:
        return None
    return Verb(
        id=r["id"], tenant_id=r["tenant_id"], noun_id=r["noun_id"],
        input_schema=r["input_schema"], output_schema=r["output_schema"],
        description=r["description"] or "", consequence=Consequence(r["consequence"]),
        degraded_mode=r["degraded_mode"], identity_mode=r["identity_mode"],
    )


def _binding(r):
    if r is None:
        return None
    rl = r["rate_limit"]
    return VerbBinding(
        verb_id=r["verb_id"], tenant_id=r["tenant_id"],
        target_type=TargetType(r["target_type"]), target_ref=r["target_ref"],
        rate_limit=RateLimit(**rl) if rl else None,
    )


def _adapter(r):
    if r is None:
        return None
    return AdapterRecord(
        id=r["id"], tenant_id=r["tenant_id"], version=r["version"], runtime=r["runtime"],
        source=r["source"], module_ref=r["module_ref"], health=AdapterHealth(r["health"]),
        spec_ref=r["spec_ref"], created_by=r["created_by"], activated=r["activated"],
    )


def _skill(r):
    if r is None:
        return None
    return Skill(
        id=r["id"], tenant_id=r["tenant_id"], version=r["version"],
        prompt_fragment=r["prompt_fragment"], tool_grants=list(r["tool_grants"] or []),
        context_requirements=r["context_requirements"] or {}, extends=r["extends"],
        locale=r["locale"] or "en",
    )


def _capability(r):
    if r is None:
        return None
    return AgentCapability(
        name=r["name"], tenant_id=r["tenant_id"], runtime=r["runtime"],
        supported_skills=list(r["supported_skills"] or []), max_depth=r["max_depth"],
        is_ephemeral=r["is_ephemeral"], cost_tier=r["cost_tier"],
        model_endpoint=r["model_endpoint"],
    )


def _workflow(r):
    if r is None:
        return None
    return WorkflowDefinition(
        id=r["id"], tenant_id=r["tenant_id"], version=r["version"],
        source=WorkflowSource(r["source"]), definition=r["definition"],
        intent_tags=list(r["intent_tags"] or []), origin_task=r["origin_task"],
    )


def _endpoint(r):
    if r is None:
        return None
    return ModelEndpoint(
        id=r["id"], tenant_id=r["tenant_id"], kind=r["kind"], model=r["model"],
        base_url=r["base_url"], fallback=r["fallback"], data_class=r["data_class"],
    )


def _work(r):
    if r is None:
        return None
    return WorkItem(
        id=r["id"], tenant_id=r["tenant_id"], source=r["source"], intent=r["intent"],
        confidence=r["confidence"], convergent=r["convergent"], status=WorkStatus(r["status"]),
        source_id=r["source_id"], owner_member=r["owner_member"], parent_id=r["parent_id"],
        hatchet_run_id=r["hatchet_run_id"], depth=r["depth"], on_behalf_of=r["on_behalf_of"],
        constraints=r["constraints"] or {}, raw=r["raw"] or {},
    )


def _hitl_req(r):
    if r is None:
        return None
    return HITLRequest(
        id=r["id"], tenant_id=r["tenant_id"], run_id=r["run_id"], type=HITLType(r["type"]),
        urgency=Urgency(r["urgency"]), context=r["context"], question=r["question"],
        status=HITLStatus(r["status"]), work_item_id=r["work_item_id"],
        options=list(r["options"] or []), assignee=r["assignee"], timeout_at=r["timeout_at"],
    )


def _hitl_resp(r):
    if r is None:
        return None
    return HITLResponse(
        id=r["id"], request_id=r["request_id"], tenant_id=r["tenant_id"], decision=r["decision"],
        respondent=r["respondent"], responded_at=r["responded_at"], notes=r["notes"] or "",
    )


def _audit(r):
    if r is None:
        return None
    return AuditEvent(
        tenant_id=r["tenant_id"], ts=r["ts"], actor=r["actor"],
        action_type=ActionType(r["action_type"]), status=r["status"], run_id=r["run_id"],
        parent_run_id=r["parent_run_id"], actor_tier=r["actor_tier"], depth=r["depth"],
        noun=r["noun"], verb=r["verb"], target_adapter=r["target_adapter"],
        on_behalf_of=r["on_behalf_of"], latency_ms=r["latency_ms"], tokens_used=r["tokens_used"],
        cost_micros=r["cost_micros"], skills_loaded=list(r["skills_loaded"] or []),
        detail=r["detail"] or {}, seq=r["seq"], prev_hash=r["prev_hash"], hash=r["hash"],
    )


def _conversation(r):
    if r is None:
        return None
    return Conversation(
        id=r["id"], tenant_id=r["tenant_id"], user_id=r["user_id"], title=r["title"],
        status=ConversationStatus(r["status"]), created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _message(r):
    if r is None:
        return None
    return ConversationMessage(
        id=r["id"], conversation_id=r["conversation_id"], tenant_id=r["tenant_id"],
        role=MessageRole(r["role"]), content=r["content"], run_id=r["run_id"],
        hitl_request_id=r["hitl_request_id"], events=list(r["events"] or []),
        created_at=r["created_at"],
    )


def _budget(r):
    if r is None:
        return None
    return Budget(
        id=r["id"], tenant_id=r["tenant_id"], scope_type=r["scope_type"],
        token_limit=r["token_limit"], cost_limit_micros=r["cost_limit_micros"],
        hard_stop=r["hard_stop"], window=r["window"], spent_tokens=r["spent_tokens"],
        spent_micros=r["spent_micros"],
    )
