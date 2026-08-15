"""H2/SEC-61 - the shared egress guard pins the vetted IP (DNS-rebinding TOCTOU).

The pure policy check (test_round_eight / test_round_sixteen) proves a resolved
IP is vetted. These tests prove the SEPARATE half H2 exposed: the connection an
adapter actually opens goes to the AUDITED address, so httpx cannot resolve a
second, different (internal) IP at connect time. A low-TTL attacker domain that
returns a public IP to the guard and 169.254.169.254 to httpx must not reach
internal space.

The connect target is observed by spying on the httpcore network backend
(``AnyIOBackend.connect_tcp``), which both the pinned client and a raw client
route through - so the same test distinguishes the fixed path (connect to the IP
literal) from the vulnerable one (connect to the hostname, re-resolved).
"""

from __future__ import annotations

import socket

import httpcore
import pytest

from boltrig.adapters.egress import EgressBlocked, pinned_async_client, resolve_host
from boltrig.models import GrantSet, InvocationContext

_PUBLIC = "93.184.216.34"  # what the guard resolves the attacker domain to
_METADATA = "169.254.169.254"  # what a rebind would flip to at connect time


class _Sentinel(Exception):
    """Raised by the connect spy so no real socket is opened."""


def _spy_connect(recorder: list[str]):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        recorder.append(host)
        raise _Sentinel(host)

    return connect_tcp


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id="acme", grants=GrantSet.of(["*"]), actor="u", run_id="rH2")


@pytest.mark.security
@pytest.mark.invariant("SEC-61")
def test_resolve_host_preserves_resolver_preference_while_deduplicating(monkeypatch):
    """The pinned address follows the host resolver's reachability preference.

    Losing that order to a set made an IPv4-only browser container randomly pin
    an IPv6 answer even when getaddrinfo had deliberately put IPv4 first.
    """

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, _port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("93.184.216.34", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1::", 0, 0, 0)),
        ],
    )

    assert resolve_host("public.example") == ["93.184.216.34", "2606:2800:220:1::"]


@pytest.mark.security
@pytest.mark.invariant("SEC-61")
async def test_egress_rejects_dns_rebind_between_check_and_connect(monkeypatch):
    """A domain that resolves public at guard time and internal at connect time
    is defeated: the connection is pinned to the vetted public IP, so httpx never
    re-resolves to the metadata address. Fails without pinning (a raw client
    connects to the hostname, which re-resolves to 169.254.169.254)."""
    from boltrig.adapters.builtin.web_fetch import build_web_fetch_adapter

    calls = {"n": 0}

    def rebind(host, port=None, *args, **kwargs):
        # DNS rebinding: the first (guard) resolution is public, any later
        # resolution flips to the cloud-metadata address.
        calls["n"] += 1
        ip = _PUBLIC if calls["n"] == 1 else _METADATA
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", rebind)

    connected: list[str] = []
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", _spy_connect(connected))

    adapter = build_web_fetch_adapter({})
    with pytest.raises(_Sentinel):  # the connect spy is the only way this call fails
        await adapter.execute("web.fetch", {"url": "http://rebind.attacker.test/"}, None, _ctx())

    assert connected, "no connection attempt was made"
    # the socket went to the audited public IP, never the rebind (metadata) target,
    # and httpx never re-resolved the hostname at connect time.
    assert all(h == _PUBLIC for h in connected), connected
    assert _METADATA not in connected
    assert "rebind.attacker.test" not in connected


@pytest.mark.security
@pytest.mark.invariant("SEC-61")
async def test_pinned_client_uses_vetted_ip_and_preserves_host(monkeypatch):
    """A normal allowed host still works: the pinned client connects to the vetted
    public IP while the request's Host header (the SNI / cert basis) stays the
    original hostname."""
    monkeypatch.setattr("boltrig.adapters.egress.resolve_host", lambda host: [_PUBLIC])

    connected: list[str] = []
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", _spy_connect(connected))

    client = pinned_async_client("https://good.example.com/path", {})
    req = client.build_request("GET", "https://good.example.com/path")
    assert req.headers["host"] == "good.example.com"
    async with client:
        with pytest.raises(_Sentinel):  # the connect spy is the only way this call fails
            await client.get("https://good.example.com/path")
    assert connected == [_PUBLIC]


@pytest.mark.security
@pytest.mark.invariant("SEC-61")
async def test_pinned_client_refuses_internal_resolution(monkeypatch):
    """resolve_and_vet refuses when the single audited resolution is internal -
    for an IPv4 or an IPv6 address - so no pinned client is ever built."""
    monkeypatch.setattr("boltrig.adapters.egress.resolve_host", lambda host: [_METADATA])
    with pytest.raises(EgressBlocked):
        pinned_async_client("https://evil.example.com/", {})

    monkeypatch.setattr("boltrig.adapters.egress.resolve_host", lambda host: ["::1"])
    with pytest.raises(EgressBlocked):
        pinned_async_client("https://evil6.example.com/", {})

    monkeypatch.setattr("boltrig.adapters.egress.resolve_host", lambda host: [])
    with pytest.raises(EgressBlocked):
        pinned_async_client("https://noresolve.example.com/", {})


_INTERNAL = "172.18.0.2"  # a docker-network address (RFC 1918)


@pytest.mark.security
@pytest.mark.invariant("SEC-61")
def test_allow_internal_skips_only_the_internal_address_check():
    """The opt-in waives EXACTLY the is_blocked_ip guard: a vetted internal
    service resolves and vets clean, while every other check - scheme, air-gap,
    block/allow lists, a failed resolution - still refuses, flag or not."""
    from boltrig.adapters.egress import check_network_policy

    url = "http://opbox-kernel:8088/mcp"
    # the guarded default refuses the internal resolution...
    assert check_network_policy(url, {}, resolved_ips=[_INTERNAL])
    # ...and the explicit opt-in permits it (this is the whole point of the flag)
    assert check_network_policy(url, {"allow_internal": True}, resolved_ips=[_INTERNAL]) is None

    # everything else still refuses even WITH the flag:
    assert check_network_policy(  # scheme
        "file:///etc/passwd", {"allow_internal": True}, resolved_ips=[_INTERNAL]
    )
    assert check_network_policy(  # air-gap
        url, {"allow_internal": True, "air_gapped": True}, resolved_ips=[_INTERNAL]
    )
    assert check_network_policy(  # block list
        url,
        {"allow_internal": True, "blocked_domains": ["opbox-kernel"]},
        resolved_ips=[_INTERNAL],
    )
    assert check_network_policy(  # allow list
        url,
        {"allow_internal": True, "allowed_domains": ["other.example"]},
        resolved_ips=[_INTERNAL],
    )
    assert check_network_policy(  # a failed resolution is still fail-closed
        url, {"allow_internal": True}, resolved_ips=[]
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-61")
async def test_allow_internal_vets_and_pins_an_operator_vetted_internal_service(monkeypatch):
    """End to end through the pinned client: with the flag the internal target
    is vetted and the connection pinned to the audited 172.x address; without
    it the same target raises EgressBlocked before any client exists."""
    monkeypatch.setattr("boltrig.adapters.egress.resolve_host", lambda host: [_INTERNAL])
    url = "http://opbox-kernel:8088/mcp"

    with pytest.raises(EgressBlocked):  # the default guard: no waiver
        pinned_async_client(url, timeout=30.0)

    connected: list[str] = []
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", _spy_connect(connected))
    client = pinned_async_client(url, {"allow_internal": True}, timeout=30.0)
    async with client:
        with pytest.raises(_Sentinel):  # the connect spy is the only way this fails
            await client.post(url, json={})
    assert connected == [_INTERNAL]  # pinned to the audited internal address
