"""DEV-MODE EGRESS LOOPBACK: governed outbound sends diverted back into the
stack that raised them, so nothing reaches a real recipient during development.

Authority: **[2026] VJS-CC-BOLTRIG-DEV-EGRESS-LOOPBACK-001** (County Court,
First Instance), PERMITTED on five conditions, all of which must hold before the
diversion may run once.

WHY IT IS GRANTED, AND WHY THE RISK RUNS THE OTHER WAY. This does not widen what
may leave the system; it prevents anything leaving. That is the opposite of the
posture cases, and it is why the ratio for THIS relief is not the one that
governs those. The court said so expressly: diverting an effect is not suspending
its control, so where the initiator is an agent and the approver a human outside
the initiator set, four-eyes is SATISFIED, not lifted, and
``[2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001`` is not engaged merely because
the same manifest tag enables both.

**THE RATIO, and it is the whole design.** A control may be narrowed by a
declared posture where the narrowing removes the protected exposure entirely; but
where the narrowing makes a human's approval mean something other than what the
human is being asked to approve, the narrowing must be **disclosed at the point
of approval, in the approval itself**. An approval obtained on a false description
of its effect is not an approval. The disclosure is not documentation - it is the
condition of the approval's validity.

That is why ``Diversion.notice`` exists and why it rides the approval
FINGERPRINT rather than only a log line: an approver who was shown "this will be
delivered to the loopback, and <recipient> will NOT be messaged" has approved
that act, and an approval carrying that description cannot be redeemed for a real
send, because the description is part of what was bound.

THE FIVE CONDITIONS, and where each lives:

  C1  an AFFIRMATIVE declared development signal. The absence of a production
      signal must never enable it - four unset variables are the state of every
      unconfigured environment. ``_R_UNDECLARED_ENV`` below.
  C2  refuse under any real ingress posture (OIDC / Cloudflare Access / session
      login), exactly as ``require_codex_trusted_posture`` does. ``_R_INGRESS``.
  C3  the HITL request, the notification and the approval surface each name the
      loopback as the ACTUAL recipient and name the declared recipient as NOT
      being messaged. ``Diversion.notice`` + the ``approval_notice`` key the
      approval gate lifts into the question (which is what the notification
      carries), and ``egress`` in the resource context (which is what the card
      renders). A log line alone does not satisfy it.
  C4  the audit row, the outbox receipt and any user-visible status record
      ``diverted`` and never ``sent``. ``DIVERTED_STATUS``, and the deliver seam
      never emits the ``sent`` string on this path.
  C5  ``expires_at`` is mandatory and an expired tag fails closed to normal
      sending. ``_R_UNBOUNDED`` / ``_R_EXPIRED``.

WHAT THE COURT DID **NOT** REQUIRE, recorded here because it is a limitation to
disclose rather than to cure: the dev path does not exercise the identical egress
transport. Requiring a real send would defeat the purpose. The loopback is
received by the REAL intake, so routing, binding, notification and approval are
genuinely exercised and only the final transport leg is substituted. Nobody may
later cite a dev-mode success as evidence that the transport works.

STILL RESERVED. What ``Tag:Not Dev`` should default to is NOT decided. The
Principal proposes "any channel they want, starting with their email by default";
the court noted only that a default which sends to a real human on first use
deserves its own examination, and that the engineering record carries a standing
instruction against email to this client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# The value type lives in boltrig.models because the channel.send adapter needs it
# and adapters are a FOUNDATION layer that may not depend upward on config
# (SEC-54). Re-exported here so there is one name for each thing; `X as X` is
# required because mypy disallows implicit re-export.
from boltrig.models.egress_diversion import (  # noqa: F401
    DIVERTED_STATUS as DIVERTED_STATUS,
    Diversion as Diversion,
)

_R_NONE = "no development egress loopback is declared for this tenant"
_R_PRODUCTION = (
    "a production signal is present ({signal}); the egress loopback never applies "
    "in production, whatever the manifest declares"
)
_R_UNDECLARED_ENV = (
    "the environment declares neither development nor production; the egress "
    "loopback requires an affirmative development signal (ENV / BOLTRIG_ENV / "
    "APP_ENV = dev|development|local|test), because the absence of a production "
    "signal is not evidence of anything"
)
_R_INGRESS = (
    "a real ingress posture is configured (OIDC / Cloudflare Access / session "
    "login); a tenant with real users at a real door is in service, and its "
    "outbound sends are real sends"
)
_R_UNBOUNDED = "the egress loopback has no expires_at; an unbounded diversion is refused"
_R_EXPIRED = "the egress loopback expired at {when}"
_R_NO_LOOPBACK = (
    "the egress loopback declares no loopback_url; a diversion with nowhere to "
    "divert TO would silently drop the message, which is the one outcome worse "
    "than sending it"
)


@dataclass(frozen=True)
class DevEgressPosture:
    """A tenant's declared development egress loopback, parsed from its manifest."""

    enabled: bool = False
    expires_at: datetime | None = None
    loopback_url: str = ""
    declared_by: str = ""
    reason: str = ""


def diversion_block(
    posture: DevEgressPosture | None,
    *,
    now: datetime,
    production_signal: str | None,
    development_signal: str | None,
    real_ingress: bool,
) -> str | None:
    """Return why the diversion does NOT apply, or None when it does.

    Fail-closed and ordered so the most serious refusal is the one reported.
    Returning a REASON rather than a bool is deliberate, for the same reason
    ``dev_posture.posture_block`` does: an operator who silently got False could
    not tell "nothing declared" from "declared, but this is production".

    EVERY CONDITION IS A PARAMETER. None is read from the environment here, so
    each is testable in isolation and adding one breaks every call site rather
    than defaulting to permissive at the one nobody updated.
    """
    if posture is None or not posture.enabled:
        return _R_NONE

    # The observed condition before the declared one: a tenant that says it is in
    # development and also says it is production is not one whose own declaration
    # should break the tie.
    if production_signal is not None:
        return _R_PRODUCTION.format(signal=production_signal)

    # C1. Absence of a production signal is not evidence of development.
    if development_signal is None:
        return _R_UNDECLARED_ENV

    # C2. The limb the development-posture case was refused for dropping.
    if real_ingress:
        return _R_INGRESS

    # C5. An unbounded diversion is a permanent condition nobody re-examines.
    if posture.expires_at is None:
        return _R_UNBOUNDED
    if posture.expires_at <= now:
        return _R_EXPIRED.format(when=posture.expires_at.isoformat())

    if not (posture.loopback_url or "").strip():
        return _R_NO_LOOPBACK

    return None


__all__ = [
    "DIVERTED_STATUS",
    "DevEgressPosture",
    "Diversion",
    "diversion_block",
]
