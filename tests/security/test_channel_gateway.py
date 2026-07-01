"""Channel identity is kernel-authoritative and fail-closed (decision 0003, SEC-01).

The ChannelPrincipalResolver maps a VERIFIED external sender to a Principal only
via a tenant-scoped binding row: the tenant comes from the channel, the role from
the binding, never the message body. An unbound sender (or an unknown tier) is
denied fail-closed, so a channel can never mint authority the payload asked for.
"""

import pytest

from boltrig.kernel.channel_gateway import resolve_channel_principal
from boltrig.models import Channel, ChannelBinding
from boltrig.store import InMemoryStore

T = "acme"


def _channel() -> Channel:
    return Channel(
        id="ch-1", tenant_id=T, platform="webhook", name="Ops webhook", transport="webhook"
    )


async def _store_with_binding(role: str = "member") -> InMemoryStore:
    s = InMemoryStore()
    await s.upsert_channel(_channel())
    await s.upsert_channel_binding(
        ChannelBinding(
            id="b-1", tenant_id=T, channel_id="ch-1", platform="webhook",
            external_user_id="U-ext-42", subject="alice", role=role,
        )
    )
    return s


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
async def test_bound_sender_resolves_to_its_internal_principal():
    s = await _store_with_binding("member")
    p = await resolve_channel_principal(s, _channel(), "U-ext-42")
    assert p is not None
    assert p.tenant_id == T  # tenant from the channel, not the payload
    assert p.subject == "alice"  # the internal identity, not the raw external id
    assert p.role == "member" and p.actor_tier == "human"


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
async def test_unbound_sender_is_denied_fail_closed():
    s = await _store_with_binding("member")
    # a verified-but-unbound sender resolves to None (caller applies unpaired_behavior)
    assert await resolve_channel_principal(s, _channel(), "U-stranger") is None


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
async def test_unknown_tier_binding_is_denied():
    # a binding to a role outside the channel tiers is fail-closed, never wide-open
    s = await _store_with_binding("root")
    assert await resolve_channel_principal(s, _channel(), "U-ext-42") is None


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
async def test_binding_is_tenant_and_channel_scoped():
    s = await _store_with_binding("member")
    other = Channel(
        id="ch-2", tenant_id=T, platform="webhook", name="Other", transport="webhook"
    )
    # same external id but a different channel: no binding -> denied
    assert await resolve_channel_principal(s, other, "U-ext-42") is None
