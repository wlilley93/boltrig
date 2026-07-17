"""The MCP consumer's bearer is the kernel's per-call credential (SEC-167).

The adapter holds no token. Every bearer it presents is the one the kernel
resolved for that call through the credential seam, so per-call resolution,
rotation and per-run scoping are live rather than inert, and a call with no
credential fails closed instead of posting an empty bearer.
"""

from __future__ import annotations

import pytest

from boltrig.adapters.base import Credential, ErrorClass
from boltrig.adapters.mcp_consumer import McpConsumerAdapter
from boltrig.config.control_mcp import bind_mcp_credential
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, InvocationContext
from boltrig.store import InMemoryStore

T = "acme"


class _Recorder:
    """Stands in for the external MCP server: records the bearer each POST sent."""

    def __init__(self) -> None:
        self.bearers: list[str | None] = []

    async def post(self, url, json, headers):  # noqa: ANN001 - httpx-shaped stub
        self.bearers.append(headers.get("x-boltrig-mcp-token"))
        return _Resp()

    async def __aenter__(self) -> "_Recorder":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class _Resp:
    def json(self) -> dict:
        return {"result": {"_boltrig": {"output": {"ok": True}}}}


def _consumer(monkeypatch, recorder: _Recorder) -> McpConsumerAdapter:
    """A consumer on the real HTTP path, with the pinned client stubbed out so the
    bearer that would go on the wire is observable (SSRF pinning is exercised
    separately in test_ssrf_pinning_still_applies)."""
    monkeypatch.setattr(
        "boltrig.adapters.egress.pinned_async_client", lambda url, timeout: recorder
    )
    consumer = McpConsumerAdapter("ext-mcp", url="http://ext-mcp.internal:9000")
    consumer.review_and_activate("alice@acme")
    return consumer


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]))


@pytest.mark.invariant("SEC-167")
async def test_the_kernels_per_call_credential_is_the_bearer(monkeypatch):
    recorder = _Recorder()
    consumer = _consumer(monkeypatch, recorder)

    # The credential the KERNEL resolved, differing from anything the adapter
    # could have been built with: whatever arrives here must be what goes out.
    kernel_cred = Credential(id="c1", kind="api_key", material={"token": "KERNEL-WINS"})
    result = await consumer.execute("ticket.create", {}, kernel_cred, _ctx())

    assert result.ok
    assert recorder.bearers == ["KERNEL-WINS"]


@pytest.mark.invariant("SEC-167")
async def test_a_second_call_uses_the_second_credential_not_the_first(monkeypatch):
    """Per-call, not per-instance: the same adapter presents whatever the kernel
    resolved for THAT call. A cached first token would fail this."""
    recorder = _Recorder()
    consumer = _consumer(monkeypatch, recorder)

    await consumer.execute(
        "ticket.create", {}, Credential(id="c1", kind="api_key", material={"token": "FIRST"}), _ctx()
    )
    await consumer.execute(
        "ticket.create", {}, Credential(id="c1", kind="api_key", material={"token": "SECOND"}),
        _ctx(),
    )

    assert recorder.bearers == ["FIRST", "SECOND"]


@pytest.mark.invariant("SEC-167")
async def test_no_credential_fails_closed_even_with_a_static_token_planted(monkeypatch):
    """No credential is a clear refusal - never an empty bearer, never an
    unauthenticated request, and never a fall back to instance-held material.

    A static token is PLANTED on the instance as a decoy: that is exactly the
    material the old code carried, so a fallback would send it instead of
    refusing. Nothing may read it.
    """
    recorder = _Recorder()
    consumer = _consumer(monkeypatch, recorder)
    consumer._token = "STATIC-BACKDOOR"  # type: ignore[attr-defined]

    result = await consumer.execute("ticket.create", {}, None, _ctx())

    assert result.ok is False
    assert result.error is not None
    assert result.error.error_class.value == "unauthorised"
    assert "credential" in result.error.message
    assert recorder.bearers == []  # no request at all, and no decoy on the wire


@pytest.mark.invariant("SEC-167")
async def test_empty_credential_material_also_fails_closed(monkeypatch):
    """Material that carries no usable token is as good as no credential: it must
    not degrade into an empty bearer, nor into planted instance material."""
    recorder = _Recorder()
    consumer = _consumer(monkeypatch, recorder)
    consumer._token = "STATIC-BACKDOOR"  # type: ignore[attr-defined]

    empty = Credential(id="c1", kind="api_key", material={})
    result = await consumer.execute("ticket.create", {}, empty, _ctx())

    assert result.ok is False
    assert recorder.bearers == []


@pytest.mark.invariant("SEC-167")
async def test_the_adapter_holds_no_token_to_fall_back_on(monkeypatch):
    """Structural: there is no instance-held bearer, so no back door exists for
    the dispatch path to fall back to when the credential is absent."""
    consumer = McpConsumerAdapter("ext-mcp", url="http://ext-mcp.internal:9000")

    assert not any("token" in name for name in vars(consumer))
    with pytest.raises(TypeError):  # the token= constructor param is gone
        McpConsumerAdapter("x", url="http://x", token="static")  # type: ignore[call-arg]


@pytest.mark.invariant("SEC-167")
async def test_rotating_the_stored_ref_changes_the_next_calls_bearer(monkeypatch):
    """Rotation is live end to end: the bearer follows the STORED credential ref
    through the kernel resolver, with no adapter rebuild."""
    monkeypatch.setenv("MCP_TOK_A", "token-a")
    monkeypatch.setenv("MCP_TOK_B", "token-b")
    recorder = _Recorder()
    consumer = _consumer(monkeypatch, recorder)

    store = InMemoryStore()
    kernel = Kernel(store)
    await bind_mcp_credential(
        store, kernel.credentials, T, consumer.id, {"credential_ref": "MCP_TOK_A"}
    )

    resolved = await kernel.credentials.resolve_for_adapter(T, consumer.id)
    await consumer.execute("ticket.create", {}, resolved, _ctx())

    # rotate the stored ref: no adapter rebuild, no re-registration
    await bind_mcp_credential(
        store, kernel.credentials, T, consumer.id, {"credential_ref": "MCP_TOK_B"}
    )
    resolved = await kernel.credentials.resolve_for_adapter(T, consumer.id)
    await consumer.execute("ticket.create", {}, resolved, _ctx())

    assert recorder.bearers == ["token-a", "token-b"]


@pytest.mark.invariant("SEC-167")
async def test_registration_binds_the_ref_and_refuses_raw_material():
    """The registration route puts a REF on the credential seam (SEC-04), and
    refuses raw secret material outright rather than parking it on the adapter."""
    from boltrig.config.control_safety import ControlConflict

    store = InMemoryStore()
    kernel = Kernel(store)
    cred_id = await bind_mcp_credential(
        store, kernel.credentials, T, "ext-mcp", {"credential_ref": "SOME_ENV_KEY"}
    )
    assert cred_id is not None
    # refs only: the stored record names the secret, it does not contain it
    stored = await store.get_credential_ref(T, cred_id)
    assert stored == {"store": "env", "ref": "SOME_ENV_KEY", "kind": "api_key"}

    for legacy in ({"token": "sk-raw"}, {"credential": "sk-raw"}):
        with pytest.raises(ControlConflict):
            await bind_mcp_credential(store, kernel.credentials, T, "ext-2", legacy)


@pytest.mark.invariant("SEC-22")
async def test_the_review_gate_still_holds_before_any_credential_is_considered(monkeypatch):
    """SEC-22 is unchanged and is checked FIRST: an unreviewed server refuses even
    when a perfectly good credential is presented."""
    recorder = _Recorder()
    monkeypatch.setattr(
        "boltrig.adapters.egress.pinned_async_client", lambda url, timeout: recorder
    )
    consumer = McpConsumerAdapter("ext-mcp", url="http://ext-mcp.internal:9000")  # not activated
    good = Credential(id="c1", kind="api_key", material={"token": "GOOD"})

    result = await consumer.execute("ticket.create", {}, good, _ctx())

    assert result.ok is False
    assert result.error is not None
    assert result.error.error_class.value == "unavailable"
    assert recorder.bearers == []


@pytest.mark.invariant("SEC-61")
async def test_ssrf_pinning_still_applies(monkeypatch):
    """SEC-61 is unchanged: a blocked destination is refused by the pinned client
    before the bearer can leave, even with a valid credential.

    The refusal is now a clean ``Result.failure(INVALID)``. It previously surfaced
    as a ``TypeError``, because the branch did ``raise AdapterError(...)`` and
    ``AdapterError`` is a plain dataclass, so it failed closed by the wrong route
    and no ``except AdapterError`` handler could have caught it. That defect is
    fixed (``_McpFailure``, mirroring ``http_base._HttpFailure``), so the refusal
    type is worth pinning rather than tolerating.
    """
    from boltrig.adapters.egress import EgressBlocked

    posted: list = []

    def _blocked(url, timeout):  # noqa: ANN001
        posted.append(url)
        raise EgressBlocked("destination resolves to internal space")

    monkeypatch.setattr("boltrig.adapters.egress.pinned_async_client", _blocked)
    consumer = McpConsumerAdapter("ext-mcp", url="http://169.254.169.254")
    consumer.review_and_activate("alice@acme")
    good = Credential(id="c1", kind="api_key", material={"token": "GOOD"})

    result = await consumer.execute("ticket.create", {}, good, _ctx())

    assert result.ok is False
    assert result.error is not None and result.error.error_class is ErrorClass.INVALID
    # the pinned client was consulted and refused: nothing was posted past it
    assert posted == ["http://169.254.169.254"]
