"""The shared outbound-egress guard (Batch 1 INJ-02, Batch 2 CLOUD-03).

SSRF defence in one place, so every adapter that makes an outbound HTTP call (not
just web.fetch) refuses a target that resolves to internal infrastructure. The
guard:

  * allows only http/https,
  * refuses any address that is private / loopback / link-local / reserved /
    multicast / unspecified - independent of the domain name, so a public name
    pointing at internal space (DNS rebinding) is still refused,
  * specifically refuses the cloud metadata endpoint 169.254.169.254 (it is
    link-local, so already covered; called out because CLOUD-03 makes it the
    headline threat: SSRF -> IMDS -> managed-identity token theft),
  * honours an optional NetworkConfig (air-gap, allow/block domain lists).

It is a pure decision (no network) over a host + its resolved IPs, plus a small
``resolve_host`` helper, so it is fully testable offline. Adapters call
``assert_egress_allowed(url, config)`` before any request and must not follow
redirects blindly (a public URL could 30x into internal space).
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
    for ip in resolve_host(host):
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
    scheme, air-gap, block list, allow list, then the SSRF guard over every IP."""
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
    return list({info[4][0] for info in infos})


class EgressBlocked(Exception):
    """An outbound request was refused by the egress guard (SSRF/policy)."""


def assert_egress_allowed(url: str, config: dict[str, Any] | None = None) -> None:
    """Resolve the URL's host and refuse it (raise) if the egress guard says so.
    Call this before any outbound request; refuses BEFORE the network call."""
    host = urlparse(url).hostname or ""
    reason = check_network_policy(url, config, resolved_ips=resolve_host(host))
    if reason:
        raise EgressBlocked(f"egress refused: {reason}")
