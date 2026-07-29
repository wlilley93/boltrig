"""DEVELOPMENT POSTURE: the four-eyes independence rule, suspended on a declared
tenant, for development.

WHAT IT DOES. While the posture holds, a tenant's own superadmin may answer an
approval they themselves raised. It suspends INDEPENDENCE - the rule that an
approver must be outside the initiator set - and nothing else. It is the same
relief the sole-author bootstrap exemption already grants a one-author tenant
(``hitl_response_auth._sole_active_author``), extended to a tenant that has more
than one author but is not yet in service.

WHAT IT DOES NOT DO, and these are load-bearing:

  * It does not remove the approval. A request is still raised, recorded,
    fingerprinted, bound to its verb, and answered by a named human. The record
    is identical to any other approval except that it carries a flag saying
    nobody independent looked.
  * It does not admit a non-human approver. ``actor_tier != "human"`` still
    refuses first, so an agent cannot clear its own work.
  * It does not touch grants. A superadmin who lacks the verb's grant is still
    refused - the posture lifts independence, never authority.
  * It does not reach outside ``control.*``. Business verbs are unaffected.
  * It does not lower any consequence. A HIGH verb still parks for a human; the
    posture only changes WHICH human may answer.

THE TWO CONDITIONS. A declared flag alone would let the party four-eyes
constrains remove their own constraint, so the posture also requires an OBSERVED
fact the operator cannot assert away: no production signal. This mirrors
``fleet/codex_trusted_wall.require_codex_trusted_posture``, which the court
approved for a comparable relaxation - an explicit off-by-default flag AND a
production refusal, under both of its postures.

AND IT EXPIRES. ``expires_at`` is mandatory. A development posture with no end
is not a posture, it is a permanent condition nobody re-examines; the whole
justification is that the tenant is not yet in service, and that claim goes stale.
An expired posture fails closed and the tenant returns to full four-eyes with no
action needed.

EVERY RELIANCE IS RECORDED. Callers that admit an approval under this posture
write a SecurityEvent (``SecurityEventType.DEVELOPMENT_POSTURE_APPROVAL``) on the
tamper-evident stream and mark the audit row. What is removed is the second
person's CLICK. What is never removed is the record that there was no second
person - so a party who was not asked can always see what was done, and when.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DevelopmentPosture:
    """A tenant's declared development posture, as parsed from its manifest."""

    enabled: bool = False
    expires_at: datetime | None = None
    declared_by: str = ""
    reason: str = ""


class DevelopmentPostureError(RuntimeError):
    """The declared posture is not one this process may honour."""


def posture_block(
    posture: DevelopmentPosture | None,
    *,
    now: datetime,
    production_signal: str | None,
    verb: str | None,
    subject_role: str,
) -> str | None:
    """Return why this ``DevelopmentPosture`` does NOT apply, or None when it does.

    Fail-closed and ordered so the most serious refusal is the one reported.
    Returning a REASON rather than a bool is deliberate: a caller that silently
    got False could not tell "no posture declared" from "declared but this is
    production", and those want very different responses from an operator.
    """
    if posture is None or not posture.enabled:
        return "no development posture is declared for this tenant"

    # The observed condition, checked BEFORE the declared one. A tenant that
    # says it is in development and also says it is production is not a tenant
    # whose own declaration should be trusted to break the tie.
    if production_signal is not None:
        return (
            f"a production signal is present ({production_signal}); the development "
            "posture never applies in production, whatever the manifest declares"
        )

    if posture.expires_at is None:
        return "the development posture has no expires_at; an unbounded posture is refused"
    if posture.expires_at <= now:
        return f"the development posture expired at {posture.expires_at.isoformat()}"

    # Only the tenant's highest tier. `admin` is a role a CLIENT is routinely
    # given so they have authority over their own data; letting it self-approve
    # would hand the relief to the very party four-eyes protects.
    if subject_role != "superadmin":
        return f"the development posture admits superadmin only, not '{subject_role}'"

    if not (verb or "").startswith("control."):
        return f"the development posture covers control.* only, not '{verb}'"

    return None
