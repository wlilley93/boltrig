"""Runpod adapter: GPU pod control behind governed verbs."""

import pytest

from boltrig.adapters.base import Credential
from boltrig.adapters.builtin.runpod import RunpodAdapter
from boltrig.models import GrantSet, InvocationContext

T = "acme"


def _ctx():
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="tester")


def _cred():
    return Credential(id="RUNPOD_API", kind="api_key", material={"value": "rpa_secret"})


@pytest.mark.invariant("FR-HOST-05")
def test_runpod_adapter_declares_read_and_mutating_verbs():
    verbs = {spec.verb_id: spec for spec in RunpodAdapter().describe()}
    assert verbs["runpod.pod.list"].consequence == "low"
    assert verbs["runpod.pod.start"].consequence == "high"
    assert verbs["runpod.pod.stop"].consequence == "high"


@pytest.mark.invariant("FR-HOST-06")
async def test_runpod_list_uses_bearer_and_redacts_pod_payload():
    seen = {}

    async def transport(method, path, headers):
        seen.update({"method": method, "path": path, "headers": headers})
        return 200, [{"id": "pod1", "name": "jellytot-inference", "desiredStatus": "RUNNING",
                      "env": {"SECRET": "x"}, "publicIp": "203.0.113.1",
                      "machine": {"machineId": "m1", "memoryInGb": 80},
                      "gpu": {"id": "A100", "displayName": "A100 SXM"}}]

    result = await RunpodAdapter(transport=transport).execute(
        "runpod.pod.list", {}, _cred(), _ctx()
    )

    assert result.ok
    assert seen == {
        "method": "GET",
        "path": "/pods",
        "headers": {"Authorization": "Bearer rpa_secret"},
    }
    rendered = repr(result.output)
    assert "SECRET" not in rendered
    assert "publicIp" not in rendered
    assert "rpa_secret" not in rendered
    assert result.output["pods"][0]["gpu"]["displayName"] == "A100 SXM"


@pytest.mark.invariant("FR-HOST-07")
async def test_runpod_start_stop_restart_paths_are_documented_rest_paths():
    seen = []

    async def transport(method, path, headers):
        seen.append((method, path, headers))
        return 200, {}

    adapter = RunpodAdapter(transport=transport)
    for verb in ("runpod.pod.start", "runpod.pod.stop", "runpod.pod.restart"):
        result = await adapter.execute(verb, {"pod_id": "abc123"}, _cred(), _ctx())
        assert result.ok

    assert [item[:2] for item in seen] == [
        ("POST", "/pods/abc123/start"),
        ("POST", "/pods/abc123/stop"),
        ("POST", "/pods/abc123/restart"),
    ]


@pytest.mark.invariant("FR-HOST-08")
async def test_runpod_missing_credential_fails_closed():
    result = await RunpodAdapter().execute("runpod.pod.list", {}, None, _ctx())
    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "unauthorised"
