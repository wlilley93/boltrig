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
  * It does not admit a non-human approver. This is enforced on the CREDENTIAL
    CLASS (``Principal.credential_kind``), not on ``actor_tier``: a PAT is
    stamped ``actor_tier="human"`` because it carries its owner's authority, and
    reading that as a humanity check let a machine bearer clear its own control
    approval on a live client tenant. The claim is now true because a different
    thing is checked, not because the old check was restated more firmly.
  * It does not touch grants. A superadmin who lacks the verb's grant is still
    refused - the posture lifts independence, never authority.
  * It does not reach outside ``control.*``. Business verbs are unaffected.
  * It does not lower any consequence. A HIGH verb still parks for a human; the
    posture only changes WHICH human may answer.

THE CONDITIONS, and the ruling that fixed them. A declared flag alone would let
the party four-eyes constrains remove their own constraint, so the posture also
requires facts the operator cannot assert away. The first version required only
"no production signal", and [2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001 refused
it as shipped on three grounds now answered here:

  D5  the absence of a production signal is not evidence of development - four
      unset variables permitted on every unconfigured environment - so an
      AFFIRMATIVE development signal is required.
  D2  ``require_codex_trusted_posture``, the precedent this was modelled on, has
      TWO limbs: no production signal AND no real ingress posture. Only the first
      was reproduced, and the dropped limb was the one that would have refused
      the tenant it was actually declared on.
  D3  a relief may suspend independence only where there is no party for
      independence to protect, so the declaration names the authors it covers and
      lapses when anyone else appears.

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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


# The credential classes that mean a person authenticated at a door. A PAT is
# excluded on purpose: it carries its owner's authority but nobody is present
# (D4). "machine" is the Principal default, so an unlabelled resolver is refused.
INTERACTIVE_CREDENTIAL_KINDS = frozenset({"session", "federated", "dev-header"})


def is_interactive_credential(kind: str) -> bool:
    """Whether this credential proves a person is present at an auth door.

    A PAT deliberately returns ``False`` even though its principal carries
    ``actor_tier='human'``: it has the owner's authority, but nobody is present
    to make a fresh consent decision.
    """
    return kind in INTERACTIVE_CREDENTIAL_KINDS


@dataclass(frozen=True)
class DevelopmentPosture:
    """A tenant's declared development posture, as parsed from its manifest."""

    enabled: bool = False
    expires_at: datetime | None = None
    declared_by: str = ""
    reason: str = ""
    # The active author-tier identities this declaration was made in respect of
    # (D3). The posture lapses the moment an author appears who is not named
    # here, mirroring how _sole_active_author lapses when a second author exists.
    # Empty means the declaration covers nobody, which refuses everything.
    covers: tuple[str, ...] = ()


# The refusals, as a named table rather than inline in the function. Each is the
# sentence an operator reads when the posture does NOT apply, so they are the
# most-read prose in this module and deserve to be reviewable in one place - and
# it keeps posture_block a readable sequence of conditions rather than a wall.
_R_NONE = "no development posture is declared for this tenant"
_R_PRODUCTION = (
    "a production signal is present ({signal}); the development posture never "
    "applies in production, whatever the manifest declares"
)
_R_UNDECLARED_ENV = (
    "the environment declares neither development nor production; the development "
    "posture requires an affirmative development signal (ENV / BOLTRIG_ENV / "
    "APP_ENV = dev|development|local|test), because the absence of a production "
    "signal is not evidence of anything"
)
_R_INGRESS = (
    "a real ingress posture is configured (OIDC / Cloudflare Access / session "
    "login); a tenant with real users at a real door is in service, whatever the "
    "manifest declares"
)
_R_UNBOUNDED = "the development posture has no expires_at; an unbounded posture is refused"
_R_EXPIRED = "the development posture expired at {when}"
_R_MACHINE = (
    "the development posture requires a person at a door, and this caller "
    "authenticated with a '{kind}' credential; suspending the independence rule "
    "for a machine bearer would leave nobody in the loop at all, not merely "
    "nobody independent"
)
_R_ROLE = "the development posture admits superadmin only, not '{role}'"
_R_VERB = "the development posture covers control.* only, not '{verb}'"
_R_UNCOVERED = (
    "the development posture does not cover every active author on this tenant: "
    "{who}. An author it does not name is a party the independence rule exists to "
    "protect, so the posture has lapsed"
)


class DevelopmentPostureError(RuntimeError):
    """The declared posture is not one this process may honour."""


def posture_block(
    posture: DevelopmentPosture | None,
    *,
    now: datetime,
    production_signal: str | None,
    development_signal: str | None,
    real_ingress: bool,
    credential_kind: str,
    active_author_ids: Sequence[str],
    verb: str | None,
    subject_role: str,
) -> str | None:
    """Return why this ``DevelopmentPosture`` does NOT apply, or None when it does.

    Fail-closed and ordered so the most serious refusal is the one reported.
    Returning a REASON rather than a bool is deliberate: a caller that silently
    got False could not tell "no posture declared" from "declared but this is
    production", and those want very different responses from an operator.

    EVERY CONDITION IS A PARAMETER, none is read from the environment here. That
    is what makes each one testable in isolation, and it means adding a condition
    breaks every call site until it is supplied, rather than defaulting to
    permissive at the one caller nobody updated.
    """
    if posture is None or not posture.enabled:
        return _R_NONE

    # The observed condition, checked BEFORE the declared one. A tenant that says
    # it is in development and also says it is production is not one whose own
    # declaration should be trusted to break the tie.
    if production_signal is not None:
        return _R_PRODUCTION.format(signal=production_signal)

    # D5. Absence of a production signal is not evidence of development.
    if development_signal is None:
        return _R_UNDECLARED_ENV

    # D2. The limb this fence dropped - and the one that would have refused the
    # tenant it was actually declared on.
    if real_ingress:
        return _R_INGRESS

    if posture.expires_at is None:
        return _R_UNBOUNDED
    if posture.expires_at <= now:
        return _R_EXPIRED.format(when=posture.expires_at.isoformat())

    # D4. The credential CLASS, never `actor_tier` - see the module docstring.
    if not is_interactive_credential(credential_kind):
        return _R_MACHINE.format(kind=credential_kind)

    # `admin` is a role a CLIENT is routinely given over their own data; admitting
    # it would hand the relief to the very party four-eyes protects.
    if subject_role != "superadmin":
        return _R_ROLE.format(role=subject_role)

    if not (verb or "").startswith("control."):
        return _R_VERB.format(verb=verb)

    # D3, last because it is the most specific: an author the declaration does not
    # name is a party the independence rule exists to protect.
    uncovered = sorted(a for a in active_author_ids if a not in set(posture.covers))
    if uncovered:
        return _R_UNCOVERED.format(who=", ".join(uncovered))

    return None
