"""The web.fetch adapter: internet access as a governed verb (Round Eight, S4).

"Uncaged" means an agent may reach the internet, NOT that it bypasses the kernel.
Internet access is therefore a normal verb (``web.fetch``) bound to this adapter,
governed by exactly the same dispatch chokepoint as every other capability - grant
check, the HITL gate, audit. No exception, no second path.

Three deliberate choices, each a bound invariant:

* **Read-only first (S4.2).** Only ``web.fetch`` (an HTTP GET) ships. Interactive
  browsing (navigate / click / sessions) is a separate, later capability, not built
  by default.

* **Higher consequence tier (S4.3).** ``web.fetch`` is ``consequence="high"``.
  Fetched content is the one place untrusted, attacker-reachable text enters an
  agent's reasoning, so the per-verb HITL gate is real defense: even if injected
  page content steers the agent toward a consequential next call, that next verb's
  OWN gate still fires. Fetched content is returned as data, never authority.

* **SSRF + NetworkConfig enforced (S4.1/S4.4, SEC-52).** ``NetworkConfig`` was
  modeled but read by nothing; this adapter enforces it (air-gap, allow/block
  domains). Independently, the SSRF guard rejects targets resolving to private /
  loopback / link-local / reserved / multicast addresses and the cloud metadata
  endpoint, regardless of the domain name - a public name pointing at internal
  infrastructure was never meant to be reachable this way. Redirects are NOT
  followed (a public URL must not redirect into internal space).

The policy/SSRF decision is a pure function (``check_network_policy``) so it is
fully testable offline, and a blocked target is refused BEFORE any network call.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

from nankle.adapters.base import Credential, Result, VerbSpec
from nankle.models import InvocationContext, NetworkPolicyViolation

_MAX_BYTES = 256 * 1024  # default cap on returned content


def _host_matches(host: str, domain: str) -> bool:
    """A host matches a domain entry if it is that domain or a subdomain of it."""
    host, domain = host.lower().rstrip("."), domain.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def is_blocked_ip(ip: str) -> bool:
    """True if an address is one the SSRF guard must refuse, independent of any
    domain list: private, loopback, link-local (incl. 169.254.169.254 metadata),
    reserved, multicast, or unspecified."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable -> fail closed
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def check_network_policy(
    url: str, config: dict[str, Any], *, resolved_ips: list[str] | None = None
) -> str | None:
    """Return a refusal reason if the fetch is not permitted, else ``None``.

    ``resolved_ips`` is injectable so the policy is testable without DNS; at
    runtime the adapter resolves the host and passes the result in. Order: scheme,
    air-gap, block list, allow list, then the SSRF guard over every resolved IP."""
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
    # SSRF: every address the host resolves to must be external.
    if resolved_ips is not None:
        if not resolved_ips:
            return "host did not resolve"
        for ip in resolved_ips:
            if is_blocked_ip(ip):
                return f"target resolves to a non-routable/internal address ({ip})"
    return None


def _resolve(host: str) -> list[str]:
    """Resolve a host to its addresses (an IP literal resolves to itself, no DNS)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []  # caller treats empty as "did not resolve" -> fail closed
    return list({info[4][0] for info in infos})


class WebFetchAdapter:
    """Read-only HTTP GET as a governed, SSRF-guarded verb."""

    id = "web"
    version = "0.1.0"
    runtime = "http"
    source = "builtin"

    def __init__(self, network_config: dict[str, Any] | None = None) -> None:
        self._config = dict(network_config or {})

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="web.fetch", noun_id="web",
                input_schema={
                    "type": "object",
                    "properties": {"url": {"type": "string"},
                                   "max_bytes": {"type": "integer"}},
                    "required": ["url"]},
                output_schema={"type": "object"},
                # High: fetched content is an untrusted-input / prompt-injection
                # surface, so the HITL gate can hold it (S4.3).
                consequence="high",
                description="Fetch a URL (read-only GET), SSRF-guarded and policy-checked"),
        ]

    async def execute(
        self, verb: str, params: dict, credential: Credential | None, context: InvocationContext
    ) -> Result:
        if verb != "web.fetch":
            from nankle.adapters.base import AdapterError, ErrorClass

            return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))
        url = params["url"]
        host = urlparse(url).hostname or ""
        resolved = _resolve(host)
        reason = check_network_policy(url, self._config, resolved_ips=resolved)
        if reason:
            # A blocked target is refused before any network call (fail-closed).
            raise NetworkPolicyViolation(f"web.fetch refused: {reason}")

        import httpx

        cap = int(params.get("max_bytes") or _MAX_BYTES)
        proxy = self._config.get("https_proxy") or None
        # Redirects are NOT followed: a public URL must not redirect into internal
        # space and slip past the SSRF guard.
        async with httpx.AsyncClient(follow_redirects=False, timeout=15.0, proxy=proxy) as client:
            resp = await client.get(url)
        body = resp.content[:cap]
        return Result.success({
            "status": resp.status_code,
            "url": url,
            "content_type": resp.headers.get("content-type", ""),
            "content": body.decode("utf-8", errors="replace"),
            "truncated": len(resp.content) > cap,
        })

    async def health(self) -> str:
        return "ok"


def build_web_fetch_adapter(network_config: dict[str, Any] | None = None) -> WebFetchAdapter:
    """Construct the web.fetch adapter from the manifest ``network`` section."""
    return WebFetchAdapter(network_config)
