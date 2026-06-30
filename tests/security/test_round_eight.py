"""Round Eight - internet access as a governed verb (SEC-52/53).

SEC-52  web.fetch is SSRF-guarded and NetworkConfig-enforced: private/loopback/
        link-local/metadata targets, blocked or non-allowed domains, and air-gap
        are refused BEFORE any network call.
SEC-53  internet access is a governed verb - web.fetch runs the chokepoint
        (grant-checked + HITL-gated like any high-consequence verb); it cannot
        bypass the kernel, and fetched untrusted content cannot escalate (the next
        verb's own gate still fires).
"""

from __future__ import annotations

import pytest

from boltrig.adapters.builtin.web_fetch import (
    build_web_fetch_adapter,
    check_network_policy,
    is_blocked_ip,
)
from boltrig.kernel import Kernel
from boltrig.models import (
    GrantMissing,
    GrantSet,
    InvocationContext,
    NetworkPolicyViolation,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


def _ctx(grants: list[str]) -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(grants), actor="u", run_id="r8")


# --------------------------------------------------------------------------- #
# SEC-52  SSRF guard + NetworkConfig enforcement
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-52")
def test_ssrf_guard_blocks_internal_addresses():
    for ip in ["127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.0.1",
               "169.254.169.254", "0.0.0.0", "::1", "fe80::1", "fc00::1"]:
        assert is_blocked_ip(ip) is True, ip
    for ip in ["93.184.216.34", "8.8.8.8", "1.1.1.1"]:
        assert is_blocked_ip(ip) is False, ip


@pytest.mark.security
@pytest.mark.invariant("SEC-52")
def test_network_policy_enforced():
    # the cloud metadata endpoint is refused even with a public-looking request
    assert check_network_policy("http://169.254.169.254/latest/meta-data/", {},
                                resolved_ips=["169.254.169.254"])
    # a public domain resolving to an internal IP (DNS rebinding) is refused
    assert check_network_policy("https://evil.example", {}, resolved_ips=["10.0.0.9"])
    # non-http schemes are refused
    assert check_network_policy("file:///etc/passwd", {}, resolved_ips=[])
    # air-gap refuses all egress
    assert check_network_policy("https://example.com", {"air_gapped": True},
                                resolved_ips=["93.184.216.34"])
    # block list (and subdomains of it) is refused
    assert check_network_policy("https://api.evil.com/x", {"blocked_domains": ["evil.com"]},
                                resolved_ips=["93.184.216.34"])
    # an allow list refuses anything not on it, and permits what is on it
    assert check_network_policy("https://other.com", {"allowed_domains": ["good.com"]},
                                resolved_ips=["93.184.216.34"])
    assert check_network_policy("https://good.com", {"allowed_domains": ["good.com"]},
                                resolved_ips=["93.184.216.34"]) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-52")
async def test_adapter_refuses_internal_target_before_any_fetch():
    adapter = build_web_fetch_adapter({})
    # an IP-literal metadata target resolves to itself (no DNS) and is refused
    # before any network call is made.
    with pytest.raises(NetworkPolicyViolation):
        await adapter.execute("web.fetch", {"url": "http://169.254.169.254/"}, None, _ctx(["*"]))


# --------------------------------------------------------------------------- #
# SEC-53  internet access is a governed verb (grant + HITL, no bypass)
# --------------------------------------------------------------------------- #
async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_web_fetch_adapter({}))
    return k


@pytest.mark.security
@pytest.mark.invariant("SEC-53")
async def test_web_fetch_is_grant_checked():
    k = await _kernel()
    with pytest.raises(GrantMissing):  # a caller without web.fetch cannot reach the net
        await k.invoke("web", "web.fetch", {"url": "https://example.com"}, _ctx(["ticket.read"]))


@pytest.mark.security
@pytest.mark.invariant("SEC-53")
async def test_web_fetch_is_hitl_gated():
    k = await _kernel()
    # web.fetch is high-consequence (untrusted-input surface) -> the gate holds it,
    # so injected page content can never drive a fetch (or any next verb) unapproved.
    with pytest.raises(PendingHuman):
        await k.invoke("web", "web.fetch", {"url": "https://example.com"}, _ctx(["*"]))
