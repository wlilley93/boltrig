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

from typing import Any
from urllib.parse import urlparse

from nankle.adapters.base import Credential, Result, VerbSpec
# The SSRF/policy guard now lives in the shared egress module so every HTTP
# adapter uses one source of truth (consolidation). Re-exported here so callers /
# tests that import them from web_fetch keep working.
from nankle.adapters.egress import (  # noqa: F401
    check_network_policy,
    is_blocked_ip,
    resolve_host as _resolve,
)
from nankle.models import InvocationContext, NetworkPolicyViolation

_MAX_BYTES = 256 * 1024  # default cap on returned content


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
