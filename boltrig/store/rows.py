"""Row mappers for the PostgreSQL store (structural partial).

The asyncpg ``Record`` -> dataclass conversion helpers extracted from
``store/postgres.py`` to bring it under the structural floor. Every mapper is
None-safe: a missing ``fetchrow`` result maps to ``None``. ``PostgresStore``
imports them back, so the store's behaviour and public method surface are
unchanged - this is a pure structural relocation.
"""

from __future__ import annotations

from boltrig.models import (
    ActionType, AdapterHealth, AdapterRecord, AiConfig, AuditEvent,
    AuditRollupAnchor, Budget, ConfigRevision, Consequence, Conversation,
    ConversationMessage, ConversationStatus, ConversationSummary, EvalCase,
    EvalRun, HITLRequest, HITLResponse, HITLStatus, HITLType, IdempotencyMode,
    MemoryErasure, MemoryFact, MemoryIngestion, MemoryItem,
    MessageRole, ModelEndpoint, NotificationPref, Noun,
    Organisation, OrgMember, PersonalAccessToken, PersonalAgent,
    RateLimit, SecurityEvent, SecurityEventType, Skill, TargetType,
    TwoFactorChallenge, Urgency, User, UserInvitation, UserSession, UserSetting,
    UserTotp, Verb, VerbBinding, WorkflowDefinition,
    WorkflowSource, Workspace, WorkspaceMember,
)
from boltrig.models.work import RunCheckpoint

from .memory_projection_rows import _mem_projection as _mem_projection


# --- row -> dataclass mappers (None-safe) ---------------------------------
def _noun(r):
    return None if r is None else Noun(
        id=r["id"], tenant_id=r["tenant_id"], description=r["description"] or "",
        schema=r["schema"] or {}, is_active=bool(r["is_active"]),
    )


def _verb(r):
    if r is None:
        return None
    return Verb(
        id=r["id"], tenant_id=r["tenant_id"], noun_id=r["noun_id"],
        input_schema=r["input_schema"], output_schema=r["output_schema"],
        description=r["description"] or "", consequence=Consequence(r["consequence"]),
        degraded_mode=r["degraded_mode"], identity_mode=r["identity_mode"],
        idempotency_mode=IdempotencyMode(r["idempotency_mode"]), is_active=bool(r["is_active"]),
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
        description=(r["description"] if "description" in r else "") or "", is_active=bool(r["is_active"]),
    )


def _workflow(r):
    if r is None:
        return None
    return WorkflowDefinition(
        id=r["id"], tenant_id=r["tenant_id"], version=r["version"],
        source=WorkflowSource(r["source"]), definition=r["definition"],
        intent_tags=list(r["intent_tags"] or []), origin_task=r["origin_task"],
        workspace_id=r["workspace_id"],
    )


def _endpoint(r):
    if r is None:
        return None
    return ModelEndpoint(
        id=r["id"], tenant_id=r["tenant_id"], kind=r["kind"], model=r["model"],
        base_url=r["base_url"], fallback=r["fallback"], data_class=r["data_class"], is_active=bool(r["is_active"]),
    )


def _checkpoint(r):
    if r is None:
        return None
    return RunCheckpoint(
        tenant_id=r["tenant_id"], run_id=r["run_id"], step=r["step"], status=r["status"],
        output=r["output"], hitl_request_id=r["hitl_request_id"], updated_at=r["updated_at"],
    )


def _hitl_req(r):
    if r is None:
        return None
    return HITLRequest(
        id=r["id"], tenant_id=r["tenant_id"], run_id=r["run_id"], type=HITLType(r["type"]),
        urgency=Urgency(r["urgency"]), context=r["context"], question=r["question"],
        status=HITLStatus(r["status"]), work_item_id=r["work_item_id"],
        options=list(r["options"] or []), assignee=r["assignee"], timeout_at=r["timeout_at"],
        verb=r["verb"], requested_by=r["requested_by"],
        requested_on_behalf_of=r["requested_on_behalf_of"], request_fingerprint=r["request_fingerprint"], action_digest=r["action_digest"], workspace_id=r["workspace_id"], department_scope=None if r["department_scope"] is None else list(r["department_scope"]),
        secure=bool(r["secure"]), secure_purpose=r["secure_purpose"],
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
        detail=r["detail"] or {},
        ip_address=r["ip_address"], user_agent=r["user_agent"], resource=r["resource"],
        resource_id=r["resource_id"], workspace_id=r["workspace_id"],
        seq=r["seq"], prev_hash=r["prev_hash"], hash=r["hash"],
    )


def _security(r):
    if r is None:
        return None
    return SecurityEvent(
        tenant_id=r["tenant_id"], ts=r["ts"], event_type=SecurityEventType(r["event_type"]),
        reason=r["reason"], actor=r["actor"], actor_tier=r["actor_tier"],
        workspace_id=r["workspace_id"], ip_address=r["ip_address"], user_agent=r["user_agent"],
        resource=r["resource"], resource_id=r["resource_id"], on_behalf_of=r["on_behalf_of"],
        detail=r["detail"] or {}, seq=r["seq"], prev_hash=r["prev_hash"], hash=r["hash"],
    )


def _anchor(r):
    if r is None:
        return None
    return AuditRollupAnchor(
        id=r["id"], tenant_id=r["tenant_id"], workspace_id=r["workspace_id"],
        seq_start=r["seq_start"], seq_end=r["seq_end"], rollup_root_hash=r["rollup_root_hash"],
        anchored_at=r["anchored_at"], is_dev_fallback=r["is_dev_fallback"],
        rfc3161_token=r["rfc3161_token"], kms_signature=r["kms_signature"],
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
        attachments=list(r["attachments"] or []), superseded_by=r["superseded_by"],
        created_at=r["created_at"],
    )


def _summary(r):
    if r is None:
        return None
    return ConversationSummary(
        id=r["id"], conversation_id=r["conversation_id"], tenant_id=r["tenant_id"],
        up_to_message_id=r["up_to_message_id"], covered_count=r["covered_count"],
        summary=r["summary"], created_at=r["created_at"],
    )


def _revision(r):
    if r is None:
        return None
    return ConfigRevision(
        id=r["id"], tenant_id=r["tenant_id"], kind=r["kind"], ref=r["ref"],
        version=r["version"], payload=r["payload"], actor=r["actor"],
        created_at=r["created_at"], rolled_back=r["rolled_back"],
    )


def _eval_case(r):
    if r is None:
        return None
    return EvalCase(
        id=r["id"], tenant_id=r["tenant_id"], target_kind=r["target_kind"],
        target_ref=r["target_ref"], input=r["input"], assertions=r["assertions"],
        labels=list(r["labels"] or []), is_active=r["is_active"],
    )


def _eval_run(r):
    if r is None:
        return None
    return EvalRun(
        id=r["id"], tenant_id=r["tenant_id"], case_id=r["case_id"], passed=r["passed"],
        score=r["score"], run_id=r["run_id"], detail=r["detail"] or {},
        created_at=r["created_at"],
    )


def _notif(r):
    if r is None:
        return None
    return NotificationPref(
        id=r["id"], tenant_id=r["tenant_id"], scope_kind=r["scope_kind"],
        scope_ref=r["scope_ref"], event_type=r["event_type"], channel=r["channel"],
        target=r["target"], enabled=r["enabled"],
    )


def _personal(r):
    if r is None:
        return None
    return PersonalAgent(
        id=r["id"], tenant_id=r["tenant_id"], user_id=r["user_id"], runtime=r["runtime"],
        skills=list(r["skills"] or []), enabled=r["enabled"],
    )


def _mem_fact(r):
    if r is None:
        return None
    return MemoryFact(
        id=r["id"], tenant_id=r["tenant_id"], owner_scope=r["owner_scope"],
        engine_ref=r["engine_ref"], kind=r["kind"], source_kind=r["source_kind"],
        source_ref=r["source_ref"], data_class=r["data_class"], content=r["content"] or "",
        created_at=r["created_at"], redacted=r["redacted"],
    )


def _mem_ingestion(r):
    if r is None:
        return None
    return MemoryIngestion(
        id=r["id"], tenant_id=r["tenant_id"], source_kind=r["source_kind"],
        source_ref=r["source_ref"], owner_scope=r["owner_scope"], status=r["status"],
        hatchet_run_id=r["hatchet_run_id"], facts_added=r["facts_added"],
        screened=r["screened"], detail=r["detail"] or {}, created_at=r["created_at"],
    )


def _mem_erasure(r):
    if r is None:
        return None
    return MemoryErasure(
        id=r["id"], tenant_id=r["tenant_id"], requested_by=r["requested_by"],
        target=r["target"], scope=r["scope"], engine_confirmed=r["engine_confirmed"],
        transcript_handled=r["transcript_handled"], facts_removed=r["facts_removed"],
        created_at=r["created_at"], completed_at=r["completed_at"],
    )


def _user(r):
    if r is None:
        return None
    return User(
        id=r["id"], tenant_id=r["tenant_id"], email=r["email"],
        display_name=r["display_name"], groups=list(r["groups"] or []), role=r["role"],
        scope=r["scope"] or {}, status=r["status"], source=r["source"],
        source_group=r["source_group"], last_seen_at=r["last_seen_at"],
        created_at=r["created_at"],
        # `.get`-style read, not r["..."]: a database that has not yet run 0039
        # has no such column, and a KeyError here would take down every user read
        # rather than the one feature the column serves ([2026] VJS-COUNTY 8, D7).
        must_change_password=bool(
            r["must_change_password"] if "must_change_password" in r.keys() else False
        ),
    )


def _pat(r):
    if r is None:
        return None
    return PersonalAccessToken(
        id=r["id"], tenant_id=r["tenant_id"], user_id=r["user_id"], name=r["name"],
        token_hash=r["token_hash"], scope=list(r["scope"] or []), created_at=r["created_at"],
        expires_at=r["expires_at"], last_used_at=r["last_used_at"], revoked=r["revoked"],
    )


def _invitation(r):
    if r is None:
        return None
    return UserInvitation(
        id=r["id"], tenant_id=r["tenant_id"], email=r["email"],
        intended_role=r["intended_role"], intended_scope=r["intended_scope"] or {},
        invited_by=r["invited_by"], created_at=r["created_at"], expires_at=r["expires_at"],
        status=r["status"],
        token_hash=(r["token_hash"] if "token_hash" in r.keys() else None),
        workspace_id=(r["workspace_id"] if "workspace_id" in r.keys() else None),
        provision_workspace_name=(
            r["provision_workspace_name"] if "provision_workspace_name" in r.keys() else None
        ),
        provision_org_name=(
            r["provision_org_name"] if "provision_org_name" in r.keys() else None
        ),
    )


def _setting(r):
    if r is None:
        return None
    return UserSetting(
        tenant_id=r["tenant_id"], user_id=r["user_id"], key=r["key"], value=r["value"],
        updated_at=r["updated_at"],
    )


def _session(r):
    if r is None:
        return None
    return UserSession(
        id=r["id"], tenant_id=r["tenant_id"], user_id=r["user_id"], client=r["client"],
        created_at=r["created_at"], last_seen_at=r["last_seen_at"], revoked=r["revoked"],
        token_hash=(r["token_hash"] if "token_hash" in r.keys() else None),
        expires_at=(r["expires_at"] if "expires_at" in r.keys() else None),
        csrf_token=(r["csrf_token"] if "csrf_token" in r.keys() else None),
        active_workspace_id=(
            r["active_workspace_id"] if "active_workspace_id" in r.keys() else None
        ),
        active_org_id=(
            r["active_org_id"] if "active_org_id" in r.keys() else None
        ),
    )


def _user_totp(r):
    if r is None:
        return None
    return UserTotp(
        tenant_id=r["tenant_id"], user_id=r["user_id"], secret_ref=r["secret_ref"],
        enrolled=r["enrolled"], created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _tfa_challenge(r):
    if r is None:
        return None
    return TwoFactorChallenge(
        tenant_id=r["tenant_id"], token_hash=r["token_hash"], user_id=r["user_id"],
        expires_at=r["expires_at"], created_at=r["created_at"],
    )


def _org(r):
    if r is None:
        return None
    return Organisation(
        id=r["id"], name=r["name"], slug=r["slug"], settings=r["settings"] or {},
        allow_own_ai_keys=r["allow_own_ai_keys"],
        require_two_factor=r["require_two_factor"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _workspace(r):
    if r is None:
        return None
    return Workspace(
        id=r["id"], tenant_id=r["tenant_id"], name=r["name"], slug=r["slug"],
        settings=r["settings"] or {}, status=r["status"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _org_member(r):
    if r is None:
        return None
    return OrgMember(
        user_id=r["user_id"], tenant_id=r["tenant_id"], role=r["role"],
        created_at=r["created_at"],
    )


def _workspace_member(r):
    if r is None:
        return None
    return WorkspaceMember(
        user_id=r["user_id"], workspace_id=r["workspace_id"],
        tenant_id=r["tenant_id"], role=r["role"],
        permissions=r["permissions"] or {}, created_at=r["created_at"],
    )


def _ai_config(r):
    if r is None:
        return None
    return AiConfig(
        tenant_id=r["tenant_id"], level=r["level"], scope_id=r["scope_id"],
        provider=r["provider"], model=r["model"], credential_ref=r["credential_ref"],
        base_url=r["base_url"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def _memory(r):
    if r is None:
        return None
    return MemoryItem(
        id=r["id"], tenant_id=r["tenant_id"], owner_scope=r["owner_scope"], kind=r["kind"],
        content=r["content"], embedding=r["embedding"], source_ref=r["source_ref"],
        data_class=r["data_class"], created_at=r["created_at"],
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
