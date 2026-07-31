"""The egress diversion value type: what a diverted send IS, not when it applies.

Split out of ``boltrig.config.dev_egress`` on 2026-07-31 because the
``channel.send`` adapter needs it and ``boltrig/adapters`` is a FOUNDATION layer
that may not depend upward on ``boltrig/config`` (SEC-54, caught by
tests/security/test_severability.py). The DECISION - the five conditions of
[2026] VJS-CC-BOLTRIG-DEV-EGRESS-LOOPBACK-001 - stays in config where it belongs;
only the fact and its disclosure live here, and config re-exports both so there
is still one name for each.
"""

from __future__ import annotations

from dataclasses import dataclass

# The status a diverted send reports, everywhere it is reported (C4). A distinct
# string rather than a flag beside ``sent``, so a reader who checks only the
# status - which is every reader that matters - cannot read a diversion as a
# delivery.
DIVERTED_STATUS = "diverted"


@dataclass(frozen=True)
class Diversion:
    """A send that will NOT reach its declared recipient, and where it goes instead.

    Constructed only when ``diversion_block`` returns None. Its existence is the
    permission; its ``notice`` is the disclosure that makes an approval of it
    valid (C3).
    """

    declared_recipient: str
    loopback_url: str

    def notice(self) -> str:
        """The one sentence every surface carries (C3).

        Both halves are load-bearing and neither may be dropped for brevity: the
        true destination, and the express statement that the declared recipient
        is NOT messaged. An approver told only "development mode" has not been
        told what they are approving.
        """
        who = self.declared_recipient or "the declared recipient"
        return (
            f"DEVELOPMENT EGRESS LOOPBACK: this message will be delivered to the "
            f"stack's own loopback intake ({self.loopback_url}). {who} will NOT "
            f"be messaged. Approving this approves the diversion, not a send."
        )

    def as_context(self) -> dict[str, object]:
        """The machine-readable half, for the approval card and the record."""
        return {
            "diverted": True,
            "declared_recipient": self.declared_recipient,
            "actual_recipient": self.loopback_url,
            "will_reach_declared_recipient": False,
            "authority": "[2026] VJS-CC-BOLTRIG-DEV-EGRESS-LOOPBACK-001",
        }


__all__ = ["DIVERTED_STATUS", "Diversion"]
