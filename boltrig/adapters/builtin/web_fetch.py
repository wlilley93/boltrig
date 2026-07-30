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

import ssl
from typing import Any
from urllib.parse import urlparse

from boltrig.adapters.base import Credential, Result, VerbSpec
# The SSRF/policy guard now lives in the shared egress module so every HTTP
# adapter uses one source of truth (consolidation). Re-exported here so callers /
# tests that import them from web_fetch keep working.
from boltrig.adapters.egress import (  # noqa: F401
    check_network_policy,
    is_blocked_ip,
    resolve_host as _resolve,
)
from boltrig.models import InvocationContext, NetworkPolicyViolation

_MAX_BYTES = 256 * 1024  # default cap on returned content


class WebFetchAdapter:
    """Read-only HTTP GET as a governed, SSRF-guarded verb."""

    id = "web"
    version = "0.1.0"
    runtime = "http"
    source = "builtin"

    def __init__(self, network_config: dict[str, Any] | None = None) -> None:
        self._config = dict(network_config or {})
        ca_bundle = self._config.get("ca_bundle")
        # Build the context once at process start.  A missing or malformed
        # operator-supplied bundle fails closed instead of silently falling back
        # to public roots.  The path/context never enters results or posture.
        self._tls_verify: ssl.SSLContext | bool = (
            ssl.create_default_context(cafile=str(ca_bundle))
            if ca_bundle
            else True
        )

    def network_policy_posture(self) -> dict[str, Any]:
        """Return the redacted policy this live adapter actually consumes."""
        allowed = tuple(self._config.get("allowed_domains") or ())
        blocked = tuple(self._config.get("blocked_domains") or ())
        proxy_configured = bool(self._config.get("https_proxy"))
        return {
            "surface": "web.fetch",
            "status": "enforced",
            "policy_snapshot": "adapter_process_start",
            "fields": {
                "air_gapped": {
                    "enforcement": "enforced",
                    "enabled": bool(self._config.get("air_gapped")),
                },
                "https_proxy": {
                    "enforcement": "enforced",
                    "configured": proxy_configured,
                },
                "ca_bundle": {
                    "enforcement": "enforced",
                    "configured": bool(self._config.get("ca_bundle")),
                },
                "allowed_domains": {
                    "enforcement": "enforced",
                    "configured": bool(allowed),
                    "entry_count": len(allowed),
                },
                "blocked_domains": {
                    "enforcement": "enforced",
                    "configured": bool(blocked),
                    "entry_count": len(blocked),
                },
            },
            "controls": {
                "ssrf_preflight": "enforced",
                "redirects": "disabled",
                "dns_pinning": (
                    "proxy_resolution_delegated"
                    if proxy_configured
                    else "enforced"
                ),
            },
        }

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
            from boltrig.adapters.base import AdapterError, ErrorClass

            return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))
        url = params["url"]
        host = urlparse(url).hostname or ""
        resolved = _resolve(host)
        reason = check_network_policy(url, self._config, resolved_ips=resolved)
        if reason:
            # A blocked target is refused before any network call (fail-closed).
            raise NetworkPolicyViolation(f"web.fetch refused: {reason}")

        # Agent-supplied max_bytes can only shrink the cap, never lift it.
        cap = min(int(params.get("max_bytes") or _MAX_BYTES), _MAX_BYTES)
        proxy = self._config.get("https_proxy") or None
        # Redirects are NOT followed: a public URL must not redirect into internal
        # space and slip past the SSRF guard.
        if proxy:
            # With a proxy the proxy performs resolution, so local IP pinning does
            # not apply; the guard above (over the local resolution) stands.
            import httpx

            client = httpx.AsyncClient(
                follow_redirects=False,
                timeout=15.0,
                proxy=proxy,
                verify=self._tls_verify,
            )
        else:
            # SSRF/rebinding (H2/SEC-61): pin the connection to an already-vetted
            # IP from the single resolution above so httpx cannot re-resolve to
            # internal space at connect time.
            from boltrig.adapters.egress import pinned_async_client_for_ip

            client = pinned_async_client_for_ip(
                resolved[0],
                timeout=15.0,
                verify=self._tls_verify,
            )
        async with client:
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
