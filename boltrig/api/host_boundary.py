"""Attribution for acts performed from the HOST SHELL
([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D6).

``set-password`` and ``mint-token`` are the two commands that operate on an
EXISTING identity from outside every in-band control. Neither restricts the
target's role, and ``mint-token`` caps the PAT at the target's own grants - so
whoever holds a shell on the box can mint a fully-scoped token as the tenant's
client, answer the operator's own approval request wearing the client's
identity, and satisfy four-eyes with a second human who never participated.

Both commands wrote their audit row with ``actor`` set to the TARGET user, so
that trail read as the client's own act. The court refused to answer this leaky
boundary by opening a third command beside it (that argument "proves too much":
every future widening becomes self-justifying as no worse than the last). It
directed the opposite - attribute the boundary honestly, and put it on the
security stream where a signal can be watched on its own.

Kept in one module so the two commands cannot drift into two different
attributions, which is how the two ``AUTHOR_ROLES`` sets ended up disagreeing.
"""

from __future__ import annotations

from typing import Any

# Deliberately not an email and not a real user id: it must not collide with any
# identity in the users table, and it must be obvious in a row that no in-band
# principal performed this. Whoever holds shell on the box is the actor, and the
# box cannot name them more precisely than this.
HOST_BOUNDARY_ACTOR = "host-boundary"


async def write_host_boundary_security_event(
    store: Any,
    *,
    tenant: str,
    subject: str,
    reason: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Record a host-boundary credential act on the security stream.

    ``subject`` is the identity ACTED UPON, never the actor - the whole point of
    the directive is that those two are not the same party here.

    Best-effort by design. These commands run at a shell, often to recover a
    tenant that is already broken, and a security-stream write that fails must
    not prevent an operator setting a password. The audit row (which is the
    business record) is written unguarded by the callers; this is the additional
    signal, and a signal that could brick the recovery path would be traded away
    the first time it did.
    """
    from boltrig.kernel.security_events import SecurityWriter
    from boltrig.models import SecurityEvent, SecurityEventType, utcnow

    try:
        await SecurityWriter(store).write(
            SecurityEvent(
                tenant_id=tenant,
                ts=utcnow(),
                event_type=SecurityEventType.HOST_BOUNDARY_CREDENTIAL,
                reason=reason,
                actor=HOST_BOUNDARY_ACTOR,
                actor_tier="host",
                # The subject rides the COLUMN, not the detail. ``SecurityWriter``
                # scrubs detail keys-only (K-20), so an email placed there comes
                # back as a digest - and an identifier nobody can read is not
                # attribution. It also keeps this stream from accumulating
                # addresses: the ``SecurityWriter`` ledger is append-only.
                on_behalf_of=subject,
                detail=dict(detail or {}),
            )
        )
    except Exception:  # noqa: BLE001 - see the best-effort note above
        pass
