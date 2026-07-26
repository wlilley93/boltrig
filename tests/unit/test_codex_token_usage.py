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


# --- tokens -> micros: the second half of the same break -------------------
# Reporting tokens is only half the job. `_true_up_cost` priced them correctly for
# the BUDGET and then dropped the number, while the audit tree and the spawn return
# read `result.cost_micros` - which a runtime never sets, because a runtime reports
# usage and the accountant prices it. So a tenant could spend and still read as free.


async def test_true_up_returns_the_priced_cost_not_the_runtimes_zero():
    from boltrig.fleet.result import AgentResult
    from boltrig.fleet.spawn import Spawner

    class _Cost:
        has_prices = False

        def price(self, tokens, cost_tier, *, model=None, input_tokens=0, output_tokens=0):
            return price_micros(
                tokens, cost_tier, model=model,
                input_tokens=input_tokens, output_tokens=output_tokens,
            )

        async def reconcile(self, *a, **k):
            return None

    class _Kernel:
        cost = _Cost()
        store = None

    class _Capability:
        model_endpoint = None
        cost_tier = "cheap"

    spawner = Spawner.__new__(Spawner)
    spawner._kernel = _Kernel()

    # A runtime that reported real usage but priced nothing (every runtime today).
    result = AgentResult.succeeded(output={}, summary="", tokens_used=11912)
    assert result.cost_micros == 0, "runtimes do not price themselves"

    priced = await spawner._true_up_cost(
        "t", ["tenant"], _Capability(), 0, 0, result
    )
    assert priced == price_micros(11912, "cheap")
    assert priced > 0, "a run that consumed 11912 tokens must not record as free"


async def test_a_zero_token_run_is_genuinely_free():
    """No usage reported => no charge. The fix must not invent spend either."""
    from boltrig.fleet.result import AgentResult
    from boltrig.fleet.spawn import Spawner

    class _Cost:
        has_prices = False

        def price(self, tokens, cost_tier, *, model=None, input_tokens=0, output_tokens=0):
            return price_micros(
                tokens, cost_tier, model=model,
                input_tokens=input_tokens, output_tokens=output_tokens,
            )

        async def reconcile(self, *a, **k):
            return None

    class _Kernel:
        cost = _Cost()
        store = None

    class _Capability:
        model_endpoint = None
        cost_tier = "cheap"

    spawner = Spawner.__new__(Spawner)
    spawner._kernel = _Kernel()
    priced = await spawner._true_up_cost(
        "t", ["tenant"], _Capability(), 0, 0, AgentResult.succeeded(output={}, summary="")
    )
    assert priced == 0


# --- a degraded run is not a free run --------------------------------------
# A model can be called, consume its tokens and THEN produce an unusable answer.
# The provider has already been paid. `AgentResult.degrade` had no way to say so,
# so every degraded run recorded as costing nothing AND was refunded in full -
# a tenant could burn real money on failing turns and never see it.


def test_degrade_carries_what_the_turn_consumed():
    from boltrig.fleet.result import AgentResult

    r = AgentResult.degrade(
        runtime="codex", reason="codex_empty_output", prompt="p", tokens_used=4321
    )
    assert r.degraded is True
    assert r.tokens_used == 4321
    assert price_micros(r.tokens_used, "cheap") > 0, "a paid-for turn must not price as free"


def test_a_degrade_that_knows_nothing_still_reports_zero():
    from boltrig.fleet.result import AgentResult

    r = AgentResult.degrade(runtime="codex", reason="no_scope", prompt="p")
    assert r.tokens_used == 0, "the fix must not invent spend either"


def test_degrade_floors_a_nonsense_count():
    from boltrig.fleet.result import AgentResult

    assert AgentResult.degrade(runtime="c", reason="r", tokens_used=-9).tokens_used == 0


async def test_usage_seen_survives_a_stream_that_raises():
    """A raise discards the drain's locals, so without the caller's sink a turn
    that consumed real tokens and then died reported zero."""
    seen: list[int] = []

    async def exploding():
        yield _Event(RuntimeEventKind.TOKEN_USAGE, {"total_tokens": 777})
        raise RuntimeError("stream died mid-turn")

    try:
        await _drain_until_complete(exploding(), seen)
    except RuntimeError:
        pass
    assert seen and seen[-1] == 777, "the caller must still know what was consumed"
