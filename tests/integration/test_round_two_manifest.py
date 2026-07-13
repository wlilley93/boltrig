"""Manifest sidecar/v2 config sections still load (S9, SEC-24)."""

from pathlib import Path

import pytest
import yaml

from boltrig.config import export_runtime_environment, load_manifest

_MANIFEST = "manifest.example.yaml"
_ACTIVE_MANIFEST = "manifest.yaml"


def test_manifest_still_loads_with_round_two_sections():
    # the R1 loader must tolerate the new runtimes/mcp/chat sections
    m = load_manifest(_MANIFEST)
    assert m.tenant_id
    assert any(rt.name == "pi-worker" and rt.runtime == "pi" for rt in m.ephemeral_runtimes)


def test_manifest_interpolated_false_is_false():
    m = load_manifest(_MANIFEST, env={"AIR_GAPPED": "false"})
    assert m.network.air_gapped is False


@pytest.mark.security
@pytest.mark.invariant("SEC-24")
def test_pi_sidecar_sandbox_is_declared_restrictive():
    with open(_MANIFEST, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    sandbox = doc["runtimes"]["pi"]["sandbox"]
    assert sandbox["native_tools"] is False  # no Pi filesystem/bash/network tools
    assert set(sandbox["network_allow"]) <= {"kernel_mcp", "model_endpoint"}  # egress only here


def test_manifest_preserves_boltrig_v2_stack_sections():
    m = load_manifest(_MANIFEST)
    assert m.section("stack") == {
        "cockpit": "herdr",
        "orchestration": "mastra",
        "durability": "hatchet",
        "runtime_sandbox": "rivet_agentos",
        "coding_agent": "opencode",
        "browser_automation": "browser_cli",
        "memory_primary": "mem0",
        "memory_projection": "cognee",
        "model_routing": "bifrost",
        "observability": "langfuse",
        "tool_protocol": "mcp_kernel",
    }
    assert m.section("mastra")["compile_to"] == "hatchet"
    assert m.section("mastra")["plan_contract"] == "boltrig.mastra.v1"
    assert m.section("rivet_agentos")["enabled"] is True
    assert m.section("rivet_agentos")["network_allow"] == ["kernel_mcp", "model_endpoint"]
    assert m.section("browser_cli")["enabled"] is True
    assert m.section("browser_cli")["runtime"] == "rivet_agentos"
    assert m.section("browser_cli")["cloud_policy"] == "disabled"
    assert m.section("langfuse")["secret_key_ref"] == "LANGFUSE_SECRET_KEY"

    memory = m.section("memory")
    assert memory["authority"] == "kernel_ledger"
    assert memory["primary_projection"] == "mem0"
    assert [p["id"] for p in memory["projections"]] == ["mem0", "cognee"]
    assert [p["enabled"] for p in memory["projections"]] == [False, False]
    assert memory["fanout"]["mode"] == "ledger_then_projection"
    assert memory["fanout"]["execution"] == "inline"


@pytest.mark.invariant("FR-HOST-13")
def test_manifest_exports_browser_cloud_policy_without_secret_material():
    m = load_manifest(_MANIFEST)
    env: dict[str, str] = {}

    export_runtime_environment(m, env)

    assert env["BOLTRIG_BROWSER_CLOUD_POLICY"] == "disabled"
    assert "BOLTRIG_BROWSER_CLOUD_API_KEY" not in env
    assert "BOLTRIG_BROWSER_CLOUD_PROFILE_ID" not in env


@pytest.mark.invariant("FR-HOST-13")
def test_manifest_export_does_not_override_browser_cloud_policy():
    m = load_manifest(_MANIFEST)
    env = {"BOLTRIG_BROWSER_CLOUD_POLICY": "stack"}

    export_runtime_environment(m, env)

    assert env["BOLTRIG_BROWSER_CLOUD_POLICY"] == "stack"


@pytest.mark.parametrize("path", [_MANIFEST])
def test_checked_in_manifests_preserve_v2_entrypoints(path):
    m = load_manifest(path)
    adapters = {adapter.id for adapter in m.adapters}
    runtimes = {runtime.name: runtime for runtime in m.ephemeral_runtimes}

    assert m.section("stack")["cockpit"] == "herdr"
    assert m.section("stack")["browser_automation"] == "browser_cli"
    assert {"herdr", "browser-cli"} <= adapters
    assert "rivet-worker" in runtimes
    assert runtimes["rivet-worker"].runtime == "rivet_agentos"
    assert "opencode-worker" in runtimes
    assert runtimes["opencode-worker"].runtime == "opencode"


def test_local_active_manifest_preserves_v2_entrypoints_when_present():
    if not Path(_ACTIVE_MANIFEST).exists():
        pytest.skip("local active manifest is ignored and absent")
    test_checked_in_manifests_preserve_v2_entrypoints(_ACTIVE_MANIFEST)
