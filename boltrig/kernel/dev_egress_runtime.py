"""Resolving the dev-egress loopback at runtime: the one place that reads the
environment, so ``boltrig.config.dev_egress`` stays a pure decision.

The split mirrors ``dev_posture`` / ``hitl_response_auth``: the config module
takes every condition as a parameter and is testable in isolation; this module
supplies them from the live process exactly once, and is the only thing that has
to be stubbed to test a caller.

Nothing here decides anything. If ``diversion_block`` returns a reason, the
reason is logged at WARNING and the send proceeds normally - a refused diversion
is a real send, which is the correct fail-closed direction for a control whose
purpose is to STOP egress: the failure mode being guarded against is a sender who
believes a message was delivered when it never left, so on any doubt the message
really leaves and the sender's belief is true.
"""

from __future__ import annotations

import logging
from typing import Any

from boltrig.config.dev_egress import DevEgressPosture, Diversion, diversion_block

log = logging.getLogger("boltrig.dev_egress")

__all__ = ["DiversionResolver", "announced_diversion_fn", "build_diversion_resolver"]


class DiversionResolver:
    """Answers "is this send diverted, and to where" for a declared posture."""

    def __init__(self, posture: DevEgressPosture | None) -> None:
        self._posture = posture

    def block_reason(self) -> str | None:
        """Why the diversion does not apply right now, or None when it does."""
        from boltrig.config.environment import development_signal, production_signal
        from boltrig.config.settings import load_settings
        from boltrig.models import utcnow

        settings = load_settings()
        return diversion_block(
            self._posture,
            now=utcnow(),
            production_signal=production_signal(),
            development_signal=development_signal(),
            # C2, the same three limbs require_codex_trusted_posture reads. Kept
            # as one expression rather than a helper so a reader can see that
            # none of the three was quietly dropped.
            real_ingress=(
                settings.oidc_configured
                or settings.cf_access_configured
                or settings.session_auth_configured
            ),
        )

    def for_send(self, declared_recipient: str) -> Diversion | None:
        """The diversion that applies to this send, or None to send for real."""
        reason = self.block_reason()
        if reason is not None:
            # Logged at DEBUG, not WARNING: on an ordinary production deployment
            # this is the answer on EVERY send, and a per-send warning about a
            # posture nobody declared is noise that trains operators to ignore
            # the log.
            log.debug("egress loopback not applied: %s", reason)
            return None
        posture = self._posture
        assert posture is not None  # diversion_block returned None
        return Diversion(
            declared_recipient=declared_recipient,
            loopback_url=posture.loopback_url.strip(),
        )


def build_diversion_resolver(manifest: Any) -> DiversionResolver:
    """Read the declared posture off a loaded manifest. Never raises.

    A malformed declaration yields a DISABLED posture rather than an error: this
    runs at the composition root, and a stack that refuses to boot because a
    development convenience is mistyped is a worse outcome than one that boots
    and sends normally.
    """
    try:
        section = manifest.section("dev_egress_loopback")
    except Exception:
        return DiversionResolver(None)
    if not isinstance(section, dict) or not section:
        return DiversionResolver(None)
    from boltrig.config.environment import is_truthy

    expires_raw = str(section.get("expires_at") or "").strip()
    expires_at = None
    if expires_raw:
        from datetime import datetime, timezone

        try:
            parsed = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            expires_at = (
                parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            )
    # An unparseable expires_at stays None, and None is REFUSED by C5. That is
    # the right direction: a typo in the one field that bounds the diversion must
    # not read as "no bound".
    return DiversionResolver(
        DevEgressPosture(
            enabled=is_truthy(str(section.get("enabled") or "")),
            expires_at=expires_at,
            loopback_url=str(section.get("loopback_url") or "").strip(),
            declared_by=str(section.get("declared_by") or "").strip(),
            reason=str(section.get("reason") or "").strip(),
        )
    )


def announced_diversion_fn(manifest: Any) -> "Any | None":
    """The resolver the channel-send adapter takes, with the boot announcement.

    Both halves live here rather than at the composition root because the root is
    under a file-growth ratchet and, more to the point, because the ANNOUNCEMENT
    is part of this decision rather than part of wiring: a stack that will divert
    every governed send is a fact an operator must see without looking for it, and
    it is stated once, at boot, at the level it deserves.

    A registration with no manifest gets None - so the demo tenant and every bare
    boot have no code path to a diversion at all, whatever the environment says.
    """
    if manifest is None:
        return None
    resolver = build_diversion_resolver(manifest)
    reason = resolver.block_reason()
    if reason is None:
        log.warning(
            "channel.send registered WITH THE DEVELOPMENT EGRESS LOOPBACK ACTIVE: "
            "governed outbound sends will be diverted to this stack's own intake "
            "and will NOT reach their declared recipients"
        )
    else:
        log.info("dev egress loopback not in effect: %s", reason)
    return resolver.for_send
