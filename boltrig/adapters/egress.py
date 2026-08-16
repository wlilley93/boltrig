"""The shared outbound-egress guard (Batch 1 INJ-02, Batch 2 CLOUD-03, H2/SEC-61).

SSRF defence in one place, so every adapter that makes an outbound HTTP call (not
just web.fetch) refuses a target that resolves to internal infrastructure. The
guard:

  * allows only http/https,
  * refuses any address that is private / loopback / link-local / reserved /
    multicast / unspecified - independent of the domain name (covers IPv4 and
    IPv6),
  * specifically refuses the cloud metadata endpoint 169.254.169.254 (it is
    link-local, so already covered; called out because CLOUD-03 makes it the
    headline threat: SSRF -> IMDS -> managed-identity token theft),
  * honours an optional NetworkConfig (air-gap, allow/block domain lists).

The internal-address refusal has ONE explicit opt-in: ``allow_internal`` in the
config skips the ``is_blocked_ip`` check (and ONLY that check - scheme, air-gap,
and the block/allow lists still apply). It exists for operator-vetted INTERNAL
services whose URL was registered through the governed control plane and
approved by a human (the MCP consumer's ``control.mcp_server.register`` +
SEC-22 review gate), never for agent-influenced URLs: the generated-adapter
spec fetch and every web/browser path must keep the full guard.

DNS rebinding (H2/SEC-61). The pure check is not enough on its own: an adapter
that vets a host then hands the raw URL to httpx lets httpx resolve AGAIN at
connect time, so a low-TTL attacker domain can return a public IP to the guard
and an internal one to httpx (a resolve-then-connect TOCTOU). The fix is to pin
the connection: resolve the host ONCE, vet every returned address, then connect
to the vetted IP literal while TLS SNI and certificate verification still use the
original host. Adapters must therefore build their httpx client via
``pinned_async_client(url, config)`` (or ``pinned_async_client_for_ip`` when they
already hold a vetted IP), NOT ``assert_egress_allowed`` + a raw-URL client. The
pinned client also forces ``follow_redirects=False`` (a 30x must not be chased
into internal space). With pinning in place, a public name pointing at internal
space really is refused - httpx cannot re-resolve past the audited address.

The pure decision (``check_network_policy``) takes a host + its resolved IPs and
does no network, so it is fully testable offline; ``resolve_host`` and the pinned
client/transport are the thin network-touching helpers.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse


def is_blocked_ip(ip: str) -> bool:
    """True if an address must be refused regardless of any domain list: private,
    loopback, link-local (incl. 169.254.169.254 cloud metadata), reserved,
    multicast, or unspecified."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable -> fail closed
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def is_metadata_ip(ip: str) -> bool:
    """True if an address is a link-local / cloud-metadata address (169.254.0.0/16
    incl. 169.254.169.254, and fe80::/10). The always-safe subset of is_blocked_ip:
    no legitimate adapter target is link-local, so blocking it never breaks a real
    integration while it closes the SSRF -> IMDS -> token-theft path (CLOUD-03)."""
    try:
        return ipaddress.ip_address(ip).is_link_local
    except ValueError:
        return False


def assert_no_metadata_egress(url: str) -> None:
    """Refuse (raise) if ``url``'s host resolves to a link-local / metadata
    address. Safe to apply on every adapter request (CLOUD-03)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return  # not an outbound HTTP target
    host = parsed.hostname
    if not host:
        return
    addresses = resolve_host(host)
    # An empty list means the host DID NOT RESOLVE - `resolve_host` returns [] on
    # OSError - and every other caller in this module treats that as a refusal.
    # This one used to iterate it, so an unresolvable host ran the loop body zero
    # times and was ALLOWED: fail-open, on the one guard whose whole subject is the
    # cloud-metadata endpoint. It was reachable by anyone who could arrange a
    # SERVFAIL for a name the caller was about to fetch.
    if not addresses:
        raise EgressBlocked("egress refused: host did not resolve (CLOUD-03)")
    for ip in addresses:
        if is_metadata_ip(ip):
            raise EgressBlocked(
                f"egress refused: target resolves to a cloud-metadata/link-local "
                f"address ({ip}) (CLOUD-03)"
            )


def _host_matches(host: str, domain: str) -> bool:
    host, domain = host.lower().rstrip("."), domain.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def check_network_policy(
    url: str, config: dict[str, Any] | None = None, *, resolved_ips: list[str] | None = None
) -> str | None:
    """Return a refusal reason if the fetch is not permitted, else ``None``.

    ``resolved_ips`` is injectable so the policy is testable without DNS. Order:
    scheme, air-gap, block list, allow list, then the SSRF guard over every IP.

    ``allow_internal`` skips ONLY the final SSRF guard (the is_blocked_ip
    check): an explicit opt-in for an operator-vetted internal service whose
    URL arrived through a human-reviewed registration - never for an
    agent-influenced URL. Scheme, air-gap, and the domain lists still apply."""
    config = config or {}
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"unsupported scheme '{parsed.scheme}'"
    host = parsed.hostname
    if not host:
        return "no host in url"
    if config.get("air_gapped"):
        return "air-gapped: no egress permitted"
    blocked = config.get("blocked_domains") or ()
    if any(_host_matches(host, d) for d in blocked):
        return f"domain '{host}' is blocked"
    allowed = config.get("allowed_domains") or ()
    if allowed and not any(_host_matches(host, d) for d in allowed):
        return f"domain '{host}' is not on the allow list"
    if resolved_ips is not None:
        if not resolved_ips:
            return "host did not resolve"
        if not config.get("allow_internal"):
            for ip in resolved_ips:
                if is_blocked_ip(ip):
                    return f"target resolves to a non-routable/internal address ({ip})"
    return None


def resolve_host(host: str) -> list[str]:
    """Resolve a host to its addresses (an IP literal resolves to itself, no DNS).
    Empty list means it did not resolve (the caller treats that as fail-closed)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    # Preserve the resolver's preference order while removing duplicates.  A
    # set made the selected, pinned address effectively random; on an
    # IPv4-only container it could pick a perfectly public IPv6 answer first
    # and fail every browser navigation even though the resolver had returned a
    # reachable IPv4 address first.  We still resolve exactly once and vet every
    # answer before the caller connects to the first audited address.
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        if isinstance(address, str) and address not in addresses:
            addresses.append(address)
    return addresses


class EgressBlocked(Exception):
    """An outbound request was refused by the egress guard (SSRF/policy)."""


def assert_egress_allowed(url: str, config: dict[str, Any] | None = None) -> None:
    """Resolve the URL's host and refuse it (raise) if the egress guard says so.
    Call this before any outbound request; refuses BEFORE the network call.

    NOTE (H2/SEC-61): this vets a resolution but does not pin it, so a caller that
    then hands the raw URL to httpx allows a second, independent DNS lookup at
    connect time (rebinding TOCTOU). Prefer ``pinned_async_client`` for the client
    an adapter actually connects with; keep this only as a pre-flight assertion
    for effective/absolute URLs that ride a pinned client to the same host."""
    host = urlparse(url).hostname or ""
    reason = check_network_policy(url, config, resolved_ips=resolve_host(host))
    if reason:
        raise EgressBlocked(f"egress refused: {reason}")


def resolve_and_vet(url: str, config: dict[str, Any] | None = None) -> tuple[str, str]:
    """Resolve ``url``'s host ONCE, run the full egress policy over every returned
    IPv4/IPv6 address, and return ``(host, vetted_ip)`` - the IP the connection
    must be pinned to. Raise :class:`EgressBlocked` if the policy refuses or the
    host does not resolve. The single audited resolution is what closes the
    rebinding TOCTOU (H2/SEC-61)."""
    host = urlparse(url).hostname or ""
    ips = resolve_host(host)
    reason = check_network_policy(url, config, resolved_ips=ips)
    if reason:
        raise EgressBlocked(f"egress refused: {reason}")
    return host, ips[0]  # every ip in ips passed is_blocked_ip; pin the first


def _pinned_backend(pinned_ip: str, inner: Any | None = None) -> Any:
    """An httpcore network backend that connects to ``pinned_ip`` regardless of
    the host httpx would otherwise resolve, so no second DNS lookup can differ
    from the audited address (H2/SEC-61). TLS SNI + cert verification still use
    the original host (it stays in the request URL). ``inner`` is injectable for
    tests."""
    import httpcore

    base = inner if inner is not None else httpcore.AnyIOBackend()

    class _PinnedBackend(httpcore.AnyIOBackend):
        async def connect_tcp(  # noqa: D401
            self,
            host: Any,
            port: Any,
            timeout: Any = None,
            local_address: Any = None,
            socket_options: Any = None,
        ) -> Any:
            return await base.connect_tcp(
                pinned_ip, port, timeout=timeout,
                local_address=local_address, socket_options=socket_options,
            )

        async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> Any:
            return await base.connect_unix_socket(*args, **kwargs)

        async def sleep(self, seconds: float) -> None:
            await base.sleep(seconds)

    return _PinnedBackend()


def pinned_transport(url: str, config: dict[str, Any] | None = None, *, inner_backend: Any | None = None) -> Any:
    """Vet ``url`` and return an ``httpx.AsyncHTTPTransport`` pinned to the audited
    IP (H2/SEC-61). For callers that build the ``httpx.AsyncClient`` themselves
    (e.g. a client with its own base_url/auth/timeout) and just need the pinned
    transport. Raise :class:`EgressBlocked` if the guard refuses."""
    import httpx

    _host, vetted_ip = resolve_and_vet(url, config)
    transport = httpx.AsyncHTTPTransport()
    transport._pool._network_backend = _pinned_backend(vetted_ip, inner_backend)
    return transport


def pinned_async_client_for_ip(vetted_ip: str, *, inner_backend: Any | None = None, **client_kwargs: Any) -> Any:
    """Return an ``httpx.AsyncClient`` whose TCP connections are pinned to an
    already-vetted IP (H2/SEC-61). ``follow_redirects`` is forced False (a 30x
    must not be chased to a different, unpinned host). The URL passed to the
    client must keep the original hostname so SNI/cert verification are correct."""
    import httpx

    # A caller-supplied TLS verifier belongs on the transport.  Passing
    # ``verify`` to AsyncClient while also supplying a transport silently leaves
    # the transport's default trust configuration in force.
    verify = client_kwargs.pop("verify", True)
    transport = httpx.AsyncHTTPTransport(verify=verify)
    transport._pool._network_backend = _pinned_backend(vetted_ip, inner_backend)
    client_kwargs["follow_redirects"] = False
    client_kwargs["transport"] = transport
    return httpx.AsyncClient(**client_kwargs)


def pinned_async_client(
    url: str, config: dict[str, Any] | None = None, *, inner_backend: Any | None = None, **client_kwargs: Any
) -> Any:
    """Vet ``url`` and return an ``httpx.AsyncClient`` pinned to the audited IP so
    httpx cannot re-resolve to a different (internal) address (H2/SEC-61). Raise
    :class:`EgressBlocked` if the egress guard refuses. Call the client with the
    original URL (host preserved) - only the TCP target is pinned."""
    _host, vetted_ip = resolve_and_vet(url, config)
    return pinned_async_client_for_ip(vetted_ip, inner_backend=inner_backend, **client_kwargs)


def _pinned_sync_backend(pinned_ip: str, inner: Any | None = None) -> Any:
    """The sync counterpart of :func:`_pinned_backend` (H2/SEC-61), for callers
    that must use a synchronous ``httpx.Client`` (e.g. spec loading, which runs
    outside the dispatch path)."""
    import httpcore

    base = inner if inner is not None else httpcore.SyncBackend()

    class _PinnedSyncBackend(httpcore.SyncBackend):
        def connect_tcp(  # noqa: D401
            self,
            host: Any,
            port: Any,
            timeout: Any = None,
            local_address: Any = None,
            socket_options: Any = None,
        ) -> Any:
            return base.connect_tcp(
                pinned_ip, port, timeout=timeout,
                local_address=local_address, socket_options=socket_options,
            )

        def connect_unix_socket(self, *args: Any, **kwargs: Any) -> Any:
            return base.connect_unix_socket(*args, **kwargs)

        def sleep(self, seconds: float) -> None:
            base.sleep(seconds)

    return _PinnedSyncBackend()


def pinned_sync_client(
    url: str, config: dict[str, Any] | None = None, *, inner_backend: Any | None = None, **client_kwargs: Any
) -> Any:
    """Vet ``url`` and return a synchronous ``httpx.Client`` pinned to the audited
    IP - the sync counterpart of :func:`pinned_async_client` (H2/SEC-61).
    ``follow_redirects`` is forced False (a 30x must not be chased into internal
    space). Raise :class:`EgressBlocked` if the egress guard refuses."""
    import httpx

    _host, vetted_ip = resolve_and_vet(url, config)
    transport = httpx.HTTPTransport()
    transport._pool._network_backend = _pinned_sync_backend(vetted_ip, inner_backend)
    client_kwargs["follow_redirects"] = False
    client_kwargs["transport"] = transport
    return httpx.Client(**client_kwargs)
