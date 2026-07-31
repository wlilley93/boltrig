"""D7-V2 of [2026] VJS-CC-BOLTRIG-D7-DISCHARGE-001: the varied checkable.

The court varied D7 of the development-posture order: the Principal relays the
drafted notice (V1), then the stack writes a host-boundary security event in the
client's own tenant recording it (V2). These tests hold the V2 mechanism
(scripts/record_d7_relay.py) to the directive's exact terms BEFORE it is ever
run against the client tenant - the one place a rehearsal is possible, since the
real run happens once, on production, after V1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import record_d7_relay  # noqa: E402

pytestmark = pytest.mark.security

# Binds directive V2 of [2026] VJS-CC-BOLTRIG-D7-DISCHARGE-001: every test below
# holds the row-writing mechanism to the varied checkable's exact terms.


def test_v2_detail_carries_every_field_the_directive_names() -> None:
    """[2026] VJS-CC-BOLTRIG-D7-DISCHARGE-001 D7-V2 names the row's contents:
    the notice sha256, the channel class, the relay date, and the audit sequence
    range 262-266. A row missing any of them is not the checkable."""
    detail = record_d7_relay.relay_detail(
        digest="a" * 64, relay_date="2026-08-01", channel_class="in-person"
    )
    assert detail["notice_sha256"] == "a" * 64
    assert detail["channel_class"] == "in-person"
    assert detail["relay_date"] == "2026-08-01"
    assert detail["audit_seq_range"] == "262-266"
    assert detail["order"] == "2026-VJS-CC-BOLTRIG-D7-DISCHARGE-001"


def test_v2_asserts_a_relay_never_a_delivery() -> None:
    """The row records what happened (a relay by the Principal), never a send the
    stack did not perform - the C4 discipline of DEV-EGRESS-LOOPBACK-001 applied
    here: no reader of this record may obtain a claim of delivery."""
    assert record_d7_relay.REASON == "d7_notice_relayed"
    detail = record_d7_relay.relay_detail(
        digest="b" * 64, relay_date="2026-08-01", channel_class="email"
    )
    joined = " ".join(f"{k}={v}" for k, v in detail.items()).lower()
    assert "sent" not in joined and "delivered" not in joined


def test_v2_refuses_to_run_without_the_v1_facts() -> None:
    """Order of operations IS the directive: the script must be unable to run
    before the Principal states the relay happened. --relay-date and
    --channel-class are the V1 facts only he can supply, so they are required
    with no defaults, and blank values are refused too."""
    with pytest.raises(SystemExit) as exc:
        record_d7_relay.main([])  # argparse: required args absent
    assert exc.value.code == 2
    assert record_d7_relay.main(["--relay-date", " ", "--channel-class", "email"]) == 2
    assert record_d7_relay.main(["--relay-date", "2026-08-01", "--channel-class", " "]) == 2


def test_v2_pins_the_notice_the_order_names_not_a_parameter() -> None:
    """The notice path and audit range are the ORDER'S facts, not flags: a flag
    would let a later run record the relay of a different document under this
    order's name. And the pinned notice must actually exist and still carry its
    own not-sent discipline."""
    assert record_d7_relay.NOTICE_PATH == Path(
        "docs/findings/2026-07-31-cv-client-notice-D7.md"
    )
    digest = record_d7_relay.notice_sha256(REPO)
    assert len(digest) == 64
    text = (REPO / record_d7_relay.NOTICE_PATH).read_text(encoding="utf-8")
    assert "NOT SENT" in text
