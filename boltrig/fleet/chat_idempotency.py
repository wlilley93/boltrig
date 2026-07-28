"""Exactly once per user message, on the surface a human actually types into.

WHY THIS EXISTS. Measured on the live Classical Visas tenant, 2026-07-27 23:16:
FIVE copies of one message landed 1.4-2.1 seconds apart - the regular spacing of a
client retry loop, not of a human retyping - and the audit log carries SEVEN
``agent_spawn`` rows across that window. Each retry did not merely duplicate a
row: it convened another agent. On a working system that is N times the model
spend and N duplicate answers to one question.

Nothing deduped it, because the guarantee existed one layer down and was never
wired to the top. ``kernel/dispatch`` runs every VERB through an
``IdempotencyCoordinator`` (SEC-15 / NFR-REL-02: "a repeated key returns the
stored result, no re-execution"), and ``SpawnBody`` carries an
``idempotency_key``. ``ChatBody`` did not, and ``chat.py`` referenced neither -
so the one surface a person types into was the only one with no replay defence.

WHY ``record_channel_delivery`` AND NOT A NEW TABLE. That primitive is already
exactly this: a record-AND-CHECK in one atomic step (PG ``INSERT ... ON CONFLICT
DO NOTHING``), tenant-scoped under RLS, TTL-bounded, surviving worker restarts and
atomic across concurrent workers - built for channel intake, where a signed
request can replay with a genuine signature. A chat retry is the same problem
arriving through a different door. Building a second dedup beside it would be the
fragmentation this estate has been paying down all week, and a lookup-then-create
would lose the race the primitive already wins: two retries 1.5s apart are two
requests, possibly on two workers.

WHAT IT DOES NOT DO. It does not re-attach the second caller to the first turn's
stream. That is the better end state (and is what US-CONV-07's dropped-client
re-attach already means), but it needs the live run's event stream, so it is a
separate change. This is the floor: the SECOND send does not spawn a second agent
and does not bill the tenant twice. Absent a key, behaviour is exactly as before -
an SDK that does not send one loses nothing it had.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# The dedup marker's channel bucket. Chat turns are not a channel, but the marker
# table is keyed (tenant, channel_id, delivery_id) and this keeps chat's keys in
# their own namespace so a client-chosen key can never collide with a real
# channel's delivery id.
CHAT_DEDUP_CHANNEL = "chat:turn"

# Long enough to cover a retry storm and a client that reconnects after a dropped
# stream; short enough that a key is never a permanent reservation. The observed
# storm spanned ~2.5 minutes.
CHAT_DEDUP_TTL_SECONDS = 900

MAX_KEY_LENGTH = 200


def normalised_key(raw: object) -> str | None:
    """The client's idempotency key, bounded, or ``None`` when absent/unusable.

    Bounded because it is caller-supplied and becomes a stored identifier. An
    over-long or non-string key is treated as ABSENT rather than refused: the
    turn is the user's message, and losing it to a malformed header would be a
    worse outcome than the duplicate this exists to prevent.
    """

    if not isinstance(raw, str):
        return None
    key = raw.strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        return None
    return key


async def claim_turn(store: Any, tenant_id: str, key: str | None) -> bool:
    """True when THIS caller owns the turn; False when it is a replay.

    One atomic step, so two concurrent retries cannot both win. Fails OPEN: if
    the marker cannot be written the turn proceeds, because refusing a person's
    message to protect against a duplicate answer is the wrong trade.
    """

    if not key:
        return True
    try:
        return await store.record_channel_delivery(
            tenant_id, CHAT_DEDUP_CHANNEL, key, ttl_seconds=CHAT_DEDUP_TTL_SECONDS
        )
    except Exception:  # noqa: BLE001 - never lose a turn to the dedup marker
        logger.warning(
            "chat idempotency marker could not be written; proceeding with the turn "
            "(a duplicate is possible, a lost message is not)"
        )
        return True


async def replay_if_duplicate(
    store: Any, tenant_id: str, raw_key: object, conversation_id: str | None
) -> list[dict[str, Any]] | None:
    """``None`` => this caller owns the turn, proceed. A list => yield it and stop.

    The whole guard in one call, so the chat lane carries the decision and not the
    mechanism.
    """

    key = normalised_key(raw_key)
    if await claim_turn(store, tenant_id, key):
        return None
    logger.info("chat turn is a replay of an accepted message; not re-running")
    return replay_frames(conversation_id)


def replay_frames(conversation_id: str | None) -> list[dict[str, Any]]:
    """What a replayed send is answered with: an honest, terminal, empty turn.

    NOT an error. The caller is a retry of a message already accepted, so the
    correct answer is that it was accepted - once. Shaped like any other turn's
    terminal frames so a client that is mid-retry does not need a special case.
    """

    return [
        {"type": "message_start", "conversation_id": conversation_id, "replay": True},
        {"type": "message_end", "conversation_id": conversation_id, "replay": True},
    ]


__all__ = [
    "CHAT_DEDUP_CHANNEL",
    "CHAT_DEDUP_TTL_SECONDS",
    "MAX_KEY_LENGTH",
    "claim_turn",
    "normalised_key",
    "replay_frames",
]
