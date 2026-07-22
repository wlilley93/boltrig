"""The channel gateway's local egress guard (decision 0003, condition 2).

A minimal local implementation (NO ``boltrig`` import, SEC-28; mirrors the
pi_sidecar guard): before the gateway connects to the kernel intake or a
platform endpoint it refuses any host that resolves to metadata / link-local /
unspecified space, and every private / loopback / reserved address UNLESS the
host is on the operator allow-list (``CHANNEL_GATEWAY_EGRESS_ALLOW``).

One deliberate deviation from the pi_sidecar guard, documented: LOOPBACK is
allow-listable here (a dev kernel is ``localhost``; the pi_sidecar refuses it
unconditionally). The always-refused subset is narrowed to link-local
(including 169.254.169.254 cloud metadata) and unspecified addresses. The real
control stays the container/network egress restriction (see the Dockerfile
header); this check is defence in depth. KNOWN RESIDUAL (DNS TOCTOU, same as
pi_sidecar): the ``getaddrinfo`` answer is validated at check time while httpx
re-resolves at connect time; a rebinding answer could pass. Connect-to-IP
pinning machinery is deliberately not carried by this severed service.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def _is_always_blocked_ip(ip: str) -> bool:
    """Link-local (incl. cloud metadata) / unspecified: NEVER a legitimate
    gateway target, refused even for an allow-listed host. Unparseable fails
    closed."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_link_local or addr.is_unspecified


def _is_internal_ip(ip: str) -> bool:
    """Private / loopback / reserved / multicast: refused unless the host is
    explicitly allow-listed. Unparseable fails closed."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def egress_refusal(url: str | None, allow: set[str]) -> str | None:
    """Return a refusal reason if ``url`` is not a safe outbound target for the
    gateway, else None. ``allow`` is the operator-configured host set (the
    kernel intake host + the platform endpoints)."""
    if not url:
        return "no url"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        return f"unsupported scheme '{parsed.scheme}'"
    host = parsed.hostname
    if not host:
        return "no host in url"
    host_l = host.lower()
    allowlisted = any(host_l == a or host_l.endswith("." + a) for a in allow)
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return "host did not resolve"
    ips = {info[4][0] for info in infos}
    if not ips:
        return "host did not resolve"
    for ip in ips:
        if _is_always_blocked_ip(ip):
            return f"target resolves to a metadata/link-local address ({ip})"
        if not allowlisted and _is_internal_ip(ip):
            return f"target resolves to an internal address ({ip}) not on the allow-list"
    return None
