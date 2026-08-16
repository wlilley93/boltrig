"""Round Four HTTP surface: settings, personal access tokens, sessions, user
directory and invitations - the account & access-management surface.

Every route is RBAC-gated server-side (C3, SEC-36) and audited; per-user routes
act on the caller's own scope (C5); admin routes require org-admin. Each setting
changeable here has an API equivalent (SET-03), so a headless client is never
second-class (US-HEAD-01). Personal access tokens are minted as a subset of the
caller's current grants and re-checked on every use, so they never escalate
(SEC-34); invitations only pre-stage a role/scope for an SSO identity (SEC-35).

These routes are thin over the Store; they add account/access policy, never new
dispatch policy - the kernel chokepoint is unchanged (NFR-MNT-01).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantMissing,
    utcnow,
)
from boltrig.kernel.account_profile_routes import register_account_profile_routes
from boltrig.kernel.ai_key_routes import register_ai_key_routes
from boltrig.kernel.conversation_account_routes import (
    register_conversation_account_routes,
)
from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.kernel.notification_routes import register_notification_routes
from boltrig.kernel.trajectory_routes import register_trajectory_routes
from boltrig.kernel.run_access import visible_work_item_by_run
from boltrig.kernel.workspace_management_routes import (
    register_workspace_management_routes,
)
# Per-workspace roles that may administer a workspace's AI key (D3 vocabulary).
_WORKSPACE_ADMIN_ROLES = frozenset({"owner", "admin"})

# IdP org-admin and console superadmin/admin are the same administration tier;
# the initiated owner can therefore create the first invitation.
_ADMIN_ROLES = frozenset({"org-admin", "superadmin", "admin"})


def _require_admin(p) -> None:
    if p.role not in _ADMIN_ROLES:
        raise GrantMissing("organisation administration not permitted for this role")


def _reject_escalation(p, role, scope) -> None:
    """Reject roles above the caller and owner-only all-authority scope (SEC-102)."""
    from boltrig.identity.rbac import _role_rank

    if role is not None and _role_rank(str(role)) < _role_rank(p.role):
        raise GrantMissing("cannot grant a role ranked above your own")
    if isinstance(scope, dict) and scope.get("all") and p.role != "superadmin":
        raise GrantMissing("only the owner may grant all-authority scope")


async def _audit(kernel, p, verb: str, detail: dict, status: str = "ok") -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=p.tenant_id,
            ts=utcnow(),
            actor=p.subject,
            actor_tier=p.actor_tier,
            action_type=ActionType.TOOL_CALL,
            verb=verb,
            status=status,
            on_behalf_of=p.on_behalf_of,
            detail=detail,
        )
    )


def _pat_view(pat) -> dict:
    """A PAT for listing: never the secret or the hash (PAT-02)."""
    return {
        "id": pat.id,
        "name": pat.name,
        "scope": list(pat.scope),
        "created_at": pat.created_at.isoformat() if pat.created_at else None,
        "last_used_at": pat.last_used_at.isoformat() if pat.last_used_at else None,
        "expires_at": pat.expires_at.isoformat() if pat.expires_at else None,
        "revoked": pat.revoked,
    }


def _user_view(u) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "role": u.role,
        "scope": u.scope,
        "status": u.status,
        "source": u.source,
        "source_group": u.source_group,
        "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
    }


def _ai_config_view(c) -> dict:
    """An AI-config row for listing: provider/model + WHETHER a key is set, NEVER the
    key itself (the secret lives only in the sealed credential store)."""
    return {
        "level": c.level,
        "scope_id": c.scope_id,
        "provider": c.provider,
        "model": c.model,
        "modality": c.modality,
        "base_url": c.base_url,
        "has_key": bool(c.credential_ref),
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _workspace_view(w) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "slug": w.slug,
        "status": w.status,
        "settings": w.settings,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


def _workspace_member_view(m) -> dict:
    return {
        "user_id": m.user_id,
        "workspace_id": m.workspace_id,
        "role": m.role,
        "permissions": m.permissions,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _org_view(o) -> dict:
    """An organisation for the management surface: the policy flags + handle, NEVER
    any secret (AI keys live in the sealed credential store, not here)."""
    return {
        "id": o.id,
        "name": o.name,
        "slug": o.slug,
        "settings": o.settings,
        "allow_own_ai_keys": bool(o.allow_own_ai_keys),
        "require_two_factor": bool(o.require_two_factor),
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def _org_member_view(m) -> dict:
    return {
        "user_id": m.user_id,
        "role": m.role,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _authz_manage_workspace(k, p, workspace_id: str):
    """Authorize workspace management, returning the row and optional denial.

    Unknown rows are 404; non-manager writes are 403 and fail closed.
    """
    ws = await k.store.get_workspace(p.tenant_id, workspace_id)
    if ws is None:
        return None, JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    if p.role in _ADMIN_ROLES:  # org-admin/owner may manage any workspace in the org
        return ws, None
    member = await k.store.get_workspace_member(p.tenant_id, workspace_id, p.subject)
    if member is None or member.role not in _WORKSPACE_ADMIN_ROLES:
        return ws, JSONResponse(
            {"status": "denied", "reason": "must be a workspace owner/admin to manage it"},
            status_code=403,
        )
    return ws, None


def register_access_routes(app, *, principal_dep, get_kernel) -> None:
    from boltrig.kernel.org_discovery_routes import register_org_discovery_routes

    P = Depends(principal_dep)
    K = Depends(get_kernel)
    register_account_profile_routes(app, P, K, _audit, _user_view)
    register_conversation_account_routes(app, P, K, _audit)
    _register_hitl_run_routes(app, principal_dep, get_kernel)
    _register_token_routes(app, principal_dep, get_kernel)
    _register_session_routes(app, principal_dep, get_kernel)
    _register_context_routes(app, principal_dep, get_kernel)
    register_org_discovery_routes(app, principal_dep=principal_dep, get_kernel=get_kernel)
    register_ai_key_routes(
        app,
        P,
        K,
        _audit,
        _ai_config_view,
        _ADMIN_ROLES,
        _WORKSPACE_ADMIN_ROLES,
    )
    register_notification_routes(app, principal_dep, get_kernel)
    register_trajectory_routes(app, principal_dep, get_kernel)
    _register_admin_directory_routes(app, principal_dep, get_kernel)
    _register_org_routes(app, principal_dep, get_kernel)
    register_workspace_management_routes(
        app,
        P,
        K,
        _audit,
        _require_admin,
        _authz_manage_workspace,
        _workspace_view,
        _workspace_member_view,
        _ADMIN_ROLES,
    )

def _register_hitl_run_routes(app, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    @app.post("/v1/hitl/{question_id}/answer")
    async def answer_question(question_id: str, body: dict, k=K, p=P) -> JSONResponse:
        # Owner-only, fail-closed, audited answer to an agent's clarifying QUESTION
        # (US-CHAT-12), mirroring the regenerate / cancel pattern. This route answers
        # ONLY a QUESTION HITL - never an approval (those stay on the approvals panel
        # with their human / anti-self-approval checks, SEC-14), so a question can
        # never be laundered into clearing a gated verb. The eligibility + wrap logic
        # is the SHARED answer path (hitl_http.answer_hitl_question) that channel
        # intake replies also use; this route only maps outcomes and audits.
        from .hitl_http import answer_hitl_question

        try:
            outcome = await answer_hitl_question(k, p, question_id, body.get("answer"))
        except HTTPException as exc:
            shape = {
                404: {"status": "error", "reason": "not_found"},
                409: {"status": "error", "reason": "not_a_question"},
                403: {"status": "denied", "reason": "not your run"},
            }.get(exc.status_code, {"status": "error", "reason": str(exc.detail)})
            return JSONResponse(shape, status_code=exc.status_code)
        # keys-only audit: the length, never the answer text (K-20 / US-CONV-08).
        # A SECURE answer records the marker only - even its length is withheld
        # (SEC-181; the value itself was sealed inside the kernel, never here).
        audit_detail = {"question_id": question_id, "run_id": outcome["run_id"]}
        if outcome.get("secure"):
            audit_detail["secure"] = True
        else:
            audit_detail["answer_len"] = outcome["answer_len"]
        await _audit(k, p, "hitl.question.answer", audit_detail)
        response_body = {
            "status": "ok",
            "question_id": question_id,
            "response_id": outcome["response_id"],
            "run_id": outcome["run_id"],
        }
        # GAP G5: echo the ?since resume cursor when present so the caller can skip
        # the already-seen backlog on the continuation follow-stream.
        if outcome.get("resume_since") is not None:
            response_body["resume_since"] = outcome["resume_since"]
        return JSONResponse(response_body)

    @app.post("/v1/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request, k=K, p=P) -> JSONResponse:
        # Owner-only, fail-closed, audited cancellation ([2026] VJS-COUNTY 6, D5):
        # scoped-read roles may read but never cancel, and a non-owner gets 403
        # without a write or audit. Ownership is the work item's on_behalf_of;
        # chat and pump runs resolve through their canonical run id.
        item = await visible_work_item_by_run(k.store, p, run_id)
        if item is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if item.on_behalf_of != p.subject:
            return JSONResponse({"status": "denied", "reason": "not your run"}, status_code=403)
        # Cooperative cancel (D2/D3): write the durable cancel-request signal the
        # pump consults at its next step boundary. The in-flight step/adapter is
        # never interrupted; the terminal CANCELLED state is written server-side by
        # the pump (in a finally). Keys-only audit: the run id, never any content.
        await k.store.request_run_cancel(p.tenant_id, run_id, p.subject)
        await _audit(k, p, "run.cancel", {"run_id": run_id})
        # If this run is a live chat turn, end its SSE stream cleanly (D5).
        chat_svc = getattr(request.app.state, "chat", None)
        if chat_svc is not None and hasattr(chat_svc, "cancel"):
            await chat_svc.cancel(p.tenant_id, run_id)
        return JSONResponse({"status": "ok", "run_id": run_id})


def _register_token_routes(app, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    # === Developer & Connections: personal access tokens (PAT-*, SEC-34) ===
    @app.get("/v1/me/tokens")
    async def list_my_tokens(k=K, p=P) -> dict:
        pats = await k.store.list_pats(p.tenant_id, p.subject)
        return {"tokens": [_pat_view(pat) for pat in pats]}

    @app.post("/v1/me/tokens")
    async def mint_my_token(body: dict, k=K, p=P) -> JSONResponse:
        from boltrig.identity.provisioning import ensure_user_record
        from boltrig.identity.tokens import mint_pat

        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse({"status": "error", "reason": "name is required"}, status_code=400)
        # the caller's current grants are the cap; record/refresh their user row so
        # the token resolves against current role/scope/status later (SEC-34).
        await ensure_user_record(k.store, p)
        pat, secret = await mint_pat(
            k.store,
            tenant_id=p.tenant_id,
            user_id=p.subject,
            name=name,
            requested_scope=body.get("scope"),
            user_grants=p.grants,
            ttl_days=body.get("ttl_days"),
        )
        await _audit(k, p, "token.mint", {"id": pat.id, "name": name, "scope": list(pat.scope)})
        view = _pat_view(pat)
        view["secret"] = secret  # shown ONCE, never stored in the clear
        return JSONResponse({"status": "ok", **view})

    @app.delete("/v1/me/tokens/{token_id}")
    async def revoke_my_token(token_id: str, k=K, p=P) -> JSONResponse:
        pat = await k.store.get_pat(p.tenant_id, token_id)
        if pat is None or pat.user_id != p.subject:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        pat.revoked = True
        await k.store.update_pat(pat)
        await _audit(k, p, "token.revoke", {"id": token_id})
        return JSONResponse({"status": "ok", "id": token_id})


def _register_session_routes(app, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    @app.get("/v1/me/connections")
    async def my_connections(request: Request, p=P) -> dict:
        # how to attach an external client headlessly (SET-41 / HEAD-03)
        base = str(request.base_url).rstrip("/")
        mcp = f"{base}/v1/mcp"
        return {
            "rest_base": base,
            "mcp_endpoint": mcp,
            "auth": "Bearer <your personal access token>",
            "snippets": {
                "claude_code": (
                    f"claude mcp add --transport http boltrig {mcp} "
                    f"--header 'Authorization: Bearer <PAT>'"
                ),
                "curl": (f"curl -s {base}/v1/capabilities -H 'Authorization: Bearer <PAT>'"),
            },
            "note": "Mint a token under Settings -> Developer & Connections; it is "
            "scoped to your own grants and shown once.",
        }

    # === Security & Sessions (SET-70) ===
    def _session_realm(request, p) -> str:
        """The tenant a session ROW lives at ([2026] VJS-COUNTY 11): the identity realm
        (session.tenant_id), which differs from the ACTIVE org (p.tenant_id) for a
        multi-org identity. Session-management reads/writes must target the realm, not
        the active org. Falls back to p.tenant_id when there is no session (unreachable
        for a session-authed caller; a PAT caller has no sessions here anyway)."""
        session = getattr(request.state, "boltrig_session", None)
        return session.tenant_id if session is not None else p.tenant_id

    @app.get("/v1/me/sessions")
    async def list_my_sessions(request: Request, k=K, p=P) -> dict:
        from boltrig.store.postgres import set_current_tenant

        realm = _session_realm(request, p)
        set_current_tenant(realm)  # sessions live at the realm; bind it for the read
        try:
            sessions = await k.store.list_sessions(realm, p.subject)
        finally:
            set_current_tenant(p.tenant_id)  # restore the active tenant
        return {
            "sessions": [
                {
                    "id": s.id,
                    "client": s.client,
                    "revoked": s.revoked,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
                }
                for s in sessions
            ]
        }

    @app.delete("/v1/me/sessions/{session_id}")
    async def revoke_my_session(session_id: str, request: Request, k=K, p=P) -> JSONResponse:
        from boltrig.store.postgres import set_current_tenant

        realm = _session_realm(request, p)
        set_current_tenant(realm)  # sessions live at the realm; bind it for the read/write
        try:
            s = await k.store.get_session(realm, session_id)
            if s is None or s.user_id != p.subject:
                return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
            s.revoked = True
            await k.store.update_session(s)
        finally:
            set_current_tenant(p.tenant_id)  # restore the active tenant for the audit
        await _audit(k, p, "session.revoke", {"id": session_id})
        return JSONResponse({"status": "ok", "id": session_id})


def _register_context_routes(app, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    # === Active workspace context ([2026] VJS-COUNTY 8, D4) ===
    @app.post("/v1/me/active-context")
    async def switch_active_context(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # Switch the session's ACTIVE WORKSPACE. Owner = the session's own user; the
        # resolver already enforced CSRF on this mutating cookie request. The switch
        # is RE-AUTHORIZED against membership, fail-closed: a workspace that does not
        # exist is 404, and one the caller is NOT a member of is 403 with NO write -
        # so a client can never set an active workspace it is not a member of, and a
        # client-supplied value is never trusted without this check.
        session = getattr(request.state, "boltrig_session", None)
        if session is None:
            # No first-party session (e.g. a PAT/bearer principal): there is no
            # session to carry an active context. Fail closed.
            return JSONResponse(
                {"status": "error", "reason": "active context requires a session login"},
                status_code=400,
            )
        workspace_id = body.get("workspace_id")
        if not isinstance(workspace_id, str) or not workspace_id:
            return JSONResponse(
                {"status": "error", "reason": "workspace_id is required"}, status_code=400
            )
        # Existence first (tenant-scoped): unknown workspace -> 404, no write.
        ws = await k.store.get_workspace(p.tenant_id, workspace_id)
        if ws is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        # Membership re-check (tenant-scoped): the caller must currently be a member
        # of this workspace. A non-member is refused 403 with NO write and NO audit.
        memberships = await k.store.list_workspaces_for_user(p.tenant_id, p.subject)
        if not any(w.id == workspace_id for w in memberships):
            return JSONResponse(
                {"status": "denied", "reason": "not a member of that workspace"}, status_code=403
            )
        # Persist the new active workspace on the session (the resolver re-authorizes
        # it again on every subsequent request). The session lives at the identity realm
        # ([2026] VJS-COUNTY 11), so bind that realm for the RLS-scoped session write,
        # then restore the active tenant for the audit. Keys-only audit: the workspace id.
        from boltrig.store.postgres import set_current_tenant

        session.active_workspace_id = workspace_id
        set_current_tenant(session.tenant_id)
        try:
            await k.store.update_session(session)
        finally:
            set_current_tenant(p.tenant_id)
        await _audit(k, p, "session.active_context.switch", {"workspace_id": workspace_id})
        return JSONResponse({"status": "ok", "workspace_id": workspace_id})

    # === Active ORG (tenant) context ([2026] VJS-COUNTY 11, D2/D3) ===
    @app.post("/v1/me/active-org")
    async def switch_active_org(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # Switch the session's ACTIVE ORG (the ONE active tenant). One email can belong
        # to several orgs; this is the only place the active org changes, and it is
        # RE-AUTHORIZED against org_members, fail-closed: an unknown org is 404, an org
        # the caller is NOT a member of is 403 with NO write - so a client-supplied
        # active org is NEVER trusted. The resolver then rebinds the RLS tenant to the
        # new active org on every subsequent request. The CSRF check on this mutating
        # cookie request is already enforced by the resolver. Mirrors the workspace
        # switch above.
        from boltrig.store.postgres import set_current_tenant

        session = getattr(request.state, "boltrig_session", None)
        if session is None:
            # No first-party session (e.g. a PAT/bearer principal): nothing to carry an
            # active org. Fail closed.
            return JSONResponse(
                {"status": "error", "reason": "active org requires a session login"},
                status_code=400,
            )
        org_id = body.get("org_id")
        if not isinstance(org_id, str) or not org_id:
            return JSONResponse(
                {"status": "error", "reason": "org_id is required"}, status_code=400
            )
        # Bind the TARGET org before its RLS-scoped reads (SEC-65). Existence first: an
        # unknown org is 404, NO write. Then RE-AUTHORIZE membership against org_members
        # (the authority, not any client hint): a non-member is 403, NO write.
        set_current_tenant(org_id)
        try:
            org = await k.store.get_org(org_id)
            if org is None:
                return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
            member = await k.store.get_org_member(org_id, p.subject)
            if member is None:
                return JSONResponse(
                    {"status": "denied", "reason": "not a member of that org"},
                    status_code=403,
                )
            # Persist the new active org on the session (the resolver re-authorizes it again
            # on every subsequent request). The session lives at the identity realm, so bind
            # that realm for the session write; the finally restores the caller's current
            # active tenant for the audit. Keys-only audit: the org id.
            session.active_org_id = org_id
            set_current_tenant(session.tenant_id)
            await k.store.update_session(session)
        finally:
            set_current_tenant(p.tenant_id)  # restore the caller's active tenant
        await _audit(k, p, "session.active_org.switch", {"org_id": org_id})
        return JSONResponse({"status": "ok", "org_id": org_id})


def _register_admin_directory_routes(app, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    # === Organisation administration: user directory & invitations (US-USR-02/03) ===
    @app.get("/v1/admin/users")
    async def list_directory(k=K, p=P) -> JSONResponse:
        _require_admin(p)
        users = await k.store.list_users(p.tenant_id)
        return JSONResponse({"users": [_user_view(u) for u in users]})

    @app.patch("/v1/admin/users/{user_id}")
    async def update_user(user_id: str, body: dict, request: Request, k=K, p=P) -> JSONResponse:
        _require_admin(p)
        _reject_escalation(p, body.get("role"), body.get("scope"))
        user = await k.store.get_user(p.tenant_id, user_id)
        if user is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        deactivation_only = body.get("status") == "deactivated" and not (
            {"role", "scope"} & body.keys()
        )
        verb = "control.user.deactivate" if deactivation_only else "control.user.update"
        params = {"user_id": user_id, **body}
        if deactivation_only:
            params.pop("status", None)
        output, pending = await dispatch_control_route(
            k,
            p,
            verb,
            params,
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.get("/v1/admin/invitations")
    async def list_invites(k=K, p=P) -> JSONResponse:
        _require_admin(p)
        invites = await k.store.list_invitations(p.tenant_id)
        return JSONResponse(
            {
                "invitations": [
                    {
                        "id": i.id,
                        "email": i.email,
                        "intended_role": i.intended_role,
                        "intended_scope": i.intended_scope,
                        "status": i.status,
                        "invited_by": i.invited_by,
                        "workspace_id": i.workspace_id,
                        "provision_workspace_name": i.provision_workspace_name,
                        "provision_org_name": i.provision_org_name,
                        "expires_at": i.expires_at.isoformat() if i.expires_at else None,
                    }
                    for i in invites
                ]
            }
        )

    @app.post("/v1/admin/invitations")
    async def create_invite(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        _require_admin(p)
        _reject_escalation(p, body.get("role"), body.get("scope"))
        email = (body.get("email") or "").strip()
        if not email:
            return JSONResponse({"status": "error", "reason": "email is required"}, status_code=400)
        # Org/workspace-scoped invite + provisioning ([2026] VJS-COUNTY 8, D6). All
        # three are optional and each is authorized BEFORE anything is written, so a
        # denial leaves no invitation behind (fail-closed):
        #   - workspace_id (target an EXISTING workspace): the inviter must be able to
        #     manage that workspace (org-admin or its owner/admin), 403 with NO write
        #     otherwise. On accept the invitee is seated into it with the invited role.
        #   - provision_workspace_name (CREATE a workspace on accept): org-admin/owner,
        #     already required by _require_admin above.
        #   - provision_org_name (provision a new org on accept): SUPERADMIN-ONLY - a
        #     lesser admin is refused 403 with NO write.
        workspace_id = (body.get("workspace_id") or "").strip() or None
        provision_workspace_name = (body.get("provision_workspace_name") or "").strip() or None
        provision_org_name = (body.get("provision_org_name") or "").strip() or None
        if provision_org_name is not None and p.role != "superadmin":
            return JSONResponse(
                {"status": "denied", "reason": "org provisioning is owner-only"},
                status_code=403,
            )
        if workspace_id is not None:
            _ws, denied = await _authz_manage_workspace(k, p, workspace_id)
            if denied is not None:
                return denied
        invite_params = {**body, "email": email}
        if workspace_id is not None:
            invite_params["workspace_id"] = workspace_id
        if provision_workspace_name is not None:
            invite_params["provision_workspace_name"] = provision_workspace_name
        if provision_org_name is not None:
            invite_params["provision_org_name"] = provision_org_name
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.invitation.create",
            invite_params,
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.delete("/v1/admin/invitations/{invite_id}")
    async def revoke_invite(invite_id: str, request: Request, k=K, p=P) -> JSONResponse:
        _require_admin(p)
        inv = await k.store.get_invitation(p.tenant_id, invite_id)
        if inv is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        _, pending = await dispatch_control_route(
            k, p, "control.invitation.revoke", {"invite_id": invite_id}, request=request
        )
        if pending is not None:
            return pending
        await _audit(k, p, "admin.invite.revoke", {"id": invite_id})
        return JSONResponse({"status": "ok", "id": invite_id})


def _register_org_routes(app, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    # === Organisation (the active tenant) management ([2026] VJS-COUNTY 8, D6) ===
    @app.get("/v1/orgs/current")
    async def get_current_org(k=K, p=P) -> JSONResponse:
        # The active org = the caller's tenant (the org id IS the tenant_id, D1).
        # Readable by any authenticated caller in the tenant: it is their own org's
        # handle + policy flags, never a secret. A pre-COUNTY-8 tenant with no org
        # row yet is shown its implicit default (not persisted here - a read).
        from boltrig.identity.tenancy import default_org_for

        org = await k.store.get_org(p.tenant_id)
        if org is None:
            org = default_org_for(p.tenant_id)
        return JSONResponse({"organisation": _org_view(org)})

    @app.patch("/v1/orgs/current")
    async def update_current_org(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # Org-admin only, fail-closed + audited: rename / settings / toggle the
        # allow_own_ai_keys + require_two_factor policy flags. A non-admin is refused
        # 403 with NO write by _require_admin (it raises GrantMissing -> 403).
        _require_admin(p)
        output, pending = await dispatch_control_route(
            k, p, "control.org.update", body, request=request
        )
        if pending is not None:
            return pending
        organisation = (output or {}).get("organisation", {})
        await _audit(
            k,
            p,
            "org.update",
            {
                "allow_own_ai_keys": organisation.get("allow_own_ai_keys"),
                "require_two_factor": organisation.get("require_two_factor"),
            },
        )
        return JSONResponse({"status": "ok", "organisation": organisation})

    @app.get("/v1/orgs/current/members")
    async def list_current_org_members(k=K, p=P) -> JSONResponse:
        # The org's membership roster (tenant-scoped by the store). Available to any
        # authenticated caller in the tenant so a workspace owner can populate an
        # add-member picker; it is their own org, never crosses a tenant boundary.
        members = await k.store.list_org_members(p.tenant_id)
        return JSONResponse({"members": [_org_member_view(m) for m in members]})
