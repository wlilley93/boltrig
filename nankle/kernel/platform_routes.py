"""Round Three HTTP surface: authoring studios, admin console, observability,
eval, personal agents, notifications, memory.

Every route is a thin layer over an existing service (C2): the registry, the
skills loader, the workflow library, the adapter generator/loader, the manifest
applier (AdminConfig), audit/cost/observability, and the two new services
(AdminConfig, EvalRunner). Authoring/admin require a permitting role and are
audited (C3, SEC-32); insight is scope-filtered (C5, SEC-33); anything that
executes runs the kernel chokepoint under the caller's grants (C4, SEC-29/30).

Services are read from ``app.state.platform`` (injected by the bootstrap, so the
kernel stays unaware of the fleet).
"""

from __future__ import annotations

import uuid

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from nankle.models import (
    ActionType,
    AuditEvent,
    Consequence,
    EvalCase,
    GrantMissing,
    NankleError,
    NotificationPref,
    PersonalAgent,
    Skill,
    TargetType,
    Verb,
    VerbBinding,
    utcnow,
)


def _require_author(p) -> None:
    from nankle.identity.rbac import can_author

    if not can_author(p.role):
        raise GrantMissing("authoring/admin not permitted for this role")


# Verb-name tokens that imply a mutating / destructive / outbound effect. A verb
# authored with such a name and no explicit consequence defaults to high, so the
# HITL gate engages by default (US-RTR-02/04, SEC-39: safe-by-default authoring).
_DESTRUCTIVE_TOKENS: frozenset[str] = frozenset({
    "delete", "remove", "destroy", "drop", "purge", "wipe", "erase",
    "send", "email", "post", "pay", "transfer", "charge", "refund",
    "deactivate", "revoke", "cancel", "terminate", "approve", "publish",
})


def safe_consequence(verb_id: str, explicit) -> str:
    """The consequence to store for an authored verb. An explicit low/high is
    honoured; otherwise a destructive/outbound verb name defaults to high (SEC-39)."""
    if explicit in ("low", "high"):
        return explicit
    tail = verb_id.rsplit(".", 1)[-1].lower()
    return "high" if any(tok in tail for tok in _DESTRUCTIVE_TOKENS) else "low"


async def _audit(kernel, p, action: str, detail: dict, status: str = "ok") -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=p.tenant_id, ts=utcnow(), actor=p.subject, actor_tier=p.actor_tier,
            action_type=ActionType.TOOL_CALL, verb=f"authoring.{action}", status=status,
            on_behalf_of=p.on_behalf_of, detail=detail,
        )
    )


async def _dept_run_ids(kernel, tenant: str, departments: list[str] | None) -> set[str] | None:
    """Run ids visible to a department-scoped caller (None = unrestricted)."""
    if departments is None:
        return None
    items = await kernel.list_work(tenant, departments=departments)
    return {w.hatchet_run_id for w in items if w.hatchet_run_id}


def register_platform_routes(app, *, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    def _platform(request: Request) -> dict:
        return getattr(request.app.state, "platform", {}) or {}

    # === Skill Studio (SKS) ===
    @app.get("/v1/skills")
    async def list_skills(k=K, p=P) -> dict:
        skills = [
            s for (t, _), s in getattr(k.store, "_skills", {}).items() if t == p.tenant_id
        ] if hasattr(k.store, "_skills") else []
        return {"skills": [{"id": s.id, "version": s.version, "extends": s.extends,
                            "tool_grants": s.tool_grants, "locale": s.locale} for s in skills]}

    @app.post("/v1/skills")
    async def upsert_skill(body: dict, k=K, p=P) -> JSONResponse:
        try:
            _require_author(p)
            skill = Skill(
                id=body["id"], tenant_id=p.tenant_id, version=body.get("version", "1.0.0"),
                prompt_fragment=body.get("prompt_fragment", ""),
                tool_grants=body.get("tool_grants", []),
                context_requirements=body.get("context_requirements", {}),
                extends=body.get("extends"), locale=body.get("locale", "en"),
            )
            await k.store.upsert_skill(skill)
            await _audit(k, p, "skill.upsert", {"id": skill.id, "version": skill.version})
            return JSONResponse({"status": "ok", "id": skill.id, "version": skill.version})
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    @app.post("/v1/skills/{skill_id}/test-spawn")
    async def test_spawn(skill_id: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # runs under the AUTHOR's grants (ceiling) - never escalates (SEC-29, C4)
        plat = _platform(request)
        spawner = plat.get("spawner")
        if spawner is None:
            return JSONResponse({"error": "spawner_unavailable"}, status_code=503)
        try:
            _require_author(p)
            ctx = p.context(extra=body.get("context", {}))
            result = await spawner.spawn(
                p.tenant_id, body.get("task", f"test {skill_id}"), [skill_id], {}, ctx,
                partial_on_budget=True, grant_ceiling=p.grants,
            )
            await _audit(k, p, "skill.test_spawn", {"skill": skill_id, "run_id": result.get("run_id")})
            return JSONResponse(result)
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    # === Router authoring (RTR) ===
    @app.post("/v1/nouns")
    async def upsert_noun(body: dict, k=K, p=P) -> JSONResponse:
        from nankle.models import Noun

        try:
            _require_author(p)
            await k.store.upsert_noun(Noun(id=body["id"], tenant_id=p.tenant_id,
                                           description=body.get("description", ""),
                                           schema=body.get("schema", {})))
            await _audit(k, p, "noun.upsert", {"id": body["id"]})
            return JSONResponse({"status": "ok", "id": body["id"]})
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    @app.post("/v1/verbs")
    async def upsert_verb(body: dict, k=K, p=P) -> JSONResponse:
        try:
            _require_author(p)
            conseq = safe_consequence(body["id"], body.get("consequence"))
            verb = Verb(
                id=body["id"], tenant_id=p.tenant_id, noun_id=body["noun_id"],
                input_schema=body.get("input_schema", {}), output_schema=body.get("output_schema", {}),
                description=body.get("description", ""),
                consequence=Consequence(conseq),
            )
            await k.store.upsert_verb(verb)
            await _audit(k, p, "verb.upsert", {"id": verb.id, "consequence": conseq})
            return JSONResponse({"status": "ok", "id": verb.id, "consequence": conseq})
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    @app.post("/v1/verbs/{verb_id}/binding")
    async def set_binding(verb_id: str, body: dict, k=K, p=P) -> JSONResponse:
        try:
            _require_author(p)
            await k.store.upsert_binding(VerbBinding(
                verb_id=verb_id, tenant_id=p.tenant_id,
                target_type=TargetType(body["target_type"]), target_ref=body["target_ref"],
            ))
            await _audit(k, p, "binding.set", {"verb": verb_id, "target": body["target_ref"]})
            return JSONResponse({"status": "ok", "verb": verb_id})
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    # === Adapter Studio (ADS) ===
    @app.post("/v1/adapters/generate")
    async def gen_adapter(body: dict, k=K, p=P) -> JSONResponse:
        from nankle.adapters.generator import generate_adapter_from_spec

        try:
            _require_author(p)
            gen = generate_adapter_from_spec(body["spec"], adapter_id=body["adapter_id"])
            k.loader.register(p.tenant_id, gen)  # loaded but inert until activated
            await _audit(k, p, "adapter.generate", {"id": body["adapter_id"], "activated": False})
            return JSONResponse({"status": "ok", "id": gen.id, "activated": gen.activated,
                                 "verbs": [v.verb_id for v in gen.describe()]})
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    @app.get("/v1/adapters/{adapter_id}/source")
    async def adapter_source(adapter_id: str, request: Request, k=K, p=P) -> JSONResponse:
        adapter = await k.loader.get(p.tenant_id, adapter_id)
        if adapter is None or not hasattr(adapter, "render_source"):
            return JSONResponse({"error": "no_source"}, status_code=404)
        return JSONResponse({"id": adapter_id, "source": adapter.render_source()})

    @app.post("/v1/adapters/{adapter_id}/activate")
    async def activate_adapter(adapter_id: str, body: dict, k=K, p=P) -> JSONResponse:
        try:
            _require_author(p)
            adapter = await k.loader.get(p.tenant_id, adapter_id)
            if adapter is None:
                return JSONResponse({"error": "not_found"}, status_code=404)
            reviewer = body.get("reviewer") or p.subject
            if hasattr(adapter, "review_and_activate"):
                adapter.review_and_activate(reviewer)
            verbs = await k.registry.register_adapter_verbs(p.tenant_id, adapter)  # bind only now
            await _audit(k, p, "adapter.activate", {"id": adapter_id, "reviewer": reviewer})
            return JSONResponse({"status": "ok", "id": adapter_id, "verbs": verbs})
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    @app.post("/v1/mcp/servers")
    async def register_mcp_server(body: dict, k=K, p=P) -> JSONResponse:
        from nankle.adapters.mcp_consumer import McpConsumerAdapter

        try:
            _require_author(p)
            consumer = McpConsumerAdapter(body["id"], url=body.get("url"), token=body.get("token"))
            k.loader.register(p.tenant_id, consumer)  # inert pending review (SEC-22)
            await _audit(k, p, "mcp.register", {"id": body["id"], "activated": False})
            return JSONResponse({"status": "ok", "id": body["id"], "activated": False})
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    @app.get("/v1/adapters")
    async def adapter_inventory(k=K, p=P) -> dict:
        await k.loader.refresh_health()
        records = await k.store.list_adapters(p.tenant_id)
        return {"adapters": [{"id": a.id, "runtime": a.runtime, "version": a.version,
                              "source": a.source, "activated": a.activated,
                              "health": k.loader.health_of(p.tenant_id, a.id)} for a in records]}

    # === Workflow Studio (WFS) ===
    @app.get("/v1/workflows")
    async def list_workflows(k=K, p=P) -> dict:
        wfs = await k.store.list_workflows(p.tenant_id)
        return {"workflows": [{"id": w.id, "version": w.version, "source": w.source.value,
                              "intent_tags": w.intent_tags} for w in wfs]}

    @app.post("/v1/workflows")
    async def upsert_workflow(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        from nankle.models import WorkflowDefinition, WorkflowSource

        try:
            _require_author(p)
            wf = WorkflowDefinition(
                id=body["id"], tenant_id=p.tenant_id, version=body.get("version", "1.0.0"),
                source=WorkflowSource(body.get("source", "precreated")),
                definition=body.get("definition", {}), intent_tags=body.get("intent_tags", []),
            )
            await k.store.upsert_workflow(wf)
            await _audit(k, p, "workflow.upsert", {"id": wf.id})
            return JSONResponse({"status": "ok", "id": wf.id})
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    @app.post("/v1/workflows/{wf_id}/schedule")
    async def schedule_workflow(wf_id: str, body: dict, k=K, p=P) -> JSONResponse:
        from nankle.workflows.generator import schedule_spec

        try:
            _require_author(p)
            spec = schedule_spec(body["cron"], body.get("timezone", "UTC"))
            await _audit(k, p, "workflow.schedule", {"id": wf_id, "cron": body["cron"]})
            return JSONResponse({"status": "ok", "id": wf_id, "schedule": spec})
        except (NankleError, ValueError) as e:
            code = getattr(e, "status_code", 400)
            return JSONResponse({"status": "error", "reason": str(e)}, status_code=code)

    @app.post("/v1/workflows/{wf_id}/trigger")
    async def trigger_workflow(wf_id: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        lib = _platform(request).get("workflows")
        if lib is None:
            return JSONResponse({"error": "workflows_unavailable"}, status_code=503)
        try:
            desc = await lib.trigger(p.tenant_id, wf_id, body.get("inputs", {}))
            await _audit(k, p, "workflow.trigger", {"id": wf_id, "run_id": desc.get("run_id"),
                                                    "durable": desc.get("durable")})
            return JSONResponse(desc)
        except LookupError:
            return JSONResponse({"error": "unknown_workflow"}, status_code=404)

    @app.get("/v1/workflows/{wf_id}/runs")
    async def workflow_runs(wf_id: str, k=K, p=P) -> dict:
        events = await k.store.audit_query(p.tenant_id, limit=1000)
        runs = sorted({e.run_id for e in events if e.run_id})
        return {"workflow_id": wf_id, "runs": runs[:100]}

    # === Admin Console (ADM) ===
    @app.get("/v1/admin/config/{section}")
    async def get_config(section: str, request: Request, p=P) -> JSONResponse:
        admin = _platform(request).get("admin")
        if admin is None:
            return JSONResponse({"error": "admin_unavailable"}, status_code=503)
        if not _can(p):
            return JSONResponse({"status": "denied", "reason": "admin_forbidden"}, status_code=403)
        return JSONResponse({"section": section, "value": admin.section(section)})

    @app.put("/v1/admin/config/{section}")
    async def put_config(section: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        admin = _platform(request).get("admin")
        if admin is None:
            return JSONResponse({"error": "admin_unavailable"}, status_code=503)
        try:
            _require_author(p)
            rev = await admin.update_section(section, body.get("value"), p.subject)
            await _audit(k, p, "config.update", {"section": section, "revision": rev.id})
            return JSONResponse({"status": "ok", "section": section, "revision": rev.id})
        except (NankleError, ValueError) as e:
            code = getattr(e, "status_code", 400)
            return JSONResponse({"status": "error", "reason": str(e)}, status_code=code)

    @app.get("/v1/admin/config/{section}/history")
    async def config_history(section: str, request: Request, p=P) -> JSONResponse:
        admin = _platform(request).get("admin")
        if admin is None or not _can(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        revs = await admin.history(section)
        return JSONResponse({"section": section, "revisions": [
            {"id": r.id, "version": r.version, "actor": r.actor, "rolled_back": r.rolled_back,
             "created_at": r.created_at.isoformat()} for r in revs]})

    @app.post("/v1/admin/config/{section}/rollback")
    async def config_rollback(section: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        admin = _platform(request).get("admin")
        if admin is None:
            return JSONResponse({"error": "admin_unavailable"}, status_code=503)
        try:
            _require_author(p)
            value = await admin.rollback(section, int(body["revision_id"]), p.subject)
            await _audit(k, p, "config.rollback", {"section": section, "to": body["revision_id"]})
            return JSONResponse({"status": "ok", "section": section, "value": value})
        except (NankleError, ValueError) as e:
            code = getattr(e, "status_code", 400)
            return JSONResponse({"status": "error", "reason": str(e)}, status_code=code)

    @app.post("/v1/admin/config/export")
    async def config_export(request: Request, p=P) -> JSONResponse:
        admin = _platform(request).get("admin")
        if admin is None or not _can(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse({"manifest": admin.export_dict()})

    @app.get("/v1/admin/credentials")
    async def admin_credentials(request: Request, p=P) -> JSONResponse:
        admin = _platform(request).get("admin")
        if admin is None or not _can(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse({"credentials": admin.credential_refs()})  # refs only, never values

    # === Observability & Cost (OBS) - scope-filtered (SEC-33) ===
    @app.get("/v1/cost")
    async def cost(request: Request, k=K, p=P) -> dict:
        depts = _scope_depts(p)
        allowed = await _dept_run_ids(k, p.tenant_id, depts)
        events = await k.store.audit_query(p.tenant_id, limit=10_000)
        total = 0
        by_actor: dict[str, int] = {}
        for e in events:
            if allowed is not None and (e.run_id not in allowed):
                continue
            c = e.cost_micros or 0
            total += c
            by_actor[e.actor] = by_actor.get(e.actor, 0) + c
        return {"total_cost_micros": total, "by_actor": by_actor, "scope": depts or "all"}

    @app.get("/v1/audit/search")
    async def audit_search(request: Request, actor: str | None = None, verb: str | None = None,
                           run: str | None = None, k=K, p=P) -> dict:
        depts = _scope_depts(p)
        allowed = await _dept_run_ids(k, p.tenant_id, depts)
        events = await k.store.audit_query(p.tenant_id, run_id=run, limit=10_000)
        rows = []
        for e in events:
            if allowed is not None and (e.run_id not in allowed):
                continue  # SEC-33: another department's runs are not visible
            if actor and e.actor != actor:
                continue
            if verb and e.verb != verb:
                continue
            rows.append({"seq": e.seq, "ts": e.ts.isoformat(), "actor": e.actor,
                         "verb": e.verb, "status": e.status, "run_id": e.run_id})
        return {"results": rows[-500:], "scope": depts or "all"}

    @app.post("/v1/audit/export")
    async def audit_export(request: Request, k=K, p=P) -> JSONResponse:
        if not _can(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        events = await k.store.audit_query(p.tenant_id, limit=100_000)
        return JSONResponse({"format": "nankle-audit-v1", "count": len(events),
                             "events": [{"seq": e.seq, "ts": e.ts.isoformat(), "actor": e.actor,
                                         "verb": e.verb, "status": e.status, "run_id": e.run_id,
                                         "on_behalf_of": e.on_behalf_of} for e in events]})

    @app.get("/v1/runs")
    async def runs(request: Request, k=K, p=P) -> dict:
        depts = _scope_depts(p)
        items = await k.list_work(p.tenant_id, departments=depts)
        return {"runs": [{"run_id": w.hatchet_run_id, "work_item": w.id, "intent": w.intent,
                          "status": w.status.value, "owner": w.owner_member} for w in items
                         if w.hatchet_run_id]}

    # === Evaluation (EVAL) ===
    @app.post("/v1/eval/cases")
    async def create_case(body: dict, k=K, p=P) -> JSONResponse:
        try:
            _require_author(p)
            case = EvalCase(id=body.get("id") or uuid.uuid4().hex, tenant_id=p.tenant_id,
                            target_kind=body["target_kind"], target_ref=body["target_ref"],
                            input=body.get("input", {}), assertions=body.get("assertions", {}),
                            labels=body.get("labels", []))
            await k.store.upsert_eval_case(case)
            return JSONResponse({"status": "ok", "id": case.id})
        except NankleError as e:
            return JSONResponse({"status": "denied", "reason": e.reason}, status_code=e.status_code)

    @app.post("/v1/eval/run")
    async def run_eval(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        runner = _platform(request).get("eval")
        if runner is None:
            return JSONResponse({"error": "eval_unavailable"}, status_code=503)
        case = await k.store.get_eval_case(p.tenant_id, body["case_id"])
        if case is None:
            return JSONResponse({"error": "no_such_case"}, status_code=404)
        run = await runner.run_case(case, grants=p.grants, actor=p.subject)  # under caller grants
        return JSONResponse({"id": run.id, "passed": run.passed, "score": run.score,
                             "run_id": run.run_id, "detail": run.detail})

    @app.get("/v1/eval/runs")
    async def eval_runs(case_id: str | None = None, k=K, p=P) -> dict:
        runs = await k.store.list_eval_runs(p.tenant_id, case_id)
        return {"runs": [{"id": r.id, "case_id": r.case_id, "passed": r.passed,
                          "score": r.score, "run_id": r.run_id} for r in runs]}

    # === Personal agents (PA) - delegated-only (SEC-30) ===
    @app.post("/v1/me/agent")
    async def configure_personal_agent(body: dict, k=K, p=P) -> JSONResponse:
        agent = PersonalAgent(id=uuid.uuid4().hex, tenant_id=p.tenant_id, user_id=p.subject,
                              runtime=body.get("runtime", "pi-worker"), skills=body.get("skills", []))
        await k.store.upsert_personal_agent(agent)
        return JSONResponse({"status": "ok", "id": agent.id, "owner": p.subject})

    @app.post("/v1/me/agent/invoke")
    async def invoke_personal_agent(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        spawner = _platform(request).get("spawner")
        agent = await k.store.get_personal_agent(p.tenant_id, p.subject)
        if spawner is None or agent is None:
            return JSONResponse({"error": "no_personal_agent"}, status_code=404)
        # delegated-only: on-behalf-of the owner, capped by the owner's grants (SEC-30)
        ctx = p.context(extra=body.get("context", {}))
        from dataclasses import replace

        ctx = replace(ctx, on_behalf_of=p.subject)
        result = await spawner.spawn(p.tenant_id, body.get("message", ""), list(agent.skills),
                                     {}, ctx, partial_on_budget=True, grant_ceiling=p.grants)
        await _audit(k, p, "personal_agent.invoke", {"run_id": result.get("run_id")})
        return JSONResponse(result)

    # === Notifications (NOT) ===
    @app.get("/v1/notifications/prefs")
    async def get_prefs(k=K, p=P) -> dict:
        prefs = await k.store.list_notification_prefs(p.tenant_id)
        mine = [pr for pr in prefs if pr.scope_kind == "user" and pr.scope_ref == p.subject]
        return {"prefs": [{"id": pr.id, "event_type": pr.event_type, "channel": pr.channel,
                          "target": pr.target, "enabled": pr.enabled} for pr in mine]}

    @app.put("/v1/notifications/prefs")
    async def put_prefs(body: dict, k=K, p=P) -> JSONResponse:
        pref = NotificationPref(id=body.get("id") or uuid.uuid4().hex, tenant_id=p.tenant_id,
                                scope_kind=body.get("scope_kind", "user"),
                                scope_ref=body.get("scope_ref", p.subject),
                                event_type=body["event_type"], channel=body["channel"],
                                target=body.get("target"), enabled=body.get("enabled", True))
        await k.store.upsert_notification_pref(pref)
        return JSONResponse({"status": "ok", "id": pref.id})

    # === Memory (MEM, optional) - scope-filtered + residency (SEC-31) ===
    @app.post("/v1/memory/query")
    async def memory_query(body: dict, k=K, p=P) -> dict:
        from nankle.identity.rbac import memory_owner_scopes

        scopes = memory_owner_scopes(p.subject, p.role, p.scope)
        items = await k.store.query_memory(p.tenant_id, scopes, kind=body.get("kind"),
                                           limit=int(body.get("limit", 20)))
        return {"items": [{"id": m.id, "owner_scope": m.owner_scope, "kind": m.kind,
                           "content": m.content, "source_ref": m.source_ref} for m in items],
                "scopes": scopes}


def _can(p) -> bool:
    from nankle.identity.rbac import can_author

    return can_author(p.role)


def _scope_depts(p) -> list[str] | None:
    from nankle.identity.rbac import departments_for

    return departments_for(p.role, p.scope)
