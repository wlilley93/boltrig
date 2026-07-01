"""The kernel HTTP surface (FastAPI) - a thin transport over the engine.

Multiple front doors (HTTP here, plus in-process callers and, later, MCP) are
dumb mouths over one smart engine: no policy lives in this module. Identity is
authenticated-by-construction (K-3): a pluggable ``principal_resolver`` turns a
verified bearer into a ``Principal``; handlers never read tenant/identity from
the request body.
"""

from __future__ import annotations

import inspect
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from boltrig.models import (
    BoltrigError,
    DegradedMode,
    GrantSet,
    HITLType,
    InvocationContext,
    PendingHuman,
)

from . import Kernel


@dataclass
class Principal:
    """The authenticated caller. Built by the principal resolver from a bearer."""

    tenant_id: str
    subject: str
    grants: GrantSet = field(default_factory=lambda: GrantSet.of([]))
    role: str = "agent"
    actor_tier: str = "ephemeral"
    on_behalf_of: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)  # visibility scope (US-IAM-02)

    def context(self, *, run_id=None, parent_run_id=None, depth=0, skills=(), extra=None):
        return InvocationContext(
            tenant_id=self.tenant_id,
            run_id=run_id,
            parent_run_id=parent_run_id,
            depth=depth,
            on_behalf_of=self.on_behalf_of,
            grants=self.grants,
            actor=self.subject,
            actor_tier=self.actor_tier,
            skills_loaded=tuple(skills),
            extra=dict(extra or {}),
        )


PrincipalResolver = Callable[[Request], Awaitable[Principal]]


def _error_envelope(e: BoltrigError) -> dict:
    """The one canonical kernel error body: a 403 is a denial, anything else is
    an error. Every transport surface returns this shape so a client parses one
    envelope, never per-route variants."""
    return {"status": "denied" if e.status_code == 403 else "error", "reason": e.reason}


async def _dev_principal(request: Request) -> Principal:
    """Development resolver. Trusts headers; replace with OIDC/SAML in prod
    (see ``boltrig.identity.auth``). SEC-01 requires real auth in production."""
    from boltrig.identity.rbac import grants_for_scope

    h = request.headers
    role = h.get("x-boltrig-role", "org-admin")
    departments = [d for d in h.get("x-boltrig-departments", "").split(",") if d]
    grants_hdr = [g for g in h.get("x-boltrig-grants", "").split(",") if g]
    verbs = [v for v in h.get("x-boltrig-verbs", "").split(",") if v]
    scope: dict[str, Any] = {"all": True} if role == "org-admin" else {
        "departments": departments, "verbs": verbs,
    }
    # Grants priority: an explicit grants header (simulate an ephemeral) wins;
    # otherwise derive from role/scope so dev discovery is not empty (US-KER-05).
    if grants_hdr:
        grants = GrantSet.of(grants_hdr)
    elif role == "org-admin":
        grants = GrantSet.of(["*"])
    else:
        grants = grants_for_scope(scope)
    return Principal(
        tenant_id=h.get("x-boltrig-tenant", "default"),
        subject=h.get("x-boltrig-subject", "dev"),
        grants=grants,
        role=role,
        actor_tier=h.get("x-boltrig-tier", "human"),
        on_behalf_of=h.get("x-boltrig-obo"),
        scope=scope,
    )


# --- request/response bodies (Pydantic) -------------------------------------
class InvokeBody(BaseModel):
    noun: str
    verb: str
    params: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    approval_id: str | None = None


class SpawnBody(BaseModel):
    task: str
    skills: list[str] = Field(default_factory=list)
    prefer: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class RespondBody(BaseModel):
    decision: str
    notes: str = ""


class ChatBody(BaseModel):
    message: str
    conversation_id: str | None = None


# Spawner seam: the fleet attaches an async (principal, body) -> dict callable.
Spawner = Callable[[Principal, SpawnBody], Awaitable[dict]]
KernelFactory = Callable[[], Awaitable[Kernel]]
SpawnerFactory = Callable[[Kernel], Spawner]


def _get_kernel(request: Request) -> Kernel:
    """Resolve the live kernel from app state (set synchronously for a prebuilt
    kernel, or built on the serving loop by the lifespan for the factory path)."""
    return request.app.state.kernel


def create_app(
    kernel: Kernel | None = None,
    *,
    principal_resolver: PrincipalResolver | None = None,
    spawner: Spawner | None = None,
    kernel_factory: KernelFactory | None = None,
    spawner_factory: SpawnerFactory | None = None,
    chat_service: Any = None,
    chat_factory: Callable[[Kernel], Any] | None = None,
    platform: dict[str, Any] | None = None,
    platform_factory: Callable[[Kernel], dict[str, Any]] | None = None,
) -> FastAPI:
    """Build the ASGI app. Pass a prebuilt ``kernel`` (tests/in-process), or a
    ``kernel_factory`` that the lifespan runs on the SERVING loop so loop-bound
    resources (the asyncpg pool) attach to the loop that handles requests.

    ``chat_service`` (or ``chat_factory(kernel)``) supplies the conversational
    service; it is injected (the kernel stays unaware of the fleet)."""
    resolver = principal_resolver
    if resolver is None:
        # SEC-60/IAM-09: the header-trusting dev resolver is the dangerous default.
        # Refuse to fall back to it under any production signal - a deployment that
        # builds the app without a resolver must not silently get full-trust auth.
        from boltrig.api.bootstrap import production_signal

        sig = production_signal()
        if sig is not None:
            raise RuntimeError(
                f"FATAL: create_app() received no principal_resolver with a production "
                f"signal ({sig}); the header-trusting dev resolver must never be the "
                "default in production. Pass an OIDC/PAT resolver (or use "
                "bootstrap.select_principal_resolver())."
            )
        resolver = _dev_principal

    def _chat_for(k: Kernel):
        if chat_service is not None:
            return chat_service
        return chat_factory(k) if chat_factory is not None else None

    def _platform_for(k: Kernel) -> dict[str, Any]:
        if platform is not None:
            return platform
        return platform_factory(k) if platform_factory is not None else {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not hasattr(app.state, "kernel"):
            if kernel_factory is None:
                raise RuntimeError("create_app needs a kernel or a kernel_factory")
            built = await kernel_factory()
            app.state.kernel = built
            app.state.spawner = spawner_factory(built) if spawner_factory else spawner
            app.state.chat = _chat_for(built)
            app.state.platform = _platform_for(built)
        try:
            yield
        finally:
            store = getattr(getattr(app.state, "kernel", None), "store", None)
            close = getattr(store, "close", None)
            if close is not None:  # PostgresStore: drain the pool on shutdown
                result = close()
                if inspect.isawaitable(result):
                    await result

    app = FastAPI(title="Boltrig Kernel", version="0.1.0", lifespan=lifespan)
    # Edge/web hardening (Batch 1 WEB-02/03/05/06, RES-01): security headers, CORS
    # allowlist, Host validation, request-body cap. Additive middleware; no route
    # or kernel change.
    from .web_security import install_security

    install_security(app)

    # One central envelope for any BoltrigError that reaches the transport
    # uncaught: a route no longer needs its own try/except to render the
    # canonical {status, reason} body (it still may, e.g. to add PendingHuman /
    # DegradedMode handling). This is the single source of the error shape.
    @app.exception_handler(BoltrigError)
    async def _on_boltrig_error(_request: Request, exc: BoltrigError) -> JSONResponse:
        return JSONResponse(_error_envelope(exc), status_code=exc.status_code)

    # Prebuilt kernel is set synchronously so it works even without lifespan
    # (Starlette TestClient used without a context manager).
    if kernel is not None:
        app.state.kernel = kernel
        app.state.spawner = spawner
        app.state.chat = _chat_for(kernel)
        app.state.platform = _platform_for(kernel)

    async def principal(request: Request) -> Principal:
        from boltrig.identity.tokens import looks_like_pat, resolve_pat_principal
        from boltrig.store.postgres import set_current_tenant

        # Headless parity (US-HEAD-02, SEC-37): a personal access token bearer is
        # resolved to its owner's effective grants (PAT scope ∩ owner's current
        # grants) and flows through the same chokepoint as the site. Anything else
        # falls through to the configured resolver (OIDC in prod, headers in dev).
        auth = request.headers.get("authorization", "")
        scheme, _, value = auth.partition(" ")
        token = value.strip() if scheme.lower() == "bearer" else None
        if token and looks_like_pat(token):
            p = await resolve_pat_principal(_get_kernel(request).store, token)
            if p is None:
                raise HTTPException(status_code=401, detail="invalid or expired access token")
        else:
            p = await resolver(request)
        # RLS-live: bind this request's tenant so the _RlsPool scopes every DB call
        # (a no-op for the in-memory store and when RLS is off).
        set_current_tenant(p.tenant_id)
        return p

    @app.get("/healthz")
    async def healthz(k: Kernel = Depends(_get_kernel)) -> dict:
        health = await k.loader.refresh_health()
        return {"status": "ok", "adapters": {f"{t}/{a}": h for (t, a), h in health.items()}}

    @app.post("/v1/invoke")
    async def invoke(
        body: InvokeBody,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ) -> JSONResponse:
        ctx = p.context(
            run_id=body.context.get("run_id"),
            parent_run_id=body.context.get("parent_run_id"),
            depth=int(body.context.get("depth", 0)),
            skills=body.context.get("skills_loaded", ()),
        )
        try:
            output = await k.invoke(
                body.noun, body.verb, body.params, ctx,
                idempotency_key=body.idempotency_key, approval_id=body.approval_id,
            )
            return JSONResponse({"status": "ok", "output": output})
        except PendingHuman as e:
            return JSONResponse(
                {"status": "pending_human", "hitl_request_id": e.hitl_request_id},
                status_code=202,
            )
        except DegradedMode as e:
            return JSONResponse({"status": "degraded", "output": e.output}, status_code=503)
        # any other BoltrigError -> the central exception handler (canonical envelope)

    @app.post("/v1/mcp")
    async def mcp(
        body: dict, request: Request, k: Kernel = Depends(_get_kernel)
    ) -> JSONResponse:
        # Two ways in, both run the same chokepoint:
        #  - a run-scoped token (the fleet/sidecar path, Round Two): scopes to a run.
        #  - a user bearer / PAT (US-HEAD-02): scopes to the user's effective grants.
        run_token = request.headers.get("x-boltrig-mcp-token")
        if run_token is None:
            auth = request.headers.get("authorization", "")
            scheme, _, value = auth.partition(" ")
            bearer = value.strip() if scheme.lower() == "bearer" else None
            if k.mcp.is_run_token(bearer):  # a run token presented as a bearer
                run_token = bearer
        if run_token is not None:
            return JSONResponse(await k.mcp.handle(run_token, body))
        # user-authenticated MCP: resolve the caller (PAT or configured resolver)
        # and advertise/scope tools to their effective grants (no weak path, SEC-37).
        p = await principal(request)
        return JSONResponse(await k.mcp.handle_user(p, body))

    @app.post("/v1/chat")
    async def chat(
        body: ChatBody, request: Request, p: Principal = Depends(principal)
    ):
        chat_svc = getattr(request.app.state, "chat", None)
        if chat_svc is None:
            return JSONResponse({"error": "chat_unavailable"}, status_code=503)
        gen = chat_svc.handle_turn(
            tenant_id=p.tenant_id, user_id=p.subject, role=p.role,
            message=body.message, conversation_id=body.conversation_id,
        )
        # RBAC / access errors happen before the first event and propagate to the
        # central exception handler (canonical envelope) - the stream hasn't begun.
        try:
            first = await gen.__anext__()
        except StopAsyncIteration:
            first = None

        async def stream():
            if first is not None:
                yield f"data: {json.dumps(first)}\n\n"
            async for event in gen:
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/v1/conversations")
    async def conversations(request: Request, p: Principal = Depends(principal)) -> dict:
        chat_svc = getattr(request.app.state, "chat", None)
        if chat_svc is None:
            return {"conversations": []}
        convs = await chat_svc.list_conversations(p.tenant_id, p.subject)
        return {
            "conversations": [
                {
                    "id": c.id, "title": c.title, "status": c.status.value,
                    "updated_at": c.updated_at.isoformat(),
                }
                for c in convs
            ]
        }

    @app.get("/v1/conversations/{conversation_id}")
    async def conversation(
        conversation_id: str, request: Request, p: Principal = Depends(principal)
    ):
        chat_svc = getattr(request.app.state, "chat", None)
        if chat_svc is None:
            return JSONResponse({"error": "chat_unavailable"}, status_code=503)
        # ConversationForbidden (403, SEC-25) propagates to the central handler.
        messages = await chat_svc.get_messages(
            p.tenant_id, p.subject, p.role, conversation_id
        )
        if messages is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return {
            "messages": [
                {
                    "id": m.id, "role": m.role.value, "content": m.content,
                    "run_id": m.run_id, "hitl_request_id": m.hitl_request_id,
                    "events": m.events, "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ]
        }

    @app.get("/v1/capabilities")
    async def capabilities(
        noun: str | None = None,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ) -> dict:
        return await k.discover(p.tenant_id, p.context(), noun)

    @app.post("/v1/spawn")
    async def spawn(
        body: SpawnBody, request: Request, p: Principal = Depends(principal)
    ) -> JSONResponse:
        spawner_fn = getattr(request.app.state, "spawner", None)
        if spawner_fn is None:
            return JSONResponse({"error": "spawner_unavailable"}, status_code=503)
        # a BoltrigError propagates to the central handler (canonical envelope -
        # was the odd {"error": ...} shape before this consolidation)
        return JSONResponse(await spawner_fn(p, body))

    @app.get("/v1/hitl")
    async def list_hitl(
        k: Kernel = Depends(_get_kernel), p: Principal = Depends(principal)
    ) -> dict:
        pending = await k.hitl.list_pending(p.tenant_id)
        return {
            "requests": [
                {
                    "id": r.id, "type": r.type.value, "urgency": r.urgency.value,
                    "question": r.question, "context": r.context, "options": r.options,
                    "work_item_id": r.work_item_id, "status": r.status.value,
                }
                for r in pending
            ]
        }

    @app.post("/v1/hitl/{request_id}/respond")
    async def respond(
        request_id: str,
        body: RespondBody,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ) -> dict:
        req = await k.hitl.get(p.tenant_id, request_id)
        if req is None:
            raise HTTPException(status_code=404, detail="unknown request")
        # SEC-14: an approval is a human decision and never self-approvable. An
        # agent (non-human tier) cannot answer one, and the requester cannot
        # approve their own request.
        if req.type == HITLType.APPROVAL:
            if p.actor_tier != "human":
                raise HTTPException(status_code=403, detail="only a human may approve")
            if req.requested_by and req.requested_by == p.subject:
                raise HTTPException(status_code=403, detail="cannot approve your own request")
        resp = await k.hitl.answer(
            p.tenant_id, request_id, body.decision, p.subject, body.notes
        )
        return {"status": "answered", "response_id": resp.id}

    @app.get("/v1/work")
    async def work(
        status: str | None = None,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ) -> dict:
        from boltrig.identity.rbac import departments_for
        from boltrig.models import WorkStatus

        st = WorkStatus(status) if status else None
        # row-level department isolation enforced at the store (US-IAM-02)
        departments = departments_for(p.role, p.scope)
        items = await k.list_work(p.tenant_id, departments=departments, status=st)
        return {
            "items": [
                {
                    "id": w.id, "intent": w.intent, "status": w.status.value,
                    "confidence": w.confidence, "convergent": w.convergent,
                    "owner_member": w.owner_member, "source": w.source,
                    "parent_id": w.parent_id, "hatchet_run_id": w.hatchet_run_id,
                }
                for w in items
            ]
        }

    @app.get("/v1/work/{item_id}")
    async def work_detail(
        item_id: str,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ):
        # A work item plus its children (the epic->story->task tree) and its audit
        # trail - the data behind the hierarchical work board (#74). Scope-filtered
        # by department (US-IAM-02): resolved from the caller's visible set, so an
        # item outside the caller's departments is simply not found.
        from boltrig.identity.rbac import departments_for

        departments = departments_for(p.role, p.scope)
        visible = await k.list_work(p.tenant_id, departments=departments)
        by_id = {w.id: w for w in visible}
        item = by_id.get(item_id)
        if item is None:
            return JSONResponse({"error": "not_found"}, status_code=404)

        def _wd(w) -> dict:
            return {
                "id": w.id, "intent": w.intent, "status": w.status.value,
                "confidence": w.confidence, "convergent": w.convergent,
                "owner_member": w.owner_member, "source": w.source,
                "parent_id": w.parent_id, "hatchet_run_id": w.hatchet_run_id,
                "on_behalf_of": w.on_behalf_of,
            }

        children = [_wd(w) for w in visible if w.parent_id == item_id]
        trail: list = []
        if item.hatchet_run_id:
            events = await k.store.audit_query(
                p.tenant_id, run_id=item.hatchet_run_id, limit=200
            )
            trail = [
                {
                    "ts": e.ts.isoformat() if hasattr(e.ts, "isoformat") else str(e.ts),
                    "actor": e.actor, "actor_tier": e.actor_tier,
                    "verb": e.verb, "noun": e.noun, "status": e.status,
                    "detail": e.detail,
                }
                for e in events
            ]
        return {"item": _wd(item), "children": children, "audit": trail}

    @app.get("/v1/audit/tree/{run_id}")
    async def audit_tree(
        run_id: str, k: Kernel = Depends(_get_kernel), p: Principal = Depends(principal)
    ) -> dict:
        from boltrig.observability.tree import build_tree

        return await build_tree(k.store, p.tenant_id, run_id)

    @app.get("/v1/runs/{run_id}/events")
    async def run_events(
        run_id: str, request: Request, follow: int = 0,
        k: Kernel = Depends(_get_kernel), p: Principal = Depends(principal),
    ):
        # Subscribe to a run's live event stream (Round Eleven, the Run drawer).
        # Tenant-scoped (SEC-56): a run is streamable only if it produced audited
        # activity in the caller's tenant - you cannot read another tenant's run.
        rows = await k.store.audit_query(p.tenant_id, run_id=run_id, limit=1)
        if not rows:
            return JSONResponse({"error": "unknown_run"}, status_code=404)

        if not follow:
            # Snapshot: the events emitted so far, then end (historical inspection).
            async def snapshot():
                for event in k.events.snapshot(run_id):
                    yield f"data: {json.dumps(event)}\n\n"

            return StreamingResponse(snapshot(), media_type="text/event-stream")

        async def live():  # backlog (re-attach) then live until the run closes
            async for event in k.events.subscribe(run_id, replay=True):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(live(), media_type="text/event-stream")

    # Round Three: authoring studios, admin console, observability, eval, etc.
    from .platform_routes import register_platform_routes

    register_platform_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    # Round Four: settings, personal access tokens, sessions, users, invitations.
    from .access_routes import register_access_routes

    register_access_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    # Round Five: kernel-governed memory verbs + scoped reads.
    from .memory_routes import register_memory_routes

    register_memory_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    # Channels (decision 0003): webhook-class ingress + admin management. The
    # inbound route is signature-authenticated (no principal); everything it
    # produces re-enters the one chokepoint as a governed work-item intake.
    from .channel_routes import register_channel_routes

    register_channel_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    return app
