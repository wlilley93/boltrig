"""Observability & Cost (OBS): cost, budgets, changelog, audit, runs (scope-filtered)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.models.work import work_item_run_id
from boltrig.observability.model_telemetry import model_telemetry
from boltrig.store.base import DEFAULT_WORK_PAGE, MAX_OBSERVABILITY_PAGE, clamp_work_page
from ._shared import audit_authoring, can_author_route, scope_depts
from .audit_search import register as register_audit_search
from .platform_status import register as register_platform_status


def register(app, P, K) -> None:
    register_platform_status(app, P, K)
    _register_cost_routes(app, P, K)
    _register_changelog_routes(app, P, K)
    _register_model_telemetry_routes(app, P, K)
    register_audit_search(app, P, K)
    _register_audit_integrity_routes(app, P, K)
    _register_runs_routes(app, P, K)
    _register_run_topology_routes(app, P, K)


def _register_cost_routes(app, P, K) -> None:
    @app.get("/v1/cost")
    async def cost(request: Request, k=K, p=P) -> dict:
        depts = scope_depts(p)
        # Scoped + bounded in the store (SEC-69 idiom): the department/workspace
        # run-scope predicate and the event workspace filter run inside the
        # query under a clamped page, not load-then-filter in Python.
        events = await k.store.audit_query_scoped(
            p.tenant_id,
            departments=depts,
            workspace_id=p.active_workspace_id,
            limit=MAX_OBSERVABILITY_PAGE,
        )
        total = 0
        by_actor: dict[str, int] = {}
        for e in events:
            c = e.cost_micros or 0
            total += c
            by_actor[e.actor] = by_actor.get(e.actor, 0) + c
        return {"total_cost_micros": total, "by_actor": by_actor, "scope": depts or "all"}


def _register_changelog_routes(app, P, K) -> None:
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
            if not (verb.startswith("authoring.") or verb.startswith("control.")):
                continue
            d = e.detail or {}
            rows.append(
                {
                    "ts": e.ts.isoformat(),
                    "actor": e.actor,
                    "action": (
                        verb[len("authoring.") :] if verb.startswith("authoring.") else verb
                    ),
                    "ref": d.get("id") or d.get("verb_id") or d.get("verb") or "",
                    "status": e.status,
                }
            )
        rows.reverse()
        return JSONResponse({"changes": rows[:200]})


def _register_model_telemetry_routes(app, P, K) -> None:
    @app.get("/v1/model/telemetry")
    async def model_telemetry_route(request: Request, limit: int = 50, k=K, p=P) -> dict:
        depts = scope_depts(p)
        events = await k.store.audit_query_scoped(
            p.tenant_id,
            departments=depts,
            workspace_id=p.active_workspace_id,
            match_parent=True,
            limit=MAX_OBSERVABILITY_PAGE,
        )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "tenant_id": p.tenant_id,
            "workspace_id": p.active_workspace_id,
            "scope": depts or "all",
            "models": model_telemetry(events, limit=limit),
        }


def _register_audit_integrity_routes(app, P, K) -> None:
    @app.get("/v1/audit/verify")
    async def audit_verify(
        request: Request, workspace: str | None = None, k=K, p=P
    ) -> JSONResponse:
        # D5: recompute the audit hash chain + check the latest rollup anchor for the
        # tenant (optionally one workspace), and report intact/broken. Author/admin
        # gated like export (integrity status is not for every member, SEC-33). The
        # tenant fence makes this org-scoped fail-closed; a workspace narrows it.
        if not can_author_route(p):
            return JSONResponse(
                {"status": "denied", "reason": "author_or_admin_required"}, status_code=403
            )
        chain_ok, first_bad = await k.audit.verify(p.tenant_id)
        anchor_ok, anchor = await k.anchorer.verify_latest(p.tenant_id, workspace_id=workspace)
        sec_ok, sec_bad = await k.security.verify(p.tenant_id)
        return JSONResponse(
            {
                "tenant_id": p.tenant_id,
                "workspace_id": workspace,
                "chain_intact": chain_ok,
                "chain_first_bad_seq": first_bad,
                "security_chain_intact": sec_ok,
                "security_first_bad_seq": sec_bad,
                "anchor_intact": anchor_ok,
                "anchor": None
                if anchor is None
                else {
                    "id": anchor.id,
                    "seq_start": anchor.seq_start,
                    "seq_end": anchor.seq_end,
                    "rollup_root_hash": anchor.rollup_root_hash,
                    "anchored_at": anchor.anchored_at.isoformat(),
                    "is_dev_fallback": anchor.is_dev_fallback,
                    "rfc3161_token": anchor.rfc3161_token,
                    "kms_signature": anchor.kms_signature,
                },
                "intact": bool(chain_ok and sec_ok and anchor_ok),
            }
        )

    @app.post("/v1/audit/export")
    async def audit_export(request: Request, k=K, p=P) -> JSONResponse:
        if not can_author_route(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        events = await k.store.audit_query(p.tenant_id, limit=100_000)
        # Exporting the audit log is itself a compliance-relevant access to sensitive
        # records; audit the export (who exported, how many rows) so the chain records
        # its own disclosure. Keys-only, never the exported content.
        await audit_authoring(k, p, "audit.export", {"count": len(events)})
        return JSONResponse(
            {
                "format": "boltrig-audit-v1",
                "count": len(events),
                "events": [
                    {
                        "seq": e.seq,
                        "ts": e.ts.isoformat(),
                        "actor": e.actor,
                        "verb": e.verb,
                        "status": e.status,
                        "run_id": e.run_id,
                        "on_behalf_of": e.on_behalf_of,
                    }
                    for e in events
                ],
            }
        )


def _run_row(w) -> dict:
    """One /v1/runs row. `external_ref` is the GENERIC opaque source_id."""
    return {
        "run_id": work_item_run_id(w),
        "work_item": w.id,
        "intent": w.intent,
        "status": w.status.value,
        "owner": w.owner_member,
        "on_behalf_of": w.on_behalf_of,
        "source": w.source,
        "external_ref": w.source_id,
    }


def _register_runs_routes(app, P, K) -> None:
    @app.get("/v1/runs")
    async def runs(
        request: Request,
        limit: int = DEFAULT_WORK_PAGE,
        cursor: str | None = None,
        owner: str | None = None,
        on_behalf_of: str | None = None,
        label: str | None = None,
        source: str | None = None,
        external_ref: str | None = None,
        k=K,
        p=P,
    ) -> dict:
        depts = scope_depts(p)
        # SEC-69: bounded keyset page, same idiom as /v1/work. The RunScope
        # visible/hidden predicate (department + workspace, hidden-wins on a
        # shared run ref) runs INSIDE the store query under the clamped page -
        # no full work-table load per request. The next cursor is the last
        # item's id when the page came back full.
        #
        # G7 filters (owner/on_behalf_of/label/source/external_ref) NARROW the
        # already-scoped set inside the same query - they can only remove rows,
        # never widen visibility. `external_ref` matches the GENERIC opaque
        # source_id column (WorkItem.source + source_id), NOT any opbox matter
        # mirror: opbox stamps source='opbox', source_id=<matterId> at intake so
        # it can list a matter's runs without boltrig knowing what a matter is.
        page = clamp_work_page(limit)
        items = await k.store.list_run_items_scoped(
            p.tenant_id,
            departments=depts,
            workspace_id=p.active_workspace_id,
            owner=owner,
            on_behalf_of=on_behalf_of,
            label=label,
            source=source,
            external_ref=external_ref,
            limit=page,
            cursor=cursor,
        )
        next_cursor = items[-1].id if len(items) == page else None
        return {
            "runs": [_run_row(w) for w in items],
            "limit": page,
            "next_cursor": next_cursor,
            "filters": {
                "owner": owner,
                "on_behalf_of": on_behalf_of,
                "label": label,
                "source": source,
                "external_ref": external_ref,
            },
        }


def _register_run_topology_routes(app, P, K) -> None:
    @app.get("/v1/runs/{run_id}/topology", response_model=None)
    async def run_topology(run_id: str, request: Request, k=K, p=P) -> JSONResponse | dict:
        # G7 roster/subagent-topology: the durable CoS -> heads -> workers tree
        # under a root run, reconstructed from the WorkItem parent/child forest
        # (the live `subagent` chat frame is unbounded and settles no completion,
        # so it cannot be the roster source). Same strict dept + enforced-
        # workspace + hidden-wins visibility as the run list and audit tree: the
        # root must be visible and only visible descendants attach, so a hidden
        # parent is never revived by a visible child.
        from boltrig.kernel.run_access import visible_run_topology

        tree = await visible_run_topology(k.store, p, run_id)
        if tree is None:
            return JSONResponse({"error": "unknown_run"}, status_code=404)
        return tree
