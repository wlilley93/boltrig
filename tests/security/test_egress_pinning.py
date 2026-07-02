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

from boltrig.adapters.egress import EgressBlocked, pinned_async_client
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
    with pytest.raises(Exception):
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
        with pytest.raises(Exception):
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
