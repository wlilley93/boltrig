"""The kernel HTTP surface (FastAPI) - a thin transport over the engine.

Multiple front doors (HTTP here, plus in-process callers and, later, MCP) are
dumb mouths over one smart engine: no policy lives in this module. Identity is
authenticated-by-construction (K-3): a pluggable ``principal_resolver`` turns a
verified bearer into a ``Principal``; handlers never read tenant/identity from
the request body.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from boltrig.models import (
    BoltrigError,
    DegradedMode,
    GrantSet,
    InvocationContext,
    PendingHuman,
)
from boltrig.store.base import DEFAULT_WORK_PAGE, MAX_WORK_PAGE, clamp_work_page

from . import Kernel
from .app_bodies import ChatBody, InvokeBody, RespondBody, SpawnBody
from .conversation_list_views import conversation_search_views, conversation_views
from .hitl_http import list_visible_hitl, respond_to_hitl
from .web_security import client_ip
from .work_http import get_visible_work_item, list_visible_work_items, work_item_audit_trail
from .bearer_principal import resolve_principal


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
    # The active WORKSPACE the caller is operating in ([2026] VJS-COUNTY 8, D4). Set
    # by the session resolver ONLY after it has re-authorized membership every
    # request (fail-closed to None); never read from the request body. Threaded onto
    # every InvocationContext this principal builds so the kernel carries it.
    active_workspace_id: str | None = None
    # Request provenance ([2026] VJS-COUNTY 9, D1/D2), stamped at the door by the
    # principal resolver from the request (client peer / CF client header + the
    # User-Agent), never from a body field. Threaded onto every context this
    # principal builds so the enriched audit row carries ip/ua.
    ip_address: str | None = None
    user_agent: str | None = None
    # HOW this caller authenticated, as opposed to `actor_tier`, which is the
    # authority they act with. The two are not the same question and conflating
    # them is what let a machine bearer clear a control approval; the full
    # reasoning lives with the concept, in `config/dev_posture.py`. Defaults to
    # "machine" so an unlabelled resolver is refused, never admitted.
    credential_kind: str = "machine"

    def context(
        self,
        *,
        run_id=None,
        parent_run_id=None,
        depth=0,
        skills=(),
        extra=None,
        trusted_extra=None,
    ):
        # ``extra`` is caller-supplied (a request body's context): reserved
        # kernel-trusted keys are dropped from it. ``trusted_extra`` is the
        # server-side stamping channel (memory/knowledge scope derivers) and is
        # merged verbatim, then the resolver-owned role/scope win last.
        stamped_extra = {
            **{k: v for k, v in dict(extra or {}).items() if k not in RESERVED_CONTEXT_KEYS},
            **dict(trusted_extra or {}),
            "principal_role": self.role,
            "principal_scope": dict(self.scope),
        }
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
            extra=stamped_extra,
            workspace_id=self.active_workspace_id,
            ip_address=self.ip_address,
            user_agent=self.user_agent,
        )


PrincipalResolver = Callable[[Request], Awaitable[Principal]]


# Context-extra keys the kernel trusts because they are stamped from server-side
# state (the resolver's role/scope, the approval gate, the memory/knowledge scope
# derivers). A caller-supplied value for one of these is silently dropped so a
# request body can never seed kernel-trusted authority (principal_role/_scope
# were already overwritten after the merge; this closes the rest of the family).
RESERVED_CONTEXT_KEYS = frozenset(
    {
        "principal_role",
        "principal_scope",
        "approved_by",
        "approval_request_id",
        "approval_request_fingerprint",
        "approval_resource_context",
        "knowledge_scopes",
        "memory_scopes",
    }
)


def _client_ip(request: Request) -> str | None:
    """The caller's client IP for the enriched audit row ([2026] VJS-COUNTY 9, D1).
    Shared with the auth routes via ``web_security.client_ip``: CF-Connecting-IP
    is honored only behind the tunnel opt-in, else the TCP peer."""
    return client_ip(request)


def _error_envelope(e: BoltrigError) -> dict:
    """The one canonical kernel error body: a 403 is a denial, anything else is
    an error. Every transport surface returns this shape so a client parses one
    envelope, never per-route variants."""
    body = {"status": "denied" if e.status_code == 403 else "error", "reason": e.reason}
    # A refusal that does not say what WOULD have been accepted cannot be acted
    # on. Only SchemaValidationError carries this, and only outward: its
    # SchemaValidationError.audit_detail stays value-free for the ledger.
    caller = getattr(e, "caller_detail", None)
    if callable(caller):
        body.update(caller())
    return body


def _mcp_wire_response(body: dict, result: dict) -> Response:
    """The streamable-HTTP answer for one JSON-RPC message.

    A JSON-RPC NOTIFICATION (no ``id``) must NOT get a JSON-RPC response frame:
    the streamable-HTTP contract is 202 with an empty body. Returning
    ``{"id": null, "result": {}}`` - the old behaviour - is a protocol violation
    that strict clients (Codex's rmcp worker) treat as a fatal transport error,
    killing the whole MCP connection. Historical clients tolerated it; Codex does not.
    Request-shaped messages (with an ``id``) keep the 200 JSON body unchanged.
    """
    if isinstance(body, dict) and body.get("id") is None:
        return Response(status_code=202)
    return JSONResponse(result)


async def _dev_principal(request: Request) -> Principal:
    """Development resolver. Trusts headers; replace with OIDC/SAML in prod
    (see ``boltrig.identity.auth``). SEC-01 requires real auth in production."""
    from boltrig.identity.rbac import grants_for_scope

    h = request.headers
    role = h.get("x-boltrig-role", "org-admin")
    departments = [d for d in h.get("x-boltrig-departments", "").split(",") if d]
    grants_hdr = [g for g in h.get("x-boltrig-grants", "").split(",") if g]
    verbs = [v for v in h.get("x-boltrig-verbs", "").split(",") if v]
    scope: dict[str, Any] = (
        {"all": True}
        if role == "org-admin"
        else {
            "departments": departments,
            "verbs": verbs,
        }
    )
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
        credential_kind="dev-header",  # stands in for an interactive session
        # The dev resolver simulates the authenticated session via headers; the
        # active workspace is part of that session. Without it a codex-routed turn
        # has no run+workspace scope and the read-only Codex phase degrades
        # (no_read_only_phase_scope). Optional: absent header keeps today's None.
        active_workspace_id=h.get("x-boltrig-workspace") or None,
    )


# --- request/response bodies (Pydantic) -------------------------------------
def _depth_from(raw: Any) -> int:
    """Caller-supplied spawn depth, clamped: garbage is 0 (never a 500) and a
    negative depth floors at 0, so a body can never reset the runaway-tree
    budget (fleet/spawn.py checks ``depth + 1 > max_depth``)."""
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


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
            active_kernel = getattr(app.state, "kernel", None)
            if active_kernel is not None:
                await active_kernel.aclose()

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
        from boltrig.store.postgres import set_current_tenant

        # A PAT bearer, else the configured resolver. Lives in bearer_principal
        # because deciding WHICH WORKSPACE a headless caller acts in is a security
        # question, and this file is at its structural ratchet.
        p = await resolve_principal(request, resolver, _get_kernel)
        # Stamp request provenance for the enriched audit row ([2026] VJS-COUNTY 9,
        # D1). Taken from the request at the door, never from a body field. Behind
        # the CF tunnel the TCP peer is the tunnel, so CF's authoritative client
        # header is honored behind the BOLTRIG_TRUST_CF_CONNECTING_IP opt-in (CF
        # strips any client-supplied copy), else the TCP peer. X-Forwarded-For is
        # deliberately NOT trusted (spoofable).
        p.ip_address = _client_ip(request)
        p.user_agent = request.headers.get("user-agent") or None
        # RLS-live: bind this request's tenant so the _RlsPool scopes every DB call
        # (a no-op for the in-memory store and when RLS is off).
        set_current_tenant(p.tenant_id)
        return p

    from .health_routes import register_health_routes

    register_health_routes(app, get_kernel=_get_kernel)

    @app.post("/v1/invoke")
    async def invoke(
        body: InvokeBody,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ) -> JSONResponse:
        # SEC-186: the body may not name somebody else's run. See run_access.
        from .run_access import foreign_run_asserted

        if await foreign_run_asserted(k.store, p, body.context):
            return JSONResponse({"status": "denied", "reason": "not your run"}, status_code=403)
        ctx = p.context(
            run_id=body.context.get("run_id"),
            parent_run_id=body.context.get("parent_run_id"),
            depth=_depth_from(body.context.get("depth", 0)),
            skills=body.context.get("skills_loaded", ()),
        )
        try:
            output = await k.invoke(
                body.noun,
                body.verb,
                body.params,
                ctx,
                idempotency_key=body.idempotency_key,
                approval_id=body.approval_id,
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

    @app.get("/v1/invoke/approvals/{request_id}")
    async def invoke_approval(
        request_id: str,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ) -> dict[str, str]:
        from .invoke_finalization import invoke_approval_state

        return await invoke_approval_state(k, p, request_id)

    @app.post("/v1/mcp")
    async def mcp(body: dict, request: Request, k: Kernel = Depends(_get_kernel)) -> JSONResponse:
        # Two ways in, both run the same chokepoint:
        #  - a run-scoped token (the fleet/gateway path, Round Two): scopes to a run.
        #  - a user bearer / PAT (US-HEAD-02): scopes to the user's effective grants.
        run_token = request.headers.get("x-boltrig-mcp-token")
        if run_token is None:
            auth = request.headers.get("authorization", "")
            scheme, _, value = auth.partition(" ")
            bearer = value.strip() if scheme.lower() == "bearer" else None
            if k.mcp.is_run_token(bearer):  # a run token presented as a bearer
                run_token = bearer
        # D2: thread the request's ip/ua so an MCP-initiated audit row carries them
        # at the SAME depth as a human action.
        ip, ua = _client_ip(request), (request.headers.get("user-agent") or None)
        if run_token is not None:
            result = await k.mcp.handle(run_token, body, ip_address=ip, user_agent=ua)
            return _mcp_wire_response(body, result)
        # user-authenticated MCP: resolve the caller (PAT or configured resolver)
        # and advertise/scope tools to their effective grants (no weak path, SEC-37).
        p = await principal(request)
        result = await k.mcp.handle_user(p, body, ip_address=ip, user_agent=ua)
        return _mcp_wire_response(body, result)

    @app.post("/v1/chat")
    async def chat(body: ChatBody, request: Request, p: Principal = Depends(principal)):
        chat_svc = getattr(request.app.state, "chat", None)
        if chat_svc is None:
            return JSONResponse({"error": "chat_unavailable"}, status_code=503)
        # The caller's role-resolved grants ride along as the ceiling every chat
        # spawn intersects ([2026] VJS-COUNTY 1) - same resolution as any verb call.
        gen = chat_svc.handle_turn(
            tenant_id=p.tenant_id,
            user_id=p.subject,
            role=p.role,
            grants=p.grants,
            workspace_id=p.active_workspace_id,
            scope=p.scope,
            message=body.message,
            conversation_id=body.conversation_id,
            attachments=body.attachments,
            on_behalf_bearer=body.on_behalf_bearer,
            idempotency_key=body.idempotency_key,
            origin=body.origin, caller_context=body.caller_context,
            model_profile_id=body.model_profile_id, model_choice_id=body.model_choice_id,
        )
        # RBAC / access errors happen before the first event and propagate to the
        # central exception handler (canonical envelope) - the stream hasn't begun.
        try:
            first = await gen.__anext__()
        except StopAsyncIteration:
            first = None

        # Mid-run steer (US-CHAT-15): the conversation's turn was already in flight,
        # so the message was durably queued instead of starting a parallel turn -
        # acknowledge with a 202, no SSE stream on this POST.
        if first is not None and first.get("type") == "queued":
            return JSONResponse(
                {
                    "status": "queued",
                    "conversation_id": first.get("conversation_id"),
                    "message_id": first.get("message_id"),
                    "run_id": first.get("run_id"),
                },
                status_code=202,
            )

        async def stream():
            if first is not None:
                yield f"data: {json.dumps(first)}\n\n"
            async for event in gen:
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/v1/conversations")
    async def conversations(
        request: Request,
        limit: int | None = None,
        offset: int = 0,
        p: Principal = Depends(principal),
    ) -> dict:
        chat_svc = getattr(request.app.state, "chat", None)
        if chat_svc is None:
            return {"conversations": []}
        # Backward-compatible (US-CONV-09): a bare call (no limit, offset 0) retains
        # the original owner-scoped wrapper and ordering. The additive, content-free
        # `working` boolean deliberately replaces any temptation to expose run ids.
        # Opting into pagination (a limit, or a non-zero offset) returns one bounded
        # page plus next_offset (null when exhausted); the page size is clamped under
        # the ChatConfig ceiling inside the service.
        if limit is None and offset <= 0:
            convs = await chat_svc.list_conversations(p.tenant_id, p.subject)
            return {"conversations": conversation_views(chat_svc, p.tenant_id, convs)}
        items, next_offset = await chat_svc.list_conversations_page(
            p.tenant_id, p.subject, limit=limit, offset=offset
        )
        return {
            "conversations": conversation_views(chat_svc, p.tenant_id, items),
            "next_offset": next_offset,
        }

    @app.get("/v1/conversations/search")
    async def search_conversations(
        request: Request,
        q: str = "",
        limit: int | None = None,
        offset: int = 0,
        p: Principal = Depends(principal),
    ):
        # Owner-scoped conversation search (US-CONV-10): case-insensitive substring
        # over the CALLER'S OWN conversation titles + LIVE message content, paginated,
        # fail-closed to the caller's scope. Registered BEFORE the /{conversation_id}
        # route so "search" is never captured as a conversation id.
        chat_svc = getattr(request.app.state, "chat", None)
        if chat_svc is None:
            return {"results": [], "next_offset": None}
        query = q.strip()
        if not query:
            return JSONResponse({"status": "error", "reason": "q is required"}, status_code=400)
        pairs, next_offset = await chat_svc.search_conversations(
            p.tenant_id, p.subject, query, limit=limit, offset=offset
        )
        return {
            "results": conversation_search_views(chat_svc, p.tenant_id, pairs),
            "next_offset": next_offset,
        }

    from .conversation_live_routes import register_worker_query_routes

    register_worker_query_routes(app, principal_dep=principal, get_kernel=_get_kernel)

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
        return {"requests": await list_visible_hitl(k, p)}

    @app.post("/v1/hitl/{request_id}/respond")
    async def respond(
        request_id: str,
        body: RespondBody,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ) -> dict:
        return await respond_to_hitl(k, p, request_id, body.decision, body.notes)

    @app.get("/v1/work")
    async def work(
        status: str | None = None,
        limit: int = DEFAULT_WORK_PAGE,
        cursor: str | None = None,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ) -> dict:
        from boltrig.identity.rbac import departments_for
        from boltrig.models import WorkStatus

        try:
            st = WorkStatus(status) if status else None
        except ValueError:
            return JSONResponse(
                {"status": "error", "reason": "unknown work status"}, status_code=400
            )
        # row-level department isolation enforced at the store (US-IAM-02)
        departments = departments_for(p.role, p.scope)
        # M7 / SEC-69: bound the page. The store clamps the limit to MAX_WORK_PAGE
        # and pages by keyset on id; the department filter is passed through, so no
        # caller can widen what it sees. The next cursor is the last item's id when
        # the page came back full (a short page means the end of the slice).
        page = clamp_work_page(limit)
        items = await list_visible_work_items(
            k.store,
            p,
            st,
            departments=departments,
            limit=page,
            cursor=cursor,
        )
        next_cursor = items[-1].id if len(items) == page else None
        return {
            "items": [
                {
                    "id": w.id,
                    "intent": w.intent,
                    "status": w.status.value,
                    "confidence": w.confidence,
                    "convergent": w.convergent,
                    "owner_member": w.owner_member,
                    "source": w.source,
                    "parent_id": w.parent_id,
                    "hatchet_run_id": w.hatchet_run_id,
                }
                for w in items
            ],
            "limit": page,
            "next_cursor": next_cursor,
        }

    @app.get("/v1/work/{item_id}")
    async def work_detail(
        item_id: str,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ):
        # A work item plus its children (the epic->story->task tree) and its audit
        # trail - the data behind the hierarchical work board (#74). Scope-filtered
        # by department (US-IAM-02): an item outside the caller's departments is
        # simply not found. M7 / SEC-69: fetch the one item and query its children
        # DIRECTLY by parent_id (bounded by the department filter + the page cap),
        # never load the whole visible set into a dict - that was O(all items).
        from boltrig.identity.rbac import departments_for

        departments = departments_for(p.role, p.scope)

        def _in_scope(w) -> bool:
            # mirror the store's US-IAM-02 department predicate exactly: None =
            # unrestricted (org-admin), else the owner_member must be in-scope.
            return departments is None or w.owner_member in set(departments)

        item = await get_visible_work_item(k.store, p, item_id)
        if item is None or not _in_scope(item):
            # out-of-scope reads 404 (not 403) so the item's existence never leaks.
            return JSONResponse({"error": "not_found"}, status_code=404)

        def _wd(w) -> dict:
            return {
                "id": w.id,
                "intent": w.intent,
                "status": w.status.value,
                "confidence": w.confidence,
                "convergent": w.convergent,
                "owner_member": w.owner_member,
                "source": w.source,
                "parent_id": w.parent_id,
                "hatchet_run_id": w.hatchet_run_id,
                "on_behalf_of": w.on_behalf_of,
            }

        # children queried directly by parent_id, still department-scoped and
        # bounded to a page (US-IAM-02 preserved; M7 / SEC-69 bounding).
        child_items = await list_visible_work_items(
            k.store,
            p,
            parent_id=item_id,
            departments=departments,
            limit=MAX_WORK_PAGE,
        )
        children = [_wd(w) for w in child_items]
        trail = await work_item_audit_trail(k.store, p, item)
        return {"item": _wd(item), "children": children, "audit": trail}

    @app.get("/v1/audit/tree/{run_id}")
    async def audit_tree(
        run_id: str, k: Kernel = Depends(_get_kernel), p: Principal = Depends(principal)
    ) -> dict:
        from boltrig.observability.tree import tree_from_events

        from .run_access import visible_audit_tree_events

        rows = await visible_audit_tree_events(k.store, p, run_id)
        if rows is None:
            return JSONResponse({"error": "unknown_run"}, status_code=404)
        return tree_from_events(rows, run_id)

    @app.get("/v1/runs/{run_id}/events")
    async def run_events(
        run_id: str,
        request: Request,
        follow: int = 0,
        since: int | None = None,
        k: Kernel = Depends(_get_kernel),
        p: Principal = Depends(principal),
    ):
        # Subscribe to a run's live event stream (Round Eleven, the Run drawer).
        # Scope check (SEC-56): run events contain raw tool args/results for the
        # canvas, so a same-tenant caller must still pass the ordinary visibility
        # fences before the stream is exposed.
        from .run_access import visible_run_events

        rows = await visible_run_events(k.store, p, run_id)
        if rows is None:
            return JSONResponse({"error": "unknown_run"}, status_code=404)

        # ?since=<seq> (GAP G5): skip the backlog the caller has already seen and
        # replay only events published AFTER that cursor. A HITL continuation passes
        # the `resume_since` the respond/answer decision returned (the relay seq
        # captured the instant before the resume lane fired), so the stream yields
        # only the post-decision segment instead of the whole retained backlog.
        # `since` only narrows what is REPLAYED to an already-authorized caller
        # (visibility was fully enforced above); it can never widen what a run
        # exposes. A missing/negative value means "no cursor" (replay everything -
        # today's behavior), so an older client is unaffected.
        cursor = since if (since is not None and since >= 0) else None

        if not follow:
            # Snapshot: the events emitted so far, then end (historical inspection).
            async def snapshot():
                for event in k.events.snapshot(p.tenant_id, run_id, since=cursor):
                    yield f"data: {json.dumps(event)}\n\n"

            return StreamingResponse(snapshot(), media_type="text/event-stream")

        async def live():  # backlog (re-attach) then live until the run closes
            async for event in k.events.subscribe(p.tenant_id, run_id, replay=True, since=cursor):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(live(), media_type="text/event-stream")

    # Round Three: authoring studios, admin console, observability, eval, etc.
    from .platform_routes import register_platform_routes

    register_platform_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    # Round Four: settings, personal access tokens, sessions, users, invitations.
    from .access_routes import register_access_routes

    register_access_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    # First-party invite-only login ([2026] VJS-COUNTY 7): accept-invite / login /
    # logout / refresh. The public login+accept routes take no principal; logout +
    # refresh depend on the session principal (which enforces CSRF on these
    # mutating requests). Registering them is harmless under other auth modes (no
    # user has a password), so they are always wired.
    from boltrig.api.auth_routes import register_auth_routes

    register_auth_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    # Round Five: kernel-governed memory verbs + scoped reads.
    from .memory_routes import register_memory_routes

    register_memory_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    # Channels (decision 0003): webhook-class ingress + admin management. The
    # inbound route is signature-authenticated (no principal); everything it
    # produces re-enters the one chokepoint as a governed work-item intake.
    from .channel_routes import register_channel_routes

    register_channel_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    # Channel gateway links (decision 0003, Phase 2): the session mint (admin)
    # and the token-gated outbox claim/ack/fail the severed gateway pumps.
    from .channel_gateway_routes import register_channel_gateway_routes

    register_channel_gateway_routes(app, principal_dep=principal, get_kernel=_get_kernel)

    # Desktop hands (decision 0016, DH-1): the host executor's authenticated pull
    # surface. The pending-command registry is created once in bootstrap and hung
    # on the kernel, shared with the desktop adapter; the factory path builds the
    # kernel on the serving loop, so it is resolved per request, not captured here.
    from .desktop_routes import register_desktop_routes

    register_desktop_routes(
        app,
        principal_dep=principal,
        get_kernel=_get_kernel,
        registry=lambda k: getattr(k, "hands_registry", None),
    )

    return app
