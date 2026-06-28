"""The kernel HTTP surface (FastAPI) - a thin transport over the engine.

Multiple front doors (HTTP here, plus in-process callers and, later, MCP) are
dumb mouths over one smart engine: no policy lives in this module. Identity is
authenticated-by-construction (K-3): a pluggable ``principal_resolver`` turns a
verified bearer into a ``Principal``; handlers never read tenant/identity from
the request body.
"""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from nankle.models import (
    DegradedMode,
    GrantSet,
    HITLType,
    InvocationContext,
    NankleError,
    PendingHuman,
    Urgency,
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


async def _dev_principal(request: Request) -> Principal:
    """Development resolver. Trusts headers; replace with OIDC/SAML in prod
    (see ``nankle.identity.auth``). SEC-01 requires real auth in production."""
    h = request.headers
    grants = [g for g in h.get("x-nankle-grants", "").split(",") if g]
    role = h.get("x-nankle-role", "org-admin")
    departments = [d for d in h.get("x-nankle-departments", "").split(",") if d]
    scope = {"all": True} if role == "org-admin" else {"departments": departments}
    return Principal(
        tenant_id=h.get("x-nankle-tenant", "default"),
        subject=h.get("x-nankle-subject", "dev"),
        grants=GrantSet.of(grants),
        role=role,
        actor_tier=h.get("x-nankle-tier", "human"),
        on_behalf_of=h.get("x-nankle-obo"),
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
) -> FastAPI:
    """Build the ASGI app. Pass a prebuilt ``kernel`` (tests/in-process), or a
    ``kernel_factory`` that the lifespan runs on the SERVING loop so loop-bound
    resources (the asyncpg pool) attach to the loop that handles requests."""
    resolver = principal_resolver or _dev_principal

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not hasattr(app.state, "kernel"):
            if kernel_factory is None:
                raise RuntimeError("create_app needs a kernel or a kernel_factory")
            built = await kernel_factory()
            app.state.kernel = built
            app.state.spawner = spawner_factory(built) if spawner_factory else spawner
        try:
            yield
        finally:
            store = getattr(getattr(app.state, "kernel", None), "store", None)
            close = getattr(store, "close", None)
            if close is not None:  # PostgresStore: drain the pool on shutdown
                result = close()
                if inspect.isawaitable(result):
                    await result

    app = FastAPI(title="Nankle Kernel", version="0.1.0", lifespan=lifespan)
    # Prebuilt kernel is set synchronously so it works even without lifespan
    # (Starlette TestClient used without a context manager).
    if kernel is not None:
        app.state.kernel = kernel
        app.state.spawner = spawner

    async def principal(request: Request) -> Principal:
        return await resolver(request)

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
        except NankleError as e:
            return JSONResponse(
                {"status": "denied" if e.status_code == 403 else "error", "reason": e.reason},
                status_code=e.status_code,
            )

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
        try:
            return JSONResponse(await spawner_fn(p, body))
        except NankleError as e:
            return JSONResponse({"error": e.reason}, status_code=e.status_code)

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
        from nankle.identity.rbac import departments_for
        from nankle.models import WorkStatus

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

    @app.get("/v1/audit/tree/{run_id}")
    async def audit_tree(
        run_id: str, k: Kernel = Depends(_get_kernel), p: Principal = Depends(principal)
    ) -> dict:
        from nankle.observability.tree import build_tree

        return await build_tree(k.store, p.tenant_id, run_id)

    # keep an unused import referenced for the HITL enums in scope
    _ = (HITLType, Urgency)
    return app
