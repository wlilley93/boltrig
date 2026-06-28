"""Round Two manifest: Pi sandbox config + the manifest still loads (S9, SEC-24)."""

import pytest
import yaml

from nankle.config import load_manifest

_MANIFEST = "manifest.example.yaml"


def test_manifest_still_loads_with_round_two_sections():
    # the R1 loader must tolerate the new runtimes/mcp/chat sections
    m = load_manifest(_MANIFEST)
    assert m.tenant_id
    assert any(rt.name == "pi-worker" and rt.runtime == "pi" for rt in m.ephemeral_runtimes)


@pytest.mark.security
@pytest.mark.invariant("SEC-24")
def test_pi_sidecar_sandbox_is_declared_restrictive():
    with open(_MANIFEST, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    sandbox = doc["runtimes"]["pi"]["sandbox"]
    assert sandbox["native_tools"] is False  # no Pi filesystem/bash/network tools
    assert set(sandbox["network_allow"]) <= {"kernel_mcp", "model_endpoint"}  # egress only here
