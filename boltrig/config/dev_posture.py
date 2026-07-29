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
_INTERACTIVE_CREDENTIALS = frozenset({"session", "federated", "dev-header"})


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
        return "no development posture is declared for this tenant"

    # The observed condition, checked BEFORE the declared one. A tenant that
    # says it is in development and also says it is production is not a tenant
    # whose own declaration should be trusted to break the tie.
    if production_signal is not None:
        return (
            f"a production signal is present ({production_signal}); the development "
            "posture never applies in production, whatever the manifest declares"
        )

    # D5. The absence of a production signal is not evidence of development: four
    # unset variables permitted on every environment nobody configured, which is
    # how this reached a live client. Require the environment to SAY so.
    if development_signal is None:
        return (
            "the environment declares neither development nor production; the "
            "development posture requires an affirmative development signal "
            "(ENV / BOLTRIG_ENV / APP_ENV = dev|development|local|test), because "
            "the absence of a production signal is not evidence of anything"
        )

    # D2. The limb this fence was missing. require_codex_trusted_posture refuses
    # a real ingress posture as well as a production signal, and this posture was
    # built expressly on that precedent while reproducing only one of its limbs.
    # A tenant with OIDC, Cloudflare Access or session login has real users
    # arriving at a real door, which is the definition of being in service.
    if real_ingress:
        return (
            "a real ingress posture is configured (OIDC / Cloudflare Access / "
            "session login); a tenant with real users at a real door is in service, "
            "whatever the manifest declares"
        )

    if posture.expires_at is None:
        return "the development posture has no expires_at; an unbounded posture is refused"
    if posture.expires_at <= now:
        return f"the development posture expired at {posture.expires_at.isoformat()}"

    # D4. `actor_tier` is not a humanity check. `resolve_pat_principal` stamps it
    # "human" on every machine bearer, so `Principal.credential_kind` is what
    # carries this instead: a PAT cleared a control approval on a live client
    # tenant with nobody present, and the check that was supposed to stop it read
    # the wrong field rather than being absent.
    if credential_kind not in _INTERACTIVE_CREDENTIALS:
        return (
            f"the development posture requires a person at a door, and this caller "
            f"authenticated with a '{credential_kind}' credential; suspending the "
            "independence rule for a machine bearer would leave nobody in the loop "
            "at all, not merely nobody independent"
        )

    # Only the tenant's highest tier. `admin` is a role a CLIENT is routinely
    # given so they have authority over their own data; letting it self-approve
    # would hand the relief to the very party four-eyes protects.
    if subject_role != "superadmin":
        return f"the development posture admits superadmin only, not '{subject_role}'"

    if not (verb or "").startswith("control."):
        return f"the development posture covers control.* only, not '{verb}'"

    # D3, and it is last because it is the most specific. Independence may be
    # suspended only where there is no party for independence to protect, so the
    # declaration must name the authors it was made in respect of, and the
    # arrival of anyone else must switch it off with no operator act. This
    # mirrors _sole_active_author, which lapses the moment a second author
    # exists - the difference between a relief that tracks an unsatisfiable rule
    # and one that tracks an operator's say-so.
    covered = set(posture.covers)
    uncovered = sorted(a for a in active_author_ids if a not in covered)
    if uncovered:
        return (
            "the development posture does not cover every active author on this "
            f"tenant: {', '.join(uncovered)}. An author it does not name is a party "
            "the independence rule exists to protect, so the posture has lapsed"
        )

    return None
