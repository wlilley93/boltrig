"""The kernel's MCP server face (Round Two, Epic MCP).

Granted verbs are advertised as MCP tools and every ``tools/call`` runs the
unchanged dispatch chokepoint (P2, SEC-26). A connection is scoped by a per-run
token (skill grants ∩ tenant ceiling), so a run sees and can call only its own
tools (SEC-23, FR-MCP-02). Credentials are resolved inside the kernel and never
cross this boundary (SEC-27).

This is a thin JSON-RPC 2.0 face (the MCP wire shape: ``initialize`` /
``tools/list`` / ``tools/call``); it adds no policy of its own, only translation
into ``kernel.invoke`` - so the core stays thin (P1) and dep-light.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from nankle.models import (
    DegradedMode,
    GrantSet,
    InvocationContext,
    NankleError,
    PendingHuman,
)

_PROTOCOL_VERSION = "2024-11-05"


def _ok(rid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


@dataclass(frozen=True)
class RunToken:
    """A run-scoped MCP connection record (least privilege, SEC-23)."""

    token: str
    tenant_id: str
    grants: GrantSet
    run_id: str | None = None
    actor: str = "ephemeral"
    skills: tuple[str, ...] = field(default_factory=tuple)


class McpFace:
    def __init__(self, kernel) -> None:
        self._kernel = kernel
        self._tokens: dict[str, RunToken] = {}

    # --- token lifecycle (issued by the fleet per run) ---
    def issue_run_token(
        self, tenant_id: str, grants: GrantSet, *, run_id=None, actor="ephemeral", skills=()
    ) -> str:
        token = uuid.uuid4().hex
        self._tokens[token] = RunToken(
            token=token, tenant_id=tenant_id, grants=grants, run_id=run_id,
            actor=actor, skills=tuple(skills),
        )
        return token

    def revoke(self, token: str) -> None:
        self._tokens.pop(token, None)

    def is_run_token(self, token: str | None) -> bool:
        """Whether ``token`` is a live run-scoped token (vs a user bearer/PAT)."""
        return bool(token) and token in self._tokens

    def _context(self, rt: RunToken) -> InvocationContext:
        return InvocationContext(
            tenant_id=rt.tenant_id, grants=rt.grants, actor=rt.actor,
            actor_tier="ephemeral", run_id=rt.run_id, skills_loaded=rt.skills,
        )

    # --- JSON-RPC dispatch ---
    async def handle(self, token: str | None, request: dict) -> dict:
        rt = self._tokens.get(token or "")
        if rt is None:
            return _err(request.get("id"), -32001, "invalid or expired run token")
        return await self._dispatch(rt, request)

    async def handle_user(self, principal, request: dict) -> dict:
        """User-authenticated MCP (US-HEAD-02, SEC-37): a transient connection
        scoped to the user's effective grants (PAT scope ∩ owner grants, or the
        user's role-derived grants). Every call runs the same chokepoint as the
        site - no reduced-security headless path - and is audited as the user."""
        rt = RunToken(
            token="", tenant_id=principal.tenant_id, grants=principal.grants,
            run_id=None, actor=principal.subject, skills=(),
        )
        return await self._dispatch(rt, request)

    async def _dispatch(self, rt: "RunToken", request: dict) -> dict:
        rid = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "initialize":
            return _ok(rid, {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "nankle-kernel", "version": "0.1.0"},
            })
        if method in ("notifications/initialized", "ping"):
            return _ok(rid, {})
        if method == "tools/list":
            return _ok(rid, {"tools": await self._list_tools(rt)})
        if method == "tools/call":
            return _ok(rid, await self._call_tool(rt, params))
        return _err(rid, -32601, f"method not found: {method}")

    async def _list_tools(self, rt: RunToken) -> list[dict]:
        """Granted-only: tenant ceiling ∩ the run's grants (SEC-23, FR-MCP-02)."""
        perms = await self._kernel.store.get_tenant_permissions(rt.tenant_id)
        verbs = await self._kernel.store.list_verbs(rt.tenant_id)
        return [
            {"name": v.id, "description": v.description or v.id, "inputSchema": v.input_schema}
            for v in verbs
            if perms.grants.permits(v.id) and rt.grants.permits(v.id)
        ]

    async def _call_tool(self, rt: RunToken, params: dict) -> dict:
        """Translate to ``kernel.invoke`` - the unchanged chokepoint (SEC-26)."""
        name = params.get("name", "")
        args = params.get("arguments") or {}
        verb_def = await self._kernel.store.get_verb(rt.tenant_id, name)
        noun = verb_def.noun_id if verb_def else (name.split(".")[0] if name else "")
        ctx = self._context(rt)
        try:
            output = await self._kernel.invoke(
                noun, name, args, ctx, approval_id=params.get("approval_id")
            )
            return {
                "content": [{"type": "text", "text": json.dumps(output)}],
                "isError": False,
                "_nankle": {"status": "ok", "output": output},
            }
        except PendingHuman as e:
            return {
                "content": [{"type": "text", "text": f"pending approval: {e.hitl_request_id}"}],
                "isError": True,
                "_nankle": {"status": "pending_human", "hitl_request_id": e.hitl_request_id},
            }
        except DegradedMode as e:
            return {
                "content": [{"type": "text", "text": "degraded"}],
                "isError": True,
                "_nankle": {"status": "degraded", "output": e.output},
            }
        except NankleError as e:
            status = "denied" if e.status_code == 403 else "error"
            return {
                "content": [{"type": "text", "text": e.reason}],
                "isError": True,
                "_nankle": {"status": status, "reason": e.reason},
            }
