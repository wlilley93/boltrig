"""Observability & Cost (OBS): cost, budgets, changelog, audit, runs (scope-filtered)."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from ._shared import can_author_route, dept_run_ids, scope_depts


def register(app, P, K) -> None:
    @app.get("/v1/cost")
    async def cost(request: Request, k=K, p=P) -> dict:
        depts = scope_depts(p)
        allowed = await dept_run_ids(k, p.tenant_id, depts)
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

    @app.get("/v1/budgets")
    async def budgets(request: Request, k=K, p=P) -> dict:
        # The tenant's budgets with live burn-down. Department-scoped budgets are
        # filtered to the caller's own departments (SEC-33); tenant + workflow
        # budgets are visible to anyone in the tenant.
        depts = scope_depts(p)
        out = []
        for b in await k.store.list_budgets(p.tenant_id):
            if b.scope_type == "department" and depts is not None and b.id not in depts:
                continue
            out.append(
                {
                    "id": b.id,
                    "scope_type": b.scope_type,
                    "window": b.window,
                    "hard_stop": b.hard_stop,
                    "token_limit": b.token_limit,
                    "spent_tokens": b.spent_tokens,
                    "cost_limit_micros": b.cost_limit_micros,
                    "spent_micros": b.spent_micros,
                }
            )
        return {"budgets": out, "scope": depts or "all"}

    @app.get("/v1/capabilities/changelog")
    async def capability_changelog(request: Request, k=K, p=P) -> JSONResponse:
        # A timeline of who changed capability (nouns / verbs / bindings / skills /
        # adapters / workflows / MCP) and when, read straight from the tamper-evident
        # audit log (authoring.* actions). Tenant-isolated; newest first. Gated to
        # authors/admins - the actor + change history is not for every tenant member
        # (SEC-33 consistency with cost/audit).
        if not can_author_route(p):
            return JSONResponse(
                {"status": "denied", "reason": "author_or_admin_required", "changes": []},
                status_code=403,
            )
        events = await k.store.audit_query(p.tenant_id, limit=2000)
        rows = []
        for e in events:
            verb = e.verb or ""
            if not verb.startswith("authoring."):
                continue
            d = e.detail or {}
            rows.append(
                {
                    "ts": e.ts.isoformat(),
                    "actor": e.actor,
                    "action": verb[len("authoring.") :],
                    "ref": d.get("id") or d.get("verb_id") or d.get("verb") or "",
                    "status": e.status,
                }
            )
        rows.reverse()
        return JSONResponse({"changes": rows[:200]})

    @app.get("/v1/audit/search")
    async def audit_search(request: Request, actor: str | None = None, verb: str | None = None,
                           run: str | None = None, k=K, p=P) -> dict:
        depts = scope_depts(p)
        allowed = await dept_run_ids(k, p.tenant_id, depts)
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
        if not can_author_route(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        events = await k.store.audit_query(p.tenant_id, limit=100_000)
        return JSONResponse({"format": "boltrig-audit-v1", "count": len(events),
                             "events": [{"seq": e.seq, "ts": e.ts.isoformat(), "actor": e.actor,
                                         "verb": e.verb, "status": e.status, "run_id": e.run_id,
                                         "on_behalf_of": e.on_behalf_of} for e in events]})

    @app.get("/v1/runs")
    async def runs(request: Request, k=K, p=P) -> dict:
        depts = scope_depts(p)
        items = await k.list_work(p.tenant_id, departments=depts)
        return {"runs": [{"run_id": w.hatchet_run_id, "work_item": w.id, "intent": w.intent,
                          "status": w.status.value, "owner": w.owner_member} for w in items
                         if w.hatchet_run_id]}
