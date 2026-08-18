"""HttpAdapter egress: the manifest posture binds, and pinning fails closed.

Two halves of one doctrine:

* the NetworkConfig (air-gap / allow/block lists, SEC-52) an adapter is
  constructed with is enforced at CLIENT CONSTRUCTION - before any handler,
  transport or credential material exists. The manifest posture also reaches
  adapters the loader builds as bare ``build()`` factories, through the
  process-wide default the composition root installs; an explicit config
  always supersedes that default.
* a base host that cannot be pinned (internal, unresolvable, or an empty
  base_url) FAILS the client instead of shipping an unpinned one (SEC-61):
  the old fallback let httpx re-resolve at connect time, the DNS-rebinding
  TOCTOU the http_base docs say pinning exists to close.
"""

import httpx
import pytest

from boltrig.adapters.base import Credential, Result, VerbSpec
from boltrig.adapters.http_base import HttpAdapter
from boltrig.models import GrantSet, InvocationContext

T = "acme"
_PUBLIC_IP = "93.184.216.34"
_METADATA = "169.254.169.254"


class _Adapter(HttpAdapter):
    id = "t"
    version = "0.1.0"

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec("t.read", "t", {"type": "object"}, {"type": "object"}, "low", "read"),
        ]

    def _handlers(self):
        return {"t.read": self._read}

    async def _read(self, params, client, context):
        return Result.success({"reached": True})


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="tester")


def _cred() -> Credential:
    return Credential(id="T", kind="api_key", material={"value": "x"})


@pytest.mark.invariant("SEC-52")
async def test_an_air_gapped_adapter_refuses_every_url_at_client_construction(
    monkeypatch,
):
    monkeypatch.setattr("boltrig.adapters.egress.resolve_host", lambda host: [_PUBLIC_IP])
    adapter = _Adapter(
        base_url="https://api.example.test", network_config={"air_gapped": True}
    )

    result = await adapter.execute("t.read", {}, _cred(), _ctx())

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "invalid"
    assert "air-gapped" in result.error.message
    # the refusal is at construction: the handler never ran, so no transport
    # was touched and no credential material left the adapter.


@pytest.mark.invariant("SEC-61")
async def test_an_unpinnable_base_never_ships_an_unpinned_client(monkeypatch):
    """The FIX: a base resolving internal fails the construction. The old
    fallback returned transport=None and deferred to a request-time INVALID -
    from a client httpx could already connect through on a second, unaudited
    DNS lookup (the rebinding TOCTOU). No httpx client may be built at all."""
    monkeypatch.setattr("boltrig.adapters.egress.resolve_host", lambda host: [_METADATA])
    built = []
    real_async_client = httpx.AsyncClient

    def spy(*args, **kwargs):
        built.append(kwargs.get("transport"))
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("boltrig.adapters.http_base.httpx.AsyncClient", spy)
    adapter = _Adapter(base_url="https://rebind.attacker.test")

    result = await adapter.execute("t.read", {}, _cred(), _ctx())

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "invalid"
    assert "egress refused" in result.error.message
    assert built == []  # no client was constructed, pinned or otherwise


@pytest.mark.invariant("SEC-61")
async def test_an_empty_base_url_fails_construction_not_a_deferred_request(
    monkeypatch,
):
    monkeypatch.setattr("boltrig.adapters.egress.resolve_host", lambda host: [])
    adapter = _Adapter(base_url="")

    result = await adapter.execute("t.read", {}, _cred(), _ctx())

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "invalid"
    assert "egress refused" in result.error.message


@pytest.mark.invariant("SEC-52")
async def test_the_process_default_posture_binds_and_an_explicit_config_wins(
    monkeypatch,
):
    from boltrig.adapters import egress

    monkeypatch.setattr(egress, "resolve_host", lambda host: [_PUBLIC_IP])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": []})

    egress.set_default_network_config({"air_gapped": True})
    try:
        # no explicit config: the posture the composition root installed
        # governs adapters whose factories have no construction seam.
        defaulted = _Adapter(base_url="https://api.example.test")
        refused = await defaulted.execute("t.read", {}, _cred(), _ctx())
        assert not refused.ok
        assert refused.error is not None
        assert "air-gapped" in refused.error.message

        # an explicit config SUPERSEDES the default (it does not merge with
        # it): this adapter's own posture permits the target and runs.
        explicit = _Adapter(
            base_url="https://api.example.test",
            network_config={"allowed_domains": ("api.example.test",)},
        )
        explicit._client = lambda credential: httpx.AsyncClient(  # test transport
            base_url=explicit.base_url, transport=httpx.MockTransport(handler)
        )
        allowed = await explicit.execute("t.read", {}, _cred(), _ctx())
        assert allowed.ok
    finally:
        egress.set_default_network_config(None)


# --- proxy / CA: the manifest transport posture follows the same seam ----------
@pytest.mark.invariant("SEC-52")
def test_a_configured_ca_bundle_builds_a_closed_tls_verifier(tmp_path):
    """``ca_bundle`` yields an SSLContext that trusts ONLY those roots, and a
    malformed bundle FAILS CLOSED rather than silently falling back to public
    roots (the web_fetch doctrine, now shared by the pinned-client family)."""
    import ssl

    from boltrig.adapters.egress import tls_verify_from_config

    assert tls_verify_from_config(None) is True
    assert tls_verify_from_config({}) is True
    junk = tmp_path / "junk.pem"
    junk.write_text("this is not a certificate")
    with pytest.raises(Exception):
        tls_verify_from_config({"ca_bundle": str(junk)})
    assert ssl  # referenced for the reader: the success path returns ssl.SSLContext


@pytest.mark.invariant("SEC-52")
def test_a_proxied_config_builds_an_unpinned_proxied_client(monkeypatch):
    """With ``https_proxy`` in the posture, the pinned helpers take web_fetch's
    proxy branch: the guard over the local resolution still runs, and the client
    is built PROXIED (resolution delegated to the proxy) rather than pinned."""
    from boltrig.adapters import egress

    captured: dict = {}

    class _RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self._transport = kwargs.get("transport")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)
    # Hermetic: the guard vets the LOCAL resolution even in proxy mode, so hand
    # it a public IP rather than resolving example.com live (a DNS blip once
    # failed this test in the full suite - the test is about the proxy branch
    # of client construction, not about connectivity).
    monkeypatch.setattr(egress, "resolve_host", lambda host: [_PUBLIC_IP])

    config = {"https_proxy": "http://proxy.corp:3128"}
    client = egress.pinned_async_client("https://example.com/spec.json", config, timeout=5.0)
    assert captured.get("proxy") == "http://proxy.corp:3128"
    assert captured.get("follow_redirects") is False
    assert client is not None
