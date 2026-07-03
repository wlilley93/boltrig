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

import uuid

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.models import (
    AI_CONFIG_LEVELS,
    WORKSPACE_ROLES,
    ActionType,
    AiConfig,
    AuditEvent,
    ConversationStatus,
    GrantMissing,
    NotificationPref,
    UserInvitation,
    UserSetting,
    Workspace,
    WorkspaceMember,
    utcnow,
)

# Per-workspace roles that may administer a workspace's AI key (D3 vocabulary).
_WORKSPACE_ADMIN_ROLES = frozenset({"owner", "admin"})


# Organisation-administration roles. org-admin is the IdP-role vocabulary; the
# console product tiers (superadmin/admin, per CF_ACCESS_TIERS) are the same
# authority under the Cloudflare-Access / first-party-session vocabularies, so the
# founding OWNER seated by ``boltrig initiate`` (role superadmin) can create the
# first invitations that make invite-only login self-sustaining ([2026] VJS-COUNTY 7).
_ADMIN_ROLES = frozenset({"org-admin", "superadmin", "admin"})


def _require_admin(p) -> None:
    if p.role not in _ADMIN_ROLES:
        raise GrantMissing("organisation administration not permitted for this role")


def _reject_escalation(p, role, scope) -> None:
    """Privilege ceiling (SEC-102): no principal may grant a role ranked above its
    own, and only the owner tier (superadmin) may grant all-authority scope. Closes
    the admin -> superadmin self-escalation via update_user / create_invite (the
    role/scope were previously written from the request body with no clamp, and
    first-party accept-invite materialises a pre-staged role as a real credential)."""
    from boltrig.identity.rbac import _role_rank

    if role is not None and _role_rank(str(role)) < _role_rank(p.role):
        raise GrantMissing("cannot grant a role ranked above your own")
    if isinstance(scope, dict) and scope.get("all") and p.role != "superadmin":
        raise GrantMissing("only the owner may grant all-authority scope")


async def _audit(kernel, p, verb: str, detail: dict, status: str = "ok") -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=p.tenant_id, ts=utcnow(), actor=p.subject, actor_tier=p.actor_tier,
            action_type=ActionType.TOOL_CALL, verb=verb, status=status,
            on_behalf_of=p.on_behalf_of, detail=detail,
        )
    )


def _pat_view(pat) -> dict:
    """A PAT for listing: never the secret or the hash (PAT-02)."""
    return {
        "id": pat.id, "name": pat.name, "scope": list(pat.scope),
        "created_at": pat.created_at.isoformat() if pat.created_at else None,
        "last_used_at": pat.last_used_at.isoformat() if pat.last_used_at else None,
        "expires_at": pat.expires_at.isoformat() if pat.expires_at else None,
        "revoked": pat.revoked,
    }


def _user_view(u) -> dict:
    return {
        "id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role,
        "scope": u.scope, "status": u.status, "source": u.source,
        "source_group": u.source_group,
        "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
    }


def _ai_config_view(c) -> dict:
    """An AI-config row for listing: provider/model + WHETHER a key is set, NEVER the
    key itself (the secret lives only in the sealed credential store)."""
    return {
        "level": c.level, "scope_id": c.scope_id, "provider": c.provider,
        "model": c.model, "has_key": bool(c.credential_ref),
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _workspace_view(w) -> dict:
    return {
        "id": w.id, "name": w.name, "slug": w.slug, "status": w.status,
        "settings": w.settings,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


def _workspace_member_view(m) -> dict:
    return {
        "user_id": m.user_id, "workspace_id": m.workspace_id, "role": m.role,
        "permissions": m.permissions,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _org_view(o) -> dict:
    """An organisation for the management surface: the policy flags + handle, NEVER
    any secret (AI keys live in the sealed credential store, not here)."""
    return {
        "id": o.id, "name": o.name, "slug": o.slug, "settings": o.settings,
        "allow_own_ai_keys": bool(o.allow_own_ai_keys),
        "require_two_factor": bool(o.require_two_factor),
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def _org_member_view(m) -> dict:
    return {
        "user_id": m.user_id, "role": m.role,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _workspace_slug(name: str) -> str:
    """A globally-unique url-safe slug for a new workspace (the workspaces_slug_idx
    is unique across tenants), derived from the name plus a short random suffix so
    two workspaces with the same name never collide."""
    from boltrig.identity.tenancy import default_org_slug

    base = default_org_slug(name) or "workspace"
    return f"{base}-{uuid.uuid4().hex[:6]}"


async def _authz_manage_workspace(k, p, workspace_id: str):
    """Authorize managing a workspace (rename/settings + membership). Fail-closed:
    returns ``(workspace, None)`` when the caller may manage it, else
    ``(workspace_or_None, JSONResponse)`` - a 404 when the workspace does not exist
    in the tenant, a 403 with NO write when the caller is neither an org-admin nor a
    workspace owner/admin of it. A caller may only manage a workspace they own/admin,
    or (org-admin) any workspace in their org."""
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
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    # === Account & profile + settings (SET-10/11/20/21) ===
    @app.get("/v1/me/settings")
    async def get_settings(k=K, p=P) -> dict:
        rows = await k.store.list_user_settings(p.tenant_id, p.subject)
        user = await k.store.get_user(p.tenant_id, p.subject)
        profile = _user_view(user) if user else {
            "id": p.subject, "role": p.role, "scope": p.scope, "status": "active",
        }
        return {"profile": profile, "settings": {s.key: s.value for s in rows}}

    @app.put("/v1/me/settings")
    async def put_settings(body: dict, k=K, p=P) -> JSONResponse:
        # accept {key, value} or {settings: {k: v}}; persist + audit (SET-01, SEC-36)
        updates = body.get("settings")
        if updates is None and "key" in body:
            updates = {body["key"]: body.get("value")}
        if not isinstance(updates, dict) or not updates:
            return JSONResponse({"status": "error", "reason": "no settings provided"},
                                status_code=400)
        for key, value in updates.items():
            await k.store.upsert_user_setting(
                UserSetting(tenant_id=p.tenant_id, user_id=p.subject, key=str(key), value=value)
            )
        await _audit(k, p, "settings.update", {"keys": sorted(str(x) for x in updates)})
        return JSONResponse({"status": "ok", "keys": sorted(str(x) for x in updates)})

    @app.get("/v1/me/activity")
    async def my_activity(k=K, p=P) -> dict:
        # scope-filtered to the caller themselves (SET-72, C5)
        events = await k.store.audit_query(p.tenant_id, limit=200)
        mine = [
            {"seq": e.seq, "ts": e.ts.isoformat() if e.ts else None, "verb": e.verb,
             "status": e.status, "run_id": e.run_id}
            for e in events
            if e.actor == p.subject or e.on_behalf_of == p.subject
        ]
        return {"results": mine}

    @app.get("/v1/me/export")
    async def my_export(k=K, p=P) -> dict:
        # own data only (SET-60): conversations, owned work, settings
        convs = await k.store.list_conversations(p.tenant_id, p.subject)
        work = await k.store.list_work_items(p.tenant_id)
        owned = [
            {"id": w.id, "intent": w.intent, "status": w.status.value}
            for w in work if w.on_behalf_of == p.subject or w.owner_member == p.subject
        ]
        settings = await k.store.list_user_settings(p.tenant_id, p.subject)
        await _audit(k, p, "data.export", {"conversations": len(convs)})
        return {
            "user": p.subject,
            "conversations": [{"id": c.id, "title": c.title, "status": c.status.value}
                              for c in convs],
            "work_items": owned,
            "settings": {s.key: s.value for s in settings},
        }

    @app.delete("/v1/me/conversations/{conversation_id}")
    async def delete_my_conversation(conversation_id: str, k=K, p=P) -> JSONResponse:
        conv = await k.store.get_conversation(p.tenant_id, conversation_id)
        if conv is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if conv.user_id != p.subject:
            return JSONResponse({"status": "denied", "reason": "not your conversation"},
                                status_code=403)
        # retention-aware close (SET-61); a hard purge is a retention-job concern.
        conv.status = ConversationStatus.CLOSED
        conv.updated_at = utcnow()
        await k.store.update_conversation(conv)
        await _audit(k, p, "data.conversation.delete", {"conversation_id": conversation_id})
        return JSONResponse({"status": "ok", "id": conversation_id})

    @app.patch("/v1/me/conversations/{conversation_id}")
    async def rename_my_conversation(conversation_id: str, body: dict, k=K, p=P) -> JSONResponse:
        conv = await k.store.get_conversation(p.tenant_id, conversation_id)
        if conv is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if conv.user_id != p.subject:
            return JSONResponse({"status": "denied", "reason": "not your conversation"},
                                status_code=403)
        title = body.get("title")
        title = title.strip() if isinstance(title, str) else ""
        if not title or len(title) > 120:
            return JSONResponse({"status": "error", "reason": "title must be 1-120 characters"},
                                status_code=400)
        conv.title = title
        conv.updated_at = utcnow()
        await k.store.update_conversation(conv)
        # keys-only audit: the length, never the title text (US-CONV-08)
        await _audit(k, p, "data.conversation.rename",
                     {"conversation_id": conversation_id, "title_len": len(title)})
        return JSONResponse({"status": "ok", "id": conversation_id})

    @app.post("/v1/me/conversations/{conversation_id}/messages/{message_id}/regenerate")
    async def regenerate_message(
        conversation_id: str, message_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        # Append-plus-supersede ([2026] VJS-COUNTY 4). Owner-only, fail-closed,
        # mirroring the delete route (D5): a scoped read role may READ a thread but
        # never regenerate it, so a non-owner is refused 403 with NO write.
        conv = await k.store.get_conversation(p.tenant_id, conversation_id)
        if conv is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if conv.user_id != p.subject:
            return JSONResponse({"status": "denied", "reason": "not your conversation"},
                                status_code=403)
        chat_svc = getattr(request.app.state, "chat", None)
        if chat_svc is None:
            return JSONResponse({"status": "error", "reason": "chat_unavailable"},
                                status_code=503)
        # Re-run the last user turn on a NEW run id through the ordinary audited
        # executor path, appending a fresh assistant reply. Eligibility is bounded to
        # the LAST assistant message (D6); RegenerateNotEligible (409) propagates to
        # the central handler with nothing written.
        new_message, superseded_id = await chat_svc.regenerate_turn(
            tenant_id=p.tenant_id, user_id=p.subject, role=p.role,
            conversation_id=conversation_id, target_message_id=message_id,
            grants=p.grants,
        )
        # THEN set the marker (D2), marker-only (D3), and audit the supersede keys
        # only - never any message content (D7).
        await k.store.mark_message_superseded(p.tenant_id, superseded_id, new_message.id)
        await _audit(k, p, "data.conversation.message.supersede",
                     {"conversation_id": conversation_id, "superseded": superseded_id,
                      "superseded_by": new_message.id, "run_id": new_message.run_id})
        # Harvest the free signal ([2026] VJS-COUNTY 5): a regenerate superseding a
        # reply is a NEGATIVE reuse signal for whatever produced it. Reweight-only,
        # under the caller's own ceiling, best-effort - it never fails the request
        # (P9) and can only change reuse likelihood, never grants/scope/tier.
        from boltrig.workflows import harvest_reuse_signal

        await harvest_reuse_signal(
            k, p.context(run_id=new_message.run_id),
            target=superseded_id, polarity="regression", kind="regenerate_superseded",
        )
        return JSONResponse({"status": "ok", "conversation_id": conversation_id,
                             "message_id": new_message.id, "superseded": superseded_id,
                             "run_id": new_message.run_id})

    @app.post("/v1/hitl/{question_id}/answer")
    async def answer_question(question_id: str, body: dict, k=K, p=P) -> JSONResponse:
        # Owner-only, fail-closed, audited answer to an agent's clarifying QUESTION
        # (US-CHAT-12), mirroring the regenerate / cancel pattern. This route answers
        # ONLY a QUESTION HITL - never an approval (those stay on the approvals panel
        # with their human / anti-self-approval checks, SEC-14), so a question can
        # never be laundered into clearing a gated verb.
        from boltrig.fleet.prompt_stack import wrap_untrusted
        from boltrig.models import HITLType

        req = await k.hitl.get(p.tenant_id, question_id)
        if req is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if req.type != HITLType.QUESTION:
            return JSONResponse({"status": "error", "reason": "not_a_question"},
                                status_code=409)
        # Owner = the run's owner (the owning work item's on_behalf_of), the same
        # identity the run was authorised under - a scoped-read role may SEE a run
        # but never answer for its owner. Fail closed with NO write and NO audit
        # when ownership cannot be confirmed (mirrors the cancel route).
        item = await k.store.get_work_item(p.tenant_id, req.work_item_id or req.run_id)
        if item is None or item.on_behalf_of != p.subject:
            return JSONResponse({"status": "denied", "reason": "not your run"},
                                status_code=403)
        raw = body.get("answer")
        answer = raw.strip() if isinstance(raw, str) else ""
        if not answer:
            return JSONResponse({"status": "error", "reason": "answer is required"},
                                status_code=400)
        # The answer is user-supplied, so it is enveloped as DATA before it is
        # recorded and replayed into the run (M1 / SEC-72): the resume wiring pushes
        # the recorded decision back into the paused run, so wrapping it here is what
        # guarantees the run never re-ingests raw inbound text as instructions.
        wrapped = wrap_untrusted("user_answer", p.subject, answer)
        resp = await k.hitl.answer(p.tenant_id, question_id, wrapped, p.subject)
        # keys-only audit: the length, never the answer text (K-20 / US-CONV-08).
        await _audit(k, p, "hitl.question.answer",
                     {"question_id": question_id, "run_id": req.run_id,
                      "answer_len": len(answer)})
        return JSONResponse({"status": "ok", "question_id": question_id,
                             "response_id": resp.id, "run_id": req.run_id})

    @app.post("/v1/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request, k=K, p=P) -> JSONResponse:
        # Server-side run cancellation ([2026] VJS-COUNTY 6, D5). Owner-only,
        # fail-closed, audited - mirroring the regenerate route: a scoped-read role
        # (org-admin/compliance) may READ a run's events but never cancel it, so a
        # non-owner is refused 403 with NO write and NO audit. Run ownership is the
        # owning work item's on_behalf_of (a chat turn's item id IS its run id; a
        # pumped item's run id is its own id), the same identity the run was
        # authorised under.
        item = await k.store.get_work_item(p.tenant_id, run_id)
        if item is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if item.on_behalf_of != p.subject:
            return JSONResponse({"status": "denied", "reason": "not your run"},
                                status_code=403)
        # Cooperative cancel (D2/D3): write the durable cancel-request signal the
        # pump consults at its next step boundary. The in-flight step/adapter is
        # never interrupted; the terminal CANCELLED state is written server-side by
        # the pump (in a finally). Keys-only audit: the run id, never any content.
        await k.store.request_run_cancel(p.tenant_id, run_id, p.subject)
        await _audit(k, p, "run.cancel", {"run_id": run_id})
        # If this run is a live chat turn, end its SSE stream cleanly (D5).
        chat_svc = getattr(request.app.state, "chat", None)
        if chat_svc is not None and hasattr(chat_svc, "cancel"):
            await chat_svc.cancel(run_id)
        return JSONResponse({"status": "ok", "run_id": run_id})

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
            return JSONResponse({"status": "error", "reason": "name is required"},
                                status_code=400)
        # the caller's current grants are the cap; record/refresh their user row so
        # the token resolves against current role/scope/status later (SEC-34).
        await ensure_user_record(k.store, p)
        pat, secret = await mint_pat(
            k.store, tenant_id=p.tenant_id, user_id=p.subject, name=name,
            requested_scope=body.get("scope"), user_grants=p.grants,
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
                "curl": (
                    f"curl -s {base}/v1/capabilities "
                    f"-H 'Authorization: Bearer <PAT>'"
                ),
            },
            "note": "Mint a token under Settings -> Developer & Connections; it is "
                    "scoped to your own grants and shown once.",
        }

    # === Security & Sessions (SET-70) ===
    @app.get("/v1/me/sessions")
    async def list_my_sessions(k=K, p=P) -> dict:
        sessions = await k.store.list_sessions(p.tenant_id, p.subject)
        return {"sessions": [
            {"id": s.id, "client": s.client, "revoked": s.revoked,
             "created_at": s.created_at.isoformat() if s.created_at else None,
             "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None}
            for s in sessions
        ]}

    @app.delete("/v1/me/sessions/{session_id}")
    async def revoke_my_session(session_id: str, k=K, p=P) -> JSONResponse:
        s = await k.store.get_session(p.tenant_id, session_id)
        if s is None or s.user_id != p.subject:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        s.revoked = True
        await k.store.update_session(s)
        await _audit(k, p, "session.revoke", {"id": session_id})
        return JSONResponse({"status": "ok", "id": session_id})

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
            return JSONResponse({"status": "error", "reason": "workspace_id is required"},
                                status_code=400)
        # Existence first (tenant-scoped): unknown workspace -> 404, no write.
        ws = await k.store.get_workspace(p.tenant_id, workspace_id)
        if ws is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        # Membership re-check (tenant-scoped): the caller must currently be a member
        # of this workspace. A non-member is refused 403 with NO write and NO audit.
        memberships = await k.store.list_workspaces_for_user(p.tenant_id, p.subject)
        if not any(w.id == workspace_id for w in memberships):
            return JSONResponse({"status": "denied", "reason": "not a member of that workspace"},
                                status_code=403)
        # Persist the new active workspace on the session (the resolver re-authorizes
        # it again on every subsequent request). Keys-only audit: the workspace id.
        session.active_workspace_id = workspace_id
        await k.store.update_session(session)
        await _audit(k, p, "session.active_context.switch", {"workspace_id": workspace_id})
        return JSONResponse({"status": "ok", "workspace_id": workspace_id})

    # === Per-org / workspace / user AI keys ([2026] VJS-COUNTY 8, D5) ===
    async def _authz_ai_key(k, p, level: str, scope_id: str):
        """Authorize a set/delete at ``level``/``scope_id``. Returns a 4xx JSONResponse
        on denial, else None. Role scoping (SEC-36):

          - org       : org-admin (the org may always set its OWN key).
          - workspace : org-admin, OR a workspace owner/admin of that workspace; AND
                        the org must allow own AI keys.
          - user      : org-admin, OR the caller acting on their OWN user; AND the org
                        must allow own AI keys.

        The allow_own_ai_keys gate is enforced at write time for workspace/user levels
        (a key that would be ignored at resolution is refused up front); the load-
        bearing guarantee is the resolution-time ignore in resolve_ai_key."""
        is_org_admin = p.role in _ADMIN_ROLES
        if level == "org":
            if not is_org_admin:
                return JSONResponse(
                    {"status": "denied", "reason": "org AI key requires org administration"},
                    status_code=403,
                )
            return None
        # workspace / user levels require the org to allow member-owned keys.
        org = await k.store.get_org(p.tenant_id)
        if org is None or not org.allow_own_ai_keys:
            return JSONResponse(
                {"status": "denied",
                 "reason": "organisation does not allow own AI keys"},
                status_code=403,
            )
        if level == "workspace":
            if is_org_admin:
                return None
            member = await k.store.get_workspace_member(p.tenant_id, scope_id, p.subject)
            if member is None or member.role not in _WORKSPACE_ADMIN_ROLES:
                return JSONResponse(
                    {"status": "denied",
                     "reason": "must be a workspace owner/admin to set its AI key"},
                    status_code=403,
                )
            return None
        # user level: the caller may only set their OWN user key (org-admin may set any).
        if not is_org_admin and scope_id != p.subject:
            return JSONResponse(
                {"status": "denied", "reason": "may only set your own user AI key"},
                status_code=403,
            )
        return None

    @app.get("/v1/ai-keys")
    async def list_ai_keys(k=K, p=P) -> dict:
        # The tenant's AI-config rows, provider/model + has_key only - NEVER the key.
        # Tenant-scoped by the store; the org allow_own flag rides along so a client
        # can render whether workspace/user keys are honoured.
        configs = await k.store.list_ai_configs(p.tenant_id)
        org = await k.store.get_org(p.tenant_id)
        return {
            "allow_own_ai_keys": bool(org.allow_own_ai_keys) if org else False,
            "ai_keys": [_ai_config_view(c) for c in configs],
        }

    @app.put("/v1/ai-keys")
    async def set_ai_key(body: dict, k=K, p=P) -> JSONResponse:
        # Set (or replace) an AI key at a level. The key is accepted ONCE and stored
        # ONLY through the sealed credential store (set_credential_ref); the ai_configs
        # row carries just the credential_ref, provider and model. The key is never
        # echoed back and never entered into the audit row (keys-only detail).
        level = str(body.get("level") or "").strip()
        if level not in AI_CONFIG_LEVELS:
            return JSONResponse(
                {"status": "error",
                 "reason": f"level must be one of {sorted(AI_CONFIG_LEVELS)}"},
                status_code=400,
            )
        # scope_id defaults sensibly per level: org -> the tenant_id, user -> the
        # caller. A workspace level requires an explicit workspace id.
        default_scope = {"org": p.tenant_id, "user": p.subject}.get(level)
        scope_id = str(body.get("scope_id") or default_scope or "").strip()
        if not scope_id:
            return JSONResponse({"status": "error", "reason": "scope_id is required"},
                                status_code=400)
        provider = str(body.get("provider") or "").strip()
        model = str(body.get("model") or "").strip()
        api_key = str(body.get("api_key") or "").strip()
        if not provider or not model or not api_key:
            return JSONResponse(
                {"status": "error", "reason": "provider, model and api_key are required"},
                status_code=400,
            )
        denied = await _authz_ai_key(k, p, level, scope_id)
        if denied is not None:
            return denied
        # Seal the key: store it through the credential store, keyed by an opaque
        # generated id. The raw key never lands in ai_configs (no plaintext column).
        credential_ref = f"cred_ai_{uuid.uuid4().hex[:16]}"
        await k.store.set_credential_ref(p.tenant_id, credential_ref, {"secret": api_key})
        await k.store.set_ai_config(AiConfig(
            tenant_id=p.tenant_id, level=level, scope_id=scope_id,
            provider=provider, model=model, credential_ref=credential_ref,
        ))
        # Keys-only audit: level/scope/provider/model + the credential REF id, NEVER
        # the api_key itself (SEC-05, K-20).
        await _audit(k, p, "ai_key.set", {
            "level": level, "scope_id": scope_id, "provider": provider,
            "model": model, "credential_ref": credential_ref,
        })
        return JSONResponse({"status": "ok", "level": level, "scope_id": scope_id,
                             "provider": provider, "model": model})

    @app.delete("/v1/ai-keys/{level}/{scope_id}")
    async def delete_ai_key(level: str, scope_id: str, k=K, p=P) -> JSONResponse:
        if level not in AI_CONFIG_LEVELS:
            return JSONResponse({"status": "error", "reason": "unknown level"},
                                status_code=400)
        denied = await _authz_ai_key(k, p, level, scope_id)
        if denied is not None:
            return denied
        existing = await k.store.get_ai_config(p.tenant_id, level, scope_id)
        if existing is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        # Drop the config row and the sealed credential together.
        await k.store.delete_ai_config(p.tenant_id, level, scope_id)
        await k.store.set_credential_ref(p.tenant_id, existing.credential_ref, {})
        await _audit(k, p, "ai_key.delete", {"level": level, "scope_id": scope_id})
        return JSONResponse({"status": "ok", "level": level, "scope_id": scope_id})

    # === Notifications (per-user, hosts SET-30) ===
    @app.get("/v1/me/notifications")
    async def my_notifications(k=K, p=P) -> dict:
        prefs = await k.store.list_notification_prefs(p.tenant_id)
        mine = [
            {"id": n.id, "event_type": n.event_type, "channel": n.channel,
             "target": n.target, "enabled": n.enabled}
            for n in prefs if n.scope_kind == "user" and n.scope_ref == p.subject
        ]
        return {"prefs": mine}

    @app.put("/v1/me/notifications")
    async def put_my_notifications(body: dict, k=K, p=P) -> JSONResponse:
        pref = NotificationPref(
            id=body.get("id") or uuid.uuid4().hex, tenant_id=p.tenant_id,
            scope_kind="user", scope_ref=p.subject,
            event_type=body["event_type"], channel=body["channel"],
            target=body.get("target"), enabled=body.get("enabled", True),
        )
        await k.store.upsert_notification_pref(pref)
        await _audit(k, p, "settings.notifications.update",
                     {"event_type": pref.event_type, "channel": pref.channel})
        return JSONResponse({"status": "ok", "id": pref.id})

    # === Personal agent (GET; configure POST lives in the platform routes) ===
    @app.get("/v1/me/agent")
    async def my_agent(k=K, p=P) -> dict:
        agent = await k.store.get_personal_agent(p.tenant_id, p.subject)
        if agent is None:
            return {"agent": None}
        return {"agent": {"id": agent.id, "runtime": agent.runtime,
                          "skills": list(agent.skills), "enabled": agent.enabled}}

    # === Organisation administration: user directory & invitations (US-USR-02/03) ===
    @app.get("/v1/admin/users")
    async def list_directory(k=K, p=P) -> JSONResponse:
        _require_admin(p)
        users = await k.store.list_users(p.tenant_id)
        return JSONResponse({"users": [_user_view(u) for u in users]})

    @app.patch("/v1/admin/users/{user_id}")
    async def update_user(user_id: str, body: dict, k=K, p=P) -> JSONResponse:
        _require_admin(p)
        _reject_escalation(p, body.get("role"), body.get("scope"))
        user = await k.store.get_user(p.tenant_id, user_id)
        if user is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if "role" in body:
            user.role = body["role"]
        if "scope" in body and isinstance(body["scope"], dict):
            user.scope = body["scope"]
        if "status" in body and body["status"] in ("active", "deactivated"):
            user.status = body["status"]  # deactivate => immediate revoke (US-USR-03)
        await k.store.upsert_user(user)
        await _audit(k, p, "admin.user.update",
                     {"user": user_id, "role": user.role, "status": user.status})
        return JSONResponse({"status": "ok", "user": _user_view(user)})

    @app.get("/v1/admin/invitations")
    async def list_invites(k=K, p=P) -> JSONResponse:
        _require_admin(p)
        invites = await k.store.list_invitations(p.tenant_id)
        return JSONResponse({"invitations": [
            {"id": i.id, "email": i.email, "intended_role": i.intended_role,
             "intended_scope": i.intended_scope, "status": i.status,
             "invited_by": i.invited_by,
             "workspace_id": i.workspace_id,
             "provision_workspace_name": i.provision_workspace_name,
             "provision_org_name": i.provision_org_name,
             "expires_at": i.expires_at.isoformat() if i.expires_at else None}
            for i in invites
        ]})

    @app.post("/v1/admin/invitations")
    async def create_invite(body: dict, k=K, p=P) -> JSONResponse:
        from boltrig.identity.invites import generate_invite_token, hash_invite_token
        from boltrig.identity.tokens import bounded_expiry

        _require_admin(p)
        _reject_escalation(p, body.get("role"), body.get("scope"))
        email = (body.get("email") or "").strip()
        if not email:
            return JSONResponse({"status": "error", "reason": "email is required"},
                                status_code=400)
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
        # Mint a single-use invite-token secret for first-party invite-only login
        # ([2026] VJS-COUNTY 7, D1): store ONLY its hash; return the secret ONCE so
        # the admin can hand the invitee an accept-invite link. Mirrors the SEC-34
        # PAT pattern (hashed at rest, bounded by the invitation's own expiry,
        # revocable via the revoke route). SSO-only deployments simply ignore it.
        invite_secret = generate_invite_token()
        inv = UserInvitation(
            id=uuid.uuid4().hex, tenant_id=p.tenant_id, email=email,
            intended_role=body.get("role", "agent"),
            intended_scope=body.get("scope", {}),
            invited_by=p.subject,
            expires_at=bounded_expiry(utcnow(), body.get("ttl_days", 14)),
            token_hash=hash_invite_token(invite_secret),
            workspace_id=workspace_id,
            provision_workspace_name=provision_workspace_name,
            provision_org_name=provision_org_name,
        )
        await k.store.add_invitation(inv)
        # Keys-only audit: email + role + the (non-secret) scope keys, never the
        # invite secret (D8).
        await _audit(k, p, "admin.invite.create", {
            "email": email, "role": inv.intended_role,
            "workspace_id": workspace_id,
            "provision_workspace": provision_workspace_name is not None,
            "provision_org": provision_org_name is not None,
        })
        return JSONResponse({"status": "ok", "id": inv.id, "email": email,
                             "invite_token": invite_secret})

    @app.delete("/v1/admin/invitations/{invite_id}")
    async def revoke_invite(invite_id: str, k=K, p=P) -> JSONResponse:
        _require_admin(p)
        inv = await k.store.get_invitation(p.tenant_id, invite_id)
        if inv is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        inv.status = "revoked"
        await k.store.update_invitation(inv)
        await _audit(k, p, "admin.invite.revoke", {"id": invite_id})
        return JSONResponse({"status": "ok", "id": invite_id})

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
    async def update_current_org(body: dict, k=K, p=P) -> JSONResponse:
        # Org-admin only, fail-closed + audited: rename / settings / toggle the
        # allow_own_ai_keys + require_two_factor policy flags. A non-admin is refused
        # 403 with NO write by _require_admin (it raises GrantMissing -> 403).
        from boltrig.identity.tenancy import ensure_default_org

        _require_admin(p)
        # Ensure a row exists to update (idempotent backfill for a pre-COUNTY-8 tenant).
        org = await ensure_default_org(k.store, p.tenant_id)
        if "name" in body and isinstance(body["name"], str) and body["name"].strip():
            org.name = body["name"].strip()
        if "slug" in body and isinstance(body["slug"], str) and body["slug"].strip():
            org.slug = body["slug"].strip()
        if "settings" in body and isinstance(body["settings"], dict):
            org.settings = body["settings"]
        if "allow_own_ai_keys" in body:
            org.allow_own_ai_keys = bool(body["allow_own_ai_keys"])
        if "require_two_factor" in body:
            org.require_two_factor = bool(body["require_two_factor"])
        await k.store.update_org(org)
        await _audit(k, p, "org.update", {
            "allow_own_ai_keys": org.allow_own_ai_keys,
            "require_two_factor": org.require_two_factor,
        })
        return JSONResponse({"status": "ok", "organisation": _org_view(org)})

    @app.get("/v1/orgs/current/members")
    async def list_current_org_members(k=K, p=P) -> JSONResponse:
        # The org's membership roster (tenant-scoped by the store). Available to any
        # authenticated caller in the tenant so a workspace owner can populate an
        # add-member picker; it is their own org, never crosses a tenant boundary.
        members = await k.store.list_org_members(p.tenant_id)
        return JSONResponse({"members": [_org_member_view(m) for m in members]})

    # === Workspace management ([2026] VJS-COUNTY 8, D6) ===
    @app.get("/v1/workspaces")
    async def list_my_workspaces(k=K, p=P) -> JSONResponse:
        # The caller's OWN workspaces (their memberships), tenant-scoped. Never lists
        # a workspace the caller is not a member of.
        workspaces = await k.store.list_workspaces_for_user(p.tenant_id, p.subject)
        return JSONResponse({"workspaces": [_workspace_view(w) for w in workspaces]})

    @app.post("/v1/workspaces")
    async def create_workspace(body: dict, k=K, p=P) -> JSONResponse:
        # Create a workspace in the caller's org. Org-admin / owner only (creating a
        # workspace is an org-level act); a non-admin is refused 403 with NO write.
        # The creator is seated as the workspace OWNER so they can manage it at once.
        _require_admin(p)
        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse({"status": "error", "reason": "name is required"},
                                status_code=400)
        ws = Workspace(
            id=uuid.uuid4().hex, tenant_id=p.tenant_id, name=name,
            slug=_workspace_slug(name),
            settings=body.get("settings") if isinstance(body.get("settings"), dict) else {},
        )
        await k.store.create_workspace(ws)
        await k.store.add_workspace_member(WorkspaceMember(
            user_id=p.subject, workspace_id=ws.id, tenant_id=p.tenant_id, role="owner",
        ))
        await _audit(k, p, "workspace.create", {"workspace_id": ws.id, "slug": ws.slug})
        return JSONResponse({"status": "ok", "workspace": _workspace_view(ws)})

    @app.patch("/v1/workspaces/{workspace_id}")
    async def update_workspace(workspace_id: str, body: dict, k=K, p=P) -> JSONResponse:
        # Rename / settings / archive. Fail-closed: a caller who is neither an
        # org-admin nor an owner/admin of THIS workspace is refused (404 unknown, 403
        # non-manager) with NO write.
        ws, denied = await _authz_manage_workspace(k, p, workspace_id)
        if denied is not None:
            return denied
        if "name" in body and isinstance(body["name"], str) and body["name"].strip():
            ws.name = body["name"].strip()
        if "settings" in body and isinstance(body["settings"], dict):
            ws.settings = body["settings"]
        if "status" in body and body["status"] in ("active", "archived"):
            ws.status = body["status"]
        await k.store.update_workspace(ws)
        await _audit(k, p, "workspace.update",
                     {"workspace_id": ws.id, "status": ws.status})
        return JSONResponse({"status": "ok", "workspace": _workspace_view(ws)})

    @app.get("/v1/workspaces/{workspace_id}/members")
    async def list_workspace_members(workspace_id: str, k=K, p=P) -> JSONResponse:
        # The workspace roster. Readable by an org-admin or a member of the workspace;
        # a non-member non-admin is refused 403 (fail-closed) with nothing disclosed.
        ws = await k.store.get_workspace(p.tenant_id, workspace_id)
        if ws is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if p.role not in _ADMIN_ROLES:
            member = await k.store.get_workspace_member(p.tenant_id, workspace_id, p.subject)
            if member is None:
                return JSONResponse(
                    {"status": "denied", "reason": "not a member of that workspace"},
                    status_code=403,
                )
        members = await k.store.list_workspace_members(p.tenant_id, workspace_id)
        return JSONResponse({"members": [_workspace_member_view(m) for m in members]})

    @app.post("/v1/workspaces/{workspace_id}/members")
    async def add_workspace_member(workspace_id: str, body: dict, k=K, p=P) -> JSONResponse:
        # Add an EXISTING org user to the workspace with a per-workspace role. Manage
        # rights required (org-admin or workspace owner/admin) - fail-closed 403 with
        # NO write otherwise. The role must be one of WORKSPACE_ROLES (400 otherwise);
        # the target user must exist in the org (404 otherwise).
        ws, denied = await _authz_manage_workspace(k, p, workspace_id)
        if denied is not None:
            return denied
        user_id = (body.get("user_id") or "").strip()
        role = (body.get("role") or "member").strip()
        if not user_id:
            return JSONResponse({"status": "error", "reason": "user_id is required"},
                                status_code=400)
        if role not in WORKSPACE_ROLES:
            return JSONResponse(
                {"status": "error", "reason": f"role must be one of {sorted(WORKSPACE_ROLES)}"},
                status_code=400,
            )
        target = await k.store.get_user(p.tenant_id, user_id)
        if target is None:
            return JSONResponse({"status": "error", "reason": "unknown user"},
                                status_code=404)
        member = WorkspaceMember(
            user_id=user_id, workspace_id=workspace_id, tenant_id=p.tenant_id, role=role,
            permissions=body.get("permissions") if isinstance(body.get("permissions"), dict) else {},
        )
        await k.store.add_workspace_member(member)
        await _audit(k, p, "workspace.member.add",
                     {"workspace_id": workspace_id, "user": user_id, "role": role})
        return JSONResponse({"status": "ok", "member": _workspace_member_view(member)})

    @app.delete("/v1/workspaces/{workspace_id}/members/{user_id}")
    async def remove_workspace_member(
        workspace_id: str, user_id: str, k=K, p=P
    ) -> JSONResponse:
        # Remove a member. Manage rights required - fail-closed 403 with NO write
        # otherwise (404 for an unknown workspace).
        ws, denied = await _authz_manage_workspace(k, p, workspace_id)
        if denied is not None:
            return denied
        await k.store.remove_workspace_member(p.tenant_id, workspace_id, user_id)
        await _audit(k, p, "workspace.member.remove",
                     {"workspace_id": workspace_id, "user": user_id})
        return JSONResponse({"status": "ok", "workspace_id": workspace_id, "user": user_id})
