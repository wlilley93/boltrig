"""Observability & Cost (OBS): cost, budgets, changelog, audit, runs (scope-filtered)."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from typing import Any
from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.observability.model_telemetry import model_telemetry
from ._shared import audit_authoring, can_author_route, dept_run_ids, scope_depts  # noqa: F401
from ._shared import platform_state

_STATUS_VALUES = {"ok", "degraded", "down", "unknown"}
_SECRET_KEY_PARTS = (
    "auth", "base_url", "bearer", "credential", "dsn", "key", "password",
    "secret", "token", "url",
)


def _status(value: Any) -> str:
    status = str(value or "unknown").strip().lower()
    return status if status in _STATUS_VALUES else "unknown"


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.lower()
        if lowered.startswith(("http://", "https://")):
            return None
        return value[:512]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            name = str(key)
            if any(part in name.lower() for part in _SECRET_KEY_PARTS):
                continue
            safe = _safe_value(item)
            if safe is not None:
                out[name] = safe
        return out
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return [_safe_value(item) for item in list(value)[:20]]
    return str(value)[:512]


def _component(item: Mapping[str, Any]) -> dict[str, Any]:
    meta = _safe_value(item.get("metadata") or item.get("detail") or {})
    return {
        "id": str(item.get("id") or item.get("name") or "unknown")[:80],
        "kind": str(item.get("kind") or item.get("type") or "component")[:40],
        "status": _status(item.get("status")),
        "message": str(item.get("message") or "")[:240],
        "updated_at": str(item.get("updated_at") or item.get("ts") or "")[:80],
        "metadata": meta if isinstance(meta, dict) else {},
    }


def _items(raw: Any, *, limit: int) -> list[dict[str, Any]]:
    if isinstance(raw, Mapping):
        raw = [{"id": key, **(value if isinstance(value, Mapping) else {"status": value})}
               for key, value in raw.items()]
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return [_component(item) for item in list(raw)[:limit] if isinstance(item, Mapping)]


async def _read_status_provider(provider: Any, p: Any) -> dict[str, Any]:
    if provider is None:
        return {}
    source = getattr(provider, "snapshot", provider)
    try:
        raw = source(tenant_id=p.tenant_id, workspace_id=p.active_workspace_id)
    except TypeError:
        try:
            raw = source(p)
        except TypeError:
            raw = source()
    if inspect.isawaitable(raw):
        raw = await raw
    return dict(raw or {}) if isinstance(raw, Mapping) else {}


def register(app, P, K) -> None:
    @app.get("/v1/platform/status")
    async def platform_status(request: Request, p=P) -> dict:
        raw = await _read_status_provider(platform_state(request).get("status"), p)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "tenant_id": p.tenant_id,
            "workspace_id": p.active_workspace_id,
            "components": _items(raw.get("components", []), limit=20),
            "runtimes": _items(raw.get("runtimes", []), limit=50),
        }

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
            if not (verb.startswith("authoring.") or verb.startswith("control.")):
                continue
            d = e.detail or {}
            rows.append(
                {
                    "ts": e.ts.isoformat(),
                    "actor": e.actor,
                    "action": (
                        verb[len("authoring.") :]
                        if verb.startswith("authoring.")
                        else verb
                    ),
                    "ref": d.get("id") or d.get("verb_id") or d.get("verb") or "",
                    "status": e.status,
                }
            )
        rows.reverse()
        return JSONResponse({"changes": rows[:200]})

    def _ws_visible(p, ws_id) -> bool:
        # Workspace fail-closed scoping ([2026] VJS-COUNTY 9, D5): a caller with an
        # active workspace sees ONLY org-wide (NULL) rows + its OWN workspace's rows,
        # never another workspace's. A caller with no active workspace sees the tenant
        # set (org boundary is tenant_id, already fenced). Mirrors workflow scoping.
        active = getattr(p, "active_workspace_id", None)
        if active is None:
            return True
        return ws_id is None or ws_id == active

    @app.get("/v1/model/telemetry")
    async def model_telemetry_route(
        request: Request, limit: int = 50, k=K, p=P
    ) -> dict:
        depts = scope_depts(p)
        allowed = await dept_run_ids(k, p.tenant_id, depts)
        events = await k.store.audit_query(p.tenant_id, limit=10_000)
        visible = [
            e for e in events
            if (
                allowed is None
                or e.run_id in allowed
                or e.parent_run_id in allowed
            ) and _ws_visible(p, e.workspace_id)
        ]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "tenant_id": p.tenant_id,
            "workspace_id": p.active_workspace_id,
            "scope": depts or "all",
            "models": model_telemetry(visible, limit=limit),
        }

    @app.get("/v1/audit/search")
    async def audit_search(request: Request, actor: str | None = None, verb: str | None = None,
                           run: str | None = None, resource: str | None = None,
                           since: str | None = None, until: str | None = None,
                           security: int = 0, event_type: str | None = None,
                           k=K, p=P) -> dict:
        # D5: filter by user (actor) / resource / date-range, and pivot to the
        # distinct SecurityEvent stream when ``security`` is set. Reads are
        # org/workspace-scoped fail-closed (tenant fence + the workspace filter).
        depts = scope_depts(p)
        allowed = await dept_run_ids(k, p.tenant_id, depts)

        # Parse the date bounds ONCE into datetimes and compare by value, not by
        # lexicographic string (a date-only until="2026-07-03" must include that
        # whole day, so it is treated as inclusive end-of-day; a naive string
        # compare "2026-07-03T06.." > "2026-07-03" wrongly excluded the day).
        def _parse_bound(raw: str | None, *, end_of_day: bool):
            if not raw:
                return None
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                return None
            if end_of_day and len(raw) == 10:  # a bare YYYY-MM-DD upper bound
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt

        since_dt = _parse_bound(since, end_of_day=False)
        until_dt = _parse_bound(until, end_of_day=True)

        def _in_range(ts) -> bool:
            if since_dt and ts < since_dt:
                return False
            if until_dt and ts > until_dt:
                return False
            return True

        if security:
            events = await k.store.security_query(
                p.tenant_id, event_type=event_type, limit=10_000
            )
            rows = []
            for e in events:
                if not _ws_visible(p, e.workspace_id):
                    continue
                if actor and e.actor != actor:
                    continue
                if resource and e.resource != resource:
                    continue
                if not _in_range(e.ts):
                    continue
                rows.append({"seq": e.seq, "ts": e.ts.isoformat(), "actor": e.actor,
                             "event_type": e.event_type.value, "reason": e.reason,
                             "workspace_id": e.workspace_id, "ip_address": e.ip_address,
                             "user_agent": e.user_agent, "resource": e.resource,
                             "resource_id": e.resource_id})
            return {"stream": "security", "results": rows[-500:], "scope": depts or "all"}

        events = await k.store.audit_query(p.tenant_id, run_id=run, limit=10_000)
        rows = []
        for e in events:
            if allowed is not None and (e.run_id not in allowed):
                continue  # SEC-33: another department's runs are not visible
            if not _ws_visible(p, e.workspace_id):
                continue
            if actor and e.actor != actor:
                continue
            if verb and e.verb != verb:
                continue
            if resource and e.resource != resource:
                continue
            if not _in_range(e.ts):
                continue
            rows.append({"seq": e.seq, "ts": e.ts.isoformat(), "actor": e.actor,
                         "verb": e.verb, "status": e.status, "run_id": e.run_id,
                         "workspace_id": e.workspace_id, "ip_address": e.ip_address,
                         "user_agent": e.user_agent, "resource": e.resource,
                         "resource_id": e.resource_id})
        return {"stream": "audit", "results": rows[-500:], "scope": depts or "all"}

    @app.get("/v1/audit/verify")
    async def audit_verify(request: Request, workspace: str | None = None, k=K, p=P) -> JSONResponse:
        # D5: recompute the audit hash chain + check the latest rollup anchor for the
        # tenant (optionally one workspace), and report intact/broken. Author/admin
        # gated like export (integrity status is not for every member, SEC-33). The
        # tenant fence makes this org-scoped fail-closed; a workspace narrows it.
        if not can_author_route(p):
            return JSONResponse(
                {"status": "denied", "reason": "author_or_admin_required"}, status_code=403
            )
        chain_ok, first_bad = await k.audit.verify(p.tenant_id)
        anchor_ok, anchor = await k.anchorer.verify_latest(
            p.tenant_id, workspace_id=workspace
        )
        sec_ok, sec_bad = await k.security.verify(p.tenant_id)
        return JSONResponse({
            "tenant_id": p.tenant_id,
            "workspace_id": workspace,
            "chain_intact": chain_ok,
            "chain_first_bad_seq": first_bad,
            "security_chain_intact": sec_ok,
            "security_first_bad_seq": sec_bad,
            "anchor_intact": anchor_ok,
            "anchor": None if anchor is None else {
                "id": anchor.id, "seq_start": anchor.seq_start, "seq_end": anchor.seq_end,
                "rollup_root_hash": anchor.rollup_root_hash,
                "anchored_at": anchor.anchored_at.isoformat(),
                "is_dev_fallback": anchor.is_dev_fallback,
                "rfc3161_token": anchor.rfc3161_token,
                "kms_signature": anchor.kms_signature,
            },
            "intact": bool(chain_ok and sec_ok and anchor_ok),
        })

    @app.post("/v1/audit/export")
    async def audit_export(request: Request, k=K, p=P) -> JSONResponse:
        if not can_author_route(p):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        events = await k.store.audit_query(p.tenant_id, limit=100_000)
        # Exporting the audit log is itself a compliance-relevant access to sensitive
        # records; audit the export (who exported, how many rows) so the chain records
        # its own disclosure. Keys-only, never the exported content.
        await audit_authoring(k, p, "audit.export", {"count": len(events)})
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
