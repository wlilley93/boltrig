"""Effective Worker network-policy coverage and web.fetch TLS enforcement."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from tests.worker_surface_ledger import assert_surface_retired
from fastapi.testclient import TestClient

import boltrig.adapters.builtin.web_fetch as web_fetch
import boltrig.adapters.egress as egress
from boltrig.adapters.builtin.web_fetch import build_web_fetch_adapter
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, InvocationContext
from boltrig.observability.network_policy import effective_network_policy
from boltrig.store import InMemoryStore

T = "acme"
ROOT = Path(__file__).resolve().parents[2]
_PUBLIC_IP = "93.184.216.34"


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def build_request(self, method: str, url: str, **kwargs):
        return httpx.Request(method, url, **kwargs)

    async def send(self, request: httpx.Request, *, stream: bool = False):
        assert stream is True
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"ok",
            request=request,
        )


def _context() -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="alice",
        run_id="network-policy",
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-35")
async def test_ca_bundle_reaches_direct_and_proxy_tls_without_changing_policy(
    monkeypatch,
):
    tls_context = object()
    ca_path = "/private/org/root-ca.pem"
    proxy_url = "https://proxy-user:proxy-secret@private-proxy.example:8443"
    created_from: list[str] = []

    def create_context(*, cafile):
        created_from.append(cafile)
        return tls_context

    monkeypatch.setattr(web_fetch.ssl, "create_default_context", create_context)
    monkeypatch.setattr(web_fetch, "_resolve", lambda _host: [_PUBLIC_IP])

    direct_call: dict = {}

    def direct_client(ip, **kwargs):
        direct_call.update({"ip": ip, **kwargs})
        return _Client()

    monkeypatch.setattr(egress, "pinned_async_client_for_ip", direct_client)
    direct = build_web_fetch_adapter(
        {
            "ca_bundle": ca_path,
            "allowed_domains": ("example.com",),
        }
    )
    result = await direct.execute(
        "web.fetch",
        {"url": "https://example.com"},
        None,
        _context(),
    )
    assert result.ok is True
    assert direct_call["ip"] == _PUBLIC_IP
    assert direct_call["verify"] is tls_context

    proxy_call: dict = {}

    def proxy_client(**kwargs):
        proxy_call.update(kwargs)
        return _Client()

    monkeypatch.setattr(httpx, "AsyncClient", proxy_client)
    proxied = build_web_fetch_adapter(
        {
            "ca_bundle": ca_path,
            "https_proxy": proxy_url,
            "blocked_domains": ("blocked.example",),
        }
    )
    await proxied.execute(
        "web.fetch",
        {"url": "https://example.com"},
        None,
        _context(),
    )
    assert proxy_call["verify"] is tls_context
    assert proxy_call["follow_redirects"] is False
    assert created_from == [ca_path, ca_path]


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-35")
def test_pinned_transport_owns_custom_tls_verifier(monkeypatch):
    tls_context = object()
    recorded: dict = {}

    class _Pool:
        _network_backend = None

    class _Transport:
        def __init__(self, **kwargs):
            recorded["transport"] = kwargs
            self._pool = _Pool()

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", _Transport)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: recorded.setdefault("client", kwargs))
    monkeypatch.setattr(egress, "_pinned_backend", lambda *_args: object())

    returned = egress.pinned_async_client_for_ip(_PUBLIC_IP, verify=tls_context)

    assert recorded["transport"]["verify"] is tls_context
    assert "verify" not in recorded["client"]
    assert recorded["client"]["follow_redirects"] is False
    assert returned is recorded["client"]


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-35")
def test_authenticated_projection_is_redacted_and_marks_every_separate_surface(
    monkeypatch,
):
    monkeypatch.setattr(
        web_fetch.ssl,
        "create_default_context",
        lambda **_kwargs: object(),
    )
    adapter = build_web_fetch_adapter(
        {
            "air_gapped": False,
            "https_proxy": "https://secret:token@proxy.private.example",
            "ca_bundle": "/private/org/root-ca.pem",
            "allowed_domains": ("allowed.private.example",),
            "blocked_domains": ("blocked.private.example",),
        }
    )
    kernel = Kernel(InMemoryStore())
    asyncio.run(kernel.register_adapter(T, adapter))

    projection = effective_network_policy(kernel, T)
    assert projection["status"] == "available"
    assert projection["universal_egress_control"] is False
    assert projection["changes_require_restart"] is True
    assert projection["web_fetch"]["fields"]["ca_bundle"] == {
        "enforcement": "enforced",
        "configured": True,
    }
    assert projection["web_fetch"]["fields"]["allowed_domains"]["entry_count"] == 1
    coverage = {item["surface"]: item for item in projection["coverage"]}
    assert set(coverage) == {
        "browser",
        "external_mcp",
        "http_adapters",
        "model_providers_and_embeddings",
    }
    # the manifest air-gap / domain-list posture now BINDS the http-adapter and
    # external-MCP legs (SEC-52); browser and provider transports still run
    # their own policies, and the projection must say so either way.
    assert coverage["browser"]["manifest_network_policy"] == "not_applied"
    assert (
        coverage["model_providers_and_embeddings"]["manifest_network_policy"]
        == "not_applied"
    )
    assert coverage["external_mcp"]["manifest_network_policy"] == "applied"
    assert coverage["http_adapters"]["manifest_network_policy"] == "applied"

    client = TestClient(create_app(kernel, platform={}))
    response = client.get(
        "/v1/platform/status",
        headers={"x-boltrig-tenant": T, "x-boltrig-subject": "alice"},
    )
    assert response.status_code == 200
    assert response.json()["network_policy"] == projection
    rendered = response.text.lower()
    for secret in (
        "secret",
        "token",
        "proxy.private.example",
        "/private/org/root-ca.pem",
        "allowed.private.example",
        "blocked.private.example",
    ):
        assert secret not in rendered


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-35")
def test_worker_contract_refuses_universal_coverage_or_raw_network_authoring():
    # The Operate surface that rendered this policy is gone; the SDK type and
    # the backend projection that make the claim honest are not, and they carry
    # the rest of this invariant below.
    assert_surface_retired(
        "apps/worker/src/components/OperationsView.tsx",
        "the coverage panel says it is not a universal egress firewall",
        "proxy addresses, CA paths and contents are never rendered",
        "no coverage is inferred where none was reported",
        "the coverage section contains no password input",
    )
    sdk = (ROOT / "sdks/web/src/types.ts").read_text(encoding="utf-8")
    bootstrap = (ROOT / "boltrig/api/bootstrap.py").read_text(encoding="utf-8")

    assert "net.as_egress_config()" in bootstrap  # the manifest network section
    # reaches web.fetch (and the other adapter legs) as one typed projection
    assert "universal_egress_control: false;" in sdk
    assert "sensitive_values_redacted: true;" in sdk
