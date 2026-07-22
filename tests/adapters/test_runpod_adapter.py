"""Runpod adapter: GPU pod control behind governed verbs."""

import socket

import httpx
import pytest

from boltrig.adapters.base import Credential
from boltrig.adapters.builtin.runpod import RunpodAdapter
from boltrig.models import GrantSet, InvocationContext

T = "acme"
_PUBLIC_IP = "93.184.216.34"


def _ctx():
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="tester")


def _cred():
    return Credential(id="RUNPOD_API", kind="api_key", material={"value": "rpa_secret"})


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    # The base's per-request egress guard resolves the host; keep the test
    # hermetic by resolving everything to a public IP.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port=None, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_IP, port or 0))
        ],
    )


def _adapter(handler) -> RunpodAdapter:
    return RunpodAdapter(transport=httpx.MockTransport(handler))


@pytest.mark.invariant("FR-HOST-05")
def test_runpod_adapter_declares_read_and_mutating_verbs():
    verbs = {spec.verb_id: spec for spec in RunpodAdapter().describe()}
    assert verbs["runpod.pod.list"].consequence == "low"
    assert verbs["runpod.pod.start"].consequence == "high"
    assert verbs["runpod.pod.stop"].consequence == "high"


@pytest.mark.invariant("FR-HOST-06")
async def test_runpod_list_uses_bearer_and_redacts_pod_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({
            "method": request.method,
            "path": request.url.path,
            "authorization": request.headers.get("authorization"),
        })
        return httpx.Response(
            200,
            json=[{"id": "pod1", "name": "jellytot-inference", "desiredStatus": "RUNNING",
                   "env": {"SECRET": "x"}, "publicIp": "203.0.113.1",
                   "machine": {"machineId": "m1", "memoryInGb": 80},
                   "gpu": {"id": "A100", "displayName": "A100 SXM"}}],
        )

    result = await _adapter(handler).execute("runpod.pod.list", {}, _cred(), _ctx())

    assert result.ok
    assert seen == {
        "method": "GET",
        "path": "/v1/pods",
        "authorization": "Bearer rpa_secret",
    }
    rendered = repr(result.output)
    assert "SECRET" not in rendered
    assert "publicIp" not in rendered
    assert "rpa_secret" not in rendered
    assert result.output["pods"][0]["gpu"]["displayName"] == "A100 SXM"


@pytest.mark.invariant("FR-HOST-07")
async def test_runpod_start_stop_restart_paths_are_documented_rest_paths():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={})

    adapter = _adapter(handler)
    for verb in ("runpod.pod.start", "runpod.pod.stop", "runpod.pod.restart"):
        result = await adapter.execute(verb, {"pod_id": "abc123"}, _cred(), _ctx())
        assert result.ok

    assert seen == [
        ("POST", "/v1/pods/abc123/start"),
        ("POST", "/v1/pods/abc123/stop"),
        ("POST", "/v1/pods/abc123/restart"),
    ]


@pytest.mark.invariant("FR-HOST-08")
async def test_runpod_missing_credential_fails_closed():
    result = await RunpodAdapter().execute("runpod.pod.list", {}, None, _ctx())
    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "unauthorised"


async def test_runpod_error_status_maps_to_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    result = await _adapter(handler).execute(
        "runpod.pod.get", {"pod_id": "nope"}, _cred(), _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "not_found"
    assert not result.error.retryable
