"""Codex token usage: the fleet's ONLY usage signal from its sole agent runtime.

Codex reports what a turn consumed on `thread/tokenUsage/updated` and nowhere
else. That method was not in the lifecycle set, so it fell through to UNKNOWN and
the numbers were discarded - `AgentResult.succeeded` then defaulted `tokens_used`
to 0 and `price_micros` priced every turn at zero, so a tenant's cost ledger
stayed empty however much it spent. These pin the wiring end to end.
"""

import pytest

from boltrig.fleet.codex_runtime import _drain_until_complete
from boltrig.fleet.domain.execution import RuntimeEventKind
from boltrig.kernel.cost import price_micros


class _Event:
    """Minimal RuntimeEvent stand-in: kind + payload with a to_mapping()."""

    def __init__(self, kind, payload=None):
        self.kind = kind
        self._payload = payload or {}

    @property
    def payload(self):
        return self

    def to_mapping(self):
        return self._payload


async def _drain(events):
    async def gen():
        for e in events:
            yield e

    return await _drain_until_complete(gen())


async def test_reported_tokens_reach_the_caller():
    tokens = await _drain(
        [
            _Event(RuntimeEventKind.TURN_STARTED),
            _Event(RuntimeEventKind.TOKEN_USAGE, {"total_tokens": 1234}),
            _Event(RuntimeEventKind.TURN_COMPLETED),
        ]
    )
    assert tokens == 1234
    # And that is what makes a turn cost anything at all.
    assert price_micros(tokens, "cheap") > 0


async def test_the_last_report_before_completion_wins():
    """Usage arrives mid-turn and can arrive repeatedly; Codex's `total` is
    cumulative for the thread, so the newest report is the run's spend."""
    tokens = await _drain(
        [
            _Event(RuntimeEventKind.TOKEN_USAGE, {"total_tokens": 10}),
            _Event(RuntimeEventKind.TOKEN_USAGE, {"total_tokens": 900}),
            _Event(RuntimeEventKind.TURN_COMPLETED),
        ]
    )
    assert tokens == 900


async def test_no_usage_report_is_honestly_zero():
    """A runtime that reports nothing bills nothing - it must not invent a number."""
    tokens = await _drain(
        [_Event(RuntimeEventKind.TURN_STARTED), _Event(RuntimeEventKind.TURN_COMPLETED)]
    )
    assert tokens == 0


async def test_events_after_completion_are_not_billed():
    tokens = await _drain(
        [
            _Event(RuntimeEventKind.TOKEN_USAGE, {"total_tokens": 5}),
            _Event(RuntimeEventKind.TURN_COMPLETED),
            _Event(RuntimeEventKind.TOKEN_USAGE, {"total_tokens": 999_999}),
        ]
    )
    assert tokens == 5


@pytest.mark.parametrize("bad", [None, "12", -4, True, 0])
async def test_a_malformed_usage_report_does_not_corrupt_the_bill(bad):
    """A bad count must not fail an otherwise good turn, and must never be billed."""
    tokens = await _drain(
        [
            _Event(RuntimeEventKind.TOKEN_USAGE, {"total_tokens": bad}),
            _Event(RuntimeEventKind.TURN_COMPLETED),
        ]
    )
    assert tokens == 0
