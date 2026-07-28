"""Exactly once per user message, on the surface a human types into.

Measured on the live Classical Visas tenant, 2026-07-27 23:16: one message sent
five times 1.4-2.1s apart (a client retry loop), and SEVEN ``agent_spawn`` rows
across that window. Each retry convened another agent - N times the spend, N
duplicate answers.
"""

from __future__ import annotations

import pytest

from boltrig.fleet.chat_idempotency import (
    CHAT_DEDUP_CHANNEL,
    MAX_KEY_LENGTH,
    claim_turn,
    normalised_key,
    replay_frames,
)


class _Store:
    """Records like the real primitive: first caller wins, atomically."""

    def __init__(self) -> None:
        self.seen: set[tuple[str, str, str]] = set()
        self.calls: list[tuple[str, str, str, int]] = []

    async def record_channel_delivery(
        self, tenant_id: str, channel_id: str, delivery_id: str, *, ttl_seconds: int
    ) -> bool:
        self.calls.append((tenant_id, channel_id, delivery_id, ttl_seconds))
        marker = (tenant_id, channel_id, delivery_id)
        if marker in self.seen:
            return False
        self.seen.add(marker)
        return True


class _BrokenStore:
    async def record_channel_delivery(self, *a, **k) -> bool:  # noqa: ANN002, ANN003
        raise RuntimeError("store is down")


async def test_the_first_send_wins_and_the_retry_does_not() -> None:
    """The whole point: a repeat must not convene a second agent."""
    store = _Store()
    assert await claim_turn(store, "cv", "key-1") is True
    assert await claim_turn(store, "cv", "key-1") is False
    assert await claim_turn(store, "cv", "key-1") is False


async def test_the_measured_storm_yields_exactly_one_run() -> None:
    """Five sends 1.4-2.1s apart produced five runs. Now: one."""
    store = _Store()
    claims = [await claim_turn(store, "cv", "storm") for _ in range(5)]
    assert claims.count(True) == 1, "exactly one send may proceed"
    assert claims.count(False) == 4


async def test_a_different_key_is_a_different_message() -> None:
    store = _Store()
    assert await claim_turn(store, "cv", "a") is True
    assert await claim_turn(store, "cv", "b") is True


async def test_keys_are_tenant_scoped() -> None:
    """Two tenants choosing the same key must not silence each other."""
    store = _Store()
    assert await claim_turn(store, "cv", "same") is True
    assert await claim_turn(store, "other-tenant", "same") is True


async def test_no_key_means_todays_behaviour_exactly() -> None:
    """An SDK that sends no key loses nothing it had - and no marker is written."""
    store = _Store()
    for _ in range(3):
        assert await claim_turn(store, "cv", None) is True
    assert store.calls == []


async def test_chat_keys_live_in_their_own_namespace() -> None:
    """A client-chosen key must not be able to collide with a channel delivery id."""
    store = _Store()
    await claim_turn(store, "cv", "k")
    assert store.calls[0][1] == CHAT_DEDUP_CHANNEL


async def test_a_dead_marker_store_never_costs_a_message() -> None:
    """Fails OPEN. A duplicate answer is bad; losing what someone typed is worse."""
    assert await claim_turn(_BrokenStore(), "cv", "key") is True


@pytest.mark.parametrize(
    "raw", ["", "   ", None, 42, b"bytes", "x" * (MAX_KEY_LENGTH + 1)]
)
def test_an_unusable_key_is_absent_not_fatal(raw: object) -> None:
    """Bounded because it is caller-supplied and stored; absent rather than refused
    because losing the turn would be worse than the duplicate."""
    assert normalised_key(raw) is None


def test_a_usable_key_is_trimmed() -> None:
    assert normalised_key("  abc  ") == "abc"
    assert normalised_key("x" * MAX_KEY_LENGTH) == "x" * MAX_KEY_LENGTH


def test_a_replay_is_answered_as_a_terminal_turn_not_an_error() -> None:
    """The caller retried something already accepted; the honest answer is that it
    was accepted, once. Shaped like any turn so a client needs no special case."""
    frames = replay_frames("conv-1")
    assert [f["type"] for f in frames] == ["message_start", "message_end"]
    assert all(f["replay"] is True for f in frames)
    assert all(f["conversation_id"] == "conv-1" for f in frames)


# --- what SHIPS, not just the helper ------------------------------------------
# A mutation that survived an entire suite earlier this week taught the lesson:
# the wiring is what goes untested. These drive the real ChatService.


def _counting_executor(runs: list[str]):
    async def executor(
        *, tenant_id, user_id, role, grants, conversation_id, run_id, message,
        relay, attachments=None, **kw,
    ):
        runs.append(run_id)
        relay.publish(run_id, {"type": "text_delta", "delta": "ok"})

    return executor


async def test_a_retried_send_does_not_convene_a_second_agent() -> None:
    """SEEDED RED against the unwired version: this is the defect itself.

    Drives the real ChatService twice with one key, and asserts the EXECUTOR ran
    once - the executor being what spawns the agent and bills the tenant.
    """
    from boltrig.fleet.chat import ChatService
    from boltrig.kernel.events import EventRelay
    from boltrig.store import InMemoryStore

    runs: list[str] = []
    chat = ChatService(InMemoryStore(), EventRelay(), turn_executor=_counting_executor(runs))

    async def send():
        return [
            e
            async for e in chat.handle_turn(
                tenant_id="cv", user_id="wb", role="admin",
                message="Fully debug the env", idempotency_key="retry-1",
            )
        ]

    first = await send()
    second = await send()

    assert len(runs) == 1, f"the retry convened another agent: {len(runs)} runs"
    assert any(e.get("type") == "text_delta" for e in first)
    assert [e.get("type") for e in second] == ["message_start", "message_end"]
    assert all(e.get("replay") for e in second)


async def test_two_distinct_messages_still_both_run() -> None:
    """The guard must not swallow genuine traffic."""
    from boltrig.fleet.chat import ChatService
    from boltrig.kernel.events import EventRelay
    from boltrig.store import InMemoryStore

    runs: list[str] = []
    chat = ChatService(InMemoryStore(), EventRelay(), turn_executor=_counting_executor(runs))
    for key in ("m1", "m2"):
        async for _ in chat.handle_turn(
            tenant_id="cv", user_id="wb", role="admin", message="hello",
            idempotency_key=key,
        ):
            pass
    assert len(runs) == 2


async def test_without_a_key_every_send_runs_exactly_as_before() -> None:
    from boltrig.fleet.chat import ChatService
    from boltrig.kernel.events import EventRelay
    from boltrig.store import InMemoryStore

    runs: list[str] = []
    chat = ChatService(InMemoryStore(), EventRelay(), turn_executor=_counting_executor(runs))
    for _ in range(2):
        async for _e in chat.handle_turn(
            tenant_id="cv", user_id="wb", role="admin", message="hello",
        ):
            pass
    assert len(runs) == 2
