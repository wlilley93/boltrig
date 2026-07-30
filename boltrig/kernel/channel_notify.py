"""Channel notification delivery (decision 0003, Phase 2; SEC-179).

Closes the notification loop for channel-originated work: when something a
human must hear about happens (a HITL approval request, an escalation, a run
reaching a terminal state), the kernel enqueues a DURABLE outbox row to the
user's BOUND channel surface, addressed back to the thread the triggering
message came from (round-trip integrity). The severed gateway's outbox pump
delivers it over the platform connection it holds; ack/retry/backoff are the
existing channel_outbox machinery, so a notification survives restarts and is
never silently dropped.

Preference resolution is data, not policy: ``notification_prefs`` rows (user
or team scope, event type, platform name) pick WHICH surface hears about WHICH
event; ``channel_bindings`` rows decide whether the user actually has a bound
surface on that channel (kernel-authoritative identity - a pref alone never
mints a recipient). A team-scoped pref names a DEPARTMENT (the codebase's team
unit: ``scope['departments']`` on the user record - the same department
vocabulary RBAC and HITL visibility use) and resolves to every ACTIVE member,
whoever triggered the event. Only the socket class is enqueued: the webhook
class has no outbox consumer (its direct ``outbound_url`` path belongs to
``channel.send``), and ``in_app`` prefs ride the UI's existing SSE event relay
- neither is rebuilt here.

Callers:
  - ``HITLManager.create`` wires approval/escalation notices (fail-safe: a
    notifier fault never voids the request record, mirroring _fire_resume) -
    the legacy subject directly, and every eligible approver through
    ``enqueue_approval_fanout`` (notice follows eligibility,
    [2026] VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001);
  - ``notify_work_item_result`` is the run-completion seam: the fleet pump
    calls it with the terminal work item and the reply returns to the
    originating thread via ``item.reply_route``.
"""

from __future__ import annotations

import uuid

from boltrig.notification_catalogue import (
    APPROVAL_EVENT,
    NOTIFICATION_EVENT_IDS,
    NOTIFICATION_PLATFORM_ALIASES,
    WORK_STATUS_EVENT,
)
from boltrig.models import ChannelOutboxMessage

# notification_prefs.channel names a platform family; map it to the channel
# platform ids (decision 0003's names). Unknown names match nothing (a pref for
# a platform with no channels is simply undeliverable today).
async def _pref_subjects(store, tenant_id: str, pref, subject: str) -> list[str]:
    """The recipient subjects a matching pref addresses (SEC-179).

    A user-scoped pref addresses its named user - and only when that user IS
    the subject being notified. A team-scoped pref names a department and
    addresses every ACTIVE member of it (the user record's
    ``scope['departments']``), whoever triggered the event. Any other scope
    kind addresses no one (an honest no-op, never a guess)."""
    if pref.scope_kind == "user":
        return [subject] if pref.scope_ref == subject else []
    if pref.scope_kind != "team":
        return []
    members = []
    for user in await store.list_users(tenant_id):
        scope = user.scope if isinstance(user.scope, dict) else {}
        departments = scope.get("departments", [])
        if user.status == "active" and pref.scope_ref in departments:
            members.append(user.id)
    return members


async def enqueue_user_notification(
    store,
    tenant_id: str,
    subject: str,
    event_type: str,
    text: str,
    *,
    source_route: dict | None = None,
) -> list[str]:
    """Enqueue one outbox row per (matching pref, resolved subject, bound
    channel).

    Returns the enqueued outbox ids ([] when nothing matched - an unreachable
    user is a delivery gap, never an error). ``source_route`` (an intake
    ``reply_route``) pins the delivery to the originating thread when the
    notification concerns that same channel (round-trip integrity)."""
    if event_type not in NOTIFICATION_EVENT_IDS:
        return []
    prefs = await store.list_notification_prefs(tenant_id)
    matching = [p for p in prefs if p.enabled and p.event_type == event_type]
    if not matching:
        return []
    enqueued: list[str] = []
    for pref in matching:
        subjects = await _pref_subjects(store, tenant_id, pref, subject)
        if not subjects:
            continue
        platform = NOTIFICATION_PLATFORM_ALIASES.get(pref.channel, pref.channel)
        for ch in await store.list_channels(tenant_id):
            route_matches = pref.channel == ch.id or ch.platform == platform
            if not ch.enabled or not route_matches or ch.transport != "socket":
                continue
            bindings = await store.list_channel_bindings(tenant_id, ch.id)
            for member in subjects:
                # The member's BOUND surface only: a binding row vouches that
                # this channel reaches this subject. No binding -> we have no
                # verified way to reach them here.
                binding = next((b for b in bindings if b.subject == member), None)
                if binding is None:
                    continue
                target = None
                if source_route and source_route.get("channel_id") == ch.id:
                    target = source_route.get("thread")  # reply in the origin thread
                target = target or pref.target or binding.external_user_id
                message = ChannelOutboxMessage(
                    id=f"co_{uuid.uuid4().hex[:16]}", tenant_id=tenant_id,
                    channel_id=ch.id,
                    payload={"text": text, "target": target,
                             "event": event_type, "subject": member},
                )
                await store.enqueue_channel_outbox(message)
                enqueued.append(message.id)
    return enqueued


async def enqueue_approval_fanout(
    store, request, *, exclude: str | None, posture=None
) -> list[str]:
    """Enqueue an APPROVAL request's notice to every eligible approver.

    Notice follows eligibility ([2026] VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001,
    D1): the audience is exactly ``eligible_approval_responders`` - the set the
    response route would admit - deduplicated against the already-notified
    ``exclude`` subject and each other. Being notified confers no authority;
    delivery stays pref/binding-gated, so an unreachable approver is an honest
    delivery gap, never an error."""
    from boltrig.kernel.hitl_response_auth import eligible_approval_responders

    enqueued: list[str] = []
    notified = {exclude} if exclude else set()
    # The posture is threaded through because eligibility depends on it: computing
    # notice against posture=None while the route uses the live one is exactly the
    # drift D2 of that order forbids, and it shipped once already.
    for responder in await eligible_approval_responders(store, request, posture=posture):
        if responder in notified:
            continue
        notified.add(responder)
        enqueued += await enqueue_user_notification(
            store, request.tenant_id, responder, APPROVAL_EVENT, request.question
        )
    return enqueued


async def notify_work_item_result(store, item, text: str | None = None) -> list[str]:
    """The run-completion seam: notify the item's human on their bound surface,
    routed back to the thread the triggering message came from (SEC-179).

    Called by the fleet pump when a channel-originated work item reaches a
    terminal state; a no-op for items without a human origin (on_behalf_of)
    or without a reply route (non-channel sources)."""
    if not getattr(item, "on_behalf_of", None) or not getattr(item, "reply_route", None):
        return []
    summary = text or f"Run {item.id} finished with status {item.status.value}"
    return await enqueue_user_notification(
        store, item.tenant_id, item.on_behalf_of, WORK_STATUS_EVENT, summary,
        source_route=item.reply_route,
    )
