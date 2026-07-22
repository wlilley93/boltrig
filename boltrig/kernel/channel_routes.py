"""Channel HTTP surface (decision 0003: the webhook / request-response class
in-kernel; the socket class re-enters over the severed gateway at the SAME
intake route - Phase 2 skeleton).

Two kinds of route:
  - Management (admin-gated, authenticated by the normal principal): list the
    tenant's channels. connect/configure/disconnect land with the console beat
    (they need a kernel-side credential write).
  - Ingress (NO principal - authenticated by the channel's own signature): a
    signed inbound webhook. The tenant is resolved from the verified channel, the
    sender from a tenant-scoped binding, and the message becomes a governed
    work-item intake. The identical terminal seam every channel shares:
        verify -> sender->Principal -> normalise(tenant from binding) -> intake.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from boltrig.adapters.builtin.inbound_webhook import (
    WebhookAuthError,
    WebhookValidationError,
    is_duplicate_delivery,
    verify_and_normalise,
)
from boltrig.models import (
    ActionType,
    AuditEvent,
    ChannelBinding,
    ChannelOutboxMessage,
    HITLStateConflict,
    HITLType,
    RateLimit,
    RateLimited,
    utcnow,
)
from boltrig.work.normalise import normalise

from .channel_principal import (
    CHANNEL_TIERS,
    SELF_ONBOARD_ROLES,
    resolve_channel_principal,
    self_onboard_subject,
)
from .control_routes import dispatch_control_route
from .hitl_http import answer_hitl_question, respond_to_hitl
from .hitl_response_auth import related_work_item

# The pairing flow (decision 0003): one-time codes are short, human-transcribable,
# hashed at rest (SEC-05), TTL-bounded, lockout-guarded. They bind an unknown
# external sender to an internal identity; consumption is single-use.
PAIR_TTL_MINUTES = 15
PAIR_MAX_TTL_MINUTES = 60
PAIR_MAX_ATTEMPTS = 5

# Inbound intake rate limits (M5). Each accepted inbound mints a work item that can
# drive model spend, so the intake is throttled BEFORE create_work_item on two
# axes: per-channel (a firehose channel), and per-(channel, sender) (one abusive
# sender). Fixed-window via the existing kernel RateLimiter, keyed by a synthetic
# verb id so the counter isolates each axis. Follow-on: a per-tenant intake budget
# for cross-channel fairness (#81).
INBOUND_RL_PER_CHANNEL = RateLimit(per="minute", max=120, scope="verb")
INBOUND_RL_PER_SENDER = RateLimit(per="minute", max=30, scope="verb")

# Self-serve onboarding (SEC-180) is throttled per channel BEFORE a binding is
# minted (the same fixed-window idiom as intake above): an open, customer-facing
# channel must not let strangers mint unbounded synthetic identities.
ONBOARD_RL_PER_CHANNEL = RateLimit(per="minute", max=5, scope="verb")


def _hash_code(code: str) -> str:
    """The at-rest representation of a pairing code: sha256, never plaintext."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


async def _channel_secret(kernel, ref: dict | None) -> str | None:
    """Resolve a channel's webhook signing secret from its credential ref row.

    Doctrine: the app DB holds REFERENCES only - a ``{store, ref}`` row resolved
    through the kernel's SecretStore seam (SEC-04/05). A legacy inline
    ``{"secret": ...}`` row (written before the reference path existed) is still
    honored so already-connected channels keep working; new connections should
    carry a reference."""
    if not ref:
        return None
    if ref.get("ref"):
        try:
            material = await kernel.credentials.fetch_material(ref)
        except Exception:  # an unresolvable reference fails closed below
            return None
        return material.get("secret") or material.get("value")
    return ref.get("secret")


# Addressing (decision 0003, Phase 2): which agent a channel message is routed
# TO. This is routing DATA, never authority - identity stays kernel-authoritative
# via the binding rows; the target only steers which agent picks the item up.
# Resolution order (first hit wins):
#   1. an explicit ``target`` the VERIFIED sender put on the message (custom
#      surfaces - the desktop familiar, hey-nabu, sites - address directly);
#   2. the channel's config mapping ``addressing.routes`` (chat/thread id ->
#      target), so a platform chat can be pinned to a subagent;
#   3. ``addressing.default_target`` on the channel, else "cos" (the tier-1
#      chief of staff - today's behaviour, so unconfigured channels are unchanged).
# A target is a short slug; anything longer/else is ignored (fail to default,
# never to an error - a malformed address must not drop a verified message).
DEFAULT_TARGET = "cos"
_TARGET_FIELDS = ("chat", "thread", "channel", "chat_id", "thread_id")


def _clean_target(value) -> str | None:
    """A target slug or None: short, safe-charset routing data."""
    import re

    slug = str(value or "").strip()
    return slug if re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", slug) else None


def _resolve_addressing(ch, body: dict) -> tuple[str, dict]:
    """Resolve (target, reply_route) for an inbound message.

    The reply_route is the way BACK for round-trip integrity (SEC-179): the
    channel, thread and sender the triggering message came from, so a reply or
    a run-completion notification returns to the same surface/thread."""
    addressing = (ch.config or {}).get("addressing") or {}
    thread_field = addressing.get("thread_field")
    thread_id = ""
    for field_name in ([thread_field] if thread_field else []) + [
        f for f in _TARGET_FIELDS if f != thread_field
    ]:
        value = body.get(field_name)
        if value is not None and str(value).strip():
            thread_id = str(value).strip()
            break
    target = _clean_target(body.get("target"))
    if target is None and thread_id:
        target = _clean_target((addressing.get("routes") or {}).get(thread_id))
    if target is None:
        target = _clean_target(addressing.get("default_target")) or DEFAULT_TARGET
    reply_route = {"channel_id": ch.id, "thread": thread_id or None, "sender": None}
    return target, reply_route


# --------------------------------------------------------------------------- #
# Channel-native HITL replies (SEC-14 the approval/question separation, SEC-179
# the round-trip): a BOUND sender answers a pending approval/question from the
# channel itself. Explicit commands work from anywhere; a plain reply answers a
# QUESTION only when it is unambiguous - EXACTLY ONE pending item addressed to
# that sender in that thread. Anything else is a normal message, never a guess.
# --------------------------------------------------------------------------- #
_HITL_COMMANDS = ("approve", "deny", "answer")


def _parse_hitl_command(text: str) -> tuple[str, str, str] | None:
    """Parse ``/approve <id>`` | ``/deny <id>`` | ``/answer <id> <text>``.

    Returns (command, request_id, remainder). A recognised verb with missing
    arguments returns ("usage", verb, "") so the caller can answer with a usage
    error rather than guess; any other text (including other slash-commands) is
    NOT a HITL command and falls through to normal intake."""
    if not text.startswith("/"):
        return None
    verb, _, rest = text[1:].partition(" ")
    if verb not in _HITL_COMMANDS:
        return None
    request_id, _, remainder = rest.strip().partition(" ")
    if not request_id or (verb == "answer" and not remainder.strip()):
        return ("usage", verb, "")
    return (verb, request_id, remainder.strip())


def _hitl_addressed_to(req, subject: str) -> bool:
    """A pending request is 'addressed to' a sender only when it NAMES them:
    the explicit assignee, or - unassigned - the human it was raised on behalf
    of (the same subject the request notification resolves to). Anything looser
    would be a guess about who may answer."""
    if req.assignee:
        return req.assignee == subject
    return bool(subject) and req.requested_on_behalf_of == subject


async def _sole_pending_for(kernel, ch, subject: str, thread: str):
    """The EXACTLY-ONE pending HITL request addressed to ``subject`` whose work
    item's reply route is this channel+thread, else None: zero matches (nothing
    to answer) or several (ambiguous) both fall back to normal intake. A SECURE
    question (SEC-181) is never matched - its answer must be sealed via the
    secure-input surface, never typed into a chat."""
    if not thread:
        return None
    matches = []
    for req in await kernel.hitl.list_pending(ch.tenant_id):
        if getattr(req, "secure", False) or not _hitl_addressed_to(req, subject):
            continue
        item = await related_work_item(kernel, req)
        route = getattr(item, "reply_route", None) or {}
        if route.get("channel_id") == ch.id and route.get("thread") == thread:
            matches.append(req)
    return matches[0] if len(matches) == 1 else None


async def _is_secure_question(kernel, tenant_id: str, request_id: str) -> bool:
    """SEC-181 adjacency: a SECURE question's answer is sealed as a
    run/purpose-scoped credential reference by the secure-input surface; a
    channel reply is plaintext chat and must never feed it."""
    req = await kernel.hitl.get(tenant_id, request_id)
    return bool(req is not None and getattr(req, "secure", False))


async def _hitl_reply_response(
    kernel, ch, principal, external_user_id: str, body: dict, reply_route: dict
) -> JSONResponse | None:
    """Route a bound sender's HITL reply through the SHARED respond/answer logic
    (hitl_http) AS THAT PRINCIPAL - approver eligibility is exactly what
    hitl_response_auth enforces on the API, so a non-approver gets the same
    fail-closed denial here. Returns the intake response when the message was
    consumed as a HITL reply (a confirmation or the denial), or None when the
    message is ordinary intake."""
    text = str(body.get("text") or "").strip()
    if not text:
        return None
    command = _parse_hitl_command(text)
    if command is None:
        # Implicit reply: unambiguous only - exactly one pending item addressed
        # to this sender in this thread, and it must be a QUESTION (a plain
        # message can never decide an approval: explicit /approve|/deny only).
        req = await _sole_pending_for(
            kernel, ch, principal.subject, reply_route.get("thread") or ""
        )
        if req is None or req.type != HITLType.QUESTION:
            return None
        verb, request_id, answer = "answer", req.id, text
    elif command[0] == "usage":
        return JSONResponse(
            {"status": "error",
             "reason": f"usage: /{command[1]} <request_id>"
                       + (" <text>" if command[1] == "answer" else "")},
            status_code=400,
        )
    else:
        verb, request_id, answer = command
    try:
        if verb == "answer":
            if await _is_secure_question(kernel, ch.tenant_id, request_id):
                return JSONResponse(
                    {"status": "denied", "reason": "secure questions use secure input"},
                    status_code=403,
                )
            outcome = await answer_hitl_question(kernel, principal, request_id, answer)
            detail = {"channel": ch.id, "request": request_id, "kind": "answer",
                      "answer_len": outcome["answer_len"]}
        else:
            decision = "approve" if verb == "approve" else "reject"
            outcome = await respond_to_hitl(kernel, principal, request_id, decision, "")
            detail = {"channel": ch.id, "request": request_id, "kind": verb}
    except HTTPException as exc:  # the SAME fail-closed denial the API returns
        status = exc.status_code if 400 <= exc.status_code < 500 else 403
        return JSONResponse(
            {"status": "denied", "reason": str(exc.detail)}, status_code=status
        )
    except HITLStateConflict as exc:  # already answered/consumed - never reusable
        return JSONResponse({"status": "denied", "reason": str(exc)}, status_code=409)
    # audit-always, keys-only (the decision kind and answer length, never text)
    await kernel.audit.write(
        AuditEvent(
            tenant_id=ch.tenant_id, ts=utcnow(), actor=principal.subject,
            actor_tier="human", action_type=ActionType.TOOL_CALL, noun="channel",
            verb="channel.hitl.reply", status="ok",
            on_behalf_of=principal.on_behalf_of, detail=detail,
        )
    )
    # Confirm the outcome back on the originating surface/thread (SEC-179):
    # the socket class gets a durable outbox row; the webhook class's
    # confirmation is this intake response body.
    if ch.transport == "socket":
        await kernel.store.enqueue_channel_outbox(
            ChannelOutboxMessage(
                id=f"co_{uuid.uuid4().hex[:16]}", tenant_id=ch.tenant_id,
                channel_id=ch.id,
                payload={"text": f"HITL {detail['kind']} recorded for {request_id}",
                         "target": reply_route.get("thread") or external_user_id,
                         "event": "hitl_reply", "subject": principal.subject},
            )
        )
    return JSONResponse(
        {"status": "ok", "hitl_reply": detail["kind"], "request": request_id,
         "response_id": outcome["response_id"]},
        status_code=200,
    )


async def _audit(kernel, p, verb: str, detail: dict, status: str = "ok") -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=p.tenant_id, ts=utcnow(), actor=p.subject, actor_tier=p.actor_tier,
            action_type=ActionType.TOOL_CALL, noun="channel", verb=verb, status=status,
            on_behalf_of=p.on_behalf_of, detail=detail,
        )
    )


async def _self_onboard(kernel, channel, external_user_id: str):
    """Opt-in self-serve onboarding for a customer-facing channel (SEC-180).

    When the channel's config carries ``self_onboard`` with a CONSTRAINED role
    (``SELF_ONBOARD_ROLES`` - never above member), an unknown VERIFIED sender is
    bound at that role/scope as a synthetic ``external:<platform>:<id>`` subject
    with NO user record (the honest minimum: identity is still a kernel-minted
    binding row, never the message body). The onboarding is a first-class audited
    event, is rate-limited per channel before anything is minted (``RateLimited``
    propagates to the caller's 429), and enqueues the configured static welcome
    to the durable outbox (socket class only - the webhook class has no outbox
    consumer). Returns the freshly-resolved Principal, or ``None`` when the
    channel does not opt in or its config role is over-broad (fail-closed)."""
    cfg = (channel.config or {}).get("self_onboard")
    if not isinstance(cfg, dict):
        return None
    role = str(cfg.get("role") or "").strip()
    if role not in SELF_ONBOARD_ROLES:
        return None  # an over-broad config role disables onboarding, fail-closed
    if await kernel.store.get_channel_binding(
        channel.tenant_id, channel.id, external_user_id
    ) is not None:
        # A binding EXISTS but resolved to no principal (an unknown tier, or a
        # deactivated user): onboarding must never mint a fresh synthetic
        # identity over it - that would resurrect a revoked sender.
        return None
    await kernel.rate_limiter.enforce(
        channel.tenant_id, f"channel.onboard:{channel.id}", ONBOARD_RL_PER_CHANNEL
    )
    subject = self_onboard_subject(channel.platform, external_user_id)
    await kernel.store.upsert_channel_binding(
        ChannelBinding(
            id=f"cb_{uuid.uuid4().hex[:12]}", tenant_id=channel.tenant_id,
            channel_id=channel.id, platform=channel.platform,
            external_user_id=external_user_id, subject=subject, role=role,
        )
    )
    await kernel.audit.write(
        AuditEvent(
            tenant_id=channel.tenant_id, ts=utcnow(), actor=subject,
            actor_tier="human", action_type=ActionType.TOOL_CALL, noun="channel",
            verb="channel.self_onboard", status="ok",
            detail={"channel": channel.id, "platform": channel.platform,
                    "external_user_id": external_user_id, "subject": subject,
                    "role": role},
        )
    )
    welcome = str(cfg.get("welcome") or "").strip()
    if welcome and channel.transport == "socket":
        await kernel.store.enqueue_channel_outbox(
            ChannelOutboxMessage(
                id=f"co_{uuid.uuid4().hex[:16]}", tenant_id=channel.tenant_id,
                channel_id=channel.id,
                payload={"text": welcome, "target": external_user_id,
                         "event": "channel.self_onboard", "subject": subject},
            )
        )
    return await resolve_channel_principal(kernel.store, channel, external_user_id)


async def _consume_pairing(kernel, channel, external_user_id, code) -> bool:
    """Consume a one-time pairing code for an unbound sender (decision 0003).

    Enforces the full pairing contract: TTL expiry, wrong-code lockout (attempts
    cap -> expired), and single-use consume. On a successful consume it mints the
    binding the pairing authorised. Returns True if the sender is now bound."""
    pairing = await kernel.store.get_pending_pairing_for_sender(
        channel.tenant_id, channel.id, external_user_id
    )
    if pairing is None:
        return False  # no pending pairing for this sender
    if pairing.expires_at is not None and pairing.expires_at <= utcnow():
        return False  # expired (TTL or lockout)
    if _hash_code(code) != pairing.code_hash:
        # wrong code -> bump attempts; lockout flips status to 'expired' at the cap.
        await kernel.store.bump_channel_pairing_attempts(
            channel.tenant_id, pairing.id, cap=PAIR_MAX_ATTEMPTS
        )
        return False
    if not await kernel.store.consume_channel_pairing(channel.tenant_id, pairing.id):
        return False  # raced / already consumed (single-use CAS)
    binding = ChannelBinding(
        id=f"cb_{uuid.uuid4().hex[:12]}", tenant_id=channel.tenant_id,
        channel_id=channel.id, platform=channel.platform,
        external_user_id=external_user_id, subject=pairing.subject, role=pairing.role,
    )
    await kernel.store.upsert_channel_binding(binding)
    await kernel.audit.write(
        AuditEvent(
            tenant_id=channel.tenant_id, ts=utcnow(), actor=pairing.subject,
            actor_tier="human", action_type=ActionType.TOOL_CALL, noun="channel",
            verb="channel.pair.consume", status="ok",
            detail={"channel": channel.id, "external_user_id": external_user_id,
                    "subject": pairing.subject, "pairing": pairing.id},
        )
    )
    return True


def register_channel_routes(app, *, principal_dep, get_kernel) -> None:
    from boltrig.identity.rbac import _role_rank, can_author

    P = Depends(principal_dep)
    K = Depends(get_kernel)

    def _role_clamp(p, role: str) -> JSONResponse | None:
        """Role-rank clamp (parity with access_routes._reject_escalation, SEC-102):
        no principal may bind an external sender to a channel role ranked above
        its own - an admin must not mint a superadmin channel identity."""
        if _role_rank(role) < _role_rank(p.role):
            return JSONResponse(
                {"status": "denied", "reason": "cannot bind a role ranked above your own"},
                status_code=403,
            )
        return None

    @app.get("/v1/channels")
    async def list_channels(k=K, p=P) -> JSONResponse:
        if not can_author(p.role):
            return JSONResponse({"status": "denied", "reason": "admin only"}, status_code=403)
        chans = await k.store.list_channels(p.tenant_id)
        return JSONResponse(
            {
                "channels": [
                    {
                        "id": c.id, "platform": c.platform, "name": c.name,
                        "transport": c.transport, "enabled": c.enabled,
                        "unpaired_behavior": c.unpaired_behavior,
                    }
                    for c in chans
                ]
            }
        )

    @app.post("/v1/channels/{channel_id}/inbound")
    async def channel_inbound(channel_id: str, body: dict, request: Request, k=K) -> JSONResponse:
        # 1. resolve the channel by its unguessable id (tenant comes from HERE).
        # ONE intake path for BOTH transport classes (decision 0003): webhook
        # platforms call this directly; a socket-class event reaches the same
        # route via the severed gateway, which signs with the same connect-time
        # secret the kernel resolves below - nothing built for Phase 1 changes.
        ch = await k.store.get_channel_by_id(channel_id)
        if ch is None or not ch.enabled or ch.transport not in ("webhook", "socket"):
            return JSONResponse({"error": "unknown_channel"}, status_code=404)

        # 2. resolve the signing secret kernel-side (SEC-05), never from the body.
        # Fail CLOSED when the channel has no resolvable secret: without one the
        # signature check is skipped entirely and intake would proceed on the
        # unguessable channel id alone.
        ref = None
        if ch.credential_ref:
            ref = await k.store.get_credential_ref(ch.tenant_id, ch.credential_ref)
        secret = await _channel_secret(k, ref)
        if not secret:
            return JSONResponse({"error": "channel_misconfigured"}, status_code=503)

        # 3. verify the signature at the edge, before acting on the body. The
        # verified candidate carries the delivery id used for replay dedup (M3).
        try:
            candidate = verify_and_normalise(body, dict(request.headers), secret)
        except WebhookAuthError:
            return JSONResponse({"status": "denied", "reason": "signature"}, status_code=401)
        except WebhookValidationError as exc:
            return JSONResponse({"status": "error", "reason": str(exc)}, status_code=400)

        # 4. bind the tenant from the VERIFIED channel (RLS + K-3)
        from boltrig.store.postgres import set_current_tenant

        set_current_tenant(ch.tenant_id)

        # 5. map the verified sender -> a governed Principal (kernel-authoritative)
        sender_field = ch.config.get("sender_field", "sender")
        external_user_id = str(body.get(sender_field) or "").strip()
        if not external_user_id:
            return JSONResponse({"status": "error", "reason": "no sender"}, status_code=400)
        principal = await resolve_channel_principal(k.store, ch, external_user_id)
        if principal is None:
            # unpaired sender. If the channel is in 'pair' mode and the message
            # carries a pairing code, consume it (expiry + wrong-code lockout) and
            # bind the sender, then proceed as the now-bound principal. Otherwise
            # apply the channel's configured behaviour (fail-closed default).
            if ch.unpaired_behavior == "pair":
                code = str(body.get("pairing_code") or "").strip()
                if code and await _consume_pairing(k, ch, external_user_id, code):
                    principal = await resolve_channel_principal(
                        k.store, ch, external_user_id
                    )
            if principal is None:
                # SEC-180: an opted-in channel onboards the stranger itself, at
                # the configured CONSTRAINED role (rate-limited per channel).
                try:
                    principal = await _self_onboard(k, ch, external_user_id)
                except RateLimited as exc:
                    headers = {}
                    if exc.retry_after_seconds is not None:
                        headers["Retry-After"] = str(int(exc.retry_after_seconds))
                    return JSONResponse(
                        {"status": "throttled", "reason": "onboarding rate limit"},
                        status_code=429,
                        headers=headers,
                    )
            if principal is None:
                if ch.unpaired_behavior == "ignore":
                    return JSONResponse({"status": "ignored"}, status_code=200)
                return JSONResponse(
                    {"status": "denied", "reason": "sender not paired"}, status_code=403
                )

        # 6. intake rate limit BEFORE minting a work item (M5): throttle per-channel
        # and per-(channel, sender) so an abusive channel or sender cannot drive
        # unbounded model spend. On the limit, return 429 and create nothing.
        try:
            await k.rate_limiter.enforce(
                ch.tenant_id, f"channel.inbound:{ch.id}", INBOUND_RL_PER_CHANNEL
            )
            await k.rate_limiter.enforce(
                ch.tenant_id, f"channel.inbound:{ch.id}:{external_user_id}", INBOUND_RL_PER_SENDER
            )
        except RateLimited as exc:
            headers = {}
            if exc.retry_after_seconds is not None:
                headers["Retry-After"] = str(int(exc.retry_after_seconds))
            return JSONResponse(
                {"status": "throttled", "reason": "intake rate limit"},
                status_code=429,
                headers=headers,
            )

        # 7. replay dedup BEFORE minting a work item (M3): a captured signed request
        # replays with a genuine signature, so the signature check cannot stop the
        # second ingest. Skip it here on a stable delivery id. The store is the
        # record-and-check AUTHORITY (decision 0003 Phase 2): dedup holds across
        # workers and restarts; the process-local set is only a first-tier cache.
        # Placed after sender resolution so only would-be intakes are marked,
        # never a rejected/unpaired request. A message with NO stable delivery id
        # still cannot be deduped (honest gap: it is ingested on every replay).
        delivery = candidate.get("delivery_id")
        if delivery and await is_duplicate_delivery(
            k.store, ch.tenant_id, ch.id, str(delivery)
        ):
            return JSONResponse(
                {"status": "duplicate", "reason": "delivery already ingested"},
                status_code=200,
            )

        # 8. channel-native HITL replies (SEC-14/SEC-179): a BOUND sender's
        # /approve|/deny|/answer command - or a plain reply in a thread with
        # EXACTLY ONE pending item addressed to them - is answered through the
        # same chokepoint logic the API uses, AS the resolved principal. A
        # consumed reply mints NO work item; anything else is normal intake.
        target, reply_route = _resolve_addressing(ch, body)
        hitl_reply = await _hitl_reply_response(
            k, ch, principal, external_user_id, body, reply_route
        )
        if hitl_reply is not None:
            return hitl_reply

        # 9. normalise -> a work-item intake (the CoS routes it), tenant-scoped.
        # The item carries the ADDRESSING (decision 0003 Phase 2): the resolved
        # target (tier-1 CoS by default, a named tier-2 subagent/run when the
        # message addresses one) and the reply route for round-trip delivery.
        item = normalise(body, source=ch.platform, tenant_id=ch.tenant_id)
        item.on_behalf_of = principal.subject
        item.target, item.reply_route = target, reply_route
        item.reply_route["sender"] = external_user_id
        await k.store.create_work_item(item)

        # 10. audit the intake as the resolved principal (audit-always)
        await k.audit.write(
            AuditEvent(
                tenant_id=ch.tenant_id, ts=utcnow(), actor=principal.subject,
                actor_tier="human", action_type=ActionType.TOOL_CALL, noun="channel",
                verb="channel.inbound", status="ok",
                detail={"channel": ch.id, "work_item": item.id, "platform": ch.platform,
                        "target": item.target},
            )
        )
        return JSONResponse({"status": "ok", "work_item": item.id}, status_code=202)

    # === Governance verbs (decision 0003): admin-authored channel lifecycle. ===
    # Lifecycle and sender bindings are admin-gated and audited; connection secrets
    # stay kernel-side and never cross into an agent (SEC-04/05).

    def _admin(p) -> JSONResponse | None:
        from boltrig.identity.rbac import can_author

        return None if can_author(p.role) else JSONResponse(
            {"status": "denied", "reason": "admin only"}, status_code=403
        )

    @app.post("/v1/channels")
    async def channel_connect(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        platform = str(body.get("platform") or "").strip()
        name = str(body.get("name") or "").strip()
        if platform not in ("webhook", "msteams") or not name:
            return JSONResponse(
                {"status": "error", "reason": "platform must be a webhook-class + name"},
                status_code=400,
            )
        output, pending = await dispatch_control_route(
            k, p, "control.channel.connect", {**body, "platform": platform, "name": name},
            request=request)
        if pending is not None:
            return pending
        output = output or {}
        channel_id = str(output.get("channel"))
        await _audit(k, p, "channel.connect",
                     {"channel": channel_id, "platform": platform,
                      "transport": output.get("transport")})
        return JSONResponse(
            {"status": "ok", "channel": channel_id,
             "inbound_url": output.get("inbound_url")},
            status_code=201,
        )

    @app.patch("/v1/channels/{channel_id}")
    async def channel_configure(channel_id: str, body: dict, request: Request,
                                k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        ch = await k.store.get_channel(p.tenant_id, channel_id)
        if ch is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        _, pending = await dispatch_control_route(
            k, p, "control.channel.configure", {"channel_id": channel_id, **body},
            request=request)
        if pending is not None:
            return pending
        await _audit(k, p, "channel.configure", {"channel": channel_id})
        return JSONResponse({"status": "ok"})

    @app.delete("/v1/channels/{channel_id}")
    async def channel_disconnect(channel_id: str, request: Request,
                                 k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        ch = await k.store.get_channel(p.tenant_id, channel_id)
        if ch is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        _, pending = await dispatch_control_route(
            k, p, "control.channel.disconnect", {"channel_id": channel_id}, request=request)
        if pending is not None:
            return pending
        await _audit(k, p, "channel.disconnect", {"channel": channel_id}, status="ok")
        return JSONResponse({"status": "ok"})

    @app.post("/v1/channels/{channel_id}/pair")
    async def channel_pair(channel_id: str, body: dict, request: Request,
                           k=K, p=P) -> JSONResponse:
        # HITL-gated by being admin-only: an admin author issuing the code IS the
        # human authorising the bind (decision 0003). The code is shown ONCE.
        denied = _admin(p)
        if denied:
            return denied
        ch = await k.store.get_channel(p.tenant_id, channel_id)
        if ch is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        external_user_id = str(body.get("external_user_id") or "").strip()
        subject = str(body.get("subject") or "").strip()
        role = str(body.get("role") or "member").strip()
        if not external_user_id or not subject or role not in CHANNEL_TIERS:
            return JSONResponse(
                {"status": "error", "reason": "external_user_id + subject + valid role required"},
                status_code=400,
            )
        escalated = _role_clamp(p, role)
        if escalated is not None:
            return escalated
        try:
            ttl = int(body.get("ttl_minutes") or PAIR_TTL_MINUTES)
        except (TypeError, ValueError):
            ttl = PAIR_TTL_MINUTES
        ttl = max(1, min(ttl, PAIR_MAX_TTL_MINUTES))
        params = {"channel_id": channel_id, "external_user_id": external_user_id,
                  "subject": subject, "role": role, "ttl_minutes": ttl}
        output, pending = await dispatch_control_route(
            k, p, "control.channel.pair", params, request=request)
        if pending is not None:
            return pending
        output = output or {}
        await _audit(k, p, "channel.pair",
                     {"channel": channel_id, "external_user_id": external_user_id,
                      "subject": subject, "role": role,
                      "pairing": output.get("pairing_id")})
        return JSONResponse({"status": "ok", **output},
                            status_code=201)  # code returned ONCE, never again

    @app.post("/v1/channels/{channel_id}/bindings")
    async def channel_bind(channel_id: str, body: dict, request: Request,
                           k=K, p=P) -> JSONResponse:
        # Direct admin binding (skip the code) - the admin vouches for the mapping.
        denied = _admin(p)
        if denied:
            return denied
        ch = await k.store.get_channel(p.tenant_id, channel_id)
        if ch is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        external_user_id = str(body.get("external_user_id") or "").strip()
        subject = str(body.get("subject") or "").strip()
        role = str(body.get("role") or "member").strip()
        if not external_user_id or not subject or role not in CHANNEL_TIERS:
            return JSONResponse(
                {"status": "error", "reason": "external_user_id + subject + valid role required"},
                status_code=400,
            )
        escalated = _role_clamp(p, role)
        if escalated is not None:
            return escalated
        params = {"channel_id": channel_id, "external_user_id": external_user_id,
                  "subject": subject, "role": role}
        output, pending = await dispatch_control_route(
            k, p, "control.channel.bind", params, request=request)
        if pending is not None:
            return pending
        binding_id = (output or {}).get("binding")
        await _audit(k, p, "channel.bind",
                     {"channel": channel_id, "external_user_id": external_user_id,
                      "subject": subject, "role": role, "binding": binding_id})
        return JSONResponse({"status": "ok", "binding": binding_id}, status_code=201)

    @app.get("/v1/channels/{channel_id}/bindings")
    async def list_bindings(channel_id: str, k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        rows = await k.store.list_channel_bindings(p.tenant_id, channel_id)
        return JSONResponse({"bindings": [
            {"id": b.id, "external_user_id": b.external_user_id, "subject": b.subject,
             "role": b.role}
            for b in rows
        ]})

    @app.delete("/v1/channels/{channel_id}/bindings/{binding_id}")
    async def delete_binding(channel_id: str, binding_id: str, request: Request,
                             k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        # the path channel_id is authoritative: the binding must belong to this
        # channel (else a wrong-but-tenant-valid id would delete across channels).
        rows = await k.store.list_channel_bindings(p.tenant_id, channel_id)
        if not any(b.id == binding_id for b in rows):
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        _, pending = await dispatch_control_route(
            k, p, "control.channel.unbind",
            {"channel_id": channel_id, "binding_id": binding_id}, request=request)
        if pending is not None:
            return pending
        await _audit(k, p, "channel.unbind", {"channel": channel_id, "binding": binding_id})
        return JSONResponse({"status": "ok"})
